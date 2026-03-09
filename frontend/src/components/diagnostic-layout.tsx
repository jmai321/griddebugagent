'use client';

import { useState } from 'react';
import { InputPanel } from './input-panel';
import { ResultsPanel } from './results-panel';
import { PipelineResult, PipelineId, DiagnoseNLResponse, DiagnoseResponse } from '@/types/diagnostic';
import { runDiagnosis, runNLDiagnosis } from '@/lib/api';

export function DiagnosticLayout() {
  const [fullResponse, setFullResponse] = useState<{ baseline: PipelineResult; agentic: PipelineResult } | null>(null);
  const [selectedPipeline, setSelectedPipeline] = useState<PipelineId>('baseline');
  const [nlExtra, setNlExtra] = useState<DiagnoseNLResponse | null>(null);
  const [currentNetwork, setCurrentNetwork] = useState<string | null>(null);
  const [currentScenario, setCurrentScenario] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const result: PipelineResult | null = fullResponse ? fullResponse[selectedPipeline] : null;

  const handleAnalyze = async (network: string, scenario: string) => {
    setIsLoading(true);
    setError(null);
    setNlExtra(null);
    setCurrentNetwork(network);
    setCurrentScenario(scenario);
    try {
      const response = await runDiagnosis(network, scenario);
      setFullResponse({ baseline: response.baseline, agentic: response.agentic });
    } catch {
      setError('Analysis failed. Please try again.');
      setFullResponse(null);
    } finally {
      setIsLoading(false);
    }
  };

  const handleAnalyzeNL = async (network: string, description: string) => {
    setIsLoading(true);
    setError(null);
    setNlExtra(null);
    setCurrentNetwork(network);
    setCurrentScenario('nl_generated');
    try {
      const response = await runNLDiagnosis(network, description);
      setNlExtra(response);
      if (response.generationStatus === 'success') {
        setFullResponse({ baseline: response.baseline, agentic: response.agentic });
      } else {
        setError(response.generationError || 'Failed to generate scenario');
        setFullResponse(null);
      }
    } catch {
      setError('NL Analysis failed. Please try again.');
      setFullResponse(null);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDiagnosisUpdate = (response: DiagnoseResponse) => {
    setFullResponse({ baseline: response.baseline, agentic: response.agentic });
  };

  return (
    <div className="flex h-screen bg-background overflow-hidden">
      <div className="w-[360px] min-w-[320px] border-r border-border flex-shrink-0 h-full overflow-y-auto">
        <InputPanel
          onAnalyze={handleAnalyze}
          onAnalyzeNL={handleAnalyzeNL}
          isLoading={isLoading}
          selectedPipeline={selectedPipeline}
          onPipelineChange={setSelectedPipeline}
        />
      </div>
      <div className="flex-1 h-full overflow-hidden">
        <ResultsPanel
          result={result}
          selectedPipeline={selectedPipeline}
          nlExtra={nlExtra}
          isLoading={isLoading}
          error={error}
          networkName={currentNetwork}
          scenarioName={currentScenario}
          onDiagnosisUpdate={handleDiagnosisUpdate}
        />
      </div>
    </div>
  );
}
