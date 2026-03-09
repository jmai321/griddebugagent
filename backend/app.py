import os
import re
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import pandas as pd
from typing import Optional, Dict, List

import pandapower as pp
from scenarios.code_sandbox import execute_safely

from openai import OpenAI

from scenarios import (
    NonConvergenceScenarios,
    VoltageViolationScenarios,
    ThermalOverloadScenarios,
    ContingencyFailureScenarios,
    NormalScenarios,
)
from scenarios.base_scenarios import load_network
from agents.baseline import BaselineAgent
from agents.agentic_pipeline import AgenticPipelineAgent
from scenarios.nl_scenario_generator import NLScenarioGenerator

load_dotenv()

app = FastAPI(title="GridDebugAgent API")

# Allow frontend to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------
#  LLM Client
# ---------------------

_openai_key = os.getenv("OPENAI_API_KEY", "")
_llm_client = OpenAI(api_key=_openai_key) if _openai_key else None
_baseline_agent = BaselineAgent(llm_client=_llm_client)
_agentic_agent = AgenticPipelineAgent(llm_client=_llm_client)
_nl_generator = NLScenarioGenerator(llm_client=_llm_client)


# ---------------------
#  Constants
# ---------------------

import inspect
import pandapower.networks as nw

def _get_available_networks() -> list[dict]:
    networks = []
    common_cases = ["case14", "case30", "case57", "case118", "case300"]
    
    # Priority defaults
    for name in common_cases:
        if hasattr(nw, name):
            networks.append({"id": name, "label": f"IEEE {name.replace('case', '')}-Bus"})
        
    # Add the rest of the zero-arg functions from pandapower.networks
    for name, obj in inspect.getmembers(nw):
        if inspect.isfunction(obj) and not name.startswith('_') and name not in common_cases:
            sig = inspect.signature(obj)
            has_required = any(
                p.default == inspect.Parameter.empty 
                and p.kind in [inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.POSITIONAL_ONLY]
                for p in sig.parameters.values()
            )
            if not has_required:
                networks.append({"id": name, "label": name})
    return networks

NETWORKS = _get_available_networks()

SCENARIO_FACTORIES = {
    "nonconvergence": NonConvergenceScenarios,
    "voltage":        VoltageViolationScenarios,
    "thermal":        ThermalOverloadScenarios,
    "contingency":    ContingencyFailureScenarios,
    "normal":         NormalScenarios,
}

SCENARIOS = [
    # Normal Operation
    {"id": "normal_operation",              "label": "Normal Operation (Baseline)",          "category": "normal"},
    # Non-convergence
    {"id": "extreme_load_scaling",          "label": "Extreme Load Scaling (20×)",           "category": "nonconvergence"},
    {"id": "all_generators_removed",        "label": "All Generators Removed",               "category": "nonconvergence"},
    {"id": "near_zero_impedance",           "label": "Near-Zero Impedance Line",             "category": "nonconvergence"},
    {"id": "disconnected_subnetwork",       "label": "Disconnected Sub-Network",             "category": "nonconvergence"},
    # Voltage violations
    {"id": "heavy_loading_undervoltage",    "label": "Heavy Loading Under-Voltage (3×)",     "category": "voltage"},
    {"id": "excess_generation_overvoltage", "label": "Excess Generation Over-Voltage",       "category": "voltage"},
    {"id": "reactive_imbalance",            "label": "Reactive Power Imbalance",             "category": "voltage"},
    # Thermal overloads
    {"id": "concentrated_loading",          "label": "Concentrated Loading on Weak Bus",     "category": "thermal"},
    {"id": "reduced_thermal_limits",        "label": "Reduced Thermal Limits (30%)",         "category": "thermal"},
    {"id": "topology_redirection",          "label": "Topology Change Flow Redirection",     "category": "thermal"},
    # Contingency
    {"id": "line_contingency_overload",     "label": "N-1 Line Contingency Overload",        "category": "contingency"},
    {"id": "trafo_contingency_voltage",     "label": "N-1 Trafo Contingency Voltage",        "category": "contingency"},
]


# ---------------------
#  Helpers
# ---------------------

