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

export interface PipelineResult {
  analysisStatus: 'success' | 'error' | 'not_implemented' | 'skipped';
  rootCauses: string[];
  affectedComponents: string[];
  correctiveActions: string[];
}

export type PipelineId = 'baseline' | 'agentic';

export interface DiagnoseResponse {
  baseline: PipelineResult;
  agentic: PipelineResult;
  plotHtml?: string;
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
  plotHtml?: string;
  responseType: 'text_only' | 'plot_only' | 'full_diagnosis';
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

