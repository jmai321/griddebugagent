'use client';

import { useCallback, useEffect, useMemo } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type Connection,
  Panel,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { TopologyResponse } from '@/types/diagnostic';

const POSITION_SCALE = 220;

function topologyToFlow(topology: TopologyResponse): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = topology.nodes.map((n) => ({
    id: n.id,
    type: 'default',
    position: { x: n.x * POSITION_SCALE, y: n.y * POSITION_SCALE },
    data: {
      label: (
        <span className="font-medium text-xs">
          {n.label}
          {!n.in_service && (
            <span className="block text-muted-foreground font-normal">(out)</span>
          )}
        </span>
      ),
    },
  }));

  const edges: Edge[] = topology.edges
    .filter((e) => e.in_service)
    .map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: 'default',
      data: e.type === 'trafo' ? { label: 'T' } : undefined,
    }));

  return { nodes, edges };
}

interface GridGraphProps {
  topology: TopologyResponse | null;
  isLoading?: boolean;
  className?: string;
}

export function GridGraph({ topology, isLoading, className = '' }: GridGraphProps) {
  const initial = useMemo(() => {
    if (!topology) return { nodes: [], edges: [] };
    return topologyToFlow(topology);
  }, [topology]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges);

  useEffect(() => {
    if (!topology) return;
    const { nodes: nextNodes, edges: nextEdges } = topologyToFlow(topology);
    setNodes(nextNodes);
    setEdges(nextEdges);
  }, [topology, setNodes, setEdges]);

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges]
  );

  if (isLoading) {
    return (
      <div className={`flex items-center justify-center bg-muted/30 rounded-lg ${className}`}>
        <p className="text-muted-foreground text-sm">Loading network...</p>
      </div>
    );
  }

  if (!topology || topology.nodes.length === 0) {
    return (
      <div className={`flex items-center justify-center bg-muted/30 rounded-lg ${className}`}>
        <p className="text-muted-foreground text-sm">Select network to view topology</p>
      </div>
    );
  }

  return (
    <div className={className}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={1.5}
        defaultViewport={{ x: 0, y: 0, zoom: 0.8 }}
        nodesDraggable
        nodesConnectable={false}
        elementsSelectable
        className="bg-muted/20 rounded-lg border border-border"
      >
        <Background gap={12} size={1} />
        <Controls showInteractive={false} />
        <MiniMap nodeColor="#94a3b8" maskColor="rgb(15 23 42 / 0.8)" />
        <Panel position="top-left" className="text-xs text-muted-foreground bg-background/90 px-2 py-1 rounded shadow">
          Drag nodes to adjust layout
        </Panel>
      </ReactFlow>
    </div>
  );
}
