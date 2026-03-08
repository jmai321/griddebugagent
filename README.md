# GridDebugAgent

An agentic assistant for diagnosing failed power flow simulations. Given a failing grid case (non-convergence, voltage violations, line overloads, or N-1 contingencies), it produces a **structured diagnosis report**: root causes, affected components, and minimal corrective actions. The project implements **(i) a simple LLM baseline** (explain from logs/results) and **(ii) an agentic pipeline** that uses solver outputs plus rule-based and LLM reasoning with tools.

---

## 1. Completed Features

### 1.1 Diagnosis Pipelines

| Pipeline | Description |
|----------|-------------|
| **Baseline (LLM only)** | EvidenceCollector gathers solver results (convergence, load/gen, violations, etc.) → one LLM call → natural-language report → backend parser extracts structured `rootCauses`, `affectedComponents`, `correctiveActions`. |
| **Agentic (with tools)** | Preprocessor (EvidenceCollector + RuleEngine) produces rule classifications and `failure_category` → LLM runs in a ReAct loop and can call **tools** (query, simulation, diagnostic) → outputs FINAL REPORT → same parser yields structured output. |

### 1.2 Scenario Input Modes

| Mode | Description |
|------|-------------|
| **Preset Scenarios** | User picks network (case14/30/57) and a fixed scenario (normal, nonconvergence, voltage, thermal, contingency — 14 total). Backend applies the scenario, runs power flow, runs both pipelines, returns structured results and `plotHtml`. |
| **Natural Language (NL)** | User describes the failure in plain language (e.g. “Scale all loads by 15x”). Backend uses NLScenarioGenerator to produce scenario code, runs it in a sandbox, gets modified `net` and ground truth, then runs both pipelines and visualization. Response can be `full_diagnosis`, `plot_only`, or `text_only` depending on generator output. |

### 1.3 Agent reasoning and tool calls

The **agentic** pipeline reasons in a **ReAct loop**:

1. **Input**: Preprocessor gives the LLM evidence text, triggered rules, `failure_category`, and network summary.
2. **Loop** (up to `MAX_TOOL_CALLS`): The LLM either **calls one or more tools** (OpenAI function calling) or **returns the final report**. When it calls tools, the backend runs them (e.g. `get_power_balance`, `check_overloads`), appends the results to the conversation, and calls the LLM again. When it stops calling tools and outputs text, that text is treated as the FINAL REPORT.
3. **Output**: The report is parsed into `rootCauses`, `affectedComponents`, `correctiveActions`.

**Inspecting which tools were called**: Each agentic run records a **tool_calls** list: `{ iteration, tool, args, result }`. The API now returns this as **`agentic.toolCalls`** in the diagnose response. The frontend shows a “Tools used (reasoning trace)” card when the Agentic pipeline is selected and `toolCalls` is non-empty. You can also log `agentic_result["tool_calls"]` in the backend after `_agentic_agent.diagnose()`.

**Full reasoning process**: The API also returns **`agentic.reasoningTrace`** (a single text string with input → each tool call and result → final report snippet). It is printed to the backend console and shown in the frontend “Full reasoning process” card.

#### How to judge if agent reasoning is reasonable or correct

- **Automated checks (reasoning quality)**  
  The backend runs heuristic checks and returns **`agentic.reasoningQuality`**: `{ checks: [{ id, passed, message }], summary, passedCount, totalCount }`. The frontend shows a “Reasoning quality” card with ✓/○ and messages. Checks include:
  - **used_tools**: Did the agent call at least one tool? (No tools ⇒ no tool-based evidence.)
  - **evidence_for_overload**: If the report mentions overload/loading/thermal, did the agent call overload/flow/diagnostic tools?
  - **evidence_for_voltage**: If the report mentions voltage/violations, did it call voltage-related tools?
  - **evidence_for_balance**: If the report mentions balance/load/generation/convergence, did it call power-balance or flow tools?
  - **reasonable_order**: Did power flow or full-diagnostics run before overload/voltage checks (data before diagnosis)?

- **Manual checks**  
  - Compare **tool results** in the trace with **what the report says**: e.g. if `get_power_balance` returns “load > gen”, the report should mention imbalance.  
  - Check **order**: e.g. `run_power_flow` or `run_full_diagnostics` before `check_overloads` / `check_voltage_violations`.  
  - Compare with **ground truth** (for preset/NL scenarios): does the reported root cause match the injected failure (e.g. extreme load scaling ⇒ load/gen imbalance)?

- **Correctness**  
  “Correct” usually means: (1) root cause matches the scenario’s ground truth, (2) suggested fixes are consistent with solver evidence and tool outputs. Use the evaluation script and manual inspection of `reasoningTrace` + `reasoningQuality` together.

