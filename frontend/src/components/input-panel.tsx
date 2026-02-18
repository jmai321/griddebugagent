'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { testCases } from '@/data/mock-data';

interface InputPanelProps {
  onAnalyze: (testCaseId: string) => void;
  isLoading: boolean;
}

export function InputPanel({ onAnalyze, isLoading }: InputPanelProps) {
  const [selectedTestCase, setSelectedTestCase] = useState<string>('');

  const handleAnalyze = () => {
    if (selectedTestCase) {
      onAnalyze(selectedTestCase);
    }
  };

  const selectedTestCaseData = testCases.find(tc => tc.id === selectedTestCase);

  return (
    <div className="flex flex-col h-full p-6">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold mb-2">GridDebugAgent</h1>
        <p className="text-muted-foreground">
          Analyze power flow failures and get diagnostic recommendations
        </p>
      </div>

      <div className="flex-1 space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Select Test Case</CardTitle>
            <CardDescription>
              Choose a failing power flow test case to analyze
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Select value={selectedTestCase} onValueChange={setSelectedTestCase}>
              <SelectTrigger>
                <SelectValue placeholder="Select a test case..." />
              </SelectTrigger>
              <SelectContent>
                {testCases.map((testCase) => (
                  <SelectItem key={testCase.id} value={testCase.id}>
                    <div className="flex flex-col items-start">
                      <span>{testCase.name}</span>
                      <span className="text-xs text-muted-foreground">
                        IEEE {testCase.busSystem}-bus • {testCase.failureType.replace('_', ' ')}
                      </span>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            {selectedTestCaseData && (
              <Card className="bg-muted/50">
                <CardContent className="p-4">
                  <div className="flex items-center justify-between mb-2">
                    <Badge variant="outline">
                      IEEE {selectedTestCaseData.busSystem}-bus
                    </Badge>
                    <Badge variant="secondary">
                      {selectedTestCaseData.failureType.replace('_', ' ')}
                    </Badge>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    {selectedTestCaseData.description}
                  </p>
                </CardContent>
              </Card>
            )}
          </CardContent>
        </Card>

        <Button
          onClick={handleAnalyze}
          disabled={!selectedTestCase || isLoading}
          className="w-full"
          size="lg"
        >
          {isLoading ? 'Analyzing...' : 'Run Analysis'}
        </Button>
      </div>
    </div>
  );
}