def _find_and_apply_scenario(scenario_id: str, network: str):
    """
    Instantiate the matching scenario, apply it, and return
    (scenario_object, ground_truth_result).
    """
    entry = next((s for s in SCENARIOS if s["id"] == scenario_id), None)
    if entry is None:
        raise HTTPException(404, f"Unknown scenario: {scenario_id}")

    factory = SCENARIO_FACTORIES[entry["category"]]
    all_scenarios = factory.all_scenarios(network)

    for sc in all_scenarios:
        result = sc.apply()
        if result.scenario_name == scenario_id:
            return sc, result

    raise HTTPException(404, f"Scenario '{scenario_id}' not found in factory")


def _parse_llm_report(report: str) -> dict:
    """
    Parse LLM markdown report into rootCauses, affectedComponents, correctiveActions.
    Tries to be robust to:
      - Sections appearing on the same line (no newlines)
      - Bulleted lists (-, *) and numbered lists (1., 2., ...)
      - Optional text after section headers (e.g. "## Root Causes (ranked...)")
    """
    result = {"rootCauses": [], "affectedComponents": [], "correctiveActions": []}

    def _normalize_block(text: str) -> str:
        """
        Insert newlines to make list-like content line-oriented.
        We only split numbered items when the dot is followed by whitespace,
        so we don't break decimals like 11.77 or 1.08.
        """
        text = text.strip()
        # Force each heading to start a new line (handles one-line outputs)
        text = re.sub(r"\s*(##\s*)", r"\n\1", text)
        # Convert " - " into real bullets on new lines
        text = re.sub(r"\s-\s", r"\n- ", text)
        # Convert " 1. " into numbered items on new lines (dot must be followed by whitespace)
        text = re.sub(r"\s(\d+)\.\s+", r"\n\1. ", text)
        return text.strip()

    def _extract_items(block: str) -> list[str]:
        items: list[str] = []
        for line in _normalize_block(block).split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith(("-", "*")):
                item = line.lstrip("-*").strip()
                if item:
                    items.append(item)
                continue
            if re.match(r"^\d+\.\s+", line):
                item = re.sub(r"^\d+\.\s+", "", line).strip()
                if item:
                    items.append(item)
                continue
        return items

    def extract_section_items(text: str, section: str) -> list[str]:
        # Match section header (optional suffix) then capture until next "##" or end.
        # Don't require a newline after the header.
        pattern = rf"##\s*{re.escape(section)}[^\n#]*\s*(.*?)(?=\s*##\s|\Z)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if not match:
            return []
        return _extract_items(match.group(1))

    result["rootCauses"] = extract_section_items(report, "Root Causes")
    result["affectedComponents"] = extract_section_items(report, "Affected Components")
    result["correctiveActions"] = extract_section_items(report, "Corrective Actions")

    return result


def _parse_affected_component(text: str) -> dict | None:
    """
    Parse LLM component strings like:
    - "Bus 3" -> {"type": "bus", "index": 3}
    - "Line 5-7" -> {"type": "line", "index": 5}
    - "Load 0-41" -> {"type": "load", "index": 0}
    - "Generator 2" -> {"type": "gen", "index": 2}
    - "Transformer 1" -> {"type": "trafo", "index": 1}
    """
    text = text.strip().lower()

    patterns = [
        (r'bus\s*(\d+)', 'bus'),
        (r'line\s*(\d+)(?:\s*[-–]\s*\d+)?', 'line'),
        (r'load\s*(\d+)(?:\s*[-–]\s*\d+)?', 'load'),
        (r'gen(?:erator)?\s*(\d+)', 'gen'),
        (r'trafo(?:rmer)?\s*(\d+)', 'trafo'),
        (r'transformer\s*(\d+)', 'trafo'),
        (r'ext(?:ernal)?\s*grid\s*(\d+)', 'ext_grid'),
    ]

    for pattern, comp_type in patterns:
        match = re.search(pattern, text)
        if match:
            return {"type": comp_type, "index": int(match.group(1))}

    return None


def _parse_affected_components_list(components: list[str]) -> dict[str, list[int]]:
    """
    Parse list of LLM component strings into structured format.
    Returns: {"bus": [3, 5], "line": [1, 2], ...}
    """
    result: dict[str, list[int]] = {}

    for comp_text in components:
        parsed = _parse_affected_component(comp_text)
        if parsed:
            comp_type = parsed["type"]
            comp_index = parsed["index"]
            if comp_type not in result:
                result[comp_type] = []
            if comp_index not in result[comp_type]:
                result[comp_type].append(comp_index)

    return result