### 1.4 Tools and Action Space (Agentic & Iterative)

The **Agentic** pipeline relies on several categories of tools to inspect the grid. The **Iterative Debugger** (Level 3) further extends this with **Modification/Action** tools to actively fix the grid (its Action Space):

| Category | Tools | Description |
|----------|--------|-------------|
| **Query** | `get_network_summary`, `get_bus_data`, `get_line_data`, `get_gen_data`, `get_voltage_profile`, `get_loading_profile`, `get_power_balance` | Inspects grid topology, limits, profiles, and basic data. |
| **Simulation** | `run_power_flow`, `run_dc_power_flow`, `run_n1_contingency` | Executes AC/DC solvers or contingency analyses to compute grid states. |
| **Diagnostic** | `run_full_diagnostics`, `check_overloads`, `check_voltage_violations`, `find_disconnected_areas` | Heuristic checks that directly identify specific constraint violations and isolated components. |
| **Modification (Action Space)** | `shed_load`, `curtail_load`, `adjust_generation`, `add_reactive_compensation`, `add_shunt_compensation`, `toggle_element`, `switch_element`, `adjust_voltage_setpoint`, `scale_all_loads` | Enables the agent to physically alter the grid (e.g., shed loads, switch lines, adjust generation/voltage, add emergency capacitors) to resolve violations. |

### 1.5 The Iterative Debugger Pipeline

Alongside the Baseline and purely Diagnostic Agentic pipelines, the system now features an **Iterative Debugger**. 
- It uses the full **Action Space** to propose a fix, apply it to a sandbox copy of the network, and run validation checks (`run_power_flow`, `check_overloads`, `check_voltage_violations`).
- If constraints are still violated, the agent loops and applies further corrections (e.g., shedding more load, adding capacitors). 
- The frontend plots the final, **Fixed Network** state to visually confirm the resolution of violations, alongside a detailed **Fix History** log.

### 1.6 Network Visualization

- Backend uses **pandapower.plotting.plotly** (`simple_plotly` + bus/line/trafo traces) to build a Plotly figure. **Ground-truth affected components** are highlighted in red.
- API returns `plotHtml` (full HTML string). Frontend renders it in an **iframe** (`srcDoc`); user can zoom and hover.

### 1.7 Frontend

- **Pipeline selector**: Dropdown to show either “Baseline (LLM only)” or “Agentic (with tools)” results.
- **Mode toggle**: “Describe Failure” (NL) vs “Preset Scenarios”. NL success shows generated scenario card and baseline/agentic results.
- **Results panel**: Root Causes, Affected Components, Recommendations (corrective actions), and Network Visualization when `plotHtml` is present.

---

## 2. Workflow

### 2.1 Preset flow (fixed scenario)

```
User selects Network + Scenario (Preset) → clicks Run Analysis
    ↓
Frontend: POST /diagnose { network, scenario, query? }
    ↓
Backend:
  1. _find_and_apply_scenario(scenario, network)
     → Load base network, apply scenario's modify logic → net, ground_truth (ScenarioResult)
  2. scenario_obj.run_pf(net)  // attempt AC power flow
  3. BaselineAgent.diagnose(net)
     → EvidenceCollector.collect(net) → EvidenceReport
     → Build prompt with report.to_text() → single LLM call → markdown report
     → _build_pipeline_result(report) → baseline { analysisStatus, rootCauses, affectedComponents, correctiveActions }
  4. AgenticPipelineAgent.diagnose(net)
     → Preprocessor.process(net) → evidence + triggered_rules + failure_category
     → ReAct loop: LLM may call tools (Query/Simulation/Diagnostic), results appended to conversation
     → LLM eventually returns "FINAL REPORT:" markdown
     → _build_pipeline_result(report) → agentic { ... }
  5. _generate_diagnostic_plot(net, ground_truth.affected_components) → plotHtml
    ↓
Response: { baseline, agentic, plotHtml }
    ↓
Frontend: store fullResponse; display fullResponse[selectedPipeline]; render plotHtml in iframe
```

### 2.2 Natural Language flow (describe failure)

