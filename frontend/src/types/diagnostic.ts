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
  analysisStatus: 'success' | 'error' | 'not_implemented' | 'skipped';
  rootCauses: string[];
  affectedComponents: string[];
  correctiveActions: string[];
}

export interface DiagnoseResponse {
  baseline: PipelineResult;
  agentic: PipelineResult;
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
}
