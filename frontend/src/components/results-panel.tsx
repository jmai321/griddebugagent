'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { PipelineResult, PipelineId, DiagnoseNLResponse } from '@/types/diagnostic';
import { AlertCircle, CheckCircle2, Zap, Loader2, Lightbulb, Code2, ChevronDown, ChevronUp, Wrench, Activity, Terminal } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { useState, useEffect, Fragment } from 'react';
import { NetworkControlBoard } from './network-control-board';
import { OverrideState, RawNetworkState } from '@/types/diagnostic';

// Helper component to display JSON data in a user-friendly, natural format
function JsonDisplay({ data }: { data: any }) {
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
        // Skip some internal useless keys
        if (key === 'action' || key === 'rationale' || key === 'iteration') return null;

        const friendlyKey = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        return (
          <div key={key} className="flex flex-col sm:flex-row sm:gap-2 items-start text-xs">
            <span className="font-semibold text-foreground/80 min-w-[140px]">
              {friendlyKey}:
            </span>
            <div className="flex-1 text-muted-foreground break-words">
              <JsonDisplay data={value} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

const PIPELINE_LABELS: Record<PipelineId, string> = {
  baseline: 'Baseline (LLM only)',
  agentic: 'Agentic (with tools)',
  iterative: 'Iterative Debugger (fix loop)',
};

interface ResultsPanelProps {
  result: PipelineResult | null;
  selectedPipeline: PipelineId;
  iterativeResult: PipelineResult | null;
  nlExtra: DiagnoseNLResponse | null;
  plotHtml: string | null;
  iterativePlotHtml?: string | null;
  isLoading: boolean;
  loadingStage: string | null;
  error: string | null;
  networkName: string | null;
  scenarioName: string | null;
}

export function ResultsPanel({ result, selectedPipeline, iterativeResult, nlExtra, plotHtml: initialPlotHtml, iterativePlotHtml, isLoading, loadingStage, error, networkName, scenarioName }: ResultsPanelProps) {
  const [codeExpanded, setCodeExpanded] = useState(false);
  const [plotHtml, setPlotHtml] = useState<string | null>(initialPlotHtml);
  const [networkState, setNetworkState] = useState<RawNetworkState | null>(null);
  const [isSimulating, setIsSimulating] = useState(false);

  // Keep plotHtml synced with the prop when it changes
  useEffect(() => {
    setPlotHtml(initialPlotHtml);
  }, [initialPlotHtml]);

  // Fetch the raw network state when a valid scenario result is loaded
  useEffect(() => {
    async function fetchNetworkState() {
      if (!result && !initialPlotHtml) return;

      try {
        // We need the selected network and scenario.
        // Assuming we can extract it from the generated code or just pass the props down.
        // Currently, ResultsPanelProps doesn't have `networkName` or `scenarioName`.
        // We will mock case14/normal_operation if missing, but ideally we should pass these props.
        // For NL mode, `nlExtra.generatedCode` is used to load the state.
        const res = await fetch('http://localhost:8000/api/network_state', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            network: networkName || 'case14',
            scenario: scenarioName || 'normal_operation',
            generatedCode: nlExtra?.generatedCode || null
          })
        });
        if (res.ok) {
          const data = await res.json();
          setNetworkState(data);
        }
      } catch (err) {
        console.error("Failed to fetch network state:", err);
      }
    }

    // Only fetch if we are not currently loading the main analysis
    if (!isLoading && (result || nlExtra || initialPlotHtml)) {
      fetchNetworkState();
    }
  }, [isLoading, result, nlExtra, initialPlotHtml]);

  const handleApplyOverrides = async (overrides: OverrideState) => {
    setIsSimulating(true);
    try {
      const res = await fetch('http://localhost:8000/api/simulate_overrides', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          network: networkName || 'case14',
          scenario: scenarioName || 'normal_operation',
          generatedCode: nlExtra?.generatedCode || null,
          overrides
        })
      });
      if (res.ok) {
        const data = await res.json();
        setPlotHtml(data.plotHtml);
        // Optionally, we could update rootCauses locally here if data.rootCauses exists
      }
    } catch (err) {
      console.error("Simulation failed:", err);
    } finally {
      setIsSimulating(false);
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
      {/* Streaming progress banner */}
      {isLoading && loadingStage && (
        <div className="mb-4 flex items-center gap-2 p-3 rounded-lg bg-primary/5 border border-primary/20 text-sm">
          <Loader2 className="h-4 w-4 text-primary animate-spin flex-shrink-0" />
          <span className="text-primary font-medium">{loadingStage}</span>
        </div>
      )}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
          <h2 className="text-xl font-semibold">Diagnostic Results</h2>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="font-normal">
              {PIPELINE_LABELS[selectedPipeline]}
            </Badge>
            <Badge
              className={`flex items-center gap-1 ${(result.analysisStatus ?? 'error') === 'success' ? 'bg-success text-white' : (result.analysisStatus ?? 'error') === 'not_implemented' ? 'bg-muted text-muted-foreground' : 'bg-destructive text-white'}`}
            >
              <CheckCircle2 className="h-3 w-3" />
              {result.analysisStatus ?? 'loading'}
            </Badge>
          </div>
        </div>
      </div>

      <div className="space-y-6">
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

        {/* Network Visualization and Control Board */}
        {plotHtml && (!nlExtra || nlExtra.responseType !== 'text_only') && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <Card className="lg:col-span-2">
              <CardHeader className="pb-2">
                <CardTitle className="text-lg">Network Visualization</CardTitle>
                <CardDescription>Interactive plot with affected components highlighted</CardDescription>
              </CardHeader>
              <CardContent className="p-0 h-[500px]">
                {isSimulating ? (
                  <div className="flex flex-col items-center justify-center h-full bg-muted/20">
                    <Loader2 className="h-8 w-8 text-primary animate-spin mb-4" />
                    <p className="text-sm text-muted-foreground">Simulating network overrides...</p>
                  </div>
                ) : (
                  <iframe
                    srcDoc={plotHtml}
                    className="w-full h-full border-0 rounded-b-lg"
                    title="Network Visualization"
                    sandbox="allow-scripts"
                  />
                )}
              </CardContent>
            </Card>

            <div className="h-[600px] lg:h-auto">
              <NetworkControlBoard
                networkState={networkState}
                onApplyOverrides={handleApplyOverrides}
                isLoading={isSimulating}
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

        {/* Agent reasoning: step-by-step (agentic only) */}
        {selectedPipeline === 'agentic' && result.toolCalls && (
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Wrench className="h-5 w-5 text-muted-foreground" />
                Agent reasoning steps
              </CardTitle>
              <CardDescription>
                Step-by-step: tool calls and results (for debugging and understanding agent decisions)
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {result.toolCalls.map((tc, idx) => (
                <div key={idx} className="rounded-lg border border-border bg-card p-3 space-y-2">
                  <div className="flex items-center gap-2 font-medium text-sm">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-primary text-xs">
                      {idx + 1}
                    </span>
                    <span>Step {idx + 1}</span>
                  </div>
                  <div className="pl-8 text-sm">
                    <p className="text-muted-foreground mb-1">
                      <span className="font-medium text-foreground">Tool call:</span>{' '}
                      <code className="text-xs bg-muted px-1.5 py-0.5 rounded">{tc.tool}</code>
                      {Object.keys(tc.args || {}).length > 0 && (
                        <span className="text-muted-foreground ml-1">
                          ({JSON.stringify(tc.args)})
                        </span>
                      )}
                    </p>
                    <p className="text-muted-foreground">
                      <span className="font-medium text-foreground">Result:</span>{' '}
                      <span className="font-mono text-xs break-all">
                        {typeof tc.result === 'object'
                          ? JSON.stringify(tc.result).length > 200
                            ? JSON.stringify(tc.result).slice(0, 200) + '…'
                            : JSON.stringify(tc.result)
                          : String(tc.result)}
                      </span>
                    </p>
                  </div>
                </div>
              ))}
              <div className="rounded-lg border border-border border-dashed bg-muted/20 p-3 pl-8">
                <p className="text-sm font-medium text-foreground">Final step</p>
                <p className="text-muted-foreground text-sm">Agent produced the report (Root Causes, Affected Components, Recommendations above).</p>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Reasoning quality checks (agentic only) */}
        {selectedPipeline === 'agentic' && result.reasoningQuality && result.reasoningQuality.checks.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Reasoning quality</CardTitle>
              <CardDescription>
                Heuristic checks: does the agent&apos;s tool usage support what it claimed in the report?
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

        {/* Iterative debugger: fix history */}
        {(selectedPipeline === 'agentic' || selectedPipeline === 'iterative') && iterativeResult?.fixHistory && iterativeResult.fixHistory.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Wrench className="h-5 w-5 text-muted-foreground" />
                Fix History
                {iterativeResult.finalConverged !== undefined && (
                  <Badge variant={iterativeResult.finalConverged ? 'default' : 'destructive'} className="ml-auto">
                    {iterativeResult.finalConverged ? '✓ Converged' : '✗ Not converged'}
                  </Badge>
                )}
              </CardTitle>
              <CardDescription>
                Corrective actions applied by the iterative debugger
                {iterativeResult.iterationsUsed !== undefined && ` (${iterativeResult.iterationsUsed} iterations)`}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {iterativeResult.fixHistory.map((fix: any, idx: number) => {
                  // Handle both automated format {action, rationale} and LLM format {tool, args, result}
                  const actionName = fix.action || fix.tool || 'unknown';
                  const description = fix.rationale || fix.message || (fix.result && typeof fix.result === 'object' ? fix.result.message : null) || '';
                  const hasResult = fix.result != null;
                  const resultObj = typeof fix.result === 'string' ? { message: fix.result } : fix.result;

                  return (
                    <div key={idx} className="flex items-start gap-3 p-3 rounded-lg border border-border bg-muted/30">
                      <div className="flex-shrink-0 w-7 h-7 rounded-full bg-primary/10 text-primary flex items-center justify-center text-xs font-bold">
                        {idx + 1}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-sm font-medium font-mono">
                            {String(actionName)}
                          </span>
                          {fix.iteration !== undefined && (
                            <span className="text-xs text-muted-foreground ml-1">
                              (Loop {fix.iteration})
                            </span>
                          )}
                          {fix.success !== undefined && (
                            <Badge variant={fix.success ? 'outline' : 'destructive'} className="text-xs">
                              {fix.success ? 'applied' : 'failed'}
                            </Badge>
                          )}
                          {fix.result?.success !== undefined && fix.success === undefined && (
                            <Badge variant={fix.result.success ? 'outline' : 'destructive'} className="text-xs">
                              {fix.result.success ? 'applied' : 'failed'}
                            </Badge>
                          )}
                        </div>
                        {description && (
                          <p className="text-sm text-muted-foreground">{String(description)}</p>
                        )}
                        {hasResult && (
                          <details className="mt-2 group border border-border/50 rounded-md">
                            <summary className="text-xs font-medium cursor-pointer text-muted-foreground hover:text-foreground bg-muted/30 px-3 py-1.5 rounded-t-md">
                              Details
                            </summary>
                            <div className="p-3 bg-muted/10 border-t border-border/50 overflow-auto max-h-[250px]">
                              <JsonDisplay data={resultObj} />
                            </div>
                          </details>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Fixed Network Visualization (Iterative only) */}
        {(selectedPipeline === 'iterative' || selectedPipeline === 'agentic') && iterativePlotHtml && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-lg flex items-center gap-2">
                <Activity className="h-5 w-5 text-primary" />
                Fixed Network State
              </CardTitle>
              <CardDescription>
                Network visualization after iterative diagnosis and fixes
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0 h-[500px]">
              <iframe
                srcDoc={iterativePlotHtml}
                className="w-full h-full border-0 rounded-b-lg"
                title="Iterative Network Visualization"
                sandbox="allow-scripts"
              />
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
                  <Zap className="h-5 w-5 text-warning" />
                  Affected Components
                </CardTitle>
                <CardDescription>
                  System components involved in the failure
                </CardDescription>
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
                <CardDescription>
                  Suggested actions to address the failure
                </CardDescription>
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
                <CheckCircle2 className="h-5 w-5 text-success" />
                Analytical Summary
              </CardTitle>
              <CardDescription>
                Direct response to your query
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-sm prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown>{result.rawResult}</ReactMarkdown>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
