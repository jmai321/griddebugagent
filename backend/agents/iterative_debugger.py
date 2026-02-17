"""
Level 3: Iterative Debugger Agent

Extends the agentic pipeline with a propose-fix-verify loop.
The agent proposes a corrective action, applies it, re-runs power
flow, and evaluates whether the fix resolved the issue.
"""
from __future__ import annotations

import copy
import json
from typing import Any

import pandapower as pp

from config import MAX_FIX_ITERATIONS
from rule_engine.preprocessor import Preprocessor
from tools.query_tools import QueryTools
from tools.simulation_tools import SimulationTools
from tools.modification_tools import ModificationTools
from tools.diagnostic_tools import DiagnosticTools


SYSTEM_PROMPT = """\
You are GridDebugAgent (Level 3: Iterative Debugger), an expert power systems \
engineer. You diagnose failed power flow simulations AND iteratively fix them.

You have access to both analysis and modification tools:

ANALYSIS TOOLS:
{analysis_tools}

MODIFICATION TOOLS:
{modification_tools}

Your workflow:
1. DIAGNOSE: Analyze evidence and identify root causes
2. PROPOSE: Choose a minimal corrective action
3. APPLY: Call a modification tool to apply the fix
4. VERIFY: Re-run power flow to check if the fix worked
5. ITERATE: If not fixed, try the next most likely correction

After each fix attempt, report:
- What you tried and why
- Whether it improved the situation
- What to try next (if needed)

When the simulation converges with all constraints satisfied, OR you've \
exhausted reasonable fixes, output your final report prefixed with \
"FINAL REPORT:" including a summary of all attempted fixes.
"""

USER_PROMPT_TEMPLATE = """\
== NETWORK: {network_name} ==
== FAILURE CATEGORY: {failure_category} ==

== PREPROCESSED EVIDENCE ==
{evidence_text}

== TRIGGERED RULES ==
{rules_text}

Please diagnose the issue and iteratively apply fixes until the power flow \
converges without violations, or until you've exhausted reasonable corrections.
"""


