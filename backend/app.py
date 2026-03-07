import os
import re
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import pandas as pd

import pandas as pd
from typing import Optional, Dict, List, Any

import pandapower as pp
from pandapower.plotting.plotly import simple_plotly, create_bus_trace, create_line_trace, create_trafo_trace
from scenarios.code_sandbox import execute_safely

from openai import OpenAI

from scenarios import (
    NonConvergenceScenarios,
    VoltageViolationScenarios,
    ThermalOverloadScenarios,
    ContingencyFailureScenarios,
    NormalScenarios,
)
from agents.baseline import BaselineAgent
from agents.agentic_pipeline import AgenticPipelineAgent
from agents.iterative_debugger import IterativeDebuggerAgent
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
_iterative_agent = IterativeDebuggerAgent(llm_client=_llm_client)
_nl_generator = NLScenarioGenerator(llm_client=_llm_client)


# ---------------------
#  Constants
# ---------------------

import inspect
import pandapower.networks as nw

def _get_available_networks() -> list[dict]:
    networks = []
    common_cases = ["case14", "case30", "case39", "case57", "case118", "case300"]
    
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
    if scenario_id == "nl_generated":
        scenario_id = "normal_operation"

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
      - Various markdown headers (##, **, etc.)
    """
    result = {"rootCauses": [], "affectedComponents": [], "correctiveActions": []}

    def _normalize_block(text: str) -> str:
        text = text.strip()
        # Convert " - " into real bullets on new lines
        text = re.sub(r"\s-\s", r"\n- ", text)
        # Convert " 1. " into numbered items on new lines
        text = re.sub(r"\s(\d+)\.\s+", r"\n\1. ", text)
        return text.strip()

    def _extract_items(block: str) -> list[str]:
        items: list[str] = []
        for line in _normalize_block(block).split("\n"):
            line = line.strip()
            # Remove leading/trailing bold markers
            if line.startswith("**") and line.endswith("**"):
                line = line[2:-2].strip()
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
            items.append(line)
        if not items and block.strip():
            return [block.strip()]
        return items

    def extract_section_items(text: str, section: str) -> list[str]:
        lines = text.split("\n")
        in_section = False
        captured_lines = []
        
        section_lower = section.lower()
        known_headers = ["root causes", "affected components", "corrective actions", "reasoning trace"]
        
        for line in lines:
            line_lower = line.lower()
            
            # Check if this line is ANY header
            is_any_header = False
            for h in known_headers:
                # Look for header near the start of the line, ignoring markdown markers
                cleaned_line = re.sub(r'^[\s#*\-\d.]+', '', line_lower).strip()
                if cleaned_line.startswith(h):
                    is_any_header = True
                    break
                    
            if is_any_header:
                cleaned_line = re.sub(r'^[\s#*\-\d.]+', '', line_lower).strip()
                if cleaned_line.startswith(section_lower):
                    in_section = True
                    # Check if there's content on the same line after a colon or **
                    if ":" in line:
                        content_after_colon = line.split(":", 1)[1].strip()
                        if content_after_colon:
                            # if it ends with bold marker, strip it
                            if content_after_colon.endswith("**"):
                                content_after_colon = content_after_colon[:-2]
                            captured_lines.append(content_after_colon)
                else:
                    in_section = False
            elif in_section:
                captured_lines.append(line)
                
        return _extract_items("\n".join(captured_lines))

    result["rootCauses"] = extract_section_items(report, "Root Causes")
    result["affectedComponents"] = extract_section_items(report, "Affected Components")
    result["correctiveActions"] = extract_section_items(report, "Corrective Actions")

    return result


def _build_pipeline_result(report: str, analysis_status: str = "success") -> dict:
    """Build pipeline result with analysisStatus and parsed fields."""
    parsed = _parse_llm_report(report)
    return {
        "analysisStatus": analysis_status,
        "rootCauses": parsed["rootCauses"],
        "affectedComponents": parsed["affectedComponents"],
        "correctiveActions": parsed["correctiveActions"],
        "rawResult": report,
    }


def _format_reasoning_trace(tool_calls: list, final_report_snippet: str | None = None, max_result_len: int = 400) -> str:
    """Build a human-readable full reasoning trace for the agentic pipeline."""
    lines = [
        "=== Agentic reasoning trace ===",
        "Input: evidence text + triggered rules + failure_category (from Preprocessor).",
        "",
    ]
    for i, tc in enumerate(tool_calls, 1):
        tool = tc.get("tool", "?")
        args = tc.get("args") or {}
        result = tc.get("result")
        it = tc.get("iteration", i - 1)
        args_str = json.dumps(args, default=str) if args else ""
        if isinstance(result, dict):
            result_str = json.dumps(result, default=str)
        else:
            result_str = str(result)
        if len(result_str) > max_result_len:
            result_str = result_str[:max_result_len] + "..."
        lines.append(f"Step {i} (iteration {it}): Called {tool}({args_str})")
        lines.append(f"  → result: {result_str}")
        lines.append("")
    lines.append("Final step: Produced FINAL REPORT (parsed into root causes, affected components, corrective actions).")
    if final_report_snippet:
        snippet = (final_report_snippet[:800] + "...") if len(final_report_snippet) > 800 else final_report_snippet
        lines.append("")
        lines.append("--- Report snippet ---")
        lines.append(snippet)
    return "\n".join(lines)


def _evaluate_reasoning_quality(
    tool_calls: list,
    root_causes: list,
    affected_components: list,
    corrective_actions: list,
) -> dict:
    """
    Heuristic checks: does the agent's tool usage support what it claimed in the report?
    Returns { "checks": [ {"id", "passed", "message"} ], "summary": "x/y passed" }.
    """
    report_text = " ".join(root_causes + affected_components + corrective_actions).lower()
    tools_used = [tc.get("tool", "") for tc in tool_calls]
    checks = []

    # 1. Agent used at least one tool (gathered evidence)
    used_tools = len(tool_calls) > 0
    checks.append({
        "id": "used_tools",
        "passed": used_tools,
        "message": "Agent called at least one tool to gather evidence." if used_tools else "Agent produced report without calling any tools (no tool-based evidence).",
    })

    # 2. If report mentions overload/loading/thermal → expect relevant tools
    overload_keywords = ["overload", "loading", "thermal", "line loading", "congestion"]
    mentions_overload = any(k in report_text for k in overload_keywords)
    overload_tools = ["check_overloads", "get_loading_profile", "run_full_diagnostics", "run_power_flow", "run_dc_power_flow"]
    has_overload_evidence = any(t in tools_used for t in overload_tools)
    if mentions_overload:
        checks.append({
            "id": "evidence_for_overload",
            "passed": has_overload_evidence,
            "message": "Report mentions overload/loading; agent used overload/flow/diagnostic tools." if has_overload_evidence else "Report mentions overload/loading but agent did not call overload or power-flow tools.",
        })

    # 3. If report mentions voltage → expect voltage-related tools
    voltage_keywords = ["voltage", "vm_pu", "violation", "undervoltage", "overvoltage"]
    mentions_voltage = any(k in report_text for k in voltage_keywords)
    voltage_tools = ["check_voltage_violations", "get_voltage_profile"]
    has_voltage_evidence = any(t in tools_used for t in voltage_tools)
    if mentions_voltage:
        checks.append({
            "id": "evidence_for_voltage",
            "passed": has_voltage_evidence,
            "message": "Report mentions voltage; agent used voltage-related tools." if has_voltage_evidence else "Report mentions voltage but agent did not call voltage tools.",
        })

    # 4. If report mentions balance/generation/load/convergence → expect balance or flow tools
    balance_keywords = ["balance", "generation", "load", "convergence", "imbalance", "gen", "demand"]
    mentions_balance = any(k in report_text for k in balance_keywords)
    balance_tools = ["get_power_balance", "get_network_summary", "run_power_flow", "run_full_diagnostics"]
    has_balance_evidence = any(t in tools_used for t in balance_tools)
    if mentions_balance:
        checks.append({
            "id": "evidence_for_balance",
            "passed": has_balance_evidence,
            "message": "Report mentions balance/load/gen; agent used balance or flow tools." if has_balance_evidence else "Report mentions balance/load/gen but agent did not call power-balance or flow tools.",
        })

    # 5. Diagnostic order: power flow before overload/voltage checks (if those were used)
    flow_tools = ["run_power_flow", "run_dc_power_flow", "run_full_diagnostics"]
    diag_tools = ["check_overloads", "check_voltage_violations"]
    flow_indices = [i for i, t in enumerate(tools_used) if t in flow_tools]
    diag_indices = [i for i, t in enumerate(tools_used) if t in diag_tools]
    order_ok = True
    if diag_indices and flow_indices:
        order_ok = min(flow_indices) < max(diag_indices)
    checks.append({
        "id": "reasonable_order",
        "passed": order_ok,
        "message": "Power flow / full diagnostics ran before overload/voltage checks (data before diagnosis)." if order_ok else "Overload/voltage checks ran but no prior power-flow/diagnostics call; consider running flow first.",
    })

    passed = sum(1 for c in checks if c["passed"])
    total = len(checks)
    return {
        "checks": checks,
        "summary": f"{passed}/{total} checks passed",
        "passedCount": passed,
        "totalCount": total,
    }


def _generate_diagnostic_plot(net: pp.pandapowerNet, affected_components: dict) -> str:
    """
    Generate an HTML string with a Plotly visualization of the network,
    highlighting the affected components in red.
    """
    try:
        # Build additional traces for affected components
        additional_traces = []
        
        # Highlight affected buses (including those from loads and gens)
        buses_to_highlight = set(affected_components.get("bus", []))
        
        if "load" in affected_components and affected_components["load"]:
            for idx in affected_components["load"]:
                if idx in net.load.index:
                    buses_to_highlight.add(net.load.at[idx, "bus"])
                    
        if "gen" in affected_components and affected_components["gen"]:
            for idx in affected_components["gen"]:
                if idx in net.gen.index:
                    buses_to_highlight.add(net.gen.at[idx, "bus"])
                    
        if "sgen" in affected_components and affected_components["sgen"]:
            for idx in affected_components["sgen"]:
                if idx in net.sgen.index:
                    buses_to_highlight.add(net.sgen.at[idx, "bus"])

        if buses_to_highlight:
            valid_buses = [b for b in buses_to_highlight if b in net.bus.index]
            if valid_buses:
                trace_bus = create_bus_trace(
                    net,
                    buses=valid_buses,
                    color="red",
                    size=25.0,  # Make it large and obvious
                    trace_name="Affected Buses/Components",
                    infofunc=pd.Series(index=valid_buses, data=[f"Affected Component at Bus {b}" for b in valid_buses])
                )
                additional_traces.extend(trace_bus)
                
        # Highlight affected lines
        if "line" in affected_components and affected_components["line"]:
            lines_to_highlight = set(affected_components["line"])
            valid_lines = [l for l in lines_to_highlight if l in net.line.index]
            if valid_lines:
                trace_line = create_line_trace(
                    net,
                    lines=valid_lines,
                    color="red",
                    width=4.0,
                    trace_name="Affected Lines",
                    infofunc=pd.Series(index=valid_lines, data=[f"Affected Line {l}" for l in valid_lines])
                )
                additional_traces.extend(trace_line)

        # Highlight affected trafos
        if "trafo" in affected_components and affected_components["trafo"]:
            trafos_to_highlight = set(affected_components["trafo"])
            valid_trafos = [t for t in trafos_to_highlight if t in net.trafo.index]
            if valid_trafos:
                trace_trafo = create_trafo_trace(
                    net,
                    trafos=valid_trafos,
                    color="red",
                    width=4.0,
                    trace_name="Affected Transformers"
                )
                additional_traces.extend(trace_trafo)

        # Draw all generators (gen, sgen, ext_grid) regardless of whether they are affected
        # This ensures they are always visible on the map.
        if hasattr(net, 'ext_grid') and not net.ext_grid.empty:
            additional_traces.extend(create_bus_trace(net, buses=net.ext_grid.bus.tolist(), size=20.0, color="yellow", trace_name="External Grid"))
            
        if hasattr(net, 'gen') and not net.gen.empty:
            additional_traces.extend(create_bus_trace(net, buses=net.gen.bus.tolist(), size=15.0, color="orange", trace_name="Generators"))
            
        if hasattr(net, 'sgen') and not net.sgen.empty:
            additional_traces.extend(create_bus_trace(net, buses=net.sgen.bus.tolist(), size=15.0, color="goldenrod", trace_name="Static Generators"))

        # Create a deep copy of the network to temporarily modify bus names for plotting
        import copy
        plot_net = copy.deepcopy(net)
        
        # Override the 'name' column of buses to explicitly equal the DataFrame index as a string
        # simple_plotly relies on the 'name' column by default to render hover text
        plot_net.bus['name'] = [f"{idx}" for idx in plot_net.bus.index]

        # Create the base plot with the additional highlight traces
        fig = simple_plotly(
            plot_net,
            additional_traces=additional_traces,
            auto_open=False
        )
        
        # Add legend if there are custom traces
        if additional_traces:
            fig.update_layout(showlegend=True)
            
        return fig.to_html(include_plotlyjs="cdn", full_html=True)

    except Exception as e:
        print(f"Failed to generate diagnostic plot: {e}")
        return "<p>Failed to generate visualization.</p>"


# ---------------------
#  Models
# ---------------------

class DiagnoseRequest(BaseModel):
    """Request body for the /diagnose endpoint."""
    network: str = "case14"
    scenario: str
    pipeline: str = "baseline"              # "baseline" or "agentic"
    query: Optional[str] = None             # optional user/benchmark query (e.g. paper queries)


class DiagnoseResult(BaseModel):
    """Response body returned by the /diagnose endpoint."""
    baseline: dict
    agentic: dict
    iterative: dict = {}
    plotHtml: str = ""


class DiagnoseNLRequest(BaseModel):
    """Request body for the /diagnose_nl endpoint."""
    network: str = "case14"
    description: str


class OverrideState(BaseModel):
    """State of manual network overrides from the frontend control board."""
    globalLoadScale: float = 1.0  # multiplier for all loads
    lineOutages: List[int] = []   # list of line indices to set in_service=False
    trafoOutages: List[int] = []  # list of trafo indices to set in_service=False
    loadOverrides: Dict[int, Dict[str, float]] = {} # e.g., {idx: {"p_mw": 50.0, "q_mvar": 20.0, "in_service": 1.0/0.0}}
    genOverrides: Dict[int, Dict[str, float]] = {}  # e.g., {idx: {"p_mw": 100.0, "vm_pu": 1.02, "in_service": 1.0/0.0}}
    extGridOverrides: Dict[int, Dict[str, float]] = {} # e.g., {idx: {"vm_pu": 1.02, "in_service": 1.0/0.0}}


class SimulateOverridesRequest(BaseModel):
    """Request body for testing manual overrides on an existing scenario."""
    network: str = "case14"
    scenario: str
    generatedCode: Optional[str] = None
    overrides: OverrideState


class NetworkStateRequest(BaseModel):
    """Request body to fetch the raw components of a network, potentially with NL code."""
    network: str = "case14"
    scenario: str
    generatedCode: Optional[str] = None



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
    scenario_obj, _ = _find_and_apply_scenario(req.scenario, req.network)
    net = scenario_obj.net

    # If it's an NLP-generated scenario, we need to apply the generated code
    if req.generatedCode:
        execute_safely(req.generatedCode, net, timeout=5)

    # Try running power flow to get res_bus and res_line if possible
    try:
        pp.runpp(net)
    except Exception:
        pass
    
    # Convert DataFrames to dicts, handling NaNs
    return {
        "bus": json.loads(net.bus.to_json(orient="records")),
        "line": json.loads(net.line.to_json(orient="records")),
        "load": json.loads(net.load.to_json(orient="records")) if getattr(net, "load", None) is not None and not net.load.empty else [],
        "gen": json.loads(net.gen.to_json(orient="records")) if getattr(net, "gen", None) is not None and not net.gen.empty else [],
        "trafo": json.loads(net.trafo.to_json(orient="records")) if getattr(net, "trafo", None) is not None and not net.trafo.empty else [],
        "ext_grid": json.loads(net.ext_grid.to_json(orient="records")) if getattr(net, "ext_grid", None) is not None and not net.ext_grid.empty else [],
        "res_bus": json.loads(net.res_bus.to_json(orient="records")) if getattr(net, "res_bus", None) is not None and not net.res_bus.empty else [],
        "res_line": json.loads(net.res_line.to_json(orient="records")) if getattr(net, "res_line", None) is not None and not net.res_line.empty else [],
    }

# ---------------------
#  POST /api/simulate_overrides
# ---------------------

@app.post("/api/simulate_overrides")
def run_simulate_overrides(req: SimulateOverridesRequest):
    """
    Apply manual user overrides (sliders/toggles) to a base network scenario,
    run the power flow, and return the new plot HTML and status.
    """
    scenario_obj, _ = _find_and_apply_scenario(req.scenario, req.network)
    net = scenario_obj.net

    if req.generatedCode:
        execute_safely(req.generatedCode, net, timeout=5)

    # Apply manual overrides
    overrides = req.overrides

    # Global scale
    if overrides.globalLoadScale != 1.0:
        if not net.load.empty and "p_mw" in net.load.columns:
            net.load["p_mw"] *= overrides.globalLoadScale
        if not net.load.empty and "q_mvar" in net.load.columns:
            net.load["q_mvar"] *= overrides.globalLoadScale

    # Line outages
    for idx in overrides.lineOutages:
        if idx in net.line.index:
            net.line.at[idx, "in_service"] = False

    # Trafo outages
    for idx in overrides.trafoOutages:
        if idx in net.trafo.index:
            net.trafo.at[idx, "in_service"] = False

    # Ext grid overrides
    for idx_str, values in overrides.extGridOverrides.items():
        idx = int(idx_str)
        if getattr(net, "ext_grid", None) is not None and idx in net.ext_grid.index:
            for k, v in values.items():
                net.ext_grid.at[idx, k] = v

    # Load overrides
    for idx_str, values in overrides.loadOverrides.items():
        idx = int(idx_str)
        if idx in net.load.index:
            if "p_mw" in values:
                net.load.at[idx, "p_mw"] = values["p_mw"]
            if "q_mvar" in values:
                net.load.at[idx, "q_mvar"] = values["q_mvar"]
            if "in_service" in values:
                net.load.at[idx, "in_service"] = bool(values["in_service"])

    # Gen overrides
    for idx_str, values in overrides.genOverrides.items():
        idx = int(idx_str)
        if idx in net.gen.index:
            if "p_mw" in values:
                net.gen.at[idx, "p_mw"] = values["p_mw"]
            if "vm_pu" in values:
                net.gen.at[idx, "vm_pu"] = values["vm_pu"]
            if "in_service" in values:
                net.gen.at[idx, "in_service"] = bool(values["in_service"])

    # Run power flow
    converged = False
    try:
        pp.runpp(net)
        converged = getattr(net, "converged", False)
    except Exception:
        pass

    # Basic root cause string if it failed
    root_causes = []
    affected_components = {}
    if not converged:
        root_causes.append("**Non-convergence**: Power flow failed with the current manual overrides.")
    else:
        v_min_global, v_max_global = 0.95, 1.05
        if not net.res_bus.empty:
            has_voltage_issues = False
            for idx, row in net.res_bus.iterrows():
                b_min = net.bus.at[idx, "min_vm_pu"] if "min_vm_pu" in net.bus.columns and pd.notna(net.bus.at[idx, "min_vm_pu"]) else v_min_global
                b_max = net.bus.at[idx, "max_vm_pu"] if "max_vm_pu" in net.bus.columns and pd.notna(net.bus.at[idx, "max_vm_pu"]) else v_max_global
                
                if row["vm_pu"] < b_min or row["vm_pu"] > b_max:
                    has_voltage_issues = True
                    affected_components.setdefault("bus", []).append(int(idx))
            
            if has_voltage_issues:
                root_causes.append("**Voltage Violations**: Buses found outside their specific voltage bounds.")
        
        if not net.res_line.empty:
            ol = net.res_line[net.res_line["loading_percent"] > 100].index.tolist()
            if ol:
                root_causes.append("**Thermal Overloads**: Lines loaded above 100%.")
                affected_components["line"] = ol

    plot_html = _generate_diagnostic_plot(net, affected_components)

    return {
        "converged": converged,
        "plotHtml": plot_html,
        "rootCauses": root_causes,
    }


def _get_combined_affected_components(net: pp.pandapowerNet, base_components: dict = None) -> dict:
    """Merge predefined affected components with dynamically found violations."""
    import copy
    combined = copy.deepcopy(base_components) if base_components else {}
    
    # Try to find voltage violations
    v_min_global, v_max_global = 0.95, 1.05
    if getattr(net, "res_bus", None) is not None and not net.res_bus.empty:
        for idx, row in net.res_bus.iterrows():
            b_min = net.bus.at[idx, "min_vm_pu"] if "min_vm_pu" in net.bus.columns and pd.notna(net.bus.at[idx, "min_vm_pu"]) else v_min_global
            b_max = net.bus.at[idx, "max_vm_pu"] if "max_vm_pu" in net.bus.columns and pd.notna(net.bus.at[idx, "max_vm_pu"]) else v_max_global
            
            if row["vm_pu"] < b_min or row["vm_pu"] > b_max:
                combined.setdefault("bus", []).append(int(idx))
                
    if "bus" in combined:
        combined["bus"] = list(set(combined["bus"]))
        
    # Try to find thermal overloads
    if getattr(net, "res_line", None) is not None and not net.res_line.empty:
        ol = net.res_line[net.res_line["loading_percent"] > 100].index.tolist()
        if ol:
            combined.setdefault("line", []).extend(ol)
            combined["line"] = list(set(combined["line"]))
            
    return combined


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

    user_query = (req.query or "").strip() or ""

    # --- Baseline pipeline ---
    baseline_result = _baseline_agent.diagnose(net, network_name=req.network, user_query=user_query)
    baseline_report = baseline_result["response"]
    baseline_status = "success"
    if baseline_report.startswith("LLM call failed"):
        baseline_status = "error"
    baseline = _build_pipeline_result(baseline_report, baseline_status)

    try:
        agentic_result = _agentic_agent.diagnose(net, network_name=req.network, user_query=user_query)
        agentic_report = agentic_result["response"]
        agentic_status = "success"
        if agentic_report.startswith("Agent loop error") or agentic_report.startswith("LLM call failed"):
            agentic_status = "error"
        agentic = _build_pipeline_result(agentic_report, agentic_status)
        tool_calls = agentic_result.get("tool_calls", [])
        agentic["toolCalls"] = tool_calls
        agentic["conversation"] = agentic_result.get("conversation", [])
        agentic["executionTrace"] = tool_calls
        reasoning_trace = _format_reasoning_trace(tool_calls, agentic_report)
        agentic["reasoningTrace"] = reasoning_trace
        agentic["reasoningQuality"] = _evaluate_reasoning_quality(
            tool_calls,
            agentic.get("rootCauses", []),
            agentic.get("affectedComponents", []),
            agentic.get("correctiveActions", []),
        )
        print("\n" + reasoning_trace + "\n")
    except Exception as e:
        agentic = {
            "analysisStatus": "error",
            "rootCauses": [],
            "affectedComponents": [],
            "correctiveActions": [],
            "toolCalls": [],
            "reasoningTrace": f"Agent failed: {e}",
            "reasoningQuality": {"checks": [], "summary": "N/A (agent failed)", "passedCount": 0, "totalCount": 0},
        }

    # --- Iterative debugger pipeline (Level 3: diagnose + fix loop) ---
    try:
        # Re-apply scenario for a fresh network (agentic pipeline may have modified it)
        scenario_obj_iter, _ = _find_and_apply_scenario(req.scenario, req.network)
        net_iter = scenario_obj_iter.net
        scenario_obj_iter.run_pf()

        iter_result = _iterative_agent.diagnose(net_iter, network_name=req.network)
        iter_report = iter_result["response"]
        iter_status = "success"
        if iter_report.startswith("Agent loop error") or iter_report.startswith("LLM call failed"):
            iter_status = "error"
        iterative = _build_pipeline_result(iter_report, iter_status)
        iterative["fixHistory"] = iter_result.get("fix_history", [])
        iterative["finalConverged"] = iter_result.get("final_converged", False)
        iterative["iterationsUsed"] = iter_result.get("iterations_used", 0)
        iterative["executionTrace"] = iter_result.get("fix_history", [])
    except Exception as e:
        iterative = {
            "analysisStatus": "error",
            "rootCauses": [],
            "affectedComponents": [],
            "correctiveActions": [],
            "fixHistory": [],
            "finalConverged": False,
            "iterationsUsed": 0,
            "executionTrace": [],
            "error": str(e),
        }

    # Generate visualization
    combined_components = _get_combined_affected_components(net, ground_truth.affected_components)
    plot_html = _generate_diagnostic_plot(net, combined_components)

    return DiagnoseResult(baseline=baseline, agentic=agentic, iterative=iterative, plotHtml=plot_html)


# ---------------------
#  POST /diagnose_stream  (Server-Sent Events)
# ---------------------

from fastapi.responses import StreamingResponse
import asyncio, traceback

@app.post("/diagnose_stream")
async def run_diagnose_stream(req: DiagnoseRequest):
    """
    Same as /diagnose, but streams each pipeline result as a Server-Sent Event
    the moment it completes:  plot → baseline → agentic → iterative → done.
    Sync pipeline calls are offloaded to threads so the event loop can flush.
    """
    valid_networks = [n["id"] for n in NETWORKS]
    if req.network not in valid_networks:
        raise HTTPException(400, f"Unknown network: {req.network}")

    def _sse_event(event: str, data: dict) -> str:
        payload = json.dumps(data, default=str)
        return f"event: {event}\ndata: {payload}\n\n"

    # ---------- sync helpers (run in thread pool) ----------
    def _run_baseline(net, network_name, user_query):
        try:
            r = _baseline_agent.diagnose(net, network_name=network_name, user_query=user_query)
            report = r["response"]
            status = "error" if report.startswith("LLM call failed") else "success"
            return _build_pipeline_result(report, status)
        except Exception as e:
            return {"analysisStatus": "error", "rootCauses": [], "affectedComponents": [],
                    "correctiveActions": [], "rawResult": str(e)}

    def _run_agentic(net, network_name, user_query):
        try:
            r = _agentic_agent.diagnose(net, network_name=network_name, user_query=user_query)
            report = r["response"]
            status = "success"
            if report.startswith("Agent loop error") or report.startswith("LLM call failed"):
                status = "error"
            out = _build_pipeline_result(report, status)
            tc = r.get("tool_calls", [])
            out["toolCalls"] = tc
            out["conversation"] = r.get("conversation", [])
            out["executionTrace"] = tc
            out["reasoningTrace"] = _format_reasoning_trace(tc, report)
            out["reasoningQuality"] = _evaluate_reasoning_quality(
                tc, out.get("rootCauses", []), out.get("affectedComponents", []),
                out.get("correctiveActions", []))
            return out
        except Exception as e:
            return {"analysisStatus": "error", "rootCauses": [], "affectedComponents": [],
                    "correctiveActions": [], "toolCalls": [], "reasoningTrace": f"Agent failed: {e}",
                    "reasoningQuality": {"checks": [], "summary": "N/A", "passedCount": 0, "totalCount": 0}}

    def _run_iterative(scenario_id, network_name):
        try:
            s, _ = _find_and_apply_scenario(scenario_id, network_name)
            s.run_pf()
            r = _iterative_agent.diagnose(s.net, network_name=network_name)
            report = r["response"]
            status = "success"
            if report.startswith("Agent loop error") or report.startswith("LLM call failed"):
                status = "error"
            out = _build_pipeline_result(report, status)
            out["fixHistory"] = r.get("fix_history", [])
            out["finalConverged"] = r.get("final_converged", False)
            out["iterationsUsed"] = r.get("iterations_used", 0)
            out["executionTrace"] = r.get("fix_history", [])
            return out
        except Exception as e:
            return {"analysisStatus": "error", "rootCauses": [], "affectedComponents": [],
                    "correctiveActions": [], "fixHistory": [], "finalConverged": False,
                    "iterationsUsed": 0, "executionTrace": [], "error": str(e)}

    async def event_generator():
        # Apply scenario
        scenario_obj, ground_truth = _find_and_apply_scenario(req.scenario, req.network)
        net = scenario_obj.net
        scenario_obj.run_pf()
        user_query = (req.query or "").strip() or ""

        # 1) Plot — instant, no LLM
        try:
            combined = _get_combined_affected_components(net, ground_truth.affected_components)
            plot_html = _generate_diagnostic_plot(net, combined)
        except Exception:
            plot_html = ""
        yield _sse_event("plot", {"plotHtml": plot_html})

        # 2) Baseline — offload to thread so yield actually flushes
        baseline = await asyncio.to_thread(_run_baseline, net, req.network, user_query)
        yield _sse_event("baseline", baseline)

        # 3) Agentic
        agentic = await asyncio.to_thread(_run_agentic, net, req.network, user_query)
        yield _sse_event("agentic", agentic)

        # 4) Iterative debugger (fresh network)
        iterative = await asyncio.to_thread(_run_iterative, req.scenario, req.network)
        yield _sse_event("iterative", iterative)

        # 5) Done
        yield _sse_event("done", {"status": "complete"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")
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
            "plotHtml": "",
            "responseType": response_type,
            "textAnswer": text_answer,
        }

    # For plot-only or full-diagnosis, we run power flow and generate the plot
    try:
        pp.runpp(net)
    except Exception:
        pass

    combined_components = _get_combined_affected_components(net, ground_truth.affected_components)
    plot_html = _generate_diagnostic_plot(net, combined_components)

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
            "plotHtml": plot_html,
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
        tool_calls = agentic_result.get("tool_calls", [])
        agentic["toolCalls"] = tool_calls
        agentic["conversation"] = agentic_result.get("conversation", [])
        agentic["executionTrace"] = tool_calls
        reasoning_trace_nl = _format_reasoning_trace(tool_calls, agentic_report)
        agentic["reasoningTrace"] = reasoning_trace_nl
        agentic["reasoningQuality"] = _evaluate_reasoning_quality(
            tool_calls,
            agentic.get("rootCauses", []),
            agentic.get("affectedComponents", []),
            agentic.get("correctiveActions", []),
        )
        print("\n[diagnose_nl] Agentic reasoning trace:\n" + reasoning_trace_nl + "\n")
    except Exception:
        agentic = {
            "analysisStatus": "error",
            "rootCauses": [],
            "affectedComponents": [],
            "correctiveActions": [],
            "toolCalls": [],
            "reasoningTrace": "Agent failed.",
            "reasoningQuality": {"checks": [], "summary": "N/A (agent failed)", "passedCount": 0, "totalCount": 0},
        }

    # --- Iterative debugger pipeline (Level 3: diagnose + fix loop) ---
    try:
        import copy
        net_iter = copy.deepcopy(gen_result["net"])
        # Re-apply the generated code on the fresh copy
        generated_code = gen_result.get("generated_code", "")
        if generated_code:
            execute_safely(generated_code, net_iter, timeout=5)
        # Attempt initial power flow
        try:
            pp.runpp(net_iter)
        except Exception:
            pass

        iter_result = _iterative_agent.diagnose(net_iter, network_name=req.network)
        iter_report = iter_result["response"]
        iter_status = "success"
        if iter_report.startswith("Agent loop error") or iter_report.startswith("LLM call failed"):
            iter_status = "error"
        iterative = _build_pipeline_result(iter_report, iter_status)
        iterative["fixHistory"] = iter_result.get("fix_history", [])
        iterative["finalConverged"] = iter_result.get("final_converged", False)
        iterative["iterationsUsed"] = iter_result.get("iterations_used", 0)
        iterative["executionTrace"] = iter_result.get("fix_history", [])
    except Exception as e:
        iterative = {
            "analysisStatus": "error",
            "rootCauses": [],
            "affectedComponents": [],
            "correctiveActions": [],
            "fixHistory": [],
            "finalConverged": False,
            "iterationsUsed": 0,
            "executionTrace": [],
            "error": str(e),
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
        "iterative": iterative,
        "plotHtml": plot_html,
        "responseType": response_type,
        "textAnswer": text_answer,
    }



# ---------------------
#  Entrypoint
# ---------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