```
User selects Network + enters natural-language description → clicks Generate & Analyze
    ↓
Frontend: POST /diagnose_nl { network, description }
    ↓
Backend:
  1. NLScenarioGenerator.generate(description, network)
     → LLM generates scenario code (modifies net) + ground_truth (root_causes, affected_components, known_fix)
     → execute_safely(generated_code, net) in sandbox → net updated, ground_truth
     → Returns generation_status, net, ground_truth, response_type (full_diagnosis | plot_only | text_only), optional text_answer
    ↓
  If generation_status != "success":
    → Return error payload: generationError, generatedCode, baseline/agentic = skipped
    ↓
  If response_type == "text_only":
    → Return generatedGroundTruth, baseline/agentic = skipped, no plot
    ↓
  If response_type == "plot_only":
    → pp.runpp(net) (best effort), _generate_diagnostic_plot(...) → plotHtml
    → Return generatedGroundTruth, plotHtml, baseline/agentic = skipped
    ↓
  Else (full_diagnosis):
    2. pp.runpp(net)
    3. _generate_diagnostic_plot(net, ground_truth.affected_components) → plotHtml
    4. BaselineAgent.diagnose(net) → _build_pipeline_result → baseline
    5. AgenticPipelineAgent.diagnose(net) → _build_pipeline_result → agentic
    ↓
Response: { generationStatus, generatedCode, generatedGroundTruth, baseline, agentic, plotHtml, responseType?, textAnswer? }
    ↓
Frontend: set nlExtra = response; if success, set fullResponse from baseline/agentic/plotHtml; show pipeline result + plot
```

### 2.3 Report parsing (shared)

- Both pipelines produce markdown with sections: `## Root Causes`, `## Affected Components`, `## Corrective Actions`.
- **`_parse_llm_report(report)`**: Extracts those sections; supports inline sections, bullet lists (`-`/`*`), and numbered lists (`1.`); returns string arrays.
- **`_build_pipeline_result(report, status)`**: Returns `{ analysisStatus, rootCauses, affectedComponents, correctiveActions }` for API response.

### 2.4 Optional: simulate overrides (manual sliders)

- **POST /api/simulate_overrides**: Accepts a base scenario plus user overrides (global load scale, line/trafo outages, per-load/per-gen overrides). Backend applies them to a copy of the network, runs power flow, builds a simple root-cause list and affected components, then returns `converged`, `plotHtml`, `rootCauses`. Used for interactive “what-if” tuning without full diagnosis.

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Frontend (Next.js)                                                      │
│  • Modes: Describe Failure (NL) / Preset Scenarios                       │
│  • Pipeline: Baseline | Agentic (which result to show)                   │
│  • Calls: POST /diagnose or POST /diagnose_nl                             │
│  • Displays: rootCauses, affectedComponents, correctiveActions, plotHtml │
└─────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Backend (FastAPI)                                                       │
│  Scenarios (preset or NL-generated) → net                               │
│  run_pf(net)                                                            │
│  Baseline: EvidenceCollector → LLM → Report Parser → baseline           │
│  Agentic:  Preprocessor (Evidence + RuleEngine) → ReAct + Tools →        │
│            Report Parser → agentic                                      │
│  _generate_diagnostic_plot(net, affected_components) → plotHtml          │
│  Response: { baseline, agentic, plotHtml } (+ NL fields if diagnose_nl)│
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Project structure

```
griddebugagent/
├── backend/
│   ├── app.py                 # FastAPI: /networks, /scenarios, /diagnose, /diagnose_nl,
│   │                           #         /api/visualize, /api/network_state, /api/simulate_overrides;
│   │                           #         report parser; plot generation
│   ├── requirements.txt
│   ├── scenarios/
│   │   ├── base_scenarios.py  # FailureScenario, ScenarioResult, load_network
│   │   ├── normal.py
│   │   ├── nonconvergence.py
│   │   ├── voltage_violations.py
│   │   ├── thermal_overloads.py
│   │   ├── contingency_failures.py
│   │   ├── nl_scenario_generator.py  # NL → scenario code + ground truth
│   │   └── code_sandbox.py
│   ├── rule_engine/
│   │   ├── evidence_collector.py
│   │   ├── rules.py
│   │   └── preprocessor.py
│   ├── agents/
│   │   ├── baseline.py        # LLM-only diagnosis
│   │   ├── agentic_pipeline.py # ReAct + tools
│   │   └── iterative_debugger.py # propose-fix-verify (implemented, not wired to API)
│   └── tools/
│       ├── query_tools.py
│       ├── simulation_tools.py
│       └── diagnostic_tools.py
├── frontend/
│   └── src/
│       ├── app/
│       ├── components/        # diagnostic-layout, input-panel, results-panel
│       ├── lib/api.ts         # fetchNetworks, fetchScenarios, runDiagnosis, runNLDiagnosis
│       └── types/diagnostic.ts
└── README.md
```

---

## 5. How to run

### Backend

