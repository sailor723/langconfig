/**
 * Graph Engineering canvas — renders a code-defined LangGraph structure with
 * React Flow. The layout is computed generically (BFS layers) so any graph
 * introspected by the backend renders sensibly, in either left→right or
 * top→bottom orientation. Running nodes are highlighted as updates arrive.
 */
import { useEffect, type CSSProperties } from 'react';
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { ArrowLeftRight } from 'lucide-react';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { studio, useStudioState, type Direction } from './studioStore';
import type { GraphSpec } from './api';

const NODE_WIDTH = 200;
const NODE_HEIGHT = 40;
const LAYER_GAP = 150; // gap between layers
const IN_LAYER_GAP = 34; // gap between stacked nodes in a layer
const OFFSET = 24;

interface GraphNodeData {
  name: string;
  current: boolean;
  direction: Direction;
}
type StudioEdgeData = { conditional: boolean };
type StudioEdge = Edge<StudioEdgeData>;

const CONDITIONAL_COLOR = '#e8a33d';

/** Generic layered layout: BFS from __start__, then stack nodes per layer. */
function computeLayout(spec: GraphSpec, direction: Direction): Record<string, { x: number; y: number }> {
  const adjacency = new Map<string, string[]>();
  for (const e of spec.edges) {
    if (!adjacency.has(e.source)) adjacency.set(e.source, []);
    adjacency.get(e.source)!.push(e.target);
  }

  // Assign each node a BFS depth starting from __start__.
  const layerOf = new Map<string, number>();
  const visited = new Set<string>();
  let frontier = ['__start__'];
  let depth = 0;
  while (frontier.length > 0) {
    const next: string[] = [];
    for (const id of frontier) {
      if (visited.has(id)) continue;
      visited.add(id);
      layerOf.set(id, depth);
      for (const t of adjacency.get(id) ?? []) {
        if (!visited.has(t)) next.push(t);
      }
    }
    frontier = next;
    depth += 1;
  }
  // Unreachable nodes (e.g. __end__ with no inbound edge) sit in layer 0.
  for (const n of spec.nodes) {
    if (!layerOf.has(n.id)) layerOf.set(n.id, 0);
  }

  // Group node ids by layer, preserving spec order.
  const groups = new Map<number, string[]>();
  for (const n of spec.nodes) {
    const l = layerOf.get(n.id)!;
    if (!groups.has(l)) groups.set(l, []);
    groups.get(l)!.push(n.id);
  }
  const maxCount = Math.max(1, ...Array.from(groups.values(), (g) => g.length));
  const mid = (maxCount - 1) / 2;
  const stepX = NODE_WIDTH + LAYER_GAP;
  const stepY = NODE_HEIGHT + IN_LAYER_GAP;

  const positions: Record<string, { x: number; y: number }> = {};
  for (const [layer, ids] of groups) {
    ids.forEach((id, i) => {
      positions[id] =
        direction === 'lr'
          ? { x: OFFSET + layer * stepX, y: OFFSET + (i - mid) * stepY }
          : { x: OFFSET + (i - mid) * stepX, y: OFFSET + layer * stepY };
    });
  }
  return positions;
}

function GraphNode({ data }: NodeProps<GraphNodeData>) {
  const t = useLayoutTokens();
  const isStart = data.name === '__start__';
  const isEnd = data.name === '__end__';
  const display = isStart ? 'Start' : isEnd ? 'End' : data.name;
  const targetPos = data.direction === 'lr' ? Position.Left : Position.Top;
  const sourcePos = data.direction === 'lr' ? Position.Right : Position.Bottom;

  const active = data.current;
  const handleStyle: CSSProperties = {
    width: 6,
    height: 6,
    border: 'none',
    background: active ? t.accent : t.textDim,
  };

  return (
    <div
      style={{
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 6,
        padding: '0 10px',
        borderRadius: 6,
        fontSize: 12.5,
        fontWeight: 500,
        fontFamily: 'inherit',
        whiteSpace: 'nowrap',
        background: isStart ? '#3f9e4d' : isEnd ? t.accent : active ? t.bgSelected : t.bgSidebar,
        color: isStart || isEnd ? '#ffffff' : active ? t.textWhite : t.textPrimary,
        border: `1px solid ${isStart || isEnd ? 'transparent' : active ? t.accent : t.border}`,
        boxShadow: active ? `0 0 0 2px ${t.accentMuted}` : 'none',
        transition: 'all 0.15s ease',
      }}
    >
      <Handle type="target" position={targetPos} style={handleStyle} isConnectable={false} />
      {!isStart && !isEnd && (
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: active ? t.accent : t.textDim,
            flexShrink: 0,
          }}
        />
      )}
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{display}</span>
      <Handle type="source" position={sourcePos} style={handleStyle} isConnectable={false} />
    </div>
  );
}