def _build_pipeline_result(report: str, analysis_status: str = "success") -> dict:
    """Build pipeline result with analysisStatus and parsed fields."""
    parsed = _parse_llm_report(report)
    parsed_components = _parse_affected_components_list(parsed["affectedComponents"])
    return {
        "analysisStatus": analysis_status,
        "rootCauses": parsed["rootCauses"],
        "affectedComponents": parsed["affectedComponents"],
        "correctiveActions": parsed["correctiveActions"],
        "parsedAffectedComponents": parsed_components,
    }


def _generate_bus_coordinates(net: pp.pandapowerNet) -> dict[int, dict[str, float]]:
    """
    Generate hierarchical layout coordinates for buses using BFS from slack bus.
    Returns {bus_idx: {"x": float, "y": float}}
    """
    from collections import deque

    coords: dict[int, dict[str, float]] = {}
    bus_indices = list(net.bus.index)
    if not bus_indices:
        return coords

    # Build adjacency list from lines and transformers
    adjacency: dict[int, list[int]] = {b: [] for b in bus_indices}

    for _, line in net.line.iterrows():
        from_bus, to_bus = int(line["from_bus"]), int(line["to_bus"])
        if from_bus in adjacency and to_bus in adjacency:
            adjacency[from_bus].append(to_bus)
            adjacency[to_bus].append(from_bus)

    if hasattr(net, 'trafo') and not net.trafo.empty:
        for _, trafo in net.trafo.iterrows():
            hv_bus, lv_bus = int(trafo["hv_bus"]), int(trafo["lv_bus"])
            if hv_bus in adjacency and lv_bus in adjacency:
                adjacency[hv_bus].append(lv_bus)
                adjacency[lv_bus].append(hv_bus)

    # Find starting bus (prefer external grid, then first generator, then bus 0)
    start_bus = bus_indices[0]
    if hasattr(net, 'ext_grid') and not net.ext_grid.empty:
        start_bus = int(net.ext_grid.iloc[0]["bus"])
    elif hasattr(net, 'gen') and not net.gen.empty:
        start_bus = int(net.gen.iloc[0]["bus"])

    # BFS to assign layers
    visited: set[int] = set()
    layers: dict[int, list[int]] = {}
    queue: deque[tuple[int, int]] = deque([(start_bus, 0)])
    visited.add(start_bus)

    while queue:
        bus, layer = queue.popleft()
        layers.setdefault(layer, []).append(bus)
        for neighbor in adjacency[bus]:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, layer + 1))

    # Handle disconnected buses
    for bus in bus_indices:
        if bus not in visited:
            max_layer = max(layers.keys()) + 1 if layers else 0
            layers.setdefault(max_layer, []).append(bus)

    # Assign coordinates: x = layer, y = position within layer
    x_spacing = 150
    y_spacing = 100

    for layer, buses in layers.items():
        for i, bus in enumerate(buses):
            y_offset = (i - len(buses) / 2) * y_spacing
            coords[bus] = {"x": float(layer * x_spacing), "y": float(y_offset)}

    return coords


# ---------------------
#  Models
# ---------------------

class DiagnoseRequest(BaseModel):
    """Request body for the /diagnose endpoint."""
    network: str = "case14"
    scenario: str
    pipeline: str = "baseline"              # "baseline" or "agentic"


class DiagnoseResult(BaseModel):
    """Response body returned by the /diagnose endpoint."""
    baseline: dict
    agentic: dict


class DiagnoseNLRequest(BaseModel):
    """Request body for the /diagnose_nl endpoint."""
    network: str = "case14"
    description: str


class OverrideState(BaseModel):
    """State of manual network overrides from the frontend control board."""
    globalLoadScale: float = 1.0  # multiplier for all loads
    # In-service state maps (boolean only)
    lineStates: Dict[int, bool] = {}
    trafoStates: Dict[int, bool] = {}
    genStates: Dict[int, bool] = {}
    loadStates: Dict[int, bool] = {}
    extGridStates: Dict[int, bool] = {}
    # Value overrides (numeric properties)
    loadValues: Dict[int, Dict[str, float]] = {}   # e.g., {idx: {"p_mw": 50.0, "q_mvar": 20.0}}
    genValues: Dict[int, Dict[str, float]] = {}    # e.g., {idx: {"p_mw": 100.0, "vm_pu": 1.02}}
    extGridValues: Dict[int, Dict[str, float]] = {} # e.g., {idx: {"vm_pu": 1.02}}


