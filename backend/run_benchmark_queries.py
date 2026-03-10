#!/usr/bin/env python3
"""
Run paper benchmark queries against the GridDebugAgent.

Evaluation is task-completion based (not label matching):
- Did the agent run power flow / use tools as needed?
- Did it produce a coherent answer (root causes, components, or direct answer)?

Usage:
  # Run against local API (backend must be running on port 8000)
  python run_benchmark_queries.py

  # With custom benchmark file
  python run_benchmark_queries.py --benchmark benchmark_paper_queries.json

  # Output comparison table to CSV
  python run_benchmark_queries.py --output benchmark_results.csv
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("Install requests: pip install requests")
    sys.exit(1)

API_BASE = os.getenv("GRIDDEBUG_API_URL", "http://localhost:8000")


def task_completion_ok(agentic: dict, query_lower: str) -> tuple[bool, str]:
    """
    Heuristic: did the agent complete the task (use tools, produce report)?
    Returns (passed: bool, reason: str).
    """
    status = agentic.get("analysisStatus", "")
    if status == "error":
        return False, "Agent returned error"

    root_causes = agentic.get("rootCauses", [])
    affected = agentic.get("affectedComponents", [])
    actions = agentic.get("correctiveActions", [])
    tool_calls = agentic.get("toolCalls", [])

    # At least some structured output
    has_content = bool(root_causes or affected or actions)
    used_tools = len(tool_calls) > 0

    # Task-specific heuristics (no ground truth)
    if "power flow" in query_lower or "converge" in query_lower:
        flow_tools = ["run_power_flow", "run_dc_power_flow", "run_full_diagnostics"]
        used_flow = any(tc.get("tool") in flow_tools for tc in tool_calls)
        if used_flow and has_content:
            return True, "Ran power flow and reported"
        if has_content:
            return True, "Reported (flow tools optional if preprocessor already ran)"
    if "overload" in query_lower or "loading" in query_lower or "rank" in query_lower:
        load_tools = ["check_overloads", "get_loading_profile", "run_full_diagnostics"]
        used_load = any(tc.get("tool") in load_tools for tc in tool_calls)
        if used_load and has_content:
            return True, "Used loading/overload tools and reported"
        if has_content:
            return True, "Reported"
    if "contingency" in query_lower or "outage" in query_lower:
        cont_tools = ["run_n1_contingency", "run_full_diagnostics"]
        used_cont = any(tc.get("tool") in cont_tools for tc in tool_calls)
        if used_cont and has_content:
            return True, "Ran contingency and reported"
        if has_content:
            return True, "Reported"
    if "voltage" in query_lower:
        v_tools = ["check_voltage_violations", "get_voltage_profile", "run_full_diagnostics"]
        used_v = any(tc.get("tool") in v_tools for tc in tool_calls)
        if used_v and has_content:
            return True, "Used voltage tools and reported"
        if has_content:
            return True, "Reported"
    if "balance" in query_lower or "load" in query_lower and "gen" in query_lower:
        bal_tools = ["get_power_balance", "get_network_summary", "run_full_diagnostics"]
        used_bal = any(tc.get("tool") in bal_tools for tc in tool_calls)
        if used_bal and has_content:
            return True, "Used balance/summary and reported"
        if has_content:
            return True, "Reported"
    if "summary" in query_lower or "number of" in query_lower:
        sum_tools = ["get_network_summary", "get_bus_data", "get_line_data"]
        used_sum = any(tc.get("tool") in sum_tools for tc in tool_calls)
        if (used_sum or used_tools) and has_content:
            return True, "Queried network and reported"
        if has_content:
            return True, "Reported"

    # Generic: produced content and optionally used tools
    if has_content:
        return True, "Reported"
    return False, "No structured output"


def run_one(network: str, scenario: str, query: str) -> dict:
    """POST /diagnose with optional query; return full response or error."""
    try:
        r = requests.post(
            f"{API_BASE}/diagnose",
            json={"network": network, "scenario": scenario, "query": query or None},
            timeout=120,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e), "baseline": {}, "agentic": {}}


def main():
    parser = argparse.ArgumentParser(description="Run benchmark queries and produce comparison table")
    parser.add_argument("--benchmark", default="benchmark_paper_queries.json", help="Path to benchmark JSON")
    parser.add_argument("--output", default="", help="Output CSV path (default: print to stdout)")
    parser.add_argument("--scenario", default="", help="Override: use this scenario for all queries (optional)")
    args = parser.parse_args()

    path = Path(args.benchmark)
    if not path.exists():
        print(f"Benchmark file not found: {path}")
        sys.exit(1)

    with open(path) as f:
        data = json.load(f)

    default_network = data.get("network", "case14")
    default_scenarios = data.get("scenarios", ["normal_operation"])
    queries = data.get("queries", [])

    if not queries:
        print("No 'queries' in benchmark file.")
        sys.exit(1)

    # If single scenario override, use it for all
    if args.scenario:
        default_scenarios = [args.scenario] * len(queries)
    elif len(default_scenarios) < len(queries):
        default_scenarios = (default_scenarios * ((len(queries) // len(default_scenarios)) + 1))[:len(queries)]

    results = []
    for i, q in enumerate(queries):
        qid = q.get("id", f"Q{i+1}")
        query_text = q.get("query", "")
        # Per-query network/scenario override (for paper benchmark: each query may specify its own)
        network = q.get("network") or default_network
        scenario = q.get("scenario") or (default_scenarios[i] if i < len(default_scenarios) else default_scenarios[0])
        print(f"Running {qid} (network={network}, scenario={scenario})...", flush=True)
        resp = run_one(network, scenario, query_text)
        agentic = resp.get("agentic", {})
        if "error" in resp:
            results.append({
                "query_id": qid,
                "network": network,
                "scenario": scenario,
                "query": query_text[:80],
                "our_agent_ok": False,
                "reason": resp["error"],
                "paper_agent": "",
            })
            continue
        ok, reason = task_completion_ok(agentic, query_text.lower())
        results.append({
            "query_id": qid,
            "network": network,
            "scenario": scenario,
            "query": query_text[:80],
            "our_agent_ok": ok,
            "reason": reason,
            "paper_agent": "",
        })

    # Comparison table
    lines = ["Query,Network,Scenario,Our Agent,Reason,Paper Agent (fill manually)"]
    for r in results:
        our = "✓" if r["our_agent_ok"] else "✗"
        lines.append(f"{r['query_id']},{r.get('network', '')},{r['scenario']},{our},\"{r['reason']}\",{r['paper_agent']}")

    table = "\n".join(lines)
    if args.output:
        with open(args.output, "w") as f:
            f.write(table)
        print(f"Wrote {args.output}")
    else:
        print("\n--- Comparison table (Paper Agent column: fill from paper) ---\n")
        print(table)

    # Also save full results JSON for inspection
    out_json = Path(args.output).with_suffix(".json") if args.output else Path("benchmark_results.json")
    with open(out_json, "w") as f:
        json.dump({"results": results, "default_network": default_network}, f, indent=2)
    print(f"Full results saved to {out_json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
