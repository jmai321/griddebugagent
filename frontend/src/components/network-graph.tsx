'use client';

import { useMemo, useEffect } from 'react';
import {
  ReactFlow,
  Node,
  Edge,
  Background,
  Controls,
  useNodesState,
  useEdgesState,
  BackgroundVariant,
  NodeProps,
  Handle,
  Position,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { RawNetworkState } from '@/types/diagnostic';
import { Loader2 } from 'lucide-react';

interface NetworkGraphProps {
  networkState: RawNetworkState | null;
  isLoading: boolean;
}

// Custom node component for buses
function BusNode({ data }: NodeProps) {
  const isAffected = data.isAffected as boolean;
  const isOutOfService = data.isOutOfService as boolean;
  const busType = data.busType as string;

  // Color based on type
  let bgColor = '#3b82f6'; // blue for regular bus
  if (busType === 'ext_grid') bgColor = '#eab308'; // yellow
  else if (busType === 'gen') bgColor = '#f97316'; // orange
  else if (busType === 'load') bgColor = '#6b7280'; // gray

  return (
    <div
      className="flex items-center justify-center rounded-full text-white text-xs font-bold"
      style={{
        width: 40,
        height: 40,
        backgroundColor: bgColor,
        border: isAffected ? '3px solid #ef4444' : isOutOfService ? '3px dashed #64748b' : '2px solid #1e293b',
        boxShadow: isAffected ? '0 0 8px #ef4444' : 'none',
        opacity: isOutOfService ? 0.5 : 1,
      }}
    >
      {data.label as string}
      <Handle type="target" position={Position.Top} className="opacity-0" />
      <Handle type="source" position={Position.Bottom} className="opacity-0" />
    </div>
  );
}

const nodeTypes = {
  bus: BusNode,
};

function transformNetworkToGraph(state: RawNetworkState): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const affectedBuses = new Set(state.affected_components?.bus || []);
  const affectedLines = new Set(state.affected_components?.line || []);
  const affectedTrafos = new Set(state.affected_components?.trafo || []);
  const affectedLoads = new Set(state.affected_components?.load || []);
  const affectedGens = new Set(state.affected_components?.gen || []);

  // Determine bus types and service status (ext_grid > gen > load > bus)
  const busTypes: Record<number, string> = {};
  const busOutOfService: Record<number, boolean> = {};

  // Mark ext_grid buses
  Object.entries(state.ext_grid || {}).forEach(([, ext]) => {
    busTypes[ext.bus] = 'ext_grid';
    // Track if ext_grid is out of service
    if (ext.in_service === false) {
      busOutOfService[ext.bus] = true;
    }
  });

  // Mark gen buses (if not already ext_grid)
  Object.entries(state.gen || {}).forEach(([idx, gen]) => {
    if (!busTypes[gen.bus]) {
      busTypes[gen.bus] = 'gen';
      // Track if gen is out of service (only if this is the primary component)
      if (gen.in_service === false) {
        busOutOfService[gen.bus] = true;
      }
    }
    // Check if this gen is affected
    if (affectedGens.has(Number(idx))) {
      affectedBuses.add(gen.bus);
    }
  });

  // Mark load buses (if not already marked)
  Object.entries(state.load || {}).forEach(([idx, load]) => {
    if (!busTypes[load.bus]) {
      busTypes[load.bus] = 'load';
      // Track if load is out of service (only if this is the primary component)
      if (load.in_service === false) {
        busOutOfService[load.bus] = true;
      }
    }
    // Check if this load is affected
    if (affectedLoads.has(Number(idx))) {
      affectedBuses.add(load.bus);
    }
  });

  // Create bus nodes
  Object.entries(state.bus || {}).forEach(([idxStr, bus]) => {
    const idx = Number(idxStr);
    const coords = state.bus_coords?.[idxStr] || { x: 0, y: 0 };
    const isAffected = affectedBuses.has(idx);
    const busType = busTypes[idx] || 'bus';
    const isOutOfService = busOutOfService[idx] || false;

    // Get voltage if available
    const voltage = state.res_bus?.[idxStr]?.vm_pu;

    nodes.push({
      id: `bus-${idx}`,
      type: 'bus',
      position: { x: coords.x, y: coords.y },
      data: {
        label: String(idx),
        name: bus.name,
        vn_kv: bus.vn_kv,
        vm_pu: voltage,
        isAffected,
        isOutOfService,
        busType,
        in_service: bus.in_service,
      },
    });
  });

  // Create edges from lines
  Object.entries(state.line || {}).forEach(([idxStr, line]) => {
    const idx = Number(idxStr);
    const isAffected = affectedLines.has(idx);
    const loading = state.res_line?.[idxStr]?.loading_percent;
    const hasLoading = loading != null && !isNaN(loading);
    const isOutOfService = line.in_service === false;

    edges.push({
      id: `line-${idx}`,
      source: `bus-${line.from_bus}`,
      target: `bus-${line.to_bus}`,
      type: 'default',
      style: {
        stroke: isAffected ? '#ef4444' : '#64748b',
        strokeWidth: isAffected ? 3 : 2,
        strokeDasharray: isOutOfService ? '5,5' : undefined,
        opacity: isOutOfService ? 0.5 : 1,
      },
      label: hasLoading ? `${loading.toFixed(0)}%` : undefined,
      labelStyle: {
        fill: isAffected ? '#ef4444' : '#64748b',
        fontSize: 10,
      },
      data: {
        loading_percent: loading,
        isAffected,
        in_service: line.in_service,
      },
    });
  });

  // Create edges from transformers
  Object.entries(state.trafo || {}).forEach(([idxStr, trafo]) => {
    const idx = Number(idxStr);
    const isAffected = affectedTrafos.has(idx);
    const isOutOfService = trafo.in_service === false;

    edges.push({
      id: `trafo-${idx}`,
      source: `bus-${trafo.hv_bus}`,
      target: `bus-${trafo.lv_bus}`,
      type: 'default',
      style: {
        stroke: isAffected ? '#ef4444' : '#8b5cf6', // purple for trafos
        strokeWidth: isAffected ? 3 : 2,
        strokeDasharray: isOutOfService ? '5,5' : undefined,
        opacity: isOutOfService ? 0.5 : 1,
      },
      label: 'T',
      labelStyle: { fill: '#8b5cf6', fontSize: 10 },
      data: {
        isAffected,
        in_service: trafo.in_service,
      },
    });
  });

  return { nodes, edges };
}

