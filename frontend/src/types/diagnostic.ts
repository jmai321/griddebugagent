export interface ComponentDetail {
  id: string;
  name: string;
  type: 'bus' | 'line' | 'generator' | 'transformer';
  value: number;
}

export interface Action {
  id: string;
  description: string;
  priority: 'high' | 'medium' | 'low';
  category: 'load_shedding' | 'generation_adjustment' | 'topology_change' | 'parameter_adjustment';
}

export interface DiagnosticResult {
  rootCauses: string[];
  affectedComponents: ComponentDetail[];
  correctiveActions: Action[];
  analysisStatus: 'success' | 'partial' | 'failed';
}

export interface TestCase {
  id: string;
  name: string;
  description: string;
  busSystem: '14' | '30' | '57';
  failureType: 'non_convergence' | 'voltage_violation' | 'line_overload';
}
