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

MAX_FIX_ITERATIONS = 10
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
5. CHECK CONSTRAINTS: If it converges, YOU MUST run `check_overloads` and `check_voltage_violations`. A converged network with violations is NOT fixed!
6. ITERATE: If not fixed, try the next most likely correction

After each fix attempt, report:
- What you tried and why
- Whether it improved the situation (including remaining violations)
- What to try next (if needed)

When the simulation converges with all constraints satisfied, OR you've \
exhausted reasonable fixes, output your final report prefixed with \
"FINAL REPORT:" including a summary of all attempted fixes.
"""

USER_PROMPT_TEMPLATE = """\
== NETWORK: {network_name} ==
== FAILURE CATEGORY: {failure_category} ==

{user_query_section}== PREPROCESSED EVIDENCE ==
{evidence_text}

== TRIGGERED RULES ==
{rules_text}

{task_instruction}
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

    def diagnose(self, net: pp.pandapowerNet, network_name: str = "unknown", user_query: str = "") -> dict[str, Any]:
        """
        Run iterative diagnosis + fix loop.

        Args:
            user_query: Optional user question. When provided for direct_answer
                        queries, the agent uses query tools to answer instead of
                        running the full fix loop.

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
        if user_query:
            user_query_section = f"== USER QUERY ==\n{user_query}\n\n"
            task_instruction = (
                "Please answer the user query above using the available query tools. "
                "Call the appropriate tools to retrieve the requested information, "
                "then provide a clear, concise answer."
            )
        else:
            user_query_section = ""
            task_instruction = (
                "Please diagnose the issue and iteratively apply fixes until the power flow "
                "converges without violations, or until you've exhausted reasonable corrections."
            )
        user_prompt = USER_PROMPT_TEMPLATE.format(
            network_name=network_name,
            failure_category=context["failure_category"],
            evidence_text=context["evidence_text"],
            rules_text=rules_text,
            user_query_section=user_query_section,
            task_instruction=task_instruction,
        )

        # Generate initial diagnosis from preprocessor context
        initial_diagnosis = self._generate_initial_diagnosis(context)

        # Run iterative loop
        fix_history = []
        conversation = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": user_prompt},
        ]

        if self.llm_client is None:
            if user_query:
                final_response = f"No LLM available to answer: {user_query}"
                fix_history = []
            else:
                # Run automated fix strategy without LLM
                final_response, fix_history = self._automated_fix_loop(
                    net, context, network_name
                )
        else:
            final_response = self._llm_fix_loop(
                net, conversation, fix_history
            )

        # Capture final state after all fixes
        final_state = self._capture_final_state(net)

        return {
            "level": "iterative_debugger",
            "response": final_response,
            # New structured fields
            "initial_diagnosis": initial_diagnosis,
            "agent_actions": fix_history,  # Unified list with reasoning + phase
            "final_state": final_state,
            # Backward compatible fields
            "fix_history": fix_history,
            "final_converged": final_state["converged"],
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
                    "phase": "verify",
                })
                break

            fix = self._pick_fix(net, state, attempted)
            if fix is None:
                fix_history.append({
                    "iteration": iteration,
                    "action": "no_fix_available",
                    "rationale": "Exhausted all automated fix strategies",
                    "phase": "diagnostic",
                })
                break

            # Track this action so we don't repeat it
            attempted.add(fix.get("action", ""))
            fix["iteration"] = iteration
            fix["phase"] = "fix"  # Automated fixes are always 'fix' phase
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
                    # Capture LLM reasoning (the text content before tool calls)
                    reasoning_text = message.content or ""
                    conversation.append(message.model_dump())

                    for tool_call in message.tool_calls:
                        fn_name = tool_call.function.name
                        fn_args = json.loads(tool_call.function.arguments)
                        phase = self._classify_tool_phase(fn_name)

                        result = self._execute_tool(net, fn_name, fn_args)
                        fix_history.append({
                            "iteration": i,
                            "tool": fn_name,
                            "args": fn_args,
                            "result": result,
                            "reasoning": reasoning_text,
                            "phase": phase,
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

    @staticmethod
    def _classify_tool_phase(tool_name: str) -> str:
        """Classify a tool call as diagnostic, fix, or verify."""
        diagnostic_tools = {
            "get_network_summary", "get_bus_data", "get_line_data", "get_gen_data",
            "get_voltage_profile", "get_loading_profile", "get_power_balance",
            "check_overloads", "check_voltage_violations", "find_disconnected_areas",
            "run_n1_contingency"
        }
        fix_tools = {
            "shed_load", "curtail_load", "adjust_generation", "add_shunt_compensation",
            "add_reactive_compensation", "toggle_element", "switch_element",
            "adjust_voltage_setpoint", "scale_all_loads"
        }
        verify_tools = {"run_power_flow", "run_dc_power_flow", "run_full_diagnostics"}

        if tool_name in diagnostic_tools:
            return "diagnostic"
        elif tool_name in fix_tools:
            return "fix"
        elif tool_name in verify_tools:
            return "verify"
        return "diagnostic"

    def _generate_initial_diagnosis(self, context: dict) -> dict:
        """Extract initial diagnosis from preprocessor context before fixes."""
        triggered_rules = context.get("triggered_rules", [])
        evidence = context.get("evidence", {})

        # Extract root causes from triggered rules (critical/high severity)
        root_causes = []
        for rule in triggered_rules:
            severity = rule.get("severity", "").lower()
            if severity in ("critical", "high"):
                root_causes.append(f"{rule['rule_name']}: {rule['description']}")

        # Extract affected components from evidence (correct nested paths)
        affected_components = []

        # Voltage violations (nested under "voltages")
        voltages = evidence.get("voltages", {})
        for v in voltages.get("undervoltage_buses", []):
            bus_idx = v.get("index", v.get("bus", "?"))
            vm_pu = v.get("vm_pu", 0)
            affected_components.append(f"Bus {bus_idx} (undervoltage: {vm_pu:.3f} pu)")
        for v in voltages.get("overvoltage_buses", []):
            bus_idx = v.get("index", v.get("bus", "?"))
            vm_pu = v.get("vm_pu", 0)
            affected_components.append(f"Bus {bus_idx} (overvoltage: {vm_pu:.3f} pu)")

        # Line overloads (nested under "line_loading")
        line_loading = evidence.get("line_loading", {})
        for line in line_loading.get("overloaded_lines", []):
            line_idx = line.get("index", line.get("line_index", "?"))
            from_bus = line.get("from_bus", "?")
            to_bus = line.get("to_bus", "?")
            loading = line.get("loading_pct", line.get("loading_percent", 0))
            affected_components.append(
                f"Line {line_idx} ({from_bus}-{to_bus}) overloaded at {loading:.1f}%"
            )

        # Transformer overloads (nested under "trafo_loading")
        trafo_loading = evidence.get("trafo_loading", {})
        for trafo in trafo_loading.get("overloaded_trafos", []):
            trafo_idx = trafo.get("index", trafo.get("trafo_index", "?"))
            loading = trafo.get("loading_pct", trafo.get("loading_percent", 0))
            affected_components.append(
                f"Transformer {trafo_idx} overloaded at {loading:.1f}%"
            )

        # Disconnected buses (nested under "topology")
        topology = evidence.get("topology", {})
        disc_buses = topology.get("disconnected_buses", [])
        if disc_buses:
            affected_components.append(f"Disconnected buses: {disc_buses}")

        # Convergence status (nested under "convergence")
        convergence = evidence.get("convergence", {})
        converged_initially = convergence.get("converged", False)

        return {
            "root_causes": root_causes,
            "affected_components": affected_components,
            "failure_category": context.get("failure_category", "unknown"),
            "converged_initially": converged_initially,
        }

    def _capture_final_state(self, net: pp.pandapowerNet) -> dict:
        """Capture the final state after all fixes."""
        state = self._observe(net)

        remaining_violations = []

        # Voltage violations
        violations = state.get("violations", {})
        for v in violations.get("undervoltage_buses", []):
            remaining_violations.append(f"Bus {v['bus']} undervoltage: {v['vm_pu']:.3f} pu")
        for v in violations.get("overvoltage_buses", []):
            remaining_violations.append(f"Bus {v['bus']} overvoltage: {v['vm_pu']:.3f} pu")

        # Thermal overloads
        overloads = state.get("overloads", {})
        for line in overloads.get("overloaded_lines", []):
            remaining_violations.append(
                f"Line {line['line_index']} overloaded at {line['loading_percent']:.1f}%"
            )
        for trafo in overloads.get("overloaded_trafos", []):
            remaining_violations.append(
                f"Transformer {trafo['trafo_index']} overloaded at {trafo['loading_percent']:.1f}%"
            )

        return {
            "converged": state["converged"],
            "remaining_violations": remaining_violations,
            "is_healthy": self._is_healthy(state),
        }
