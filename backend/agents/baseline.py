"""
Level 1: Baseline LLM Agent

Passes raw solver outputs directly to an LLM for natural language
explanation. No tool access — establishes what an LLM can infer
from unstructured data alone.
"""
from __future__ import annotations

import json
from typing import Any

import pandapower as pp

from rule_engine.evidence_collector import EvidenceCollector


SYSTEM_PROMPT = """\
You are GridDebugAgent, an expert power systems engineer \
specializing in diagnosing failed power flow simulations run with pandapower.

## Your Analysis Approach

When the power flow DID NOT CONVERGE:
1. First check the LOAD vs GENERATION comparison — is total load far exceeding \
generation capacity? If load/gen ratio >> 1.0, the primary root cause is EXCESSIVE LOAD \
or INSUFFICIENT GENERATION, not impedance or topology issues.
2. Check for disconnected buses or isolated elements that might prevent power delivery.
3. The pandapower diagnostics section may contain generic warnings (impedance, bus indexing) \
that are present on MANY healthy networks. Do NOT cite these as root causes unless they \
directly contribute to non-convergence.

When the power flow CONVERGED but has violations:
1. Check bus voltages for under/over-voltage violations.
2. Check line/trafo loading for thermal overloads (>100%).
3. Trace the violation to its root cause (e.g., heavy loading → voltage drop).

## Output Format

Format your response as a structured diagnostic report:
## Root Causes
(Rank from most to least likely. Be specific — cite numbers from the evidence.)
## Affected Components
(List with specific types and indices, e.g., "Load 0-41", "Line 5", "Bus 3")
## Corrective Actions
(Minimal, engineering-feasible actions. Be specific.)
## Confidence Assessment
"""

USER_PROMPT_TEMPLATE = """\
The following power flow simulation has {status}.

Network: {network_name}
Buses: {bus_count} | Lines: {line_count} | Generators: {gen_count} | Loads: {load_count}

{evidence_text}

IMPORTANT: Focus on the LOAD vs GENERATION COMPARISON section when diagnosing non-convergence.
Identify the SPECIFIC components (with indices) that are affected.
Do NOT list generic pandapower warning names as root causes — they are often noise."""


class BaselineAgent:
    """
    Level 1 agent: raw solver output → LLM explanation.
    No tool access, no rule engine — pure LLM interpretation.
    """

    def __init__(self, llm_client=None):
        """
        Args:
            llm_client: An OpenAI-compatible client. If None, uses a mock.
        """
        self.llm_client = llm_client
        self.collector = EvidenceCollector()

    def diagnose(self, net: pp.pandapowerNet, network_name: str = "unknown") -> dict[str, Any]:
        """
        Run baseline diagnosis on a network.

        Args:
            net: pandapower network (after failed or converged PF attempt)
            network_name: name of the test network

        Returns:
            dict with keys: "prompt", "response", "evidence"
        """
        # Collect evidence
        report = self.collector.collect(net)

        # Build prompt
        status = "FAILED TO CONVERGE" if not report.converged else "CONVERGED"
        prompt = USER_PROMPT_TEMPLATE.format(
            status=status,
            network_name=network_name,
            bus_count=report.bus_count,
            line_count=report.line_count,
            gen_count=report.gen_count,
            load_count=len(net.load),
            evidence_text=report.to_text(),
        )

        # Call LLM
        response = self._call_llm(prompt)

        return {
            "level": "baseline",
            "prompt": prompt,
            "response": response,
            "evidence": report.to_dict(),
        }

    def _call_llm(self, user_prompt: str) -> str:
        """Call the LLM with the system + user prompt."""
        if self.llm_client is None:
            return self._mock_response(user_prompt)

        try:
            completion = self.llm_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=2000,
            )
            return completion.choices[0].message.content
        except Exception as e:
            return f"LLM call failed: {str(e)}"

    def _mock_response(self, prompt: str) -> str:
        """Generate a mock response when no LLM client is available."""
        if "FAILED TO CONVERGE" in prompt:
            return (
                "## Root Causes\n"
                "- Power flow did not converge, likely due to extreme "
                "load/generation imbalance or network topology issues.\n\n"
                "## Affected Components\n"
                "- Unable to determine specific components without "
                "converged results.\n\n"
                "## Corrective Actions\n"
                "- Run pp.diagnostic(net) for detailed checks\n"
                "- Check for disconnected buses\n"
                "- Reduce loads or add generation\n\n"
                "## Confidence Assessment\n"
                "- Low confidence — limited evidence without convergence."
            )
        return (
            "## Root Causes\n"
            "- Analysis of converged results needed.\n\n"
            "## Affected Components\n"
            "- See evidence report for details.\n\n"
            "## Corrective Actions\n"
            "- Address any voltage or thermal violations.\n\n"
            "## Confidence Assessment\n"
            "- Moderate confidence based on available data."
        )
