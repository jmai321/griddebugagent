'use client';

import { useState } from 'react';
import { InputPanel } from './input-panel';
import { ResultsPanel } from './results-panel';
import { PipelineResult, PipelineId, DiagnoseNLResponse } from '@/types/diagnostic';
import { runDiagnosis, runNLDiagnosis } from '@/lib/api';

export function DiagnosticLayout() {
  const [fullResponse, setFullResponse] = useState<{ baseline: PipelineResult; agentic: PipelineResult; plotHtml?: string } | null>(null);
  const [selectedPipeline, setSelectedPipeline] = useState<PipelineId>('baseline');
  const [nlExtra, setNlExtra] = useState<DiagnoseNLResponse | null>(null);
  const [plotHtml, setPlotHtml] = useState<string | null>(null);
  const [currentNetwork, setCurrentNetwork] = useState<string | null>(null);
  const [currentScenario, setCurrentScenario] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const result: PipelineResult | null = fullResponse ? fullResponse[selectedPipeline] : null;

  const handleAnalyze = async (network: string, scenario: string) => {
    setIsLoading(true);
    setError(null);
    setNlExtra(null);
    setPlotHtml(null);
    setCurrentNetwork(network);
    setCurrentScenario(scenario);
    try {
      const response = await runDiagnosis(network, scenario);
      setFullResponse({ baseline: response.baseline, agentic: response.agentic, plotHtml: response.plotHtml });
      setPlotHtml(response.plotHtml ?? null);
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
    setPlotHtml(null);
    setCurrentNetwork(network);
    setCurrentScenario('nl_generated');
    try {
      const response = await runNLDiagnosis(network, description);
      setNlExtra(response);
      setPlotHtml(response.plotHtml ?? null);
      if (response.generationStatus === 'success') {
        setFullResponse({ baseline: response.baseline, agentic: response.agentic, plotHtml: response.plotHtml });
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

  return (
    <div className="flex h-screen bg-background">
      <div className="w-1/2 border-r border-border">
        <InputPanel
          onAnalyze={handleAnalyze}
          onAnalyzeNL={handleAnalyzeNL}
          isLoading={isLoading}
          selectedPipeline={selectedPipeline}
          onPipelineChange={setSelectedPipeline}
        />
      </div>
      <div className="w-1/2">
        <ResultsPanel
          result={result}
          selectedPipeline={selectedPipeline}
          nlExtra={nlExtra}
          plotHtml={plotHtml}
          isLoading={isLoading}
          error={error}
          networkName={currentNetwork}
          scenarioName={currentScenario}
        />
      </div>
    </div>
  );
}
