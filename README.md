# GridDebugAgent

以 LLM 輔助電力系統潮流模擬失敗診斷的實驗專案。在 IEEE 測試網路（pandapower）上注入各類故障情境，透過 Baseline（純 LLM）與規劃中的 Agentic pipeline 產出結構化診斷報告（根因、受影響元件、矯正建議），供期中／期末報告評估與比較。

---

## 1. 專案概述與動機

- **目標**：當 pandapower 潮流計算不收斂或收斂後出現違規時，自動產出可解釋的診斷（根因、受影響元件、矯正措施）。
- **方法**：結合規則引擎預處理與 LLM 推論，並預留「具工具呼叫的 Agentic pipeline」以進行對比實驗。
- **評估**：每個情境有 ground truth（`ScenarioResult`），可與模型輸出的 root causes / affected components / corrective actions 比對。

---

## 2. 系統架構

整體為前後端分離：**前端**提供測試案例選擇與結果展示，**後端**負責情境注入、潮流計算、證據收集、規則評估與 LLM 診斷。

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Frontend (Next.js)                                                      │
│  • 選擇測試案例（網路 + 情境）→ 呼叫 POST /diagnose                       │
│  • 顯示 baseline / agentic 的 rootCauses, affectedComponents, correctiveActions │
└─────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Backend (FastAPI)                                                       │
│  ┌─────────────┐   ┌──────────────┐   ┌─────────────┐   ┌─────────────┐  │
│  │  Scenarios  │   │  Rule Engine │   │   Agents    │   │  Report     │  │
│  │  情境注入   │ → │  證據+規則   │ → │ Baseline /  │ → │  Parser     │  │
│  │  (pandapower)│   │  分類失敗類型 │   │ Agentic     │   │  結構化輸出  │  │
│  └─────────────┘   └──────────────┘   └─────────────┘   └─────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.1 後端模組

| 模組 | 路徑 | 功能 |
|------|------|------|
| **API** | `backend/app.py` | FastAPI 應用：`/networks`、`/scenarios`、`/pipelines`、`/diagnose`。依請求的 network + scenario 載入情境、跑潮流、呼叫 baseline（與預留 agentic）、解析 LLM 報告為結構化 JSON。 |
| **Scenarios** | `backend/scenarios/` | 以 IEEE 14/30/57 為基礎，注入四類故障：**不收斂**（極端負載、全發電機移除、近零阻抗、斷網）、**電壓違規**（重載低壓、過發高壓、無功不平衡）、**熱過載**（集中負載、降熱限、拓樸轉移）、**N−1 事故**（線路／變壓器）。每個情境回傳 `ScenarioResult`（含 root_causes、affected_components、known_fix）作為 ground truth。 |
| **Rule Engine** | `backend/rule_engine/` | **EvidenceCollector**：從 pandapower 網路收集收斂狀態、負載/發電、電壓、線路/變壓器負載、diagnostic 結果等。**RuleEngine**：依證據觸發規則（如 nonconvergence、undervoltage、line_overload、generation_deficit 等）並分類失敗類型。**Preprocessor**：串接證據收集與規則評估，產出給 LLM（或 Agentic）的結構化 context。 |
| **Agents** | `backend/agents/` | **Baseline**：僅將證據摘要送給 LLM，無工具、無規則輸出，產出自然語言報告後由 app 內 **Report Parser** 解析成 `rootCauses`、`affectedComponents`、`correctiveActions`。**Agentic**（規劃）：ReAct + 工具呼叫；**Iterative Debugger**（規劃）：在 Agentic 上加入 propose-fix-verify 迴圈。 |

### 2.2 前端模組

| 模組 | 路徑 | 功能 |
|------|------|------|
| **Layout** | `frontend/src/components/diagnostic-layout.tsx` | 左側輸入、右側結果；目前以 mock 資料示範，可改為呼叫 `POST /diagnose` 並對接 API 回傳的 `baseline` / `agentic` 結構。 |
| **Input** | `frontend/src/components/input-panel.tsx` | 測試案例下拉選單（可改為依 `/networks` + `/scenarios` 動態取得）、執行分析按鈕。 |
| **Results** | `frontend/src/components/results-panel.tsx` | 顯示 root causes、affected components、corrective actions；型別定義於 `frontend/src/types/diagnostic.ts`，可與後端 `DiagnoseResult.baseline` / `agentic` 對齊。 |

---

## 3. 實驗方法

### 3.1 測試網路

- **IEEE 14-bus**（case14）、**IEEE 30-bus**（case30）、**IEEE 57-bus**（case57），由 pandapower 內建網路載入，每個情境在指定網路上施加修改後執行潮流。

### 3.2 故障情境（Scenarios）

共 **13 個情境**，分四類：

| 類別 | 情境 ID（範例） | 說明 |
|------|------------------|------|
| **nonconvergence** | extreme_load_scaling, all_generators_removed, near_zero_impedance, disconnected_subnetwork | 潮流不收斂 |
| **voltage** | heavy_loading_undervoltage, excess_generation_overvoltage, reactive_imbalance | 電壓越界（如 &lt;0.95 或 &gt;1.05 pu） |
| **thermal** | concentrated_loading, reduced_thermal_limits, topology_redirection | 線路／變壓器熱過載 |
| **contingency** | line_contingency_overload, trafo_contingency_voltage | N−1 事故導致過載或電壓違規 |

