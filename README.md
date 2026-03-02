# GridDebugAgent

以 LLM 與 Agentic pipeline 輔助電力系統潮流模擬失敗診斷。在 IEEE 測試網路（pandapower）上注入故障情境，產出結構化診斷報告（根因、受影響元件、矯正建議），並提供網路視覺化與自然語言情境生成。

---

## 1. 已完成功能（Completed Features）

### 1.1 診斷管道（Pipelines）

| 功能 | 說明 |
|------|------|
| **Baseline (LLM only)** | 由 EvidenceCollector 彙整潮流結果（收斂、負載/發電、違規等）→ 單次 LLM 呼叫 → 產出自然語言報告 → 後端解析成結構化 `rootCauses`、`affectedComponents`、`correctiveActions`。 |
| **Agentic (with tools)** | 由 Preprocessor（EvidenceCollector + RuleEngine）產出規則分類與 failure_category → LLM 在 ReAct 迴圈中可呼叫 **tools**（查詢、模擬、診斷）→ 產出 FINAL REPORT → 同一套 parser 解析成結構化輸出。 |

### 1.2 情境輸入方式

| 方式 | 說明 |
|------|------|
| **Preset Scenarios** | 從固定情境清單選擇：網路（case14/30/57）+ 情境（normal、nonconvergence、voltage、thermal、contingency 等 14 個）。後端依 scenario 注入故障、跑潮流、跑 baseline + agentic，回傳結構化結果與 plotHtml。 |
| **Natural Language (NL)** | 使用者以自然語言描述故障（例如「Scale all loads by 15x」）。後端用 NLScenarioGenerator 產生情境程式碼並在 sandbox 執行，得到修改後的 net 與 ground_truth，再跑 baseline + agentic 與視覺化。 |

### 1.3 工具（Tools，供 Agentic 使用）

| 類別 | 工具範例 |
|------|----------|
| **Query** | `get_network_summary`、`get_bus_data`、`get_line_data`、`get_gen_data`、`get_voltage_profile`、`get_loading_profile`、`get_power_balance` |
| **Simulation** | `run_power_flow`、`run_dc_power_flow`、`run_n1_contingency` |
| **Diagnostic** | `run_full_diagnostics`、`check_overloads`、`check_voltage_violations`、`find_disconnected_areas` |

### 1.4 網路視覺化（Network Visualization）

- 後端以 **pandapower.plotting.plotly**（`simple_plotly` + `create_bus_trace` / `create_line_trace` / `create_trafo_trace`）根據 **ground truth 的 affected_components** 產生 Plotly 圖，受影響的 bus/line/trafo 標為紅色。
- 回傳 `plotHtml`（完整 HTML 字串），前端以 **iframe srcDoc** 嵌入顯示，可縮放、hover。

### 1.5 前端行為

- **Pipeline 選擇**：下拉選「Baseline (LLM only)」或「Agentic (with tools)」，結果區顯示對應管道的輸出。
- **模式切換**：Describe Failure（NL）／Preset Scenarios；NL 成功時會顯示 generated scenario 與 baseline/agentic 結果。
- **結果區**：Root Causes、Affected Components、Recommendations（corrective actions），以及 Network Visualization（若有 plotHtml）。

---

## 2. 整體 Workflow

### 2.1 Preset 流程（選擇固定情境）

```
使用者選擇 Network + Scenario（Preset）
    → 前端 POST /diagnose { network, scenario }
    → 後端：_find_and_apply_scenario → 得到 net, ground_truth
    → 後端：run_pf(net)
    → 後端：BaselineAgent.diagnose(net) → 報告 → _build_pipeline_result → baseline
    → 後端：AgenticPipelineAgent.diagnose(net) → ReAct + tools → 報告 → _build_pipeline_result → agentic
    → 後端：_generate_diagnostic_plot(net, ground_truth.affected_components) → plotHtml
    → 回傳 { baseline, agentic, plotHtml }
    → 前端：存 fullResponse，依 selectedPipeline 顯示 baseline 或 agentic；若有 plotHtml 則 iframe 顯示
```

### 2.2 Natural Language 流程（描述故障）

```
使用者輸入 Network + 自然語言描述（Describe Failure）
    → 前端 POST /diagnose_nl { network, description }
    → 後端：NLScenarioGenerator.generate(description, network) → 產生程式碼、執行、得到 net, ground_truth
    → 若 generation_status != success → 回傳錯誤與 generatedCode，baseline/agentic 為 skipped
    → 否則：run_pf(net)，再跑 baseline + agentic（同 Preset），_generate_diagnostic_plot → plotHtml
    → 回傳 { generationStatus, generatedCode, generatedGroundTruth, baseline, agentic, plotHtml }
    → 前端：顯示 NL 生成結果（含 ground truth）、可切換 pipeline 看 baseline/agentic、顯示 plotHtml
```

### 2.3 報告解析（共用）