def _apply_overrides(net: pp.pandapowerNet, overrides: OverrideState) -> None:
    """Apply manual overrides to a pandapower network (mutates net in place)."""
    # Global load scale
    if overrides.globalLoadScale != 1.0:
        if not net.load.empty and "p_mw" in net.load.columns:
            net.load["p_mw"] *= overrides.globalLoadScale
        if not net.load.empty and "q_mvar" in net.load.columns:
            net.load["q_mvar"] *= overrides.globalLoadScale

    # Line states (in_service)
    for idx_str, in_service in overrides.lineStates.items():
        idx = int(idx_str)
        if idx in net.line.index:
            net.line.at[idx, "in_service"] = in_service

    # Trafo states (in_service)
    for idx_str, in_service in overrides.trafoStates.items():
        idx = int(idx_str)
        if idx in net.trafo.index:
            net.trafo.at[idx, "in_service"] = in_service

    # Gen states (in_service)
    for idx_str, in_service in overrides.genStates.items():
        idx = int(idx_str)
        if idx in net.gen.index:
            net.gen.at[idx, "in_service"] = in_service

    # Gen values (p_mw, vm_pu)
    for idx_str, values in overrides.genValues.items():
        idx = int(idx_str)
        if idx in net.gen.index:
            if "p_mw" in values:
                net.gen.at[idx, "p_mw"] = values["p_mw"]
            if "vm_pu" in values:
                net.gen.at[idx, "vm_pu"] = values["vm_pu"]

    # Load states (in_service)
    for idx_str, in_service in overrides.loadStates.items():
        idx = int(idx_str)
        if idx in net.load.index:
            net.load.at[idx, "in_service"] = in_service

    # Load values (p_mw, q_mvar)
    for idx_str, values in overrides.loadValues.items():
        idx = int(idx_str)
        if idx in net.load.index:
            if "p_mw" in values:
                net.load.at[idx, "p_mw"] = values["p_mw"]
            if "q_mvar" in values:
                net.load.at[idx, "q_mvar"] = values["q_mvar"]

    # Ext grid states (in_service)
    for idx_str, in_service in overrides.extGridStates.items():
        idx = int(idx_str)
        if getattr(net, "ext_grid", None) is not None and idx in net.ext_grid.index:
            net.ext_grid.at[idx, "in_service"] = in_service

    # Ext grid values (vm_pu)
    for idx_str, values in overrides.extGridValues.items():
        idx = int(idx_str)
        if getattr(net, "ext_grid", None) is not None and idx in net.ext_grid.index:
            if "vm_pu" in values:
                net.ext_grid.at[idx, "vm_pu"] = values["vm_pu"]


class SimulateOverridesRequest(BaseModel):
    """Request body for testing manual overrides on an existing scenario."""
    network: str = "case14"
    scenario: str
    generatedCode: Optional[str] = None
    overrides: OverrideState
    llmAffectedComponents: Optional[Dict[str, List[int]]] = None


class NetworkStateRequest(BaseModel):
    """Request body to fetch the raw components of a network, potentially with NL code."""
    network: str = "case14"
    scenario: str
    generatedCode: Optional[str] = None
    llmAffectedComponents: Optional[Dict[str, List[int]]] = None


class ReDiagnoseRequest(BaseModel):
    """Request body for re-diagnosing with overrides applied."""
    network: str = "case14"
    scenario: str
    generatedCode: Optional[str] = None
    overrides: OverrideState



# ---------------------
#  GET  /networks
# ---------------------

@app.get("/networks")
def get_networks():
    """Return the list of available IEEE test networks for the dropdown."""
    return {"networks": NETWORKS}


# ---------------------
#  GET  /scenarios
# ---------------------

@app.get("/scenarios")
def get_scenarios():
    """Return the list of available failure scenarios for the dropdown."""
    return {"scenarios": SCENARIOS}



# ---------------------
#  POST /api/network_state
# ---------------------

