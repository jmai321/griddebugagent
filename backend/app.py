import os
import re
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
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

        # Create the base plot with the additional highlight traces
        fig = simple_plotly(
            net,
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


class DiagnoseResult(BaseModel):
    """Response body returned by the /diagnose endpoint."""
    baseline: dict
    agentic: dict
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
        "load": json.loads(net.load.to_json(orient="records")),
        "gen": json.loads(net.gen.to_json(orient="records")),
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
        # Quick check for overloads or voltage violations to highlight
        v_min, v_max = 0.95, 1.05
        if not net.res_bus.empty:
            uv = net.res_bus[net.res_bus["vm_pu"] < v_min].index.tolist()
            ov = net.res_bus[net.res_bus["vm_pu"] > v_max].index.tolist()
            if uv or ov:
                root_causes.append("**Voltage Violations**: Buses found outside 0.95–1.05 p.u. bounds.")
                affected_components["bus"] = uv + ov
        
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
    except Exception as e:
        agentic = {
            "analysisStatus": "error",
            "rootCauses": [],
            "affectedComponents": [],
            "correctiveActions": [],
        }

    # Generate visualization
    plot_html = _generate_diagnostic_plot(net, ground_truth.affected_components)

    return DiagnoseResult(baseline=baseline, agentic=agentic, plotHtml=plot_html)


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
            "plotHtml": "",
            "responseType": response_type,
            "textAnswer": text_answer,
        }

    # For plot-only or full-diagnosis, we run power flow and generate the plot
    try:
        pp.runpp(net)
    except Exception:
        pass

    plot_html = _generate_diagnostic_plot(net, ground_truth.affected_components)

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
    baseline_result = _baseline_agent.diagnose(net, network_name=req.network)
    baseline_report = baseline_result["response"]
    baseline_status = "success"
    if baseline_report.startswith("LLM call failed"):
        baseline_status = "error"
    baseline = _build_pipeline_result(baseline_report, baseline_status)

    # --- Agentic pipeline ---
    try:
        agentic_result = _agentic_agent.diagnose(net, network_name=req.network)
        agentic_report = agentic_result["response"]
        agentic_status = "success"
        if agentic_report.startswith("Agent loop error") or agentic_report.startswith("LLM call failed"):
            agentic_status = "error"
        agentic = _build_pipeline_result(agentic_report, agentic_status)
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
        "plotHtml": plot_html,
        "responseType": response_type,
        "textAnswer": text_answer,
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
