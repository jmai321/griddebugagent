"""
Level 2: Agentic Pipeline Agent

ReAct-style agent that receives rule-engine context and can call
query/simulation/diagnostic tools to gather additional evidence.
Produces a structured DiagnosticReport.
"""
from __future__ import annotations

import copy
import json
from typing import Any

import pandapower as pp

from rule_engine.preprocessor import Preprocessor
from tools.query_tools import QueryTools
from tools.simulation_tools import SimulationTools
from tools.diagnostic_tools import DiagnosticTools


# ── Prompt templates ───────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are GridDebugAgent Level 2, an expert power systems engineer with tool \
access for deep diagnosis of power flow simulation issues.

You have been provided with preprocessed evidence from a pandapower simulation, \
including rule-engine classifications that have already identified likely failure modes.

## Analysis Strategy

1. FIRST read the triggered rules carefully — they pre-classify the failure mode.
2. For NON-CONVERGENCE: Focus on the load-vs-generation balance. If loads far \
exceed generation, the root cause is load/generation imbalance, NOT impedance or \
bus indexing issues. Use tools to verify the load/gen data.
3. For VOLTAGE VIOLATIONS: Use get_voltage_profile to identify specific buses, \
then trace back to root cause (overloaded feeder, missing reactive support).
4. For THERMAL OVERLOADS: Use get_loading_profile to rank overloaded elements, \
then check contingency impacts.
5. Use tools STRATEGICALLY — don't call every tool, only those that test your hypothesis.

## Available Tools
{tool_descriptions}

## Output Requirements

When done analyzing, output "FINAL REPORT:" followed by:
## Root Causes (ranked, with specific numbers from evidence)
## Affected Components (type + specific indices, e.g. "Load 0-41", "Bus 3")
## Corrective Actions (minimal, engineering-feasible, specific)
## Reasoning Trace (summarize analysis steps and tool findings)
"""

USER_PROMPT_TEMPLATE = """\
== NETWORK: {network_name} ==
== FAILURE CATEGORY: {failure_category} ==

{evidence_text}

== TRIGGERED RULES (from rule engine) ==
{rules_text}

== NETWORK SUMMARY ==
{network_summary}

Analyze this case using the triggered rules as your starting hypothesis. \
Use tools to gather evidence if needed, then produce your FINAL REPORT."""


class AgenticPipelineAgent:
    """
    Level 2 agent: rule-engine preprocessed context + tool access.
    Uses a ReAct loop to iteratively gather evidence.
    """

    MAX_TOOL_CALLS = 10

    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        self.preprocessor = Preprocessor()

    def diagnose(self, net: pp.pandapowerNet, network_name: str = "unknown") -> dict[str, Any]:
        """
        Run agentic diagnosis with tool access.

        Returns:
            dict with keys: "level", "prompt", "response", "evidence",
            "tool_calls", "conversation"
        """
        # Step 1: Preprocess
        context = self.preprocessor.process(net)

        # Step 2: Build initial prompt
        rules_text = self._format_rules(context["triggered_rules"])
        network_summary = json.dumps(context["network_summary"], indent=2)

        user_prompt = USER_PROMPT_TEMPLATE.format(
            network_name=network_name,
            failure_category=context["failure_category"],
            evidence_text=context["evidence_text"],
            rules_text=rules_text,
            network_summary=network_summary,
        )

        # Step 3: Run ReAct loop
        tool_calls_log = []
        conversation = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": user_prompt},
        ]

        final_response = self._run_react_loop(net, conversation, tool_calls_log)

        return {
            "level": "agentic_pipeline",
            "prompt": user_prompt,
            "response": final_response,
            "evidence": context["evidence"],
            "triggered_rules": context["triggered_rules"],
            "failure_category": context["failure_category"],
            "tool_calls": tool_calls_log,
            "conversation": conversation,
        }

    def _build_system_prompt(self) -> str:
        """Build system prompt with tool descriptions."""
        all_tools = (
            QueryTools.TOOL_DEFINITIONS +
            SimulationTools.TOOL_DEFINITIONS +
            DiagnosticTools.TOOL_DEFINITIONS
        )
        tool_desc = "\n".join(
            f"- {t['name']}: {t['description']}" for t in all_tools
        )
        return SYSTEM_PROMPT.format(tool_descriptions=tool_desc)

    def _run_react_loop(
        self,
        net: pp.pandapowerNet,
        conversation: list[dict],
        tool_calls_log: list[dict],
    ) -> str:
        """
        Run the ReAct loop: call LLM, parse tool calls, execute tools,
        feed results back. Repeat until final report or max iterations.
        """
        if self.llm_client is None:
            return self._mock_agentic_response(conversation)

        for i in range(self.MAX_TOOL_CALLS):
            try:
                # Get tool schemas for function calling
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

                # Check if the model wants to call a tool
                if message.tool_calls:
                    conversation.append(message.model_dump())

                    for tool_call in message.tool_calls:
                        fn_name = tool_call.function.name
                        fn_args = json.loads(tool_call.function.arguments)

                        # Execute the tool
                        result = self._execute_tool(net, fn_name, fn_args)
                        tool_calls_log.append({
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
                    # Model produced a final response
                    return message.content or ""

            except Exception as e:
                return f"Agent loop error at iteration {i}: {str(e)}"

        return "Max tool call iterations reached. Please review the gathered evidence."

    def _execute_tool(self, net: pp.pandapowerNet, name: str, args: dict) -> Any:
        """Dispatch a tool call to the appropriate function."""
        tool_map = {
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
        }

        if name in tool_map:
            try:
                return tool_map[name]()
            except Exception as e:
                return {"error": str(e)}
        return {"error": f"Unknown tool: {name}"}

    def _get_openai_tools(self) -> list[dict]:
        """Build OpenAI function-calling tool schemas."""
        all_tools = (
            QueryTools.TOOL_DEFINITIONS +
            SimulationTools.TOOL_DEFINITIONS +
            DiagnosticTools.TOOL_DEFINITIONS
        )
        openai_tools = []
        for t in all_tools:
            schema = {
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
            openai_tools.append(schema)
        return openai_tools

    def _format_rules(self, rules: list[dict]) -> str:
        """Format triggered rules for prompt."""
        if not rules:
            return "No rules triggered."
        lines = []
        for r in rules:
            lines.append(f"[{r['severity'].upper()}] {r['rule_name']}: {r['description']}")
            for action in r.get("suggested_actions", []):
                lines.append(f"  → {action}")
        return "\n".join(lines)

    def _mock_agentic_response(self, conversation: list[dict]) -> str:
        """Mock response when no LLM client is available."""
        return (
            "FINAL REPORT:\n\n"
            "## Root Causes\n"
            "1. Based on rule-engine preprocessing, the primary failure mode "
            "has been identified from triggered rules.\n"
            "2. Additional tool-based investigation would refine this diagnosis.\n\n"
            "## Affected Components\n"
            "- See triggered rules and evidence for specific component indices.\n\n"
            "## Corrective Actions\n"
            "- Follow the suggested actions from triggered rules.\n"
            "- Verify fixes by re-running power flow.\n\n"
            "## Reasoning Trace\n"
            "- Analyzed preprocessed evidence and rule classifications.\n"
            "- (Mock mode: no actual tool calls were made)\n"
        )
