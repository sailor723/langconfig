/**
 * ModernStudioCanvas — dark canvas with subtle grid + LangChain-style edges.
 * Uses useNodesState/useEdgesState for node dragging/resizing.
 * Features force-resistance to prevent node overlap.
 */

import { useMemo, useEffect, useCallback, useRef } from 'react';
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

// ── Force-directed collision repulsion ───────────────────────────
const FORCE_PUSH = 12;   // pixels to push overlapping nodes away
const GAP_MIN = 24;       // minimum gap between node edges

/** Compute overlaps for a pair of nodes and return push vector. */
function repulsePair(a: Node, b: Node): { x: number; y: number } | null {
  const aL = a.position.x;
  const aR = aL + (a.width || 180);
  const aT = a.position.y;
  const aB = aT + (a.height || 100);
  const bL = b.position.x;
  const bR = bL + (b.width || 180);
  const bT = b.position.y;
  const bB = bT + (b.height || 100);

  const gapX = Math.max(aL - bR, bL - aR);
  const gapY = Math.max(aT - bB, bT - aB);

  // Only repel if overlapping (gap is negative)
  if (gapX < 0 && gapY < 0) {
    const aCx = aL + (a.width  || 180) / 2;
    const aCy = aT + (a.height || 100) / 2;
    const bCx = bL + (b.width  || 180) / 2;
    const bCy = bT + (b.height || 100) / 2;
    const dirX = bCx - aCx;
    const dirY = bCy - aCy;
    const dist = Math.sqrt(dirX * dirX + dirY * dirY) || 1;
    const normX = dirX / dist;
    const normY = dirY / dist;
    return { x: normX * FORCE_PUSH, y: normY * FORCE_PUSH };
  }
  return null;
}

/** Apply N-body repulsion between ALL overlapping node pairs. */
function applyNBodyRepulsion(nodes: Node[]): Node[] {
  const updated = nodes.map(n => ({ ...n }));
  const n = updated.length;
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const push = repulsePair(updated[i], updated[j]);
      if (push) {
        updated[i] = {
          ...updated[i],
          position: {
            x: updated[i].position.x - push.x,
            y: updated[i].position.y - push.y,
          },
        };
        updated[j] = {
          ...updated[j],
          position: {
            x: updated[j].position.x + push.x,
            y: updated[j].position.y + push.y,
          },
        };
      }
    }
  }
  return updated;
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
  const dragRef = useRef(false);       // only repel during active drag

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

  // Reset layout — restore to auto-layout positions
  const handleResetLayout = useCallback(() => {
    setNodes(layout.nodes);
    setEdges(layout.edges);
    setTimeout(() => {
      try { fitView({ padding: 0.2, duration: 400 }); } catch {}
    }, 50);
  }, [layout, setNodes, setEdges, fitView]);

  const handleNodeClick = useCallback(
    (_: any, node: Node) => onNodeClick?.(node.id, node),
    [onNodeClick]
  );

  const handleNodeDragStart = useCallback(() => {
    dragRef.current = true;
  }, []);

  const handleNodeDrag = useCallback(
    (_: any, node: Node) => {
      if (!dragRef.current) return;
      setNodes(prev => applyNBodyRepulsion(prev));
    },
    []
  );

  const handleNodeDragStop = useCallback(() => {
    dragRef.current = false;
  }, []);

  // Inject custom keyframe animation
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
        onNodeDragStart={handleNodeDragStart}
        onNodeDrag={handleNodeDrag}
        onNodeDragStop={handleNodeDragStop}
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
        {/* Reset Layout button (icon only) */}
        <button
          onClick={handleResetLayout}
          className="absolute bottom-4 left-4 z-10 flex items-center justify-center w-9 h-9 rounded-lg transition-all"
          style={{
            background: 'linear-gradient(135deg, rgba(0, 109, 221, 0.25), rgba(127, 200, 255, 0.1))',
            border: '1px solid rgba(0, 109, 221, 0.5)',
            color: '#F2FAFF',
            boxShadow: '0 2px 6px rgba(0, 0, 0, 0.3)',
          }}
          title="Reset layout"
        >
          <span style={{ fontSize: 16 }}>↺</span>
        </button>
      </ReactFlow>
    </div>
  );
}
