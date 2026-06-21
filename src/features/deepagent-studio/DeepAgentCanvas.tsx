/**
 * DeepAgentCanvas — read-only ReactFlow wrapper.
 * No drag-and-drop, no add/delete. Pan + zoom + select only.
 */

import { useMemo, useEffect } from 'react';
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
} from 'reactflow';
import 'reactflow/dist/style.css';
import PropertyPopup from './components/PropertyPopup';

import { nodeTypes } from './nodes/nodeTypes';
import { buildLayout } from './utils/autoLayout';
import type { AgentStructure } from './types';

interface Props {
  structure: AgentStructure | null;
  selectedNodeId?: string | null;
  onNodeSelect?: (nodeId: string | null, data: any) => void;
}

export default function DeepAgentCanvas({ structure, selectedNodeId, onNodeSelect }: Props) {
  const layout = useMemo(() => structure ? buildLayout(structure) : { nodes: [], edges: [] }, [structure]);
  const [nodes, setNodes, onNodesChange] = useNodesState(layout.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(layout.edges);

  // Re-sync on structure change
  useEffect(() => {
    setNodes(layout.nodes);
    setEdges(layout.edges);
  }, [layout, setNodes, setEdges]);

  // Highlight selected node from external prop
  useEffect(() => {
    setNodes(curr => curr.map(n => ({ ...n, selected: n.id === selectedNodeId })));
  }, [selectedNodeId, setNodes]);

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
    <>
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={(_, n) => onNodeSelect?.(n.id, n.data)}
      onPaneClick={() => onNodeSelect?.(null, null)}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.25 }}
      nodesDraggable={true}
      nodesConnectable={false}
      elementsSelectable={true}
      zoomOnDoubleClick={false}
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="rgba(255,255,255,0.06)" />
      <Controls showInteractive={false} />
      <MiniMap
        nodeColor={(n) => n.type === 'mainAgent' ? 'var(--color-primary)' : n.type === 'tool' ? '#3b82f6' : '#94a3b8'}
        maskColor="rgba(0,0,0,0.5)"
        style={{ backgroundColor: 'var(--color-panel-dark)' }}
        pannable
        zoomable
      />
    </ReactFlow>
    <PropertyPopup structure={structure} />
    </>
  );
}