import os
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from openai import OpenAI

from scenarios import (
    NonConvergenceScenarios,
    VoltageViolationScenarios,
    ThermalOverloadScenarios,
    ContingencyFailureScenarios,
)
from agents.baseline import BaselineAgent

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
    network: str
    scenario: str
    pipeline: str
    converged: bool
    report: str
    evidence: Optional[dict] = None         # raw evidence data


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
#  POST /diagnose
# ---------------------

@app.post("/diagnose", response_model=DiagnoseResult)
def run_diagnose(req: DiagnoseRequest):
    """
    Run the selected scenario on the chosen network through the
    specified pipeline (baseline or agentic) and return the diagnosis report.
    """
    # Validate network
    valid_networks = [n["id"] for n in NETWORKS]
    if req.network not in valid_networks:
        raise HTTPException(400, f"Unknown network: {req.network}. Choose from {valid_networks}")

    # Apply the scenario to get a modified network
    scenario_obj, ground_truth = _find_and_apply_scenario(req.scenario, req.network)
    net = scenario_obj.net

    # Attempt power flow
    converged = scenario_obj.run_pf()

    if req.pipeline == "baseline":
        # --- Baseline pipeline: send network state to LLM ---
        result = _baseline_agent.diagnose(net, network_name=req.network)
        report = result["response"]
        evidence = result.get("evidence")
    else:
        # TODO: agentic pipeline
        report = "(Agentic pipeline not yet implemented)"
        evidence = None

    return DiagnoseResult(
        network=req.network,
        scenario=req.scenario,
        pipeline=req.pipeline,
        converged=converged,
        report=report,
        evidence=evidence,
    )


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