- 兩管道皆產出含 `## Root Causes`、`## Affected Components`、`## Corrective Actions` 的 markdown。
- `_parse_llm_report` 支援同一行多個 section、bullet（`-`/`*`）與編號（`1.`）清單，擷取為字串陣列。
- `_build_pipeline_result(report, status)` 產出 `{ analysisStatus, rootCauses, affectedComponents, correctiveActions }`。

---

## 3. 系統架構簡圖

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Frontend (Next.js)                                                      │
│  • 模式：Describe Failure (NL) / Preset Scenarios                         │
│  • Pipeline 選擇：Baseline | Agentic                                     │
│  • 呼叫 POST /diagnose 或 POST /diagnose_nl                               │
│  • 顯示 rootCauses / affectedComponents / correctiveActions + plotHtml   │
└─────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Backend (FastAPI)                                                       │
│  Scenarios → 情境注入 (preset 或 NL 生成) → net                           │
│  run_pf(net)                                                             │
│  Baseline: EvidenceCollector → LLM → Report Parser → baseline             │
│  Agentic:  Preprocessor (Evidence + RuleEngine) → ReAct + Tools →      │
│            Report Parser → agentic                                       │
│  _generate_diagnostic_plot(net, affected_components) → plotHtml          │
│  回傳 { baseline, agentic, plotHtml }                                    │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 4. 專案目錄結構

```
griddebugagent/
├── backend/
│   ├── app.py                    # FastAPI：/networks, /scenarios, /diagnose, /diagnose_nl,
│   │                              #         /api/visualize, /api/network_state；Report Parser；Plot 生成
│   ├── requirements.txt
│   ├── scenarios/                 # 情境定義與注入
│   │   ├── base_scenarios.py      # FailureScenario, ScenarioResult, load_network
│   │   ├── normal.py
│   │   ├── nonconvergence.py
│   │   ├── voltage_violations.py
│   │   ├── thermal_overloads.py
│   │   ├── contingency_failures.py
│   │   ├── nl_scenario_generator.py  # 自然語言 → 情境程式碼 → 執行
│   │   └── code_sandbox.py
│   ├── rule_engine/               # 證據收集與規則分類
│   │   ├── evidence_collector.py
│   │   ├── rules.py
│   │   └── preprocessor.py
│   ├── agents/
│   │   ├── baseline.py            # 純 LLM 診斷
│   │   ├── agentic_pipeline.py    # ReAct + tools
│   │   └── iterative_debugger.py  # propose-fix-verify（已實作，尚未接 API）
│   └── tools/                     # Agentic 可用工具
│       ├── query_tools.py
│       ├── simulation_tools.py
│       └── diagnostic_tools.py
├── frontend/
│   └── src/
│       ├── app/
│       ├── components/            # diagnostic-layout, input-panel, results-panel
│       ├── lib/api.ts             # fetchNetworks, fetchScenarios, runDiagnosis, runNLDiagnosis
│       └── types/diagnostic.ts
└── README.md
```

---

## 5. 如何執行

### 5.1 後端

```bash
cd backend
pip install -r requirements.txt
# 設定 .env：OPENAI_API_KEY=sk-...（若未設定，baseline/agentic 會用 mock）
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

### 5.2 前端

```bash
cd frontend
npm install
npm run dev
```

預設會連 `http://localhost:8000`（可透過 `NEXT_PUBLIC_API_URL` 調整）。

### 5.3 快速測試 API

```bash
# Preset 診斷
curl -X POST http://localhost:8000/diagnose \
  -H "Content-Type: application/json" \
  -d '{"network": "case14", "scenario": "extreme_load_scaling"}' | python3 -m json.tool

# 取得情境列表
curl http://localhost:8000/scenarios
```

---

## 6. API 摘要

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/networks` | 測試網路列表（case14, case30, case57）。 |
| GET | `/scenarios` | 情境列表（id, label, category），含 normal 與四類故障。 |
| POST | `/diagnose` | Body: `{ network, scenario }`。回傳 `{ baseline, agentic, plotHtml }`，兩管道皆為 `{ analysisStatus, rootCauses, affectedComponents, correctiveActions }`。 |
| POST | `/diagnose_nl` | Body: `{ network, description }`。NL 生成情境後跑 baseline + agentic，回傳 `generationStatus`、`generatedCode`、`generatedGroundTruth`、`baseline`、`agentic`、`plotHtml`。 |
| GET | `/api/visualize/{network}/{scenario}` | 回傳該情境之 Plotly 網路圖 HTML（HTMLResponse）。 |
| GET | `/api/network_state/{network}/{scenario}` | 回傳該情境之 bus/line/load/gen 與 res_bus/res_line（JSON）。 |
| GET | `/result/{scenario}` | 占位，可擴充為查詢歷史診斷結果。 |

---

## 7. 評估與後續可做

- **Ground truth**：每個情境有 `ScenarioResult`（root_causes、affected_components、known_fix）；NL 情境有 `generatedGroundTruth`。可據此做 correctness / usefulness / consistency 的自動或人工評估。
- **Stretch**：`IterativeDebuggerAgent` 已實作（propose-fix-verify + ModificationTools），可接 API 與前端以支援「試一個修正 → 重跑 → 解釋剩餘問題」。
