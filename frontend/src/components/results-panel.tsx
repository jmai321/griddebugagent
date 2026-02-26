'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { PipelineResult, DiagnoseNLResponse } from '@/types/diagnostic';
import { AlertCircle, CheckCircle2, Zap, Loader2, Lightbulb, Code2, ChevronDown, ChevronUp } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { useState } from 'react';

interface ResultsPanelProps {
  result: PipelineResult | null;
  nlExtra: DiagnoseNLResponse | null;
  isLoading: boolean;
  error: string | null;
}

export function ResultsPanel({ result, nlExtra, isLoading, error }: ResultsPanelProps) {
  const [codeExpanded, setCodeExpanded] = useState(false);

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
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-xl font-semibold">Diagnostic Results</h2>
          <Badge
            className={`flex items-center gap-1 ${result.analysisStatus === 'success' ? 'bg-success text-white' : 'bg-destructive text-white'}`}
          >
            <CheckCircle2 className="h-3 w-3" />
            {result.analysisStatus}
          </Badge>
        </div>
      </div>

      <div className="space-y-6">
        {/* Generated Scenario Card (NL mode only) */}
        {nlExtra && nlExtra.generationStatus === 'success' && (
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
      </div>
    </div>
  );
}
