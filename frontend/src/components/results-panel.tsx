'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { PipelineResult, DiagnoseNLResponse } from '@/types/diagnostic';
import { AlertCircle, CheckCircle2, Zap, Loader2, Lightbulb, Code2, ChevronDown, ChevronUp, Wrench, Activity } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { useState, useEffect, useCallback } from 'react';
import { NetworkControlBoard } from './network-control-board';
import { NetworkGraph } from './network-graph';
import { OverrideState, RawNetworkState, DiagnoseResponse } from '@/types/diagnostic';
import { API_BASE, runReDiagnosis } from '@/lib/api';

// Helper component to display JSON data in a user-friendly format
function JsonDisplay({ data }: { data: unknown }) {
  if (data === null || data === undefined) return <span className="text-muted-foreground">None</span>;
  if (typeof data !== 'object') {
    if (typeof data === 'boolean') return <span>{data ? 'Yes' : 'No'}</span>;
    return <span>{String(data)}</span>;
  }

  if (Array.isArray(data)) {
    if (data.length === 0) return <span className="text-muted-foreground italic">Empty list</span>;
    if (data.length > 0 && typeof data[0] !== 'object') {
      return <span>{data.join(', ')}</span>;
    }
    return (
      <ul className="list-disc pl-4 space-y-1 mt-1">
        {data.map((item, i) => (
          <li key={i}><JsonDisplay data={item} /></li>
        ))}
      </ul>
    );
  }

  const entries = Object.entries(data);
  if (entries.length === 0) return <span className="text-muted-foreground italic">Empty object</span>;

  return (
    <div className="space-y-1.5 mt-1">
      {entries.map(([key, value]) => {
        if (key === 'action' || key === 'rationale' || key === 'iteration') return null;
        const friendlyKey = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        return (
          <div key={key} className="flex flex-col sm:flex-row sm:gap-2 items-start text-xs">
            <span className="font-semibold text-foreground/80 min-w-[140px]">{friendlyKey}:</span>
            <div className="flex-1 text-muted-foreground break-words">
              <JsonDisplay data={value} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

type TabId = 'baseline' | 'agentic';

const TAB_LABELS: Record<TabId, string> = {
  baseline: 'Baseline',
  agentic: 'Agentic',
};

interface ResultsPanelProps {
  baselineResult: PipelineResult | null;
  agenticResult: PipelineResult | null;
  nlExtra: DiagnoseNLResponse | null;
  isLoading: boolean;
  loadingStage: string | null;
  error: string | null;
  networkName: string | null;
  scenarioName: string | null;
  onDiagnosisUpdate?: (response: DiagnoseResponse) => void;
}

export function ResultsPanel({ baselineResult, agenticResult, nlExtra, isLoading, loadingStage, error, networkName, scenarioName, onDiagnosisUpdate }: ResultsPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>('baseline');
  const [codeExpanded, setCodeExpanded] = useState(false);
  const [networkState, setNetworkState] = useState<RawNetworkState | null>(null);
  const [isSimulating, setIsSimulating] = useState(false);
  const [isReDiagnosing, setIsReDiagnosing] = useState(false);
  const [lastSimulationConverged, setLastSimulationConverged] = useState<boolean | null>(null);

  // Compute active result based on selected tab
  const result = activeTab === 'baseline' ? baselineResult : agenticResult;
  const hasAnyResult = baselineResult || agenticResult;

  // Fetch network state helper
  const fetchNetworkState = useCallback(async (overrides?: OverrideState) => {
    if (!networkName) return;

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
        if (overrides) {
          setLastSimulationConverged(data.converged ?? false);
        }
      }
    } catch {
      console.error("Failed to fetch network state");
    }
  }, [networkName, scenarioName, nlExtra?.generatedCode, result?.parsedAffectedComponents]);

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

  if (isLoading && !result) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6" role="status" aria-label="Loading">
        <Loader2 className="h-10 w-10 text-muted-foreground animate-spin mb-4" />
        <p className="text-muted-foreground">{loadingStage || 'Analyzing power flow failure...'}</p>
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

  if (!hasAnyResult) {
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
      {/* Streaming progress banner */}
      {isLoading && loadingStage && (
        <div className="mb-4 flex items-center gap-2 p-3 rounded-lg bg-primary/5 border border-primary/20 text-sm">
          <Loader2 className="h-4 w-4 text-primary animate-spin flex-shrink-0" />
          <span className="text-primary font-medium">{loadingStage}</span>
        </div>
      )}

      {/* Header with tabs */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
          <h2 className="text-xl font-semibold">Diagnostic Results</h2>
          {/* Convergence indicator */}
          {result && (() => {
            const converged = activeTab === 'agentic'
              ? result.finalConverged
              : networkState?.converged;
            if (converged === true) {
              return (
                <Badge className="flex items-center gap-1 bg-green-600 text-white">
                  <CheckCircle2 className="h-3 w-3" />
                  Converged
                </Badge>
              );
            } else if (converged === false) {
              return (
                <Badge className="flex items-center gap-1 bg-destructive text-white">
                  <AlertCircle className="h-3 w-3" />
                  Did not converge
                </Badge>
              );
            } else {
              return (
                <Badge variant="outline" className="flex items-center gap-1 text-muted-foreground">
                  <span className="h-3 w-3">○</span>
                  Convergence unknown
                </Badge>
              );
            }
          })()}
        </div>

        {/* Tab buttons */}
        <div className="flex rounded-lg border border-border overflow-hidden">
          {(['baseline', 'agentic'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              disabled={tab === 'baseline' ? !baselineResult : !agenticResult}
              className={`flex-1 px-4 py-2 text-sm font-medium transition-colors ${
                activeTab === tab
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted/30 text-muted-foreground hover:bg-muted/50'
              } ${(tab === 'baseline' ? !baselineResult : !agenticResult) ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              {TAB_LABELS[tab]}
              {(tab === 'baseline' ? !baselineResult : !agenticResult) && isLoading && ' ...'}
            </button>
          ))}
        </div>
      </div>

      {/* Show loading state if current tab result is not yet available */}
      {!result && (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <Loader2 className="h-8 w-8 text-muted-foreground animate-spin mb-4" />
          <p className="text-muted-foreground">Loading {TAB_LABELS[activeTab]} results...</p>
        </div>
      )}

      {result && <div className="space-y-6">
        {/* Simple Text Answer Card */}
        {nlExtra?.textAnswer && nlExtra.responseType !== 'direct_answer' && (
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

        {/* Network Visualization and Control Board - Only for Baseline tab */}
        {activeTab === 'baseline' && networkState && (!nlExtra || nlExtra.responseType !== 'text_only') && (
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

        {/* Agent Actions (unified tool calls + fixes, agentic only) */}
        {activeTab === 'agentic' && result.agentActions && result.agentActions.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Activity className="h-5 w-5 text-muted-foreground" />
                Agent Actions
                <span className="text-sm font-normal text-muted-foreground ml-auto">
                  {result.agentActions.length} action{result.agentActions.length !== 1 ? 's' : ''}
                </span>
              </CardTitle>
              <CardDescription>
                Chronological list of diagnostic and corrective actions
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {result.agentActions.map((action, idx) => {
                const toolName = action.tool || action.action || 'unknown';
                const phaseBadgeColor = action.phase === 'diagnostic' ? 'bg-blue-500/10 text-blue-600' :
                                        action.phase === 'fix' ? 'bg-green-500/10 text-green-600' :
                                        action.phase === 'verify' ? 'bg-purple-500/10 text-purple-600' :
                                        'bg-muted text-muted-foreground';
                const hasReasoning = action.reasoning && action.reasoning.trim();
                const hasRationale = action.rationale && action.rationale.trim();
                const hasResult = action.result != null;

                return (
                  <div key={idx} className="rounded-lg border border-border bg-card p-3 space-y-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-bold flex-shrink-0">
                        {idx + 1}
                      </span>
                      <code className="text-sm font-medium bg-muted px-2 py-0.5 rounded">{toolName}</code>
                      {action.phase && (
                        <Badge variant="outline" className={`text-xs ${phaseBadgeColor}`}>
                          {action.phase}
                        </Badge>
                      )}
                      {action.success !== undefined && (
                        <Badge variant={action.success ? 'outline' : 'destructive'} className="text-xs">
                          {action.success ? 'applied' : 'failed'}
                        </Badge>
                      )}
                      <span className="text-xs text-muted-foreground ml-auto">
                        iteration {action.iteration}
                      </span>
                    </div>

                    {/* LLM Reasoning (if present) */}
                    {hasReasoning && (
                      <div className="pl-8 text-sm">
                        <p className="text-muted-foreground italic border-l-2 border-primary/30 pl-3">
                          {action.reasoning}
                        </p>
                      </div>
                    )}

                    {/* Rationale for automated fixes */}
                    {hasRationale && !hasReasoning && (
                      <div className="pl-8 text-sm">
                        <p className="text-muted-foreground">
                          {action.rationale}
                        </p>
                      </div>
                    )}

                    {/* Collapsible result details */}
                    {hasResult && (
                      <details className="pl-8 group">
                        <summary className="text-xs font-medium cursor-pointer text-muted-foreground hover:text-foreground">
                          View result details
                        </summary>
                        <div className="mt-2 p-2 bg-muted/30 rounded-md overflow-auto max-h-[200px]">
                          <JsonDisplay data={action.result} />
                        </div>
                      </details>
                    )}
                  </div>
                );
              })}
            </CardContent>
          </Card>
        )}

        {/* Final State (agentic only) */}
        {activeTab === 'agentic' && result.finalState && (
          <Card className={result.finalState.is_healthy ? 'border-green-500/30' : 'border-orange-500/30'}>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <CheckCircle2 className={`h-5 w-5 ${result.finalState.is_healthy ? 'text-green-500' : 'text-orange-500'}`} />
                Final State
                <Badge
                  variant={result.finalState.converged ? 'default' : 'destructive'}
                  className={`ml-auto ${result.finalState.converged ? 'bg-green-600' : ''}`}
                >
                  {result.finalState.converged ? 'Converged' : 'Not Converged'}
                </Badge>
              </CardTitle>
              <CardDescription>
                Network status after all corrective actions
              </CardDescription>
            </CardHeader>
            <CardContent>
              {result.finalState.is_healthy ? (
                <div className="flex items-center gap-2 text-green-600">
                  <CheckCircle2 className="h-5 w-5" />
                  <span className="font-medium">All constraints satisfied - network is healthy</span>
                </div>
              ) : result.finalState.remaining_violations.length > 0 ? (
                <div>
                  <p className="text-sm font-medium mb-2 text-orange-600">Remaining Violations:</p>
                  <ul className="space-y-1">
                    {result.finalState.remaining_violations.map((v, idx) => (
                      <li key={idx} className="flex items-start gap-2 text-sm">
                        <AlertCircle className="h-4 w-4 text-orange-500 mt-0.5 flex-shrink-0" />
                        <span className="text-muted-foreground">{v}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {result.finalState.converged
                    ? 'Power flow converged but constraint status unknown'
                    : 'Power flow did not converge - manual intervention required'}
                </p>
              )}
            </CardContent>
          </Card>
        )}

        {/* Reasoning quality checks (agentic only) */}
        {activeTab === 'agentic' && result.reasoningQuality && result.reasoningQuality.checks.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Reasoning Quality</CardTitle>
              <CardDescription>
                Heuristic checks: does the agent&apos;s tool usage support the report?
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm font-medium mb-3">{result.reasoningQuality.summary}</p>
              <ul className="space-y-2 text-sm">
                {result.reasoningQuality.checks.map((c) => (
                  <li key={c.id} className="flex items-start gap-2">
                    <span className={c.passed ? 'text-green-600 dark:text-green-400' : 'text-amber-600 dark:text-amber-400'}>
                      {c.passed ? '✓' : '○'}
                    </span>
                    <span className={c.passed ? 'text-muted-foreground' : ''}>{c.message}</span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}


        {/* Full Diagnosis Results (Baseline tab only) */}
        {activeTab === 'baseline' && (!nlExtra || nlExtra.responseType === 'full_diagnosis') && (
          <>
            <Card>
              <CardHeader>
                <CardTitle className="text-lg flex items-center gap-2">
                  <AlertCircle className="h-5 w-5 text-destructive" />
                  Root Causes
                </CardTitle>
                <CardDescription>Identified failure mechanisms</CardDescription>
              </CardHeader>
              <CardContent>
                {(result.rootCauses ?? []).length > 0 ? (
                  <ul className="space-y-2">
                    {(result.rootCauses ?? []).map((cause, index) => (
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
                  <Zap className="h-5 w-5 text-yellow-500" />
                  Affected Components
                </CardTitle>
                <CardDescription>System components involved in the failure</CardDescription>
              </CardHeader>
              <CardContent>
                {(result.affectedComponents ?? []).length > 0 ? (
                  <ul className="space-y-2">
                    {(result.affectedComponents ?? []).map((component, index) => (
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
                <CardDescription>Suggested actions to address the failure</CardDescription>
              </CardHeader>
              <CardContent>
                {(result.correctiveActions ?? []).length > 0 ? (
                  <ul className="space-y-2">
                    {(result.correctiveActions ?? []).map((action, index) => (
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

        {/* Direct Answer Results */}
        {nlExtra && nlExtra.responseType === 'direct_answer' && result.rawResult && (
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <CheckCircle2 className="h-5 w-5 text-green-600" />
                Analytical Summary
              </CardTitle>
              <CardDescription>Direct response to your query</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-sm prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown>{result.rawResult}</ReactMarkdown>
              </div>
            </CardContent>
          </Card>
        )}
      </div>}
    </div>
  );
}
