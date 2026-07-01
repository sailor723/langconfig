/**
 * ModernStudioCanvas — dark canvas with subtle grid + LangChain-style edges.
 * Uses useNodesState/useEdgesState for node dragging/resizing.
 */

import { useMemo, useEffect, useCallback } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  Edge,
  Node,
  ReactFlowProvider,
  useNodesState,
  useEdgesState,
  useReactFlow,
} from 'reactflow';
import 'reactflow/dist/style.css';

import { nodeTypes } from './nodes/nodeTypes';
import { autoLayout } from './utils/autoLayout';
import type { AgentStructure } from './types';

interface Props {
  structure: AgentStructure | null;
  onNodeClick?: (nodeId: string | null, node: Node | null) => void;
}

export default function ModernStudioCanvas(props: Props) {
  return (
    <ReactFlowProvider>
      <ModernStudioCanvasInner {...props} />
    </ReactFlowProvider>
  );
}

function ModernStudioCanvasInner({ structure, onNodeClick }: Props) {
  const layout = useMemo(
    () => (structure ? autoLayout(structure) : { nodes: [], edges: [] }),
    [structure]
  );
  const [nodes, setNodes, onNodesChange] = useNodesState(layout.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(layout.edges);
  const { fitView } = useReactFlow();

  // Re-sync on structure change
  useEffect(() => {
    setNodes(layout.nodes);
    setEdges(layout.edges);
    const t = setTimeout(() => {
      try {
        fitView({ padding: 0.2, duration: 300, maxZoom: 1.0, minZoom: 0.2 });
      } catch {}
    }, 100);
    return () => clearTimeout(t);
  }, [layout, setNodes, setEdges, fitView]);

  const handleNodeClick = useCallback(
    (_: any, node: Node) => onNodeClick?.(node.id, node),
    [onNodeClick]
  );

  // Inject custom keyframe animation for glow and edge dash flow
  useEffect(() => {
    const style = document.createElement('style');
    style.textContent = `
      @keyframes pulse-glow {
        0%, 100% { box-shadow: 0 0 16px rgba(0, 109, 221, 0.4), inset 0 0 8px rgba(127, 200, 255, 0.1); }
        50% { box-shadow: 0 0 24px rgba(127, 200, 255, 0.5), inset 0 0 12px rgba(127, 200, 255, 0.18); }
      }
    `;
    document.head.appendChild(style);
    return () => { style.remove(); };
  }, []);

  return (
    <div
      className="w-full h-full"
      style={{ background: '#030710', pointerEvents: 'all' }}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        nodesDraggable={true}
        nodesConnectable={false}
        elementsSelectable={true}
        panOnDrag={[1, 2]}           // pan with right-click/middle-click
        zoomOnScroll={true}
        zoomOnDoubleClick={false}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{ animated: false }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1.5}
          color="rgba(127, 200, 255, 0.15)"
        />
        <MiniMap
          style={{
            background: '#0D1322',
            border: '1px solid rgba(0, 109, 221, 0.4)',
            borderRadius: 8,
          }}
          maskColor="rgba(3, 7, 16, 0.85)"
          nodeColor={() => '#006DDD'}
        />
        <Controls
          style={{
            background: '#0D1322',
            border: '1px solid rgba(0, 109, 221, 0.4)',
            borderRadius: 8,
          }}
          showInteractive={false}
        />
      </ReactFlow>
    </div>
  );
}
