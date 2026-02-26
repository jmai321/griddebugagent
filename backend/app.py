import os
import re
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json

import pandapower as pp

from openai import OpenAI

from scenarios import (
    NonConvergenceScenarios,
    VoltageViolationScenarios,
    ThermalOverloadScenarios,
    ContingencyFailureScenarios,
)
from agents.baseline import BaselineAgent
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
_nl_generator = NLScenarioGenerator(llm_client=_llm_client)


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


class DiagnoseNLRequest(BaseModel):
    """Request body for the /diagnose_nl endpoint."""
    network: str = "case14"
    description: str


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
#  GET  /api/visualize
# ---------------------

@app.get("/api/visualize/{network}/{scenario}", response_class=HTMLResponse)
def get_visualization(network: str, scenario: str):
    """
    Generate an interactive Plotly HTML visualization of the power network
    for a given scenario to verify testcases visually.
    """
    try:
        from pandapower.plotting.plotly import simple_plotly
    except ImportError:
        return HTMLResponse("Plotly is not installed. Run `pip install plotly matplotlib`", status_code=500)
    
    # Apply the scenario to get a modified network
    scenario_obj, _ = _find_and_apply_scenario(scenario, network)
    net = scenario_obj.net
    
    try:
        fig = simple_plotly(net)
        html_content = fig.to_html(include_plotlyjs="cdn", full_html=True)
        return HTMLResponse(content=html_content)
    except Exception as e:
        return HTMLResponse(content=f"Error generating plot: {e}", status_code=500)


# ---------------------
#  GET  /api/network_state
# ---------------------

@app.get("/api/network_state/{network}/{scenario}")
def get_network_state(network: str, scenario: str):
    """
    Return the raw network components data (buses, lines, generators)
    for a specific scenario to verify testcases programmatically.
    """
    scenario_obj, _ = _find_and_apply_scenario(scenario, network)
    net = scenario_obj.net
    
    # Try running power flow to get res_bus and res_line if possible
    scenario_obj.run_pf()
    
    # Convert DataFrames to dicts, handling NaNs
    return {
        "bus": json.loads(net.bus.to_json(orient="records")),
        "line": json.loads(net.line.to_json(orient="records")),
        "load": json.loads(net.load.to_json(orient="records")),
        "gen": json.loads(net.gen.to_json(orient="records")),
        "res_bus": json.loads(net.res_bus.to_json(orient="records")) if getattr(net, "res_bus", None) is not None and not net.res_bus.empty else [],
        "res_line": json.loads(net.res_line.to_json(orient="records")) if getattr(net, "res_line", None) is not None and not net.res_line.empty else [],
    }


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
        }

    net = gen_result["net"]
    ground_truth = gen_result["ground_truth"]

    # Run power flow
    try:
        pp.runpp(net)
    except Exception:
        pass

    # --- Baseline pipeline ---
    baseline_result = _baseline_agent.diagnose(net, network_name=req.network)
    baseline_report = baseline_result["response"]
    baseline_status = "success"
    if baseline_report.startswith("LLM call failed"):
        baseline_status = "error"
    baseline = _build_pipeline_result(baseline_report, baseline_status)

    # --- Agentic pipeline (stub) ---
    agentic = {
        "analysisStatus": "not_implemented",
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
    }


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
