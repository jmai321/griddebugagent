'use client';

import { useState } from 'react';
import { InputPanel } from './input-panel';
import { ResultsPanel } from './results-panel';
import { DiagnosticResult } from '@/types/diagnostic';
import { mockDiagnosticResult } from '@/data/mock-data';

export function DiagnosticLayout() {
  const [result, setResult] = useState<DiagnosticResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // TODO: Replace with async API call to POST /diagnose with testCaseId
  const handleAnalyze = (testCaseId: string) => {
    setIsLoading(true);
    setResult(mockDiagnosticResult);
    setIsLoading(false);
  };

  return (
    <div className="flex h-screen bg-background">
      <div className="w-1/2 border-r border-border">
        <InputPanel onAnalyze={handleAnalyze} isLoading={isLoading} />
      </div>
      <div className="w-1/2">
        <ResultsPanel result={result} isLoading={isLoading} />
      </div>
    </div>
  );
}