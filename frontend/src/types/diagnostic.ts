// API response types

export interface Network {
  id: string;
  label: string;
}

export interface Scenario {
  id: string;
  label: string;
  category: 'nonconvergence' | 'voltage' | 'thermal' | 'contingency';
}

export interface PipelineResult {
  analysisStatus: 'success' | 'error' | 'not_implemented';
  rootCauses: string[];
  affectedComponents: string[];
  correctiveActions: string[];
}

export interface DiagnoseResponse {
  baseline: PipelineResult;
  agentic: PipelineResult;
}
