'use client';

import { useState } from 'react';
import { InputPanel } from './input-panel';
import { ResultsPanel } from './results-panel';
import { PipelineResult } from '@/types/diagnostic';
import { runDiagnosis } from '@/lib/api';

export function DiagnosticLayout() {
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      <div className="w-1/2 border-r border-border">
        <InputPanel onAnalyze={handleAnalyze} isLoading={isLoading} />
      </div>
      <div className="w-1/2">
        <ResultsPanel result={result} isLoading={isLoading} error={error} />
      </div>
    </div>
  );
}
