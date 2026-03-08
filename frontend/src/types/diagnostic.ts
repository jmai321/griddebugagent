// API response types

export interface Network {
  id: string;
  label: string;
}

export interface Scenario {
  id: string;
  label: string;
  category: 'normal' | 'nonconvergence' | 'voltage' | 'thermal' | 'contingency';
}

/** One tool invocation during agentic reasoning. */
export interface AgentToolCall {
  iteration: number;
  tool: string;
  args: Record<string, unknown>;
  result: unknown;
}

export interface PipelineResult {
  rawResult?: string;
  analysisStatus: 'success' | 'error' | 'not_implemented' | 'skipped';
  rootCauses: string[];
  affectedComponents: string[];
  correctiveActions: string[];
  /** Present for agentic pipeline: tools the agent called (reasoning trace). */
  toolCalls?: AgentToolCall[];
  /** Alias for backward compat with local execution trace UI */
  tool_calls?: AgentToolCall[];
  /** Full reasoning process text (agentic only): steps and tool results. */
  reasoningTrace?: string;
  /** Heuristic checks: does tool usage support the report? (agentic only). */
  reasoningQuality?: {
    checks: { id: string; passed: boolean; message: string }[];
    summary: string;
    passedCount: number;
    totalCount: number;
  };
  /** Iterative debugger: history of corrective actions applied. */
  fixHistory?: Array<Record<string, unknown>>;
  /** Whether power flow converged after all fixes (iterative only). */
  finalConverged?: boolean;
  /** Number of fix iterations used (iterative only). */
  iterationsUsed?: number;
  /** Execution trace (tool calls or fix history). */
  executionTrace?: unknown[];
}

export type PipelineId = 'baseline' | 'agentic' | 'iterative';

export interface DiagnoseResponse {
  baseline: PipelineResult;
  agentic: PipelineResult;
  iterative?: PipelineResult;
  plotHtml?: string;
  iterativePlotHtml?: string;
}

export interface GeneratedGroundTruth {
  failureType: string;
  rootCauses: string[];
  affectedComponents: Record<string, unknown>;
  knownFix: string;
}

export interface DiagnoseNLResponse {
  generationStatus: 'success' | 'error';
  generationError: string | null;
  generatedCode: string;
  generatedGroundTruth: GeneratedGroundTruth | null;
  baseline: PipelineResult;
  agentic: PipelineResult;
  iterative?: PipelineResult;
  plotHtml?: string;
  iterativePlotHtml?: string;
  responseType: 'text_only' | 'plot_only' | 'direct_answer' | 'full_diagnosis';
  textAnswer?: string;
}

// Network Manipulation Types
export interface OverrideState {
  globalLoadScale: number;
  lineOutages: number[];
  trafoOutages: number[];
  loadOverrides: Record<number, { p_mw?: number; q_mvar?: number; in_service?: boolean }>;
  genOverrides: Record<number, { p_mw?: number; vm_pu?: number; in_service?: boolean }>;
  extGridOverrides: Record<number, { vm_pu?: number; in_service?: boolean }>;
}

export interface BusData {
  name: string;
  vn_kv: number;
  type: string;
  in_service: boolean;
  [key: string]: any;
}

export interface LineData {
  name: string;
  from_bus: number;
  to_bus: number;
  length_km: number;
  in_service: boolean;
  [key: string]: any;
}

export interface LoadData {
  name: string;
  bus: number;
  p_mw: number;
  q_mvar: number;
  in_service: boolean;
  [key: string]: any;
}

export interface GenData {
  name: string;
  bus: number;
  p_mw: number;
  vm_pu: number;
  in_service: boolean;
  [key: string]: any;
}

export interface TrafoData {
  name: string;
  hv_bus: number;
  lv_bus: number;
  in_service: boolean;
  [key: string]: any;
}

export interface ExtGridData {
  name: string;
  bus: number;
  vm_pu: number;
  in_service: boolean;
  [key: string]: any;
}

export interface RawNetworkState {
  bus: Record<string, BusData>;
  line: Record<string, LineData>;
  load: Record<string, LoadData>;
  gen: Record<string, GenData>;
  trafo: Record<string, TrafoData>;
  ext_grid: Record<string, ExtGridData>;
  res_bus?: any[];
  res_line?: any[];
}