@app.post("/api/network_state")
def get_network_state(req: NetworkStateRequest):
    """
    Return the raw network components data (buses, lines, generators)
    for a specific scenario (or generated NLP code).
    """
    # Handle NL-generated scenarios specially (not in SCENARIOS list)
    if req.scenario == "nl_generated" or req.scenario is None:
        net = load_network(req.network)
    else:
        scenario_obj, _ = _find_and_apply_scenario(req.scenario, req.network)
        net = scenario_obj.net

    # If it's an NLP-generated scenario, apply the generated code
    if req.generatedCode:
        execute_safely(req.generatedCode, net, timeout=5)

    # Try running power flow to get res_bus and res_line if possible
    converged = False
    try:
        pp.runpp(net)
        converged = getattr(net, "converged", False)
    except Exception:
        pass

    # Generate bus coordinates for visualization
    bus_coords = _generate_bus_coordinates(net)

    # Use LLM-identified affected components (if provided), not math-based
    affected_components = req.llmAffectedComponents or {}

    # Convert DataFrames to dicts (index-keyed for frontend compatibility)
    return {
        "bus": json.loads(net.bus.to_json(orient="index")),
        "line": json.loads(net.line.to_json(orient="index")),
        "load": json.loads(net.load.to_json(orient="index")) if getattr(net, "load", None) is not None and not net.load.empty else {},
        "gen": json.loads(net.gen.to_json(orient="index")) if getattr(net, "gen", None) is not None and not net.gen.empty else {},
        "trafo": json.loads(net.trafo.to_json(orient="index")) if getattr(net, "trafo", None) is not None and not net.trafo.empty else {},
        "ext_grid": json.loads(net.ext_grid.to_json(orient="index")) if getattr(net, "ext_grid", None) is not None and not net.ext_grid.empty else {},
        "res_bus": json.loads(net.res_bus.to_json(orient="index")) if getattr(net, "res_bus", None) is not None and not net.res_bus.empty else {},
        "res_line": json.loads(net.res_line.to_json(orient="index")) if getattr(net, "res_line", None) is not None and not net.res_line.empty else {},
        "bus_coords": bus_coords,
        "affected_components": affected_components,
        "converged": converged,
    }

# ---------------------
#  POST /api/simulate_overrides
# ---------------------

@app.post("/api/simulate_overrides")
def run_simulate_overrides(req: SimulateOverridesRequest):
    """
    Apply manual user overrides (sliders/toggles) to a base network scenario,
    run the power flow, and return the updated network state.
    """
    # Handle NL-generated scenarios specially (not in SCENARIOS list)
    if req.scenario == "nl_generated" or req.scenario is None:
        net = load_network(req.network)
    else:
        scenario_obj, _ = _find_and_apply_scenario(req.scenario, req.network)
        net = scenario_obj.net

    if req.generatedCode:
        execute_safely(req.generatedCode, net, timeout=5)

    # Apply manual overrides using helper
    _apply_overrides(net, req.overrides)

    # Run power flow
    converged = False
    try:
        pp.runpp(net)
        converged = getattr(net, "converged", False)
    except Exception:
        pass

    # Generate bus coordinates for visualization
    bus_coords = _generate_bus_coordinates(net)

    # Use LLM-identified affected components (if provided)
    affected_components = req.llmAffectedComponents or {}

    # Return full network state (same structure as /api/network_state)
    return {
        "bus": json.loads(net.bus.to_json(orient="index")),
        "line": json.loads(net.line.to_json(orient="index")),
        "load": json.loads(net.load.to_json(orient="index")) if getattr(net, "load", None) is not None and not net.load.empty else {},
        "gen": json.loads(net.gen.to_json(orient="index")) if getattr(net, "gen", None) is not None and not net.gen.empty else {},
        "trafo": json.loads(net.trafo.to_json(orient="index")) if getattr(net, "trafo", None) is not None and not net.trafo.empty else {},
        "ext_grid": json.loads(net.ext_grid.to_json(orient="index")) if getattr(net, "ext_grid", None) is not None and not net.ext_grid.empty else {},
        "res_bus": json.loads(net.res_bus.to_json(orient="index")) if getattr(net, "res_bus", None) is not None and not net.res_bus.empty else {},
        "res_line": json.loads(net.res_line.to_json(orient="index")) if getattr(net, "res_line", None) is not None and not net.res_line.empty else {},
        "bus_coords": bus_coords,
        "affected_components": affected_components,
        "converged": converged,
    }


# ---------------------
#  POST /api/rediagnose
# ---------------------

