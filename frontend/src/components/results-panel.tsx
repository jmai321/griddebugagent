'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { PipelineResult, PipelineId, DiagnoseNLResponse } from '@/types/diagnostic';
import { AlertCircle, CheckCircle2, Zap, Loader2, Lightbulb, Code2, ChevronDown, ChevronUp } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { useState, useEffect } from 'react';
import { NetworkControlBoard } from './network-control-board';
import { OverrideState, RawNetworkState } from '@/types/diagnostic';

const PIPELINE_LABELS: Record<PipelineId, string> = {
  baseline: 'Baseline (LLM only)',
  agentic: 'Agentic (with tools)',
};

interface ResultsPanelProps {
  result: PipelineResult | null;
  selectedPipeline: PipelineId;
  nlExtra: DiagnoseNLResponse | null;
  plotHtml: string | null;
  isLoading: boolean;
  error: string | null;
  networkName: string | null;
  scenarioName: string | null;
}

export function ResultsPanel({ result, selectedPipeline, nlExtra, plotHtml: initialPlotHtml, isLoading, error, networkName, scenarioName }: ResultsPanelProps) {
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
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="font-normal">
              {PIPELINE_LABELS[selectedPipeline]}
            </Badge>
            <Badge
              className={`flex items-center gap-1 ${result.analysisStatus === 'success' ? 'bg-success text-white' : result.analysisStatus === 'not_implemented' ? 'bg-muted text-muted-foreground' : 'bg-destructive text-white'}`}
            >
              <CheckCircle2 className="h-3 w-3" />
              {result.analysisStatus}
            </Badge>
          </div>
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
