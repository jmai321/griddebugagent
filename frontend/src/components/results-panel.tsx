'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { PipelineResult } from '@/types/diagnostic';
import { AlertCircle, CheckCircle2, Zap, Loader2, Lightbulb } from 'lucide-react';

interface ResultsPanelProps {
  result: PipelineResult | null;
  isLoading: boolean;
  error: string | null;
}

export function ResultsPanel({ result, isLoading, error }: ResultsPanelProps) {
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
                    <span className="text-sm">{cause}</span>
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
                    <span className="text-sm">{component}</span>
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
                    <span className="text-sm">{action}</span>
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
