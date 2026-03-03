'use client';

import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';
import { OverrideState, RawNetworkState } from '@/types/diagnostic';
import { RefreshCcw, Play } from 'lucide-react';

interface NetworkControlBoardProps {
    networkState: RawNetworkState | null;
    onApplyOverrides: (overrides: OverrideState) => void;
    isLoading: boolean;
}

const DEFAULT_OVERRIDES: OverrideState = {
    globalLoadScale: 1.0,
    lineOutages: [],
    trafoOutages: [],
    loadOverrides: {},
    genOverrides: {},
    extGridOverrides: {},
};

export function NetworkControlBoard({ networkState, onApplyOverrides, isLoading }: NetworkControlBoardProps) {
    const [overrides, setOverrides] = useState<OverrideState>(DEFAULT_OVERRIDES);

    const handleGlobalScaleChange = (value: number[]) => {
        setOverrides(prev => ({ ...prev, globalLoadScale: value[0] }));
    };

    const toggleLineOutage = (index: number, initiallyInService: boolean) => {
        setOverrides(prev => {
            const isCurrentlyOutaged = prev.lineOutages.includes(index) ? initiallyInService : !initiallyInService;

            const newLineOutages = prev.lineOutages.includes(index)
                ? prev.lineOutages.filter(i => i !== index)
                : [...prev.lineOutages, index];
            return { ...prev, lineOutages: newLineOutages };
        });
    };

    const updateLoadOverride = (index: number, field: 'p_mw' | 'q_mvar' | 'in_service', value: string | boolean) => {
        const parsedValue = typeof value === 'boolean' ? value : parseFloat(value);
        if (typeof parsedValue === 'number' && isNaN(parsedValue)) return;

        setOverrides(prev => {
            const currentLoadOverrides = { ...prev.loadOverrides };
            if (!currentLoadOverrides[index]) currentLoadOverrides[index] = {};
            currentLoadOverrides[index][field] = parsedValue as any;
            return { ...prev, loadOverrides: currentLoadOverrides };
        });
    };

    const updateGenOverride = (index: number, field: 'p_mw' | 'vm_pu' | 'in_service', value: string | boolean) => {
        const parsedValue = typeof value === 'boolean' ? value : parseFloat(value);
        if (typeof parsedValue === 'number' && isNaN(parsedValue)) return;

        setOverrides(prev => {
            const currentGenOverrides = { ...prev.genOverrides };
            if (!currentGenOverrides[index]) currentGenOverrides[index] = {};
            currentGenOverrides[index][field] = parsedValue as any;
            return { ...prev, genOverrides: currentGenOverrides };
        });
    };

    const updateExtGridOverride = (index: number, field: 'vm_pu' | 'in_service', value: string | boolean) => {
        const parsedValue = typeof value === 'boolean' ? value : parseFloat(value);
        if (typeof parsedValue === 'number' && isNaN(parsedValue)) return;

        setOverrides(prev => {
            const currentExtOverrides = { ...prev.extGridOverrides };
            if (!currentExtOverrides[index]) currentExtOverrides[index] = {};
            currentExtOverrides[index][field] = parsedValue as any;
            return { ...prev, extGridOverrides: currentExtOverrides };
        });
    };

    const toggleTrafoOutage = (index: number, initiallyInService: boolean) => {
        setOverrides(prev => {
            const isCurrentlyOutaged = prev.trafoOutages.includes(index) ? initiallyInService : !initiallyInService;

            const newTrafoOutages = prev.trafoOutages.includes(index)
                ? prev.trafoOutages.filter(i => i !== index)
                : [...prev.trafoOutages, index];
            return { ...prev, trafoOutages: newTrafoOutages };
        });
    };

    const handleReset = () => {
        setOverrides(DEFAULT_OVERRIDES);
        onApplyOverrides(DEFAULT_OVERRIDES);
    };

    const handleApply = () => {
        onApplyOverrides(overrides);
    };

    if (!networkState) {
        return (
            <Card className="h-full">
                <CardContent className="flex items-center justify-center p-6 text-muted-foreground">
                    No network data available for manipulation.
                </CardContent>
            </Card>
        );
    }

    // Convert array-like objects to arrays for easier mapping
    const lines = Object.entries(networkState.line || {});
    const loads = Object.entries(networkState.load || {});
    const gens = Object.entries(networkState.gen || {});
    const trafos = Object.entries(networkState.trafo || {});
    const extGrids = Object.entries(networkState.ext_grid || {});

    return (
        <Card className="h-full flex flex-col">
            <CardHeader className="pb-3 border-b">
                <CardTitle className="text-md flex justify-between items-center">
                    Manual Controls
                    <div className="flex gap-2">
                        <Button variant="outline" size="icon" onClick={handleReset} disabled={isLoading} aria-label="Reset">
                            <RefreshCcw className="h-4 w-4" />
                        </Button>
                        <Button size="icon" onClick={handleApply} disabled={isLoading} aria-label="Apply Overrides">
                            <Play className="h-4 w-4" />
                        </Button>
                    </div>
                </CardTitle>
                <CardDescription>Tweak parameters and re-run flow</CardDescription>
            </CardHeader>

            <CardContent className="flex-1 overflow-y-auto p-0">
                <div className="p-4 space-y-6">
                    {/* Global Controls */}
                    <div className="space-y-3">
                        <div className="flex justify-between items-center text-sm font-medium">
                            <span>Global Load Scale</span>
                            <span>{(overrides.globalLoadScale * 100).toFixed(0)}%</span>
                        </div>
                        <Slider
                            value={[overrides.globalLoadScale]}
                            min={0}
                            max={3}
                            step={0.1}
                            onValueChange={handleGlobalScaleChange}
                            disabled={isLoading}
                        />
                    </div>

                    <Accordion type="multiple" className="w-full">
                        {/* Lines & Topology */}
                        <AccordionItem value="lines">
                            <AccordionTrigger className="text-sm font-medium">Lines & Topology ({lines.length})</AccordionTrigger>
                            <AccordionContent>
                                <div className="space-y-2 pt-2">
                                    {lines.map(([idxStr, line]) => {
                                        const idx = parseInt(idxStr);
                                        const initiallyOutaged = line.in_service === false;
                                        const isToggledByUser = overrides.lineOutages.includes(idx);
                                        const isOutaged = isToggledByUser ? !initiallyOutaged : initiallyOutaged;

                                        return (
                                            <div key={`line-${idxStr}`} className="flex items-center justify-between text-xs p-2 rounded bg-muted/30">
                                                <span>{line.name || `Line ${idxStr}`} (Bus {line.from_bus} ➔ {line.to_bus})</span>
                                                <div className="flex items-center gap-2">
                                                    <span className={isOutaged ? "text-destructive" : "text-success"}>
                                                        {isOutaged ? "Tripped" : "In Service"}
                                                    </span>
                                                    <Switch
                                                        checked={!isOutaged}
                                                        onCheckedChange={() => toggleLineOutage(idx, line.in_service !== false)}
                                                        disabled={isLoading}
                                                    />
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            </AccordionContent>
                        </AccordionItem>

                        {/* Generators */}
                        <AccordionItem value="gens">
                            <AccordionTrigger className="text-sm font-medium">Generators ({gens.length})</AccordionTrigger>
                            <AccordionContent>
                                <div className="space-y-4 pt-2">
                                    {gens.map(([idxStr, gen]) => {
                                        const idx = parseInt(idxStr);
                                        const currentP = overrides.genOverrides[idx]?.p_mw ?? gen.p_mw;
                                        const currentV = overrides.genOverrides[idx]?.vm_pu ?? gen.vm_pu;
                                        const inService = overrides.genOverrides[idx]?.in_service ?? gen.in_service ?? true;
                                        return (
                                            <div key={`gen-${idxStr}`} className="space-y-2 p-2 rounded bg-muted/30 text-xs">
                                                <div className="flex items-center justify-between font-medium">
                                                    <span>{gen.name || `Gen ${idxStr}`} (Bus {gen.bus})</span>
                                                    <div className="flex items-center gap-2">
                                                        <span className={!inService ? "text-destructive" : "text-success"}>
                                                            {!inService ? "Tripped" : "In Service"}
                                                        </span>
                                                        <Switch
                                                            checked={inService}
                                                            onCheckedChange={(val) => updateGenOverride(idx, 'in_service', val)}
                                                            disabled={isLoading}
                                                        />
                                                    </div>
                                                </div>
                                                <div className="flex items-center gap-2">
                                                    <label className="w-16">P (MW)</label>
                                                    <Input
                                                        type="number"
                                                        className="h-7 text-xs"
                                                        value={currentP}
                                                        onChange={(e) => updateGenOverride(idx, 'p_mw', e.target.value)}
                                                        disabled={isLoading}
                                                    />
                                                </div>
                                                <div className="flex items-center gap-2">
                                                    <label className="w-16">V (p.u.)</label>
                                                    <Input
                                                        type="number"
                                                        className="h-7 text-xs"
                                                        value={currentV}
                                                        step={0.01}
                                                        onChange={(e) => updateGenOverride(idx, 'vm_pu', e.target.value)}
                                                        disabled={isLoading}
                                                    />
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            </AccordionContent>
                        </AccordionItem>

                        {/* Loads */}
                        <AccordionItem value="loads">
                            <AccordionTrigger className="text-sm font-medium">Loads ({loads.length})</AccordionTrigger>
                            <AccordionContent>
                                <div className="space-y-4 pt-2">
                                    {loads.map(([idxStr, load]) => {
                                        const idx = parseInt(idxStr);
                                        const currentP = overrides.loadOverrides[idx]?.p_mw ?? load.p_mw;
                                        const currentQ = overrides.loadOverrides[idx]?.q_mvar ?? load.q_mvar;
                                        const inService = overrides.loadOverrides[idx]?.in_service ?? load.in_service ?? true;
                                        return (
                                            <div key={`load-${idxStr}`} className="space-y-2 p-2 rounded bg-muted/30 text-xs">
                                                <div className="flex items-center justify-between font-medium">
                                                    <span>{load.name || `Load ${idxStr}`} (Bus {load.bus})</span>
                                                    <div className="flex items-center gap-2">
                                                        <span className={!inService ? "text-destructive" : "text-success"}>
                                                            {!inService ? "Tripped" : "In Service"}
                                                        </span>
                                                        <Switch
                                                            checked={inService}
                                                            onCheckedChange={(val) => updateLoadOverride(idx, 'in_service', val)}
                                                            disabled={isLoading}
                                                        />
                                                    </div>
                                                </div>
                                                <div className="flex items-center gap-2">
                                                    <label className="w-16">P (MW)</label>
                                                    <Input
                                                        type="number"
                                                        className="h-7 text-xs"
                                                        value={currentP}
                                                        onChange={(e) => updateLoadOverride(idx, 'p_mw', e.target.value)}
                                                        disabled={isLoading}
                                                    />
                                                </div>
                                                <div className="flex items-center gap-2">
                                                    <label className="w-16">Q (MVAR)</label>
                                                    <Input
                                                        type="number"
                                                        className="h-7 text-xs"
                                                        value={currentQ}
                                                        onChange={(e) => updateLoadOverride(idx, 'q_mvar', e.target.value)}
                                                        disabled={isLoading}
                                                    />
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            </AccordionContent>
                        </AccordionItem>

                        {/* Transformers */}
                        {trafos.length > 0 && (
                            <AccordionItem value="trafos">
                                <AccordionTrigger className="text-sm font-medium">Transformers ({trafos.length})</AccordionTrigger>
                                <AccordionContent>
                                    <div className="space-y-4 pt-2">
                                        {trafos.map(([idxStr, trafo]) => {
                                            const idx = parseInt(idxStr);
                                            const initiallyOutaged = trafo.in_service === false;
                                            const isToggledByUser = overrides.trafoOutages.includes(idx);
                                            const isOutaged = isToggledByUser ? !initiallyOutaged : initiallyOutaged;

                                            return (
                                                <div key={`trafo-${idxStr}`} className="flex items-center justify-between text-xs p-2 rounded bg-muted/30">
                                                    <span>{trafo.name || `Trafo ${idxStr}`} (Bus {trafo.hv_bus} ➔ {trafo.lv_bus})</span>
                                                    <div className="flex items-center gap-2">
                                                        <span className={isOutaged ? "text-destructive" : "text-success"}>
                                                            {isOutaged ? "Tripped" : "In Service"}
                                                        </span>
                                                        <Switch
                                                            checked={!isOutaged}
                                                            onCheckedChange={() => toggleTrafoOutage(idx, trafo.in_service !== false)}
                                                            disabled={isLoading}
                                                        />
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </AccordionContent>
                            </AccordionItem>
                        )}

                        {/* External Grids */}
                        {extGrids.length > 0 && (
                            <AccordionItem value="ext_grids">
                                <AccordionTrigger className="text-sm font-medium">External Grids ({extGrids.length})</AccordionTrigger>
                                <AccordionContent>
                                    <div className="space-y-4 pt-2">
                                        {extGrids.map(([idxStr, ext]) => {
                                            const idx = parseInt(idxStr);
                                            const currentV = overrides.extGridOverrides[idx]?.vm_pu ?? ext.vm_pu;
                                            const inService = overrides.extGridOverrides[idx]?.in_service ?? ext.in_service ?? true;
                                            return (
                                                <div key={`ext-${idxStr}`} className="space-y-2 p-2 rounded bg-muted/30 text-xs">
                                                    <div className="flex items-center justify-between font-medium">
                                                        <span>{ext.name || `Ext Grid ${idxStr}`} (Bus {ext.bus})</span>
                                                        <div className="flex items-center gap-2">
                                                            <span className={!inService ? "text-destructive" : "text-success"}>
                                                                {!inService ? "Tripped" : "In Service"}
                                                            </span>
                                                            <Switch
                                                                checked={inService}
                                                                onCheckedChange={(val) => updateExtGridOverride(idx, 'in_service', val)}
                                                                disabled={isLoading}
                                                            />
                                                        </div>
                                                    </div>
                                                    <div className="flex items-center gap-2">
                                                        <label className="w-16">V (p.u.)</label>
                                                        <Input
                                                            type="number"
                                                            className="h-7 text-xs"
                                                            value={currentV}
                                                            step={0.01}
                                                            onChange={(e) => updateExtGridOverride(idx, 'vm_pu', e.target.value)}
                                                            disabled={isLoading}
                                                        />
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </AccordionContent>
                            </AccordionItem>
                        )}

                    </Accordion>
                </div>
            </CardContent>
        </Card>
    );
}
