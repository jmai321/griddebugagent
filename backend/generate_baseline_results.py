import json
import os
from typing import Any

from app import (
    NETWORKS,
    SCENARIOS,
    _find_and_apply_scenario,
    _baseline_agent
)

def generate_results(output_file: str = "baseline_results.json"):
    all_results: list[dict[str, Any]] = []

    for network_info in NETWORKS:
        network_id = network_info["id"]
        print(f"Processing network: {network_id}")

        for scenario_info in SCENARIOS:
            scenario_id = scenario_info["id"]
            print(f"  Running scenario: {scenario_id}")

            try:
                # Apply the scenario to get a modified network
                scenario_obj, ground_truth = _find_and_apply_scenario(scenario_id, network_id)
                net = scenario_obj.net

                # Attempt power flow
                converged = scenario_obj.run_pf()

                # Call the baseline agent
                result = _baseline_agent.diagnose(net, network_name=network_id)
                report = result["response"]
                evidence = result.get("evidence")

                # Store the result
                result_entry = {
                    "network": network_id,
                    "scenario": scenario_id,
                    "category": scenario_info["category"],
                    "converged": converged,
                    "pipeline": "baseline",
                    "report": report,
                    "ground_truth_known_fix": ground_truth.known_fix,
                    "ground_truth_root_causes": ground_truth.root_causes
                }
                
                # Optional: include evidence if needed for further analysis
                # result_entry["evidence"] = evidence
                
                all_results.append(result_entry)

            except Exception as e:
                print(f"    Error processing {network_id} - {scenario_id}: {e}")
                all_results.append({
                    "network": network_id,
                    "scenario": scenario_id,
                    "error": str(e)
                })

    # Save to file
    with open(output_file, "w") as f:
        json.dump(all_results, f, indent=2)
    
    print(f"\nGenerated {len(all_results)} results and saved to {output_file}")

if __name__ == "__main__":
    # Ensure OPENAI_API_KEY is set in environment or loaded via .env before running
    generate_results()