const nodeTypes = { studio: GraphNode };

function iconButtonStyle(t: ReturnType<typeof useLayoutTokens>): CSSProperties {
  return {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 26,
    height: 26,
    border: `1px solid ${t.border}`,
    borderRadius: 6,
    background: t.bgSidebar,
    color: t.textMuted,
    cursor: 'pointer',
  };
}

function GraphCanvasInner() {
  const t = useLayoutTokens();
  const { fitView } = useReactFlow();
  const { graph, direction, runPath, running } = useStudioState();
  const [nodes, setNodes, onNodesChange] = useNodesState<GraphNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<StudioEdgeData>([]);

  // Rebuild layout when the graph or direction changes.
  useEffect(() => {
    if (!graph) {
      setNodes([]);
      setEdges([]);
      return;
    }
    const positions = computeLayout(graph, direction);
    setNodes(
      graph.nodes.map((n) => ({
        id: n.id,
        position: positions[n.id] ?? { x: OFFSET, y: OFFSET },
        type: 'studio',
        data: { name: n.id, current: false, direction },
      })),
    );
    setEdges(
      graph.edges.map((e, i) => ({
        id: `${e.source}→${e.target}#${i}`,
        source: e.source,
        target: e.target,
        type: 'smoothstep',
        data: { conditional: Boolean(e.conditional) },
        style: {
          stroke: e.conditional ? CONDITIONAL_COLOR : t.border,
          strokeWidth: 1.2,
          opacity: 0.45,
        },
      })),
    );
  }, [graph, direction, t.border, setNodes, setEdges]);

  // Highlight nodes that are executing in the current run.
  useEffect(() => {
    setNodes((ns) =>
      ns.map((n) => ({ ...n, data: { ...n.data, current: runPath.includes(n.id) } })),
    );
    setEdges((es) =>
      es.map((e) => {
        const onPath = runPath.includes(e.source) && runPath.includes(e.target);
        return {
          ...e,
          style: {
            ...e.style,
            opacity: onPath ? 1 : 0.45,
            stroke: onPath
              ? e.data?.conditional
                ? CONDITIONAL_COLOR
                : t.accent
              : e.data?.conditional
                ? CONDITIONAL_COLOR
                : t.border,
          },
        };
      }),
    );
  }, [runPath, t.accent, t.border, setNodes, setEdges]);

  // Fit the fresh layout into view.
  useEffect(() => {
    if (!graph) return;
    const timer = setTimeout(() => fitView({ padding: 0.2, duration: 300 }), 60);
    return () => clearTimeout(timer);
  }, [graph, direction, fitView]);

  if (!graph) {
    return (
      <div
        style={{
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: t.textDim,
          fontSize: 13,
        }}
      >
        Select an assistant to view its graph.
      </div>
    );
  }

  return (
    <div style={{ height: '100%', width: '100%', position: 'relative' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        minZoom={0.2}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        <Background color={t.border} gap={24} variant={BackgroundVariant.Dots} style={{ opacity: 0.35 }} />
        <Controls showInteractive={false} />
      </ReactFlow>

      {/* Overlay: direction toggle + run status + legend */}
      <div style={{ position: 'absolute', top: 10, left: 10, zIndex: 5, display: 'flex', alignItems: 'center', gap: 8 }}>
        <button style={iconButtonStyle(t)} onClick={studio.toggleDirection} title="Toggle layout direction">
          <ArrowLeftRight size={14} />
        </button>
        <span
          style={{
            fontSize: 11,
            color: t.textDim,
            background: t.bgSidebar,
            border: `1px solid ${t.border}`,
            borderRadius: 4,
            padding: '3px 8px',
          }}
        >
          {running ? '● running' : '○ idle'}
        </span>
      </div>
      <div
        style={{
          position: 'absolute',
          bottom: 10,
          left: 10,
          zIndex: 5,
          display: 'flex',
          flexDirection: 'column',
          gap: 4,
          fontSize: 11,
          color: t.textDim,
          background: t.bgSidebar,
          border: `1px solid ${t.border}`,
          borderRadius: 6,
          padding: '6px 10px',
        }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: t.accent }} /> executing
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: CONDITIONAL_COLOR }} /> conditional edge
        </span>
      </div>
    </div>
  );
}

export function GraphCanvas() {
  return (
    <ReactFlowProvider>
      <GraphCanvasInner />
    </ReactFlowProvider>
  );
}
