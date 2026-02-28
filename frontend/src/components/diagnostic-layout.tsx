'use client';

import { useState, useEffect } from 'react';
import { InputPanel } from './input-panel';
import { ResultsPanel } from './results-panel';
import { GridGraph } from './grid-graph';
import { PipelineResult, TopologyResponse } from '@/types/diagnostic';
import { runDiagnosis, fetchTopology } from '@/lib/api';

export function DiagnosticLayout() {
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedNetwork, setSelectedNetwork] = useState<string>('');
  const [selectedScenario, setSelectedScenario] = useState<string>('');
  const [topology, setTopology] = useState<TopologyResponse | null>(null);
  const [topologyLoading, setTopologyLoading] = useState(false);

  useEffect(() => {
    if (!selectedNetwork) {
      setTopology(null);
      return;
    }
    let cancelled = false;
    setTopologyLoading(true);
    fetchTopology(selectedNetwork, selectedScenario || undefined)
      .then((data) => {
        if (!cancelled) setTopology(data);
      })
      .catch(() => {
        if (!cancelled) setTopology(null);
      })
      .finally(() => {
        if (!cancelled) setTopologyLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedNetwork, selectedScenario]);

  const handleAnalyze = async (network: string, scenario: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await runDiagnosis(network, scenario);
      setResult(response.baseline);
    } catch {
      setError('Analysis failed. Please try again.');
      setResult(null);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex h-screen bg-background">
      <div className="w-1/2 border-r border-border flex flex-col min-w-0">
        <div className="flex-shrink-0 overflow-y-auto">
          <InputPanel
            onAnalyze={handleAnalyze}
            isLoading={isLoading}
            selectedNetwork={selectedNetwork}
            selectedScenario={selectedScenario}
            onNetworkChange={setSelectedNetwork}
            onScenarioChange={setSelectedScenario}
          />
        </div>
        <div className="flex-1 min-h-[280px] border-t border-border">
          <GridGraph topology={topology} isLoading={topologyLoading} className="h-full w-full" />
        </div>
      </div>
      <div className="w-1/2 min-w-0">
        <ResultsPanel result={result} isLoading={isLoading} error={error} />
      </div>
    </div>
  );
}
