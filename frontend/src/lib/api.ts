import { Network, Scenario, DiagnoseResponse, DiagnoseNLResponse } from '@/types/diagnostic';

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

export async function runDiagnosis(
  network: string,
  scenario: string,
  query?: string
): Promise<DiagnoseResponse> {
  const body: { network: string; scenario: string; query?: string } = { network, scenario };
  if (query?.trim()) body.query = query.trim();
  const res = await fetch(`${API_BASE}/diagnose`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error('Diagnosis request failed');
  return res.json();
}

export async function runNLDiagnosis(network: string, description: string): Promise<DiagnoseNLResponse> {
  const res = await fetch(`${API_BASE}/diagnose_nl`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ network, description }),
  });
  if (!res.ok) throw new Error('NL Diagnosis request failed');
  return res.json();
}
