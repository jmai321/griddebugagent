import { TestCase, DiagnosticResult } from '@/types/diagnostic';

/**
 * Mock test cases for dropdown selection.
 * TODO: Replace with GET /testcases API call
 */
export const testCases: TestCase[] = [
  {
    id: 'case14_test1',
    name: 'IEEE 14-bus: Base Case',
    description: 'Standard IEEE 14-bus test network power flow analysis.',
    busSystem: '14',
    failureType: 'non_convergence'
  },
  {
    id: 'case14_test2',
    name: 'IEEE 14-bus: Voltage Check',
    description: 'IEEE 14-bus network with voltage limit verification.',
    busSystem: '14',
    failureType: 'voltage_violation'
  },
  {
    id: 'case30_test1',
    name: 'IEEE 30-bus: Base Case',
    description: 'Standard IEEE 30-bus test network power flow analysis.',
    busSystem: '30',
    failureType: 'line_overload'
  },
  {
    id: 'case57_test1',
    name: 'IEEE 57-bus: Base Case',
    description: 'Standard IEEE 57-bus test network power flow analysis.',
    busSystem: '57',
    failureType: 'voltage_violation'
  }
];

/**
 * Mock diagnostic result for UI development.
 * TODO: Replace with POST /diagnose API response
 */
export const mockDiagnosticResult: DiagnosticResult = {
  analysisStatus: 'success',
  rootCauses: [
    'Root Cause 1',
    'Root Cause 2',
    'Root Cause 3'
  ],
  affectedComponents: [
    { id: 'comp_1', name: 'Component 1', type: 'bus', value: 1.0 },
    { id: 'comp_2', name: 'Component 2', type: 'line', value: 1.0 }
  ],
  correctiveActions: [
    {
      id: 'action_1',
      description: 'Action 1',
      priority: 'high',
      category: 'load_shedding'
    },
    {
      id: 'action_2',
      description: 'Action 2',
      priority: 'medium',
      category: 'generation_adjustment'
    }
  ]
};
