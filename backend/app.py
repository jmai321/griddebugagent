import os
import re
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from openai import OpenAI

from scenarios import (
    NonConvergenceScenarios,
    VoltageViolationScenarios,
    ThermalOverloadScenarios,
    ContingencyFailureScenarios,
)
from scenarios.base_scenarios import load_network
from agents.baseline import BaselineAgent

try:
    from pandapower.topology import create_nxgraph
    import networkx as nx
    _HAS_NX = True
except ImportError:
    _HAS_NX = False

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


# ---------------------
#  Constants
# ---------------------

NETWORKS = [
    {"id": "case14", "label": "IEEE 14-Bus"},
    {"id": "case30", "label": "IEEE 30-Bus"},
    {"id": "case57", "label": "IEEE 57-Bus"},
]

SCENARIO_FACTORIES = {
    "nonconvergence": NonConvergenceScenarios,
    "voltage":        VoltageViolationScenarios,
    "thermal":        ThermalOverloadScenarios,
    "contingency":    ContingencyFailureScenarios,
}

SCENARIOS = [
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


def _get_network_for_topology(network: str, scenario: str | None):
    """Return pandapower net for topology: base network or with scenario applied."""
    if scenario:
        scenario_obj, _ = _find_and_apply_scenario(scenario, network)
        return scenario_obj.net
    return load_network(network)


def _build_topology(net) -> dict:
    """
    Build nodes (buses) and edges (lines + trafos) with positions for frontend graph.
    Uses net.bus_geodata if present, else networkx spring_layout.
    """
    nodes = []
    bus_ids = list(net.bus.index)
    in_service = net.bus["in_service"].to_dict()

    # Resolve (x, y) for each bus
    positions = {}
    if hasattr(net, "bus_geodata") and net.bus_geodata is not None and len(net.bus_geodata) > 0:
        for bus_id in bus_ids:
            if bus_id in net.bus_geodata.index:
                row = net.bus_geodata.loc[bus_id]
                x = float(row.get("x", 0))
                y = float(row.get("y", 0))
                positions[bus_id] = (x, y)
    if len(positions) < len(bus_ids):
        if _HAS_NX:
            G = create_nxgraph(net, respect_switches=False)
            pos = nx.spring_layout(G, seed=42, k=1.5)
            for bus_id in bus_ids:
                if bus_id in pos:
                    positions[bus_id] = (float(pos[bus_id][0]), float(pos[bus_id][1]))
        else:
            # Fallback: place buses in a circle
            import math
            n = len(bus_ids)
            for i, bus_id in enumerate(bus_ids):
                angle = 2 * math.pi * i / n if n else 0
                positions[bus_id] = (math.cos(angle), math.sin(angle))
    for bus_id in bus_ids:
        x, y = positions.get(bus_id, (0.0, 0.0))
        name = net.bus.at[bus_id, "name"] if "name" in net.bus.columns else f"Bus {bus_id}"
        nodes.append({
            "id": str(bus_id),
            "busId": int(bus_id),
            "label": str(name),
            "x": round(x, 4),
            "y": round(y, 4),
            "in_service": bool(in_service.get(bus_id, True)),
        })

    edges = []
    for idx, row in net.line.iterrows():
        edges.append({
            "id": f"line-{idx}",
            "source": str(int(row["from_bus"])),
            "target": str(int(row["to_bus"])),
            "type": "line",
            "lineIndex": int(idx),
            "in_service": bool(row.get("in_service", True)),
        })
    for idx, row in net.trafo.iterrows():
        edges.append({
            "id": f"trafo-{idx}",
            "source": str(int(row["hv_bus"])),
            "target": str(int(row["lv_bus"])),
            "type": "trafo",
            "trafoIndex": int(idx),
            "in_service": bool(row.get("in_service", True)),
        })

    return {"nodes": nodes, "edges": edges}


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


def _build_pipeline_result(report: str, analysis_status: str = "success") -> dict:
    """Build pipeline result with analysisStatus and parsed fields."""
    print('========================================')
    print(report)
    print('========================================')
    parsed = _parse_llm_report(report)
    return {
        "analysisStatus": analysis_status,
        "rootCauses": parsed["rootCauses"],
        "affectedComponents": parsed["affectedComponents"],
        "correctiveActions": parsed["correctiveActions"],
    }


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
#  GET  /topology
# ---------------------

@app.get("/topology")
def get_topology(network: str = "case14", scenario: str | None = None):
    """
    Return network topology for graph visualization: nodes (buses) and edges (lines, trafos)
    with coordinates. Optional query param scenario applies that scenario before returning topology.
    """
    valid_networks = [n["id"] for n in NETWORKS]
    if network not in valid_networks:
        raise HTTPException(400, f"Unknown network: {network}. Choose from {valid_networks}")
    if scenario is not None:
        entry = next((s for s in SCENARIOS if s["id"] == scenario), None)
        if entry is None:
            raise HTTPException(404, f"Unknown scenario: {scenario}")
    net = _get_network_for_topology(network, scenario)
    return _build_topology(net)


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

    # --- Agentic pipeline (stub until implemented) ---
    agentic = {
        "analysisStatus": "not_implemented",
        "rootCauses": [],
        "affectedComponents": [],
        "correctiveActions": [],
    }

    return DiagnoseResult(baseline=baseline, agentic=agentic)


# ---------------------
#  GET  /result/{scenario}
# ---------------------

@app.get("/result/{scenario}")
def get_result(scenario: str, network: str = "case14"):
    """
    Retrieve the latest diagnosis text output for a given scenario + network.
    TODO: fetch stored result from database/cache.
    """
    return {
        "network": network,
        "scenario": scenario,
        "report": "",
    }


# ---------------------
#  Entrypoint
# ---------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
