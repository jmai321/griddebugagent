'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { DiagnosticResult } from '@/types/diagnostic';
import { AlertCircle, CheckCircle2, Zap, Power, Cable, Factory, Loader2, Lightbulb } from 'lucide-react';

interface ResultsPanelProps {
  result: DiagnosticResult | null;
  isLoading: boolean;
}

const componentTypeIcons = {
  bus: Power,
  line: Cable,
  generator: Factory,
  transformer: Zap
};

const actionCategoryLabels = {
  load_shedding: 'Load Shedding',
  generation_adjustment: 'Generation Adjustment',
  topology_change: 'Topology Change',
  parameter_adjustment: 'Parameter Adjustment'
};

const priorityStyles = {
  high: 'bg-destructive text-white',
  medium: 'bg-warning text-white',
  low: 'bg-muted text-muted-foreground'
};

export function ResultsPanel({ result, isLoading }: ResultsPanelProps) {
  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6" role="status" aria-label="Loading">
        <Loader2 className="h-10 w-10 text-muted-foreground animate-spin mb-4" />
        <p className="text-muted-foreground">Analyzing power flow failure...</p>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6 text-center">
        <AlertCircle className="h-12 w-12 text-muted-foreground mb-4" />
        <h3 className="text-lg font-medium mb-2">No Analysis Results</h3>
        <p className="text-muted-foreground">
          Select a test case and run analysis to see diagnostic results
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
            <ul className="space-y-2">
              {result.rootCauses.map((cause, index) => (
                <li key={index} className="flex items-start gap-2">
                  <span className="w-2 h-2 rounded-full bg-muted-foreground mt-2 flex-shrink-0"></span>
                  <span className="text-sm">{cause}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Zap className="h-5 w-5 text-warning" />
              Affected Components
            </CardTitle>
            <CardDescription>
              System components with violations
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {result.affectedComponents.map((component) => {
                const IconComponent = componentTypeIcons[component.type];
                return (
                  <div key={component.id} className="flex items-center p-3 rounded-lg bg-muted/50">
                    <div className="flex items-center gap-3">
                      <IconComponent className="h-4 w-4 text-muted-foreground" />
                      <div>
                        <p className="font-medium text-sm">{component.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {component.type} • {component.value.toFixed(2)}
                        </p>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
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
            <div className="space-y-4">
              {result.correctiveActions.map((action, index) => (
                <div key={action.id}>
                  <div className="flex items-start justify-between mb-2">
                    <p className="text-sm font-medium pr-4">{action.description}</p>
                    <Badge className={`text-xs ${priorityStyles[action.priority]}`}>
                      {action.priority}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {actionCategoryLabels[action.category]}
                  </p>
                  {index < result.correctiveActions.length - 1 && (
                    <Separator className="mt-4" />
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}