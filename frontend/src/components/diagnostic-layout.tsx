'use client';

import { useState } from 'react';
import { InputPanel } from './input-panel';
import { ResultsPanel } from './results-panel';
import { PipelineResult, DiagnoseNLResponse } from '@/types/diagnostic';
import { runDiagnosis, runNLDiagnosis } from '@/lib/api';

export function DiagnosticLayout() {
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [nlExtra, setNlExtra] = useState<DiagnoseNLResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAnalyze = async (network: string, scenario: string) => {
    setIsLoading(true);
    setError(null);
    setNlExtra(null);
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

  const handleAnalyzeNL = async (network: string, description: string) => {
    setIsLoading(true);
    setError(null);
    setNlExtra(null);
    try {
      const response = await runNLDiagnosis(network, description);
      setNlExtra(response);
      if (response.generationStatus === 'success') {
        setResult(response.baseline);
      } else {
        setError(response.generationError || 'Failed to generate scenario');
        setResult(null);
      }
    } catch {
      setError('NL Analysis failed. Please try again.');
      setResult(null);
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
        />
      </div>
      <div className="w-1/2">
        <ResultsPanel
          result={result}
          nlExtra={nlExtra}
          isLoading={isLoading}
          error={error}
        />
      </div>
    </div>
  );
}