@app.post("/api/rediagnose")
def run_rediagnose(req: ReDiagnoseRequest):
    """
    Re-run LLM diagnosis on a network with manual overrides applied.
    Returns same structure as /diagnose.
    """
    print(f"[REDIAGNOSE] Received overrides: {req.overrides}")
    # Load base network
    if req.scenario == "nl_generated" or req.scenario is None:
        net = load_network(req.network)
    else:
        scenario_obj, _ = _find_and_apply_scenario(req.scenario, req.network)
        net = scenario_obj.net

    # Apply generated code if present
    if req.generatedCode:
        execute_safely(req.generatedCode, net, timeout=5)

    # Apply manual overrides using helper
    _apply_overrides(net, req.overrides)

    # Debug: show gen state after overrides
    print(f"[REDIAGNOSE] Gen table after overrides:\n{net.gen[['bus', 'p_mw', 'vm_pu', 'in_service']]}")

    # Run power flow
    try:
        pp.runpp(net)
        print(f"[REDIAGNOSE] Power flow converged: {net.converged}")
    except Exception as e:
        print(f"[REDIAGNOSE] Power flow failed: {e}")

    # Run both diagnosis pipelines
    baseline_result = _baseline_agent.diagnose(net, network_name=req.network)
    baseline_report = baseline_result["response"]
    baseline_status = "success" if not baseline_report.startswith("LLM call failed") else "error"
    baseline = _build_pipeline_result(baseline_report, baseline_status)

    try:
        agentic_result = _agentic_agent.diagnose(net, network_name=req.network)
        agentic_report = agentic_result["response"]
        agentic_status = "success"
        if agentic_report.startswith("Agent loop error") or agentic_report.startswith("LLM call failed"):
            agentic_status = "error"
        agentic = _build_pipeline_result(agentic_report, agentic_status)
        agentic["tool_calls"] = agentic_result.get("tool_calls", [])
        agentic["conversation"] = agentic_result.get("conversation", [])
    except Exception:
        agentic = {
            "analysisStatus": "error",
            "rootCauses": [],
            "affectedComponents": [],
            "correctiveActions": [],
            "parsedAffectedComponents": {},
        }

    return {"baseline": baseline, "agentic": agentic}


# ---------------------
#  POST /diagnose
# ---------------------

@app.post("/diagnose", response_model=DiagnoseResult)
def run_diagnose(req: DiagnoseRequest):
    """
    Run the selected scenario on the chosen network through both
    baseline and agentic pipelines, returning structured diagnosis results.
    """
    # Validate network
    valid_networks = [n["id"] for n in NETWORKS]
    if req.network not in valid_networks:
        raise HTTPException(400, f"Unknown network: {req.network}. Choose from {valid_networks}")

    # Apply the scenario to get a modified network
    scenario_obj, ground_truth = _find_and_apply_scenario(req.scenario, req.network)
    net = scenario_obj.net

    # Attempt power flow
    scenario_obj.run_pf()

    # --- Baseline pipeline ---
    baseline_result = _baseline_agent.diagnose(net, network_name=req.network)
    baseline_report = baseline_result["response"]
    baseline_status = "success"
    if baseline_report.startswith("LLM call failed"):
        baseline_status = "error"
    baseline = _build_pipeline_result(baseline_report, baseline_status)

    # --- Agentic pipeline (with tools) ---
    try:
        agentic_result = _agentic_agent.diagnose(net, network_name=req.network)
        agentic_report = agentic_result["response"]
        agentic_status = "success"
        if agentic_report.startswith("Agent loop error") or agentic_report.startswith("LLM call failed"):
            agentic_status = "error"
        agentic = _build_pipeline_result(agentic_report, agentic_status)
        agentic["tool_calls"] = agentic_result.get("tool_calls", [])
        agentic["conversation"] = agentic_result.get("conversation", [])
    except Exception as e:
        agentic = {
            "analysisStatus": "error",
            "rootCauses": [],
            "affectedComponents": [],
            "correctiveActions": [],
        }

    return DiagnoseResult(baseline=baseline, agentic=agentic)


# ---------------------
#  POST /diagnose_nl
# ---------------------