export function NetworkGraph({ networkState, isLoading }: NetworkGraphProps) {
  const { nodes: initialNodes, edges: initialEdges } = useMemo(() => {
    if (!networkState) return { nodes: [], edges: [] };
    return transformNetworkToGraph(networkState);
  }, [networkState]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Update nodes/edges when networkState changes
  useEffect(() => {
    if (networkState) {
      const { nodes: newNodes, edges: newEdges } = transformNetworkToGraph(networkState);
      setNodes(newNodes);
      setEdges(newEdges);
    }
  }, [networkState, setNodes, setEdges]);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-full bg-muted/20">
        <Loader2 className="h-8 w-8 text-primary animate-spin mb-4" />
        <p className="text-sm text-muted-foreground">Simulating network overrides...</p>
      </div>
    );
  }

  if (!networkState) {
    return (
      <div className="flex flex-col items-center justify-center h-full bg-muted/20">
        <p className="text-sm text-muted-foreground">No network data available</p>
      </div>
    );
  }

  return (
    <div className="w-full h-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.1}
        maxZoom={2}
        attributionPosition="bottom-left"
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
        <Controls />
      </ReactFlow>

      {/* Legend */}
      <div className="absolute bottom-4 right-4 bg-background/90 border rounded-lg p-3 text-xs space-y-1">
        <div className="font-medium mb-2">Legend</div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-yellow-500" />
          <span>External Grid</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-orange-500" />
          <span>Generator</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-gray-500" />
          <span>Load</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-blue-500" />
          <span>Bus</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full border-2 border-red-500 bg-transparent" />
          <span>Affected</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-gray-400 opacity-50" style={{ border: '2px dashed #64748b' }} />
          <span>Out of Service</span>
        </div>
        <div className="flex items-center gap-2 mt-2 pt-2 border-t">
          <div className="w-4 h-0.5 bg-purple-500" />
          <span>Transformer</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-0.5 bg-red-500" style={{ height: 3 }} />
          <span>Affected (LLM)</span>
        </div>
      </div>
    </div>
  );
}