class IterativeDebuggerAgent:
    """
    Level 3 agent: diagnose + iterative fix-verify loop.
    Extends agentic pipeline with modification tool access.
    """

    def __init__(self, llm_client=None, max_iterations: int = MAX_FIX_ITERATIONS):
        self.llm_client = llm_client
        self.preprocessor = Preprocessor()
        self.max_iterations = max_iterations

    def diagnose(self, net: pp.pandapowerNet, network_name: str = "unknown") -> dict[str, Any]:
        """
        Run iterative diagnosis + fix loop.

        Returns:
            dict with keys: "level", "response", "fix_history",
            "final_converged", "iterations_used"
        """
        # Save original for comparison
        original_net = copy.deepcopy(net)

        # Preprocess
        context = self.preprocessor.process(net)

        # Build prompt
        rules_text = self._format_rules(context["triggered_rules"])
        user_prompt = USER_PROMPT_TEMPLATE.format(
            network_name=network_name,
            failure_category=context["failure_category"],
            evidence_text=context["evidence_text"],
            rules_text=rules_text,
        )

        # Run iterative loop
        fix_history = []
        conversation = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": user_prompt},
        ]

        if self.llm_client is None:
            # Run automated fix strategy  without LLM
            final_response, fix_history = self._automated_fix_loop(
                net, context, network_name
            )
        else:
            final_response = self._llm_fix_loop(
                net, conversation, fix_history
            )

        return {
            "level": "iterative_debugger",
            "response": final_response,
            "fix_history": fix_history,
            "final_converged": getattr(net, "converged", False),
            "iterations_used": len(fix_history),
            "evidence": context["evidence"],
            "failure_category": context["failure_category"],
        }

    def _automated_fix_loop(
        self,
        net: pp.pandapowerNet,
        context: dict,
        network_name: str,
    ) -> tuple[str, list[dict]]:
        """
        Automated fix strategy without LLM, based on triggered rules.
        Applies fixes in priority order and tracks results.
        """
        fix_history = []
        category = context["failure_category"]
        rules = context["triggered_rules"]

        for iteration in range(self.max_iterations):
            # Check current state
            try:
                pp.runpp(net)
                converged = net.converged
            except Exception:
                converged = False

            if converged:
                # Check for remaining violations
                violations = DiagnosticTools.check_voltage_violations(net)
                overloads = DiagnosticTools.check_overloads(net)

                total_issues = (
                    violations.get("total_violations", 0) +
                    len(overloads.get("overloaded_lines", [])) +
                    len(overloads.get("overloaded_trafos", []))
                )

                if total_issues == 0:
                    fix_history.append({
                        "iteration": iteration,
                        "action": "verification",
                        "result": "All constraints satisfied",
                        "converged": True,
                    })
                    break

            # Apply fix based on category and rules
            fix_result = self._apply_automated_fix(net, category, rules, iteration)
            fix_history.append(fix_result)

            if fix_result.get("action") == "no_fix_available":
                break

        # Generate report
        final_converged = getattr(net, "converged", False)
        report = self._generate_automated_report(
            network_name, category, fix_history, final_converged
        )

        return report, fix_history

    def _apply_automated_fix(
        self,
        net: pp.pandapowerNet,
        category: str,
        rules: list[dict],
        iteration: int,
    ) -> dict:
        """Apply a heuristic fix based on the failure category."""

        # Strategy 1: Load shedding for non-convergence or overload
        if category in ("nonconvergence", "thermal_overload") and iteration == 0:
            result = ModificationTools.scale_all_loads(net, factor=0.8)
            result["iteration"] = iteration
            result["rationale"] = "Reduce all loads by 20% to alleviate stress"
            return result

        # Strategy 2: Add reactive compensation for voltage violations
        if category == "voltage_violation" and iteration == 0:
            undervoltage_rule = next(
                (r for r in rules if r["rule_name"] == "undervoltage"), None
            )
            if undervoltage_rule:
                buses = undervoltage_rule.get("evidence", {}).get("buses", [])
                if buses:
                    bus_idx = buses[0]["index"]
                    result = ModificationTools.add_reactive_compensation(net, bus_idx, 10.0)
                    result["iteration"] = iteration
                    result["rationale"] = f"Add 10 Mvar capacitor at under-voltage bus {bus_idx}"
                    return result

        # Strategy 3: Further load reduction
        if iteration == 1:
            result = ModificationTools.scale_all_loads(net, factor=0.7)
            result["iteration"] = iteration
            result["rationale"] = "Further reduce loads to 70%"
            return result

        # Strategy 4: Adjust voltage setpoints
        if iteration == 2:
            if len(net.ext_grid) > 0:
                result = ModificationTools.adjust_voltage_setpoint(
                    net, "ext_grid", int(net.ext_grid.index[0]), 1.02
                )
                result["iteration"] = iteration
                result["rationale"] = "Raise slack bus voltage to 1.02 pu"
                return result

        # Strategy 5: Re-enable generators if they were disabled
        if iteration == 3:
            disabled_gens = net.gen[~net.gen["in_service"]]
            if len(disabled_gens) > 0:
                gen_idx = int(disabled_gens.index[0])
                result = ModificationTools.toggle_element(net, "gen", gen_idx, True)
                result["iteration"] = iteration
                result["rationale"] = f"Re-enable generator {gen_idx}"
                return result

        return {
            "iteration": iteration,
            "action": "no_fix_available",
            "rationale": "Exhausted automated fix strategies",
        }

    def _generate_automated_report(
        self,
        network_name: str,
        category: str,
        fix_history: list[dict],
        converged: bool,
    ) -> str:
        """Generate a text report from the automated fix loop."""
        lines = [
            "FINAL REPORT:",
            "",
            f"## Network: {network_name}",
            f"## Failure Category: {category}",
            f"## Final Status: {'CONVERGED ✓' if converged else 'NOT CONVERGED ✗'}",
            f"## Iterations: {len(fix_history)}",
            "",
            "## Fix History",
        ]

        for fix in fix_history:
            action = fix.get("action", "unknown")
            rationale = fix.get("rationale", "")
            lines.append(f"- Iteration {fix.get('iteration', '?')}: "
                         f"{action} — {rationale}")

        lines.extend([
            "",
            "## Summary",
            f"Applied {len(fix_history)} corrective action(s). "
            f"{'System restored to feasible operating point.' if converged else 'Further manual intervention required.'}",
        ])

        return "\n".join(lines)

    def _llm_fix_loop(
        self,
        net: pp.pandapowerNet,
        conversation: list[dict],
        fix_history: list[dict],
    ) -> str:
        """LLM-driven fix loop with function calling."""
        for i in range(self.max_iterations * 3):  # More iterations for LLM
            try:
                tools = self._get_openai_tools()
                completion = self.llm_client.chat.completions.create(
                    model="gpt-4o",
                    messages=conversation,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.3,
                    max_tokens=2000,
                )

                message = completion.choices[0].message

                if message.tool_calls:
                    conversation.append(message.model_dump())

                    for tool_call in message.tool_calls:
                        fn_name = tool_call.function.name
                        fn_args = json.loads(tool_call.function.arguments)

                        result = self._execute_tool(net, fn_name, fn_args)
                        fix_history.append({
                            "iteration": i,
                            "tool": fn_name,
                            "args": fn_args,
                            "result": result,
                        })

                        conversation.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps(result),
                        })
                else:
                    return message.content or ""

            except Exception as e:
                return f"Iterative debugger error at step {i}: {str(e)}"

        return "Max iterations reached in iterative debugger."

    def _execute_tool(self, net: pp.pandapowerNet, name: str, args: dict) -> Any:
        """Dispatch tool calls — includes both analysis and modification tools."""
        tool_map = {
            # Analysis tools
            "get_network_summary": lambda: QueryTools.get_network_summary(net),
            "get_bus_data": lambda: QueryTools.get_bus_data(net, **args),
            "get_line_data": lambda: QueryTools.get_line_data(net, **args),
            "get_gen_data": lambda: QueryTools.get_gen_data(net, **args),
            "get_voltage_profile": lambda: QueryTools.get_voltage_profile(net),
            "get_loading_profile": lambda: QueryTools.get_loading_profile(net),
            "get_power_balance": lambda: QueryTools.get_power_balance(net),
            "run_power_flow": lambda: SimulationTools.run_power_flow(net),
            "run_dc_power_flow": lambda: SimulationTools.run_dc_power_flow(net),
            "run_n1_contingency": lambda: SimulationTools.run_n1_contingency(net, **args),
            "run_full_diagnostics": lambda: DiagnosticTools.run_full_diagnostics(net),
            "check_overloads": lambda: DiagnosticTools.check_overloads(net, **args),
            "check_voltage_violations": lambda: DiagnosticTools.check_voltage_violations(net, **args),
            "find_disconnected_areas": lambda: DiagnosticTools.find_disconnected_areas(net),
            # Modification tools
            "shed_load": lambda: ModificationTools.shed_load(net, **args),
            "adjust_generation": lambda: ModificationTools.adjust_generation(net, **args),
            "add_reactive_compensation": lambda: ModificationTools.add_reactive_compensation(net, **args),
            "toggle_element": lambda: ModificationTools.toggle_element(net, **args),
            "adjust_voltage_setpoint": lambda: ModificationTools.adjust_voltage_setpoint(net, **args),
            "scale_all_loads": lambda: ModificationTools.scale_all_loads(net, **args),
        }

        if name in tool_map:
            try:
                return tool_map[name]()
            except Exception as e:
                return {"error": str(e)}
        return {"error": f"Unknown tool: {name}"}

    def _build_system_prompt(self) -> str:
        all_analysis = (
            QueryTools.TOOL_DEFINITIONS +
            SimulationTools.TOOL_DEFINITIONS +
            DiagnosticTools.TOOL_DEFINITIONS
        )
        all_mods = ModificationTools.TOOL_DEFINITIONS

        analysis_desc = "\n".join(f"  - {t['name']}: {t['description']}" for t in all_analysis)
        mod_desc = "\n".join(f"  - {t['name']}: {t['description']}" for t in all_mods)

        return SYSTEM_PROMPT.format(
            analysis_tools=analysis_desc,
            modification_tools=mod_desc,
        )

    def _get_openai_tools(self) -> list[dict]:
        all_tools = (
            QueryTools.TOOL_DEFINITIONS +
            SimulationTools.TOOL_DEFINITIONS +
            DiagnosticTools.TOOL_DEFINITIONS +
            ModificationTools.TOOL_DEFINITIONS
        )
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": {
                        "type": "object",
                        "properties": t.get("parameters", {}),
                        "required": [],
                    },
                },
            }
            for t in all_tools
        ]

    def _format_rules(self, rules: list[dict]) -> str:
        if not rules:
            return "No rules triggered."
        lines = []
        for r in rules:
            lines.append(f"[{r['severity'].upper()}] {r['rule_name']}: {r['description']}")
            for action in r.get("suggested_actions", []):
                lines.append(f"  → {action}")
        return "\n".join(lines)
