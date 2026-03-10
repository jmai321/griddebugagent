"""
Simulation tools for the agentic pipeline: run power flow, DC PF, N-1 contingency.
"""
from __future__ import annotations

import copy
import pandapower as pp
from tools.diagnostic_tools import DiagnosticTools


TOOL_DEFINITIONS = [
    {
        "name": "run_power_flow",
        "description": "Run AC power flow (Newton-Raphson). Returns convergence status and a short summary.",
        "parameters": {},
    },
    {
        "name": "run_dc_power_flow",
        "description": "Run DC power flow (linear approximation). Often converges when AC fails.",
        "parameters": {},
    },
    {
        "name": "run_n1_contingency",
        "description": "Run N-1 contingency: outage one line or trafo and run power flow. Pass line_index or trafo_index.",
        "parameters": {
            "line_index": {"type": "integer", "description": "Line index to take out of service for N-1."},
            "trafo_index": {"type": "integer", "description": "Transformer index to take out of service for N-1."},
        },
    },
]


class SimulationTools:
    TOOL_DEFINITIONS = TOOL_DEFINITIONS

    @staticmethod
    def run_power_flow(net: pp.pandapowerNet) -> dict:
        try:
            pp.runpp(net)
            converged = bool(net.converged)
            return {
                "converged": converged,
                "message": "AC power flow converged." if converged else "AC power flow did not converge.",
            }
        except pp.LoadflowNotConverged:
            return {"converged": False, "message": "AC power flow did not converge (LoadflowNotConverged)."}
        except Exception as e:
            return {"converged": False, "message": str(e), "error": str(e)}

    @staticmethod
    def run_dc_power_flow(net: pp.pandapowerNet) -> dict:
        try:
            pp.rundcpp(net)
            return {"converged": True, "message": "DC power flow completed (linear approximation)."}
        except Exception as e:
            return {"converged": False, "message": str(e), "error": str(e)}

    @staticmethod
    def run_n1_contingency(
        net: pp.pandapowerNet,
        line_index: int | None = None,
        trafo_index: int | None = None,
        **kwargs,
    ) -> dict:
        line_index = line_index if line_index is not None else kwargs.get("line_index")
        trafo_index = trafo_index if trafo_index is not None else kwargs.get("trafo_index")
        if line_index is None and trafo_index is None:
            return {"error": "Provide line_index or trafo_index for N-1 contingency."}
        net_copy = copy.deepcopy(net)
        element = "unknown"
        try:
            if line_index is not None:
                if line_index not in net_copy.line.index:
                    return {"error": f"Line index {line_index} not in network."}
                net_copy.line.at[line_index, "in_service"] = False
                element = f"line_{line_index}"
            else:
                if trafo_index not in net_copy.trafo.index:
                    return {"error": f"Trafo index {trafo_index} not in network."}
                net_copy.trafo.at[trafo_index, "in_service"] = False
                element = f"trafo_{trafo_index}"
            pp.runpp(net_copy)
            converged = bool(net_copy.converged)
            
            result = {
                "element_out": element,
                "converged": converged,
                "message": f"N-1 ({element} out): power flow {'converged' if converged else 'did not converge'}.",
            }
            
            if converged:
                violations = DiagnosticTools.check_voltage_violations(net_copy)
                overloads = DiagnosticTools.check_overloads(net_copy)
                result["voltage_violations"] = violations.get("total_violations", 0)
                result["undervoltage_buses"] = violations.get("undervoltage_buses", [])
                result["overvoltage_buses"] = violations.get("overvoltage_buses", [])
                result["overloaded_lines"] = overloads.get("overloaded_lines", [])
                result["overloaded_trafos"] = overloads.get("overloaded_trafos", [])
                
            return result
        except pp.LoadflowNotConverged:
            return {
                "element_out": element,
                "converged": False,
                "message": f"N-1 ({element} out): power flow did not converge.",
            }
        except Exception as e:
            return {"error": str(e), "element_out": element}