每個情境的 `apply()` 會修改網路並回傳 **ScenarioResult**（root_causes、affected_components、known_fix），用作評估時的 ground truth。

### 3.3 診斷管道（Pipelines）

- **Baseline**：EvidenceCollector 產出證據摘要 → 單次 LLM 呼叫（system + user prompt）→ 回傳 markdown 報告 → 後端 **Report Parser** 從 `## Root Causes`、`## Affected Components`、`## Corrective Actions` 區塊擷取條目（支援 bullet 與編號清單），組合成結構化輸出。
- **Agentic**（預留）：預期為規則引擎 context + 工具呼叫（query/simulation/diagnostic），目前 API 回傳 `analysisStatus: "not_implemented"` 與空陣列。

### 3.4 實驗流程（單次 run）

1. 選定 **network**（case14 / case30 / case57）與 **scenario**（上述 13 個之一）。
2. 後端依 scenario 載入對應情境類別、執行 `apply()` 得到修改後網路與 ground truth。
3. 執行 **潮流**（`run_pf()`），不論收斂與否皆繼續。
4. **Baseline**：收集證據 → 組 prompt → 呼叫 LLM → 解析報告 → 得到 `baseline.rootCauses`、`baseline.affectedComponents`、`baseline.correctiveActions`。
5. **Agentic**：目前回傳 stub。
6. API 回傳結構為：
   - `baseline`: `{ analysisStatus, rootCauses, affectedComponents, correctiveActions }`
   - `agentic`: 同上結構（目前為 not_implemented + 空陣列）

### 3.5 評估要點（可寫在報告中）

- **Ground truth**：來自 `ScenarioResult` 的 root_causes、affected_components、known_fix。
- **自動化評估**：可比較模型輸出的 root causes / affected components 與 ground truth 的重疊度（例如關鍵字或元件 ID 比對）。
- **對照實驗**：Baseline（僅 LLM）vs 未來的 Agentic（規則 + 工具），比較診斷準確度與可解釋性。

---

## 4. 專案目錄結構

```
griddebugagent/
├── backend/
│   ├── app.py                 # FastAPI：/networks, /scenarios, /pipelines, /diagnose，Report Parser
│   ├── requirements.txt
│   ├── scenarios/             # 情境定義與注入
│   │   ├── base_scenarios.py  # FailureScenario, ScenarioResult, load_network
│   │   ├── nonconvergence.py
│   │   ├── voltage_violations.py
│   │   ├── thermal_overloads.py
│   │   └── contingency_failures.py
│   ├── rule_engine/           # 證據收集與規則分類
│   │   ├── evidence_collector.py
│   │   ├── rules.py
│   │   └── preprocessor.py
│   └── agents/
│       ├── baseline.py        # Level 1：純 LLM 診斷
│       ├── agentic_pipeline.py # Level 2（預留）
│       └── iterative_debugger.py # Level 3（預留）
├── frontend/                  # Next.js：輸入面板、結果面板、mock/API 對接
│   └── src/
│       ├── app/
│       ├── components/
│       ├── types/
│       └── data/
└── README.md
```

---

## 5. 如何執行

### 5.1 後端

```bash
cd backend
pip install -r requirements.txt
# 若需真實 LLM：在 .env 設定 OPENAI_API_KEY
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

無 API key 時會使用 baseline 內建的 mock 回應，仍可得到結構化輸出。

### 5.2 前端

```bash
cd frontend
npm install
npm run dev
```

目前結果為 mock；要接真實 API 時，在 `diagnostic-layout.tsx` 將 `handleAnalyze` 改為對 `POST http://localhost:8000/diagnose` 發送 `{ network, scenario, pipeline }`，並將回傳的 `baseline`（或 `agentic`）對應到 `DiagnosticResult` 顯示。

### 5.3 以 curl 測試診斷 API

```bash
curl -X POST http://localhost:8000/diagnose \
  -H "Content-Type: application/json" \
  -d '{"network": "case14", "scenario": "extreme_load_scaling", "pipeline": "baseline"}' \
  | python3 -m json.tool
```

回傳格式為 `{ "baseline": { ... }, "agentic": { ... } }`，可直接用於撰寫實驗結果與比較。

---

## 6. API 摘要

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/networks` | 取得測試網路列表（case14, case30, case57）。 |
| GET | `/scenarios` | 取得情境列表（id, label, category）。 |
| GET | `/pipelines` | 取得診斷管道列表（目前含 baseline）。 |
| POST | `/diagnose` | Body: `{ network, scenario, pipeline }`。回傳 `{ baseline, agentic }`，各有 `analysisStatus`、`rootCauses`、`affectedComponents`、`correctiveActions`。 |

---

## 7. 參考與延伸

- 潮流與網路： [pandapower](https://www.pandapower.org/).
- 實驗設計可延伸：加入更多情境、對 root causes / corrective actions 做自動評分、或接上 Agentic pipeline 後做 A/B 比較，用於期中／期末報告的實驗方法與架構說明。
