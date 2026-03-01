import json
import os
import argparse
from typing import Any
from pathlib import Path

from openai import OpenAI

SYSTEM_PROMPT = """\
You are an expert impartial judge evaluating the performance of an AI power systems diagnostic agent.
Your task is to compare the agent's generated diagnostic report against the known ground truth metadata for a failure scenario in a power grid simulation.

You MUST score the agent on three distinct criteria on a scale of 0 to 5 (integers only):

1. **root_cause_score (0-5)**: Did the agent correctly identify the primary technical reason for the failure?
   - 5: Perfect identification of the exact root cause.
   - 3-4: Identified the general nature of the issue but missed key specifics.
   - 1-2: Vague or partially incorrect diagnosis.
   - 0: Completely incorrect or missed the main issue.

2. **action_score (0-5)**: Are the suggested fixes practical, engineering-feasible, and aligned with the known ground truth fix?
   - 5: Excellent, practical, and directly address the root cause like the known fix.
   - 3-4: Good suggestions, but maybe too generic or missing the most direct fix.
   - 1-2: Vague actions or actions that don't address the core problem well.
   - 0: Completely bad or harmful suggestions.

3. **specificity_score (0-5)**: Did the agent accurately pinpoint the specific nodes/buses/lines involved?
   - 5: Exactly identified the correct component indices/types.
   - 3-4: Identified some components but missed others or included false positives.
   - 1-2: Very vague ("some lines are overloaded").
   - 0: Failed to identify any affected components or hallucinated components.

You must output your evaluation EXACTLY in the following JSON format:
```json
{
  "root_cause_score": <int>,
  "action_score": <int>,
  "specificity_score": <int>,
  "reasoning": "<string summarizing your logic>"
}
```
"""

USER_PROMPT_TEMPLATE = """\
Please evaluate the following agent diagnostic report against the given GROUND TRUTH.

=== GROUND TRUTH ===
Network: {network}
Scenario: {scenario}
Failure Category: {category}
Known Fix: {ground_truth_known_fix}
Root Causes:
{ground_truth_root_causes}

=== AGENT REPORT ===
{report}
"""

def evaluate_results(input_file: str, output_file: str):
    from dotenv import load_dotenv
    load_dotenv()
    # Initialize OpenAI client
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        print("Warning: OPENAI_API_KEY environment variable is not set. Evaluations will fail.")
        return
    
    client = OpenAI(api_key=openai_key)
    
    # Load results
    with open(input_file, "r") as f:
        results = json.load(f)
    
    print(f"Loaded {len(results)} results from {input_file}")
    
    evaluated_results = []
    
    for i, result in enumerate(results):
        print(f"Evaluating {i+1}/{len(results)}: {result['network']} - {result['scenario']}")
        
        # Skip if error in generation
        if "error" in result:
             print(f"  Skipping due to generation error: {result['error']}")
             evaluated_results.append(result)
             continue
             
        ground_truth_root_causes = "\\n".join(f"- {rc}" for rc in result.get("ground_truth_root_causes", []))
        
        user_prompt = USER_PROMPT_TEMPLATE.format(
            network=result["network"],
            scenario=result["scenario"],
            category=result["category"],
            ground_truth_known_fix=result.get("ground_truth_known_fix", "None"),
            ground_truth_root_causes=ground_truth_root_causes,
            report=result["report"]
        )
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            
            evaluation = json.loads(response.choices[0].message.content)
            
            # Merge evaluation into result
            result["evaluation"] = evaluation
            
        except Exception as e:
            print(f"  Error during LLM evaluation: {e}")
            result["evaluation"] = {"error": str(e)}
            
        evaluated_results.append(result)
        
    # Save evaluated results
    with open(output_file, "w") as f:
        json.dump(evaluated_results, f, indent=2)
        
    print(f"\\nEvaluations complete. Saved to {output_file}")
    
    # Aggregate and print summary
    aggregate_scores(evaluated_results)

def aggregate_scores(results):
    total_rc = 0
    total_act = 0
    total_spec = 0
    count = 0
    
    category_scores = {}
    
    for result in results:
        eval_data = result.get("evaluation", {})
        if "error" in eval_data or not eval_data:
            continue
            
        rc = eval_data.get("root_cause_score", 0)
        act = eval_data.get("action_score", 0)
        spec = eval_data.get("specificity_score", 0)
        
        total_rc += rc
        total_act += act
        total_spec += spec
        count += 1
        
        cat = result.get("category", "unknown")
        if cat not in category_scores:
            category_scores[cat] = {"rc": 0, "act": 0, "spec": 0, "count": 0}
            
        category_scores[cat]["rc"] += rc
        category_scores[cat]["act"] += act
        category_scores[cat]["spec"] += spec
        category_scores[cat]["count"] += 1
        
    if count == 0:
        print("No valid evaluations found to aggregate.")
        return
        
    print("\\n=== AGGREGATE SCORES (0-5 scale) ===")
    print(f"Total Evaluated: {count}")
    print(f"Average Root Cause Accuracy: {total_rc / count:.2f}")
    print(f"Average Corrective Action: {total_act / count:.2f}")
    print(f"Average Specificity: {total_spec / count:.2f}")
    print("\\n=== SCORES BY CATEGORY ===")
    
    for cat, scores in category_scores.items():
        c = scores["count"]
        if c > 0:
            print(f"- {cat.upper()} ({c} cases):")
            print(f"    Root Cause: {scores['rc'] / c:.2f}")
            print(f"    Action:     {scores['act'] / c:.2f}")
            print(f"    Spec:       {scores['spec'] / c:.2f}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate GridDebugAgent baseline results using LLM as a judge.")
    parser.add_argument("--input", default="baseline_results.json", help="Path to the input JSON file containing generated results.")
    parser.add_argument("--output", default="baseline_evaluations.json", help="Path to save the evaluated JSON output.")
    
    args = parser.parse_args()
    
    evaluate_results(args.input, args.output)
