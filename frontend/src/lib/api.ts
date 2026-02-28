import { Network, Scenario, DiagnoseResponse, TopologyResponse } from '@/types/diagnostic';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function fetchNetworks(): Promise<Network[]> {
  const res = await fetch(`${API_BASE}/networks`);
  if (!res.ok) throw new Error('Failed to fetch networks');
  const data = await res.json();
  return data.networks;
}

export async function fetchScenarios(): Promise<Scenario[]> {
  const res = await fetch(`${API_BASE}/scenarios`);
  if (!res.ok) throw new Error('Failed to fetch scenarios');
  const data = await res.json();
  return data.scenarios;
}

export async function runDiagnosis(network: string, scenario: string): Promise<DiagnoseResponse> {
  const res = await fetch(`${API_BASE}/diagnose`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ network, scenario }),
  });
  if (!res.ok) throw new Error('Diagnosis request failed');
  return res.json();
}

export async function fetchTopology(network: string, scenario?: string | null): Promise<TopologyResponse> {
  const params = new URLSearchParams({ network });
  if (scenario) params.set('scenario', scenario);
  const res = await fetch(`${API_BASE}/topology?${params.toString()}`);
  if (!res.ok) throw new Error('Failed to fetch topology');
  return res.json();
}
