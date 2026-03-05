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

MAX_FIX_ITERATIONS = 5
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
1. DIAGNOSE: Analyze evidence and identify root causes. If the user query specifies an initiating event (e.g. line disconnection), that is the primary root cause. Treat voltage/thermal violations as symptoms.
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

    # ── Observation-driven helpers ──────────────────────────────────

    @staticmethod
    def _observe(net: pp.pandapowerNet) -> dict:
        """Run power flow + all diagnostics to snapshot full network health."""
        try:
            pp.runpp(net)
            converged = bool(net.converged)
        except Exception:
            converged = False

        disconnected_info = DiagnosticTools.find_disconnected_areas(net)
        disconnected_buses = set(disconnected_info.get("disconnected_buses", []))

        # Identify disconnected buses that still have active loads
        # (these need fixing).  Inert disconnected buses (no active load)
        # are physically isolated but harmless — NaN voltage is expected.
        disc_with_load: set[int] = set()
        for idx, row in net.load.iterrows():
            if row.get("in_service", True) and int(row["bus"]) in disconnected_buses:
                if row.get("p_mw", 0) > 0 or row.get("q_mvar", 0) > 0:
                    disc_with_load.add(int(row["bus"]))
        inert_buses = disconnected_buses - disc_with_load

        # NaN voltages on inert disconnected buses are expected; only flag
        # NaN on connected (or load-bearing disconnected) buses.
        has_nan_voltage = False
        if converged and hasattr(net, "res_bus") and not net.res_bus.empty:
            nan_buses = set(net.res_bus[net.res_bus["vm_pu"].isna()].index.astype(int))
            real_nan = nan_buses - inert_buses
            has_nan_voltage = len(real_nan) > 0

        violations = DiagnosticTools.check_voltage_violations(net) if converged else {}
        overloads = DiagnosticTools.check_overloads(net) if converged else {}

        # Filter out voltage violations on inert disconnected buses
        if violations and inert_buses:
            violations = dict(violations)  # copy
            for key in ("undervoltage_buses", "overvoltage_buses"):
                if key in violations:
                    violations[key] = [
                        v for v in violations[key] if v["bus"] not in inert_buses
                    ]
            violations["total_violations"] = (
                len(violations.get("undervoltage_buses", []))
                + len(violations.get("overvoltage_buses", []))
            )

        return {
            "converged": converged,
            "has_nan_voltage": has_nan_voltage,
            "disconnected_buses": sorted(disc_with_load),  # only actionable ones
            "inert_buses": sorted(inert_buses),
            "violations": violations,
            "overloads": overloads,
        }

    @staticmethod
    def _is_healthy(state: dict) -> bool:
        """True only when converged, no real NaN voltages, and zero violations."""
        if not state["converged"] or state["has_nan_voltage"]:
            return False
        if state["violations"].get("total_violations", 0) > 0:
            return False
        if len(state["overloads"].get("overloaded_lines", [])) > 0:
            return False
        if len(state["overloads"].get("overloaded_trafos", [])) > 0:
            return False
        return True

    @staticmethod
    def _pick_fix(
        net: pp.pandapowerNet,
        state: dict,
        attempted: set[str],
    ) -> dict | None:
        """
        Walk a priority-ordered list of fixes and return the first
        applicable one that hasn't been tried yet.  Returns None when
        every applicable strategy has been exhausted.
        """

        # --- P1: Disconnected buses with loads → shed isolated loads ---
        if state["disconnected_buses"]:
            tag = "shed_disconnected_loads"
            if tag not in attempted:
                try:
                    from pandapower.topology import create_nxgraph
                    import networkx as nx

                    G = create_nxgraph(net, respect_switches=True,
                                       include_out_of_service=False)
                    ext_buses = set(net.ext_grid["bus"].astype(int))
                    reachable: set[int] = set()
                    for sb in ext_buses:
                        if sb in G:
                            reachable |= set(nx.descendants(G, sb)) | {sb}
                    disconnected = set(G.nodes()) - reachable

                    shed_count = 0
                    for idx, row in net.load.iterrows():
                        if int(row["bus"]) in disconnected:
                            ModificationTools.curtail_load(net, int(idx), 0.0)
                            shed_count += 1

                    return {
                        "action": tag,
                        "success": True,
                        "loads_shed": shed_count,
                        "disconnected_buses": len(disconnected),
                        "rationale": f"Shed {shed_count} load(s) on "
                                     f"{len(disconnected)} disconnected bus(es)",
                    }
                except Exception as e:
                    return {"action": tag, "success": False, "error": str(e),
                            "rationale": "Attempted to shed disconnected loads"}

        # --- P2: Not converged → aggressive load reduction ---
        if not state["converged"]:
            if "scale_loads_50" not in attempted:
                result = ModificationTools.scale_all_loads(net, factor=0.5)
                result["rationale"] = "Halve all loads to restore convergence"
                return {**result, "action": "scale_loads_50"}

            if "shed_largest_load" not in attempted:
                biggest = IterativeDebuggerAgent._find_biggest_loads(net, n=1)
                if biggest:
                    result = ModificationTools.curtail_load(net, biggest[0], 0.0)
                    result["rationale"] = (
                        f"Shed largest load {biggest[0]} entirely"
                    )
                    return {**result, "action": "shed_largest_load"}

            if "scale_loads_25" not in attempted:
                result = ModificationTools.scale_all_loads(net, factor=0.5)
                result["rationale"] = "Further reduce loads to 25% of original"
                return {**result, "action": "scale_loads_25"}

            if "raise_slack_v" not in attempted and len(net.ext_grid) > 0:
                result = ModificationTools.adjust_voltage_setpoint(
                    net, "ext_grid", int(net.ext_grid.index[0]), 1.03
                )
                result["rationale"] = "Raise slack bus voltage to 1.03 pu"
                return {**result, "action": "raise_slack_v"}

        # --- P3: Undervoltage → shunt capacitor at worst bus ---
        uv = state["violations"].get("undervoltage_buses", [])
        if uv:
            worst = min(uv, key=lambda b: b["vm_pu"])
            bus_idx = worst["bus"]
            tag = f"shunt_cap_bus_{bus_idx}"
            if tag not in attempted:
                result = ModificationTools.add_shunt_compensation(
                    net, bus_idx, 15.0
                )
                result["rationale"] = (
                    f"Add 15 Mvar capacitor at undervoltage bus {bus_idx} "
                    f"(vm={worst['vm_pu']:.4f} pu)"
                )
                return {**result, "action": tag}

            # secondary: raise slack voltage
            if "raise_slack_uv" not in attempted and len(net.ext_grid) > 0:
                result = ModificationTools.adjust_voltage_setpoint(
                    net, "ext_grid", int(net.ext_grid.index[0]), 1.02
                )
                result["rationale"] = "Raise slack bus voltage to 1.02 pu"
                return {**result, "action": "raise_slack_uv"}

            # tertiary: raise gen voltage
            in_svc_gens = net.gen[net.gen["in_service"]]
            if len(in_svc_gens) > 0:
                gen_idx = int(in_svc_gens.index[0])
                tag_g = f"raise_gen_{gen_idx}_v"
                if tag_g not in attempted:
                    result = ModificationTools.adjust_voltage_setpoint(
                        net, "gen", gen_idx, 1.03
                    )
                    result["rationale"] = (
                        f"Raise generator {gen_idx} voltage to 1.03 pu"
                    )
                    return {**result, "action": tag_g}

        # --- P4: Overvoltage → shunt reactor at worst bus ---
        ov = state["violations"].get("overvoltage_buses", [])
        if ov:
            worst = max(ov, key=lambda b: b["vm_pu"])
            bus_idx = worst["bus"]
            tag = f"shunt_reactor_bus_{bus_idx}"
            if tag not in attempted:
                result = ModificationTools.add_shunt_compensation(
                    net, bus_idx, -10.0
                )
                result["rationale"] = (
                    f"Add 10 Mvar reactor at overvoltage bus {bus_idx} "
                    f"(vm={worst['vm_pu']:.4f} pu)"
                )
                return {**result, "action": tag}

            # secondary: lower gen voltage setpoint
            in_svc_gens = net.gen[net.gen["in_service"]]
            if len(in_svc_gens) > 0:
                gen_idx = int(in_svc_gens.index[0])
                tag_g = f"lower_gen_{gen_idx}_v"
                if tag_g not in attempted:
                    result = ModificationTools.adjust_voltage_setpoint(
                        net, "gen", gen_idx, 1.00
                    )
                    result["rationale"] = (
                        f"Lower generator {gen_idx} voltage to 1.00 pu"
                    )
                    return {**result, "action": tag_g}

        # --- P5: Thermal overload → curtail nearby load ---
        ol_lines = state["overloads"].get("overloaded_lines", [])
        if ol_lines:
            worst_line = max(ol_lines, key=lambda l: l["loading_percent"])
            line_idx = worst_line["line_index"]
            from_bus = worst_line["from_bus"]

            tag = f"curtail_near_line_{line_idx}"
            if tag not in attempted:
                nearby = net.load[net.load["bus"] == from_bus]
                if len(nearby) > 0:
                    result = ModificationTools.curtail_load(
                        net, int(nearby.index[0]), 0.5
                    )
                    result["rationale"] = (
                        f"Curtail load near overloaded line {line_idx} by 50% "
                        f"(loading={worst_line['loading_percent']:.1f}%)"
                    )
                    return {**result, "action": tag}

            if "scale_loads_85" not in attempted:
                result = ModificationTools.scale_all_loads(net, factor=0.85)
                result["rationale"] = "Reduce all loads to 85% to ease thermal loading"
                return {**result, "action": "scale_loads_85"}

        # --- P6: Generic fallback ---
        if "generic_scale_80" not in attempted:
            result = ModificationTools.scale_all_loads(net, factor=0.8)
            result["rationale"] = "Generic: reduce all loads by 20%"
            return {**result, "action": "generic_scale_80"}

        return None  # exhausted all strategies

    # ── Automated fix loop (observation-driven) ──────────────────────

    def _automated_fix_loop(
        self,
        net: pp.pandapowerNet,
        context: dict,
        network_name: str,
    ) -> tuple[str, list[dict]]:
        """
        Observation-driven fix strategy without LLM.
        At each iteration: observe full network state, pick highest-priority
        applicable fix, apply it, and re-observe.
        """
        fix_history: list[dict] = []
        attempted: set[str] = set()

        for iteration in range(self.max_iterations):
            state = self._observe(net)

            if self._is_healthy(state):
                fix_history.append({
                    "iteration": iteration,
                    "action": "verification",
                    "result": "All constraints satisfied",
                    "converged": True,
                })
                break

            fix = self._pick_fix(net, state, attempted)
            if fix is None:
                fix_history.append({
                    "iteration": iteration,
                    "action": "no_fix_available",
                    "rationale": "Exhausted all automated fix strategies",
                })
                break

            # Track this action so we don't repeat it
            attempted.add(fix.get("action", ""))
            fix["iteration"] = iteration
            fix_history.append(fix)

        # Generate report
        final_state = self._observe(net)
        healthy = self._is_healthy(final_state)
        category = context.get("failure_category", "unknown")
        report = self._generate_automated_report(
            network_name, category, fix_history, healthy,
        )

        return report, fix_history

    @staticmethod
    def _find_biggest_loads(net: pp.pandapowerNet, n: int = 3) -> list[int]:
        """Return indices of the n largest in-service loads by p_mw."""
        in_service = net.load[net.load["in_service"]]
        if in_service.empty:
            return []
        return in_service.nlargest(n, "p_mw").index.tolist()

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
            "curtail_load": lambda: ModificationTools.curtail_load(net, **args),
            "adjust_generation": lambda: ModificationTools.adjust_generation(net, **args),
            "add_reactive_compensation": lambda: ModificationTools.add_reactive_compensation(net, **args),
            "add_shunt_compensation": lambda: ModificationTools.add_shunt_compensation(net, **args),
            "toggle_element": lambda: ModificationTools.toggle_element(net, **args),
            "switch_element": lambda: ModificationTools.switch_element(net, **args),
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
