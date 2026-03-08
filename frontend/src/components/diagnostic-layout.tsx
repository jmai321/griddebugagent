'use client';

import { useState } from 'react';
import { InputPanel } from './input-panel';
import { ResultsPanel } from './results-panel';
import { PipelineResult, PipelineId, DiagnoseNLResponse } from '@/types/diagnostic';
import { runDiagnosisStream, runNLDiagnosis } from '@/lib/api';

export function DiagnosticLayout() {
  const [fullResponse, setFullResponse] = useState<{ baseline: PipelineResult; agentic: PipelineResult; iterative?: PipelineResult; plotHtml?: string } | null>(null);
  const [selectedPipeline, setSelectedPipeline] = useState<PipelineId>('baseline');
  const [nlExtra, setNlExtra] = useState<DiagnoseNLResponse | null>(null);
  const [plotHtml, setPlotHtml] = useState<string | null>(null);
  const [iterativePlotHtml, setIterativePlotHtml] = useState<string | null>(null);
  const [currentNetwork, setCurrentNetwork] = useState<string | null>(null);
  const [currentScenario, setCurrentScenario] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [loadingStage, setLoadingStage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [readyPipelines, setReadyPipelines] = useState<Set<PipelineId>>(new Set(['baseline', 'agentic']));

  const result: PipelineResult | null = fullResponse ? (fullResponse[selectedPipeline] ?? null) : null;
  const iterativeResult: PipelineResult | null = fullResponse?.iterative ?? null;

  const handleAnalyze = async (network: string, scenario: string, query?: string) => {
    setIsLoading(true);
    setError(null);
    setNlExtra(null);
    setPlotHtml(null);
    setFullResponse(null);
    setCurrentNetwork(network);
    setCurrentScenario(scenario);
    setLoadingStage('Generating visualization...');
    setReadyPipelines(new Set());

    try {
      await runDiagnosisStream(network, scenario, query, (event, data) => {
        switch (event) {
          case 'plot':
            setPlotHtml(data.plotHtml ?? null);
            setLoadingStage('Running baseline...');
            break;
          case 'baseline':
            setReadyPipelines(prev => new Set(prev).add('baseline'));
            setFullResponse(prev => ({
              baseline: data,
              agentic: prev?.agentic ?? ({} as PipelineResult),
              iterative: prev?.iterative,
              plotHtml: prev?.plotHtml,
            }));
            setLoadingStage('Running agentic pipeline...');
            break;
          case 'agentic':
            setReadyPipelines(prev => new Set(prev).add('agentic'));
            setFullResponse(prev => ({ ...prev!, agentic: data }));
            setLoadingStage('Running iterative debugger...');
            break;
          case 'iterative':
            setFullResponse(prev => ({ ...prev!, iterative: data }));
            if (data.iterativePlotHtml) setIterativePlotHtml(data.iterativePlotHtml);
            setLoadingStage(null);
            break;
          case 'done':
            setLoadingStage(null);
            break;
        }
      });
    } catch {
      setError('Analysis failed. Please try again.');
      setFullResponse(null);
    } finally {
      setIsLoading(false);
      setLoadingStage(null);
    }
  };

  const handleAnalyzeNL = async (network: string, description: string) => {
    setIsLoading(true);
    setError(null);
    setNlExtra(null);
    setPlotHtml(null);
    setIterativePlotHtml(null);
    setCurrentNetwork(network);
    setCurrentScenario('nl_generated');
    try {
      const response = await runNLDiagnosis(network, description);
      setNlExtra(response);
      setPlotHtml(response.plotHtml ?? null);
      setIterativePlotHtml(response.iterativePlotHtml ?? null);
      if (response.generationStatus === 'success') {
        setFullResponse({ baseline: response.baseline, agentic: response.agentic, iterative: response.iterative, plotHtml: response.plotHtml });
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
          readyPipelines={readyPipelines}
        />
      </div>
      <div className="w-1/2">
        <ResultsPanel
          result={result}
          selectedPipeline={selectedPipeline}
          iterativeResult={iterativeResult}
          nlExtra={nlExtra}
          plotHtml={plotHtml}
          iterativePlotHtml={iterativePlotHtml}
          isLoading={isLoading}
          loadingStage={loadingStage}
          error={error}
          networkName={currentNetwork}
          scenarioName={currentScenario}
        />
      </div>
    </div>
  );
}
