'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { PipelineResult, PipelineId, DiagnoseNLResponse } from '@/types/diagnostic';
import { AlertCircle, Zap, Loader2, Lightbulb, Code2, ChevronDown, ChevronUp } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { useState, useEffect, useCallback } from 'react';
import { NetworkControlBoard } from './network-control-board';
import { NetworkGraph } from './network-graph';
import { OverrideState, RawNetworkState, DiagnoseResponse } from '@/types/diagnostic';
import { API_BASE, runReDiagnosis } from '@/lib/api';

const PIPELINE_LABELS: Record<PipelineId, string> = {
  baseline: 'Baseline (LLM only)',
  agentic: 'Agentic (with tools)',
};

interface ResultsPanelProps {
  result: PipelineResult | null;
  selectedPipeline: PipelineId;
  nlExtra: DiagnoseNLResponse | null;
  isLoading: boolean;
  error: string | null;
  networkName: string | null;
  scenarioName: string | null;
  onDiagnosisUpdate?: (response: DiagnoseResponse) => void;
}

export function ResultsPanel({ result, selectedPipeline, nlExtra, isLoading, error, networkName, scenarioName, onDiagnosisUpdate }: ResultsPanelProps) {
  const [codeExpanded, setCodeExpanded] = useState(false);
  const [networkState, setNetworkState] = useState<RawNetworkState | null>(null);
  const [isSimulating, setIsSimulating] = useState(false);
  const [isReDiagnosing, setIsReDiagnosing] = useState(false);
  const [lastSimulationConverged, setLastSimulationConverged] = useState<boolean | null>(null);

  // Fetch network state helper
  const fetchNetworkState = useCallback(async (overrides?: OverrideState) => {
    if (!networkName) return;

    // Get LLM-parsed affected components for highlighting
    const llmAffectedComponents = result?.parsedAffectedComponents || null;

    try {
      const endpoint = overrides ? `${API_BASE}/api/simulate_overrides` : `${API_BASE}/api/network_state`;
      const body = overrides
        ? { network: networkName, scenario: scenarioName || 'normal_operation', generatedCode: nlExtra?.generatedCode || null, overrides, llmAffectedComponents }
        : { network: networkName, scenario: scenarioName || 'normal_operation', generatedCode: nlExtra?.generatedCode || null, llmAffectedComponents };

      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      if (res.ok) {
        const data = await res.json();
        setNetworkState(data);
        // Track convergence status when simulating with overrides
        if (overrides) {
          setLastSimulationConverged(data.converged ?? false);
        }
      }
    } catch {
      console.error("Failed to fetch network state");
    }
  }, [networkName, scenarioName, nlExtra?.generatedCode, result?.parsedAffectedComponents]);

  // Fetch the raw network state when a valid scenario result is loaded
  useEffect(() => {
    if (!isLoading && (result || nlExtra) && networkName) {
      fetchNetworkState();
    }
  }, [isLoading, result, nlExtra, networkName, fetchNetworkState]);

  const handleApplyOverrides = async (overrides: OverrideState) => {
    setIsSimulating(true);
    try {
      await fetchNetworkState(overrides);
    } finally {
      setIsSimulating(false);
    }
  };

  const handleReDiagnose = async (overrides: OverrideState) => {
    if (!networkName || !onDiagnosisUpdate) return;

    setIsReDiagnosing(true);
    try {
      const response = await runReDiagnosis(
        networkName,
        scenarioName || 'normal_operation',
        overrides,
        nlExtra?.generatedCode || null
      );
      onDiagnosisUpdate(response);
    } catch (err) {
      console.error("Re-diagnosis failed:", err);
    } finally {
      setIsReDiagnosing(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6" role="status" aria-label="Loading">
        <Loader2 className="h-10 w-10 text-muted-foreground animate-spin mb-4" />
        <p className="text-muted-foreground">Analyzing power flow failure...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6 text-center">
        <AlertCircle className="h-12 w-12 text-destructive mb-4" />
        <h3 className="text-lg font-medium mb-2">Analysis Error</h3>
        <p className="text-muted-foreground">{error}</p>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6 text-center">
        <AlertCircle className="h-12 w-12 text-muted-foreground mb-4" />
        <h3 className="text-lg font-medium mb-2">No Analysis Results</h3>
        <p className="text-muted-foreground">
          Select a network and scenario, then run analysis
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full p-6 overflow-y-auto">
      <div className="mb-6">
        <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
          <h2 className="text-xl font-semibold">Diagnostic Results</h2>
          <Badge variant="outline" className="font-normal">
            {PIPELINE_LABELS[selectedPipeline]}
          </Badge>
        </div>
      </div>

      <div className="space-y-6">
        {/* Simple Text Answer Card */}
        {nlExtra?.textAnswer && (
          <Card className="border-secondary mb-4">
            <CardHeader className="pb-3">
              <CardTitle className="text-lg">Agent Response</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-sm prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown>{nlExtra.textAnswer}</ReactMarkdown>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Network Visualization and Control Board */}
        {networkState && (!nlExtra || nlExtra.responseType !== 'text_only') && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <Card className="lg:col-span-2">
              <CardHeader className="pb-2">
                <CardTitle className="text-lg">Network Visualization</CardTitle>
                <CardDescription>
                  Interactive graph with affected components highlighted
                  {networkState.converged === false && (
                    <span className="ml-2 text-destructive">(Power flow did not converge)</span>
                  )}
                </CardDescription>
              </CardHeader>
              <CardContent className="p-0 h-[500px] relative">
                <NetworkGraph
                  networkState={networkState}
                  isLoading={isSimulating}
                />
              </CardContent>
            </Card>

            <div className="h-[600px] lg:h-auto">
              <NetworkControlBoard
                networkState={networkState}
                onApplyOverrides={handleApplyOverrides}
                onReDiagnose={handleReDiagnose}
                isLoading={isSimulating}
                isReDiagnosing={isReDiagnosing}
                lastSimulationConverged={lastSimulationConverged}
              />
            </div>
          </div>
        )}
        {/* Generated Scenario Card (NL mode only) */}
        {nlExtra && nlExtra.generationStatus === 'success' && nlExtra.responseType === 'full_diagnosis' && (
          <Card className="border-primary/30">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Code2 className="h-5 w-5 text-primary" />
                Generated Scenario
              </CardTitle>
              <CardDescription>
                LLM-generated failure: {nlExtra.generatedGroundTruth?.failureType ?? 'unknown'}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {nlExtra.generatedGroundTruth && (
                <div className="text-sm space-y-1">
                  <p className="font-medium">Expected root causes:</p>
                  <ul className="list-disc list-inside text-muted-foreground">
                    {nlExtra.generatedGroundTruth.rootCauses.map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                  <p className="text-muted-foreground mt-2">
                    <span className="font-medium text-foreground">Known fix:</span>{' '}
                    {nlExtra.generatedGroundTruth.knownFix}
                  </p>
                </div>
              )}
              <button
                onClick={() => setCodeExpanded(!codeExpanded)}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                {codeExpanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                {codeExpanded ? 'Hide' : 'Show'} mutation code
              </button>
              {codeExpanded && (
                <pre className="p-3 rounded-md bg-muted/50 text-xs font-mono overflow-x-auto whitespace-pre-wrap">
                  {nlExtra.generatedCode}
                </pre>
              )}
            </CardContent>
          </Card>
        )}

        {/* Generation Error Card */}
        {nlExtra && nlExtra.generationStatus === 'error' && (
          <Card className="border-destructive/30">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2 text-destructive">
                <AlertCircle className="h-5 w-5" />
                Scenario Generation Failed
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">{nlExtra.generationError}</p>
              {nlExtra.generatedCode && (
                <pre className="mt-3 p-3 rounded-md bg-muted/50 text-xs font-mono overflow-x-auto whitespace-pre-wrap">
                  {nlExtra.generatedCode}
                </pre>
              )}
            </CardContent>
          </Card>
        )}

        {/* Full Diagnosis Results */}
        {(!nlExtra || nlExtra.responseType === 'full_diagnosis') && (
          <>
            <Card>
              <CardHeader>
                <CardTitle className="text-lg flex items-center gap-2">
                  <AlertCircle className="h-5 w-5 text-destructive" />
                  Root Causes
                </CardTitle>
                <CardDescription>
                  Identified failure mechanisms
                </CardDescription>
              </CardHeader>
              <CardContent>
                {result.rootCauses.length > 0 ? (
                  <ul className="space-y-2">
                    {result.rootCauses.map((cause, index) => (
                      <li key={index} className="flex items-start gap-2">
                        <span className="w-2 h-2 rounded-full bg-muted-foreground mt-2 flex-shrink-0" />
                        <div className="text-sm prose prose-sm dark:prose-invert max-w-none">
                          <ReactMarkdown>{cause}</ReactMarkdown>
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground">No root causes identified</p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-lg flex items-center gap-2">
                  <Zap className="h-5 w-5 text-warning" />
                  Affected Components
                </CardTitle>
                <CardDescription>
                  System components involved in the failure
                </CardDescription>
              </CardHeader>
              <CardContent>
                {result.affectedComponents.length > 0 ? (
                  <ul className="space-y-2">
                    {result.affectedComponents.map((component, index) => (
                      <li key={index} className="flex items-start gap-2">
                        <span className="w-2 h-2 rounded-full bg-muted-foreground mt-2 flex-shrink-0" />
                        <div className="text-sm prose prose-sm dark:prose-invert max-w-none">
                          <ReactMarkdown>{component}</ReactMarkdown>
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground">No components identified</p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-lg flex items-center gap-2">
                  <Lightbulb className="h-5 w-5 text-muted-foreground" />
                  Recommendations
                </CardTitle>
                <CardDescription>
                  Suggested actions to address the failure
                </CardDescription>
              </CardHeader>
              <CardContent>
                {result.correctiveActions.length > 0 ? (
                  <ul className="space-y-2">
                    {result.correctiveActions.map((action, index) => (
                      <li key={index} className="flex items-start gap-2">
                        <span className="w-2 h-2 rounded-full bg-muted-foreground mt-2 flex-shrink-0" />
                        <div className="text-sm prose prose-sm dark:prose-invert max-w-none">
                          <ReactMarkdown>{action}</ReactMarkdown>
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground">No recommendations available</p>
                )}
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}
