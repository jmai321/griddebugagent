'use client';

import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Network, Scenario } from '@/types/diagnostic';
import { fetchNetworks, fetchScenarios } from '@/lib/api';

interface InputPanelProps {
  onAnalyze: (network: string, scenario: string) => void;
  isLoading: boolean;
}

export function InputPanel({ onAnalyze, isLoading }: InputPanelProps) {
  const [networks, setNetworks] = useState<Network[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selectedNetwork, setSelectedNetwork] = useState<string>('');
  const [selectedScenario, setSelectedScenario] = useState<string>('');
  const [fetchError, setFetchError] = useState<string | null>(null);

  useEffect(() => {
    async function loadData() {
      try {
        const [networksData, scenariosData] = await Promise.all([
          fetchNetworks(),
          fetchScenarios(),
        ]);
        setNetworks(networksData);
        setScenarios(scenariosData);
        setFetchError(null);
      } catch {
        setFetchError('Failed to load data. Is the backend running?');
      }
    }
    loadData();
  }, []);

  const handleAnalyze = () => {
    if (selectedNetwork && selectedScenario) {
      onAnalyze(selectedNetwork, selectedScenario);
    }
  };

  const selectedScenarioData = scenarios.find(s => s.id === selectedScenario);

  return (
    <div className="flex flex-col h-full p-6">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold mb-2">GridDebugAgent</h1>
        <p className="text-muted-foreground">
          Analyze power flow failures and get diagnostic recommendations
        </p>
      </div>

      {fetchError && (
        <div className="mb-4 p-3 bg-destructive/10 text-destructive rounded-md text-sm">
          {fetchError}
        </div>
      )}

      <div className="flex-1 space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Network</CardTitle>
            <CardDescription>
              Select an IEEE test network
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Select value={selectedNetwork} onValueChange={setSelectedNetwork}>
              <SelectTrigger>
                <SelectValue placeholder="Select network..." />
              </SelectTrigger>
              <SelectContent>
                {networks.map((network) => (
                  <SelectItem key={network.id} value={network.id}>
                    {network.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Failure Scenario</CardTitle>
            <CardDescription>
              Choose a failure scenario to diagnose
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Select value={selectedScenario} onValueChange={setSelectedScenario}>
              <SelectTrigger>
                <SelectValue placeholder="Select scenario..." />
              </SelectTrigger>
              <SelectContent>
                {scenarios.map((scenario) => (
                  <SelectItem key={scenario.id} value={scenario.id}>
                    <div className="flex flex-col items-start">
                      <span>{scenario.label}</span>
                      <span className="text-xs text-muted-foreground">
                        {scenario.category}
                      </span>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            {selectedScenarioData && (
              <div className="p-3 bg-muted/50 rounded-md text-sm text-muted-foreground">
                Category: {selectedScenarioData.category}
              </div>
            )}
          </CardContent>
        </Card>

        <Button
          onClick={handleAnalyze}
          disabled={!selectedNetwork || !selectedScenario || isLoading}
          className="w-full"
          size="lg"
        >
          {isLoading ? 'Analyzing...' : 'Run Analysis'}
        </Button>
      </div>
    </div>
  );
}
