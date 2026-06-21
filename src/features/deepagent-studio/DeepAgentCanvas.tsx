/**
 * DeepAgentCanvas — ReactFlow wrapper with snap-to-grid, grid background,
 * and a "Reset Layout" button to restore auto-layout positions.
 */

import { useMemo, useEffect, useCallback } from 'react';
import { RotateCcw } from 'lucide-react';
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  useReactFlow,
  ReactFlowProvider,
} from 'reactflow';
import 'reactflow/dist/style.css';

import { nodeTypes } from './nodes/nodeTypes';
import { buildLayout } from './utils/autoLayout';
import type { AgentStructure } from './types';

interface Props {
  structure: AgentStructure | null;
  selectedNodeId?: string | null;
  onNodeSelect?: (nodeId: string | null, data: any) => void;
}

export default function DeepAgentCanvas(props: Props) {
  return (
    <ReactFlowProvider>
      <DeepAgentCanvasInner {...props} />
    </ReactFlowProvider>
  );
}

function DeepAgentCanvasInner({ structure, selectedNodeId, onNodeSelect }: Props) {
  const layout = useMemo(() => structure ? buildLayout(structure) : { nodes: [], edges: [] }, [structure]);
  const [nodes, setNodes, onNodesChange] = useNodesState(layout.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(layout.edges);
  const { fitView } = useReactFlow();

  // Re-sync on structure change
  useEffect(() => {
    setNodes(layout.nodes);
    setEdges(layout.edges);
  }, [layout, setNodes, setEdges]);

  // Highlight selected node from external prop
  useEffect(() => {
    setNodes(curr => curr.map(n => ({ ...n, selected: n.id === selectedNodeId })));
  }, [selectedNodeId, setNodes]);

  const resetLayout = useCallback(() => {
    const fresh = structure ? buildLayout(structure) : { nodes: [], edges: [] };
    setNodes(fresh.nodes);
    setEdges(fresh.edges);
    setTimeout(() => fitView({ padding: 0.25, duration: 300 }), 50);
  }, [structure, setNodes, setEdges, fitView]);

  if (!structure) {
    return (
      <div className="flex-1 flex items-center justify-center"
        style={{ backgroundColor: 'var(--color-canvas-bg)', color: 'var(--color-text-muted)' }}>
        <div className="text-center">
          <div className="text-6xl mb-3">🎨</div>
          <p className="text-sm">Pick a DeepAgent above to visualize its structure</p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative w-full h-full" style={{ minHeight: 0 }}>
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={(_, n) => onNodeSelect?.(n.id, n.data)}
      onPaneClick={() => onNodeSelect?.(null, null)}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.25, maxZoom: 1.0 }}
      defaultViewport={{ x: 0, y: 0, zoom: 0.8 }}
      minZoom={0.3}
      maxZoom={2}
      nodesDraggable={true}
      nodesConnectable={false}
      elementsSelectable={true}
      zoomOnDoubleClick={false}
      snapToGrid
      snapGrid={[10, 10]}
      proOptions={{ hideAttribution: true }}
      style={{ width: '100%', height: '100%' }}
    >
      <Background variant={BackgroundVariant.Lines} gap={20} size={1} color="rgba(140,140,160,0.25)" />
      <Controls showInteractive={false} />
      <MiniMap
        nodeColor={(n) =>
          n.type === 'mainAgent' ? 'var(--color-primary)' :
          n.type === 'tool' ? '#3b82f6' :
          n.type === 'info' ? ((n.data as any)?.accent ?? '#94a3b8') :
          '#94a3b8'
        }
        maskColor="rgba(0,0,0,0.5)"
        style={{ backgroundColor: 'var(--color-panel-dark)' }}
        pannable
        zoomable
      />
    </ReactFlow>
    {/* Reset Layout button (top-right) */}
    <button
      onClick={resetLayout}
      className="absolute top-3 right-3 z-10 flex items-center gap-1.5 px-2.5 py-1.5 rounded text-[11px] font-medium shadow-md transition-colors"
      style={{
        backgroundColor: 'var(--color-panel-dark)',
        color: 'var(--color-text-primary)',
        border: '1px solid var(--color-border)',
      }}
      onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'rgba(255,255,255,0.08)'; }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--color-panel-dark)'; }}
      title="Restore default auto-layout positions"
    >
      <RotateCcw className="w-3 h-3" />
      Reset Layout
    </button>
    </div>
  );
}