@app.post("/diagnose_nl")
def run_diagnose_nl(req: DiagnoseNLRequest):
    """
    Generate a failure scenario from a natural language description,
    then run it through the diagnosis pipelines.
    """
    # Validate network
    valid_networks = [n["id"] for n in NETWORKS]
    if req.network not in valid_networks:
        raise HTTPException(400, f"Unknown network: {req.network}. Choose from {valid_networks}")

    # Generate the scenario from NL
    gen_result = _nl_generator.generate(
        description=req.description,
        network_name=req.network,
    )

    if gen_result["generation_status"] != "success":
        return {
            "generationStatus": "error",
            "generationError": gen_result["error"],
            "generatedCode": gen_result.get("generated_code", ""),
            "generatedGroundTruth": None,
            "baseline": {
                "analysisStatus": "skipped",
                "rootCauses": [],
                "affectedComponents": [],
                "correctiveActions": [],
            },
            "agentic": {
                "analysisStatus": "skipped",
                "rootCauses": [],
                "affectedComponents": [],
                "correctiveActions": [],
            },
            "responseType": gen_result.get("response_type", "full_diagnosis"),
            "textAnswer": gen_result.get("text_answer", ""),
            "agentic": {
                "analysisStatus": "skipped",
                "rootCauses": [],
                "affectedComponents": [],
                "correctiveActions": [],
            },
        }

    net = gen_result["net"]
    ground_truth = gen_result["ground_truth"]

    response_type = gen_result.get("response_type", "full_diagnosis")
    text_answer = gen_result.get("text_answer", "")

    # For text-only simple questions, skip power flow and diagnosis
    if response_type == "text_only":
        return {
            "generationStatus": "success",
            "generationError": None,
            "generatedCode": gen_result["generated_code"],
            "generatedGroundTruth": {
                "failureType": ground_truth.failure_type,
                "rootCauses": ground_truth.root_causes,
                "affectedComponents": ground_truth.affected_components,
                "knownFix": ground_truth.known_fix,
            },
            "baseline": {"analysisStatus": "skipped", "rootCauses": [], "affectedComponents": [], "correctiveActions": []},
            "agentic": {"analysisStatus": "skipped", "rootCauses": [], "affectedComponents": [], "correctiveActions": []},
            "responseType": response_type,
            "textAnswer": text_answer,
        }

    # For plot-only or full-diagnosis, we run power flow
    try:
        pp.runpp(net)
    except Exception:
        pass

    # For plot-only, skip the LLM diagnosis
    if response_type == "plot_only":
        return {
            "generationStatus": "success",
            "generationError": None,
            "generatedCode": gen_result["generated_code"],
            "generatedGroundTruth": {
                "failureType": ground_truth.failure_type,
                "rootCauses": ground_truth.root_causes,
                "affectedComponents": ground_truth.affected_components,
                "knownFix": ground_truth.known_fix,
            },
            "baseline": {"analysisStatus": "skipped", "rootCauses": [], "affectedComponents": [], "correctiveActions": []},
            "agentic": {"analysisStatus": "skipped", "rootCauses": [], "affectedComponents": [], "correctiveActions": []},
            "responseType": response_type,
            "textAnswer": text_answer,
        }

    # --- Baseline pipeline ---
    baseline_result = _baseline_agent.diagnose(net, network_name=req.network, user_query=req.description)
    baseline_report = baseline_result["response"]
    baseline_status = "success"
    if baseline_report.startswith("LLM call failed"):
        baseline_status = "error"
    baseline = _build_pipeline_result(baseline_report, baseline_status)

    # --- Agentic pipeline ---
    try:
        agentic_result = _agentic_agent.diagnose(net, network_name=req.network, user_query=req.description)
        agentic_report = agentic_result["response"]
        agentic_status = "success"
        if agentic_report.startswith("Agent loop error") or agentic_report.startswith("LLM call failed"):
            agentic_status = "error"
        agentic = _build_pipeline_result(agentic_report, agentic_status)
        agentic["tool_calls"] = agentic_result.get("tool_calls", [])
        agentic["conversation"] = agentic_result.get("conversation", [])
    except Exception:
        agentic = {
            "analysisStatus": "error",
            "rootCauses": [],
            "affectedComponents": [],
            "correctiveActions": [],
        }

    return {
        "generationStatus": "success",
        "generationError": None,
        "generatedCode": gen_result["generated_code"],
        "generatedGroundTruth": {
            "failureType": ground_truth.failure_type,
            "rootCauses": ground_truth.root_causes,
            "affectedComponents": ground_truth.affected_components,
            "knownFix": ground_truth.known_fix,
        },
        "baseline": baseline,
        "agentic": agentic,
        "responseType": response_type,
        "textAnswer": text_answer,
    }


# ---------------------
#  Entrypoint
# ---------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