```bash
cd backend
pip install -r requirements.txt
# Optional: set OPENAI_API_KEY in .env (otherwise baseline/agentic use mocks)
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Uses `http://localhost:8000` by default (override with `NEXT_PUBLIC_API_URL`).

### Quick API test

```bash
# Preset diagnosis
curl -X POST http://localhost:8000/diagnose \
  -H "Content-Type: application/json" \
  -d '{"network": "case14", "scenario": "extreme_load_scaling"}' | python3 -m json.tool

# Scenario list
curl http://localhost:8000/scenarios
```

---

## 6. API summary

| Method | Path | Description |
|--------|------|-------------|
| GET | `/networks` | List test networks (case14, case30, case57). |
| GET | `/scenarios` | List scenarios (id, label, category). |
| POST | `/diagnose` | Body: `{ network, scenario, query? }`. Optional `query` for benchmark/user task (e.g. paper queries). Returns `{ baseline, agentic, plotHtml }`; agentic includes `toolCalls`, `reasoningTrace`, `reasoningQuality`. |
| POST | `/diagnose_nl` | Body: `{ network, description }`. NL scenario generation then (depending on response_type) full diagnosis, plot only, or text only. Returns `generationStatus`, `generatedCode`, `generatedGroundTruth`, `baseline`, `agentic`, `plotHtml`, `responseType`, `textAnswer`. |
| GET | `/api/visualize/{network}/{scenario}` | Plotly network plot HTML for that scenario. |
| POST | `/api/network_state` | Raw bus/line/load/gen and res_bus/res_line for a scenario (optional generatedCode). |
| POST | `/api/simulate_overrides` | Apply manual overrides to a scenario, run power flow, return `converged`, `plotHtml`, `rootCauses`. |
| GET | `/result/{scenario}` | Placeholder for stored diagnosis results. |

---

## 7. Evaluation and extensions

### 7.1 Evaluation method (task completion, not label matching)

Evaluation should **not** rely on our own labels as ground truth (no expert-labeled dataset; power grid scenarios are complex; our labels may be wrong). Instead, evaluate whether the **agent completes the task**:

- Run power flow and report convergence
- Find overloaded lines
- Contingency analysis
- Rank line flows
- Identify voltage violations, suggest mitigation, etc.

Focus: **Did the agent correctly complete the user query?** not strict output-vs-label matching.

### 7.2 Paper queries benchmark

- Use the **11 queries from the reference paper** as a benchmark. Run them on the current framework and collect agent results.
- **`backend/benchmark_paper_queries.json`**: defines benchmark queries (replace with the paper’s 11 queries when available).
- **`backend/run_benchmark_queries.py`**: runs each query via `POST /diagnose` (with optional `query`), then applies task-completion heuristics and outputs a **comparison table** (Query | Paper Agent | Our Agent). Fill the “Paper Agent” column manually from the paper’s reported results.

```bash
cd backend
# Ensure API is running: uvicorn app:app --reload --port 8000
python run_benchmark_queries.py --output benchmark_results.csv
```

### 7.3 Additional custom queries

After running the paper’s 11 queries, add more user queries (e.g. “Find top 5 heavily loaded lines”, “Identify worst contingency”, “Explain why power flow fails”, “Suggest mitigation”). No ground truth required—show **agent capability** only.

### 7.4 Agent reasoning in the UI

The UI shows the agent’s **reasoning trace** for the Agentic pipeline:

- **Agent reasoning steps**: Step 1, Step 2, … with **tool call** and **result** for each step, then the final report. Use this to debug agent behavior and understand the decision process.
- **Full reasoning process**: Raw trace text (input → tool calls/results → report snippet).
- **Reasoning quality**: Heuristic checks (e.g. used tools, evidence for overload/voltage/balance, reasonable order).

### 7.5 Other

- **Ground truth** (scenario `ScenarioResult`, NL `generatedGroundTruth`) remains available for manual inspection and consistency checks, but is not used as the primary evaluation criterion.
- **Stretch**: `IterativeDebuggerAgent` (propose-fix-verify + ModificationTools) is implemented but not exposed via API; can be wired for iterative what-if debugging.

### 7.6 Suggested next steps

1. **Implement and test the 11 queries from the paper** (replace placeholders in `benchmark_paper_queries.json` with the paper’s exact queries).
2. **Run them on the current agent** via `run_benchmark_queries.py` (backend must be running).
3. **Create an evaluation table** comparing Paper Agent vs Our Agent (fill Paper column from paper; Our column from script output).
4. **Add additional custom queries** to demonstrate agent capability (no ground truth needed).
5. **UI already displays** agent reasoning steps, tool calls, and tool outputs; use this to debug and explain agent decisions.
