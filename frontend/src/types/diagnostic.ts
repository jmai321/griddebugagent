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

// Topology graph (nodes = buses, edges = lines/trafos)
export interface TopologyNode {
  id: string;
  busId: number;
  label: string;
  x: number;
  y: number;
  in_service: boolean;
}

export interface TopologyEdge {
  id: string;
  source: string;
  target: string;
  type: 'line' | 'trafo';
  lineIndex?: number;
  trafoIndex?: number;
  in_service: boolean;
}

export interface TopologyResponse {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
}
