/**
 * Graph Engineering canvas — renders a code-defined LangGraph structure with
 * React Flow. The layout is computed generically (BFS layers) so any graph
 * introspected by the backend renders sensibly, in either left→right or
 * top→bottom orientation. Running nodes are highlighted as updates arrive.
 */
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from 'react';
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
import { ArrowLeftRight, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useLayoutTokens, type LayoutTokens } from '../../components/layout2/tokens';
import { studio, useStudioState, type Direction } from './studioStore';
import type { GraphSpec } from './api';
import SchemaViewToolbar from './SchemaViewToolbar';
import { ErDiagram } from './ErDiagram';
import { Neo4jNetwork } from './Neo4jNetwork';
import { SchemaNodePopup } from './SchemaNodePopup';

const NODE_WIDTH = 200;
const NODE_HEIGHT = 40;
const LAYER_GAP = 150; // gap between layers
const IN_LAYER_GAP = 34; // gap between stacked nodes in a layer
const OFFSET = 24;

interface GraphNodeData {
  name: string;
  current: boolean;
  direction: Direction;
  selected: boolean;
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
  const selected = data.selected;
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
        border: `1px solid ${isStart || isEnd ? 'transparent' : active || selected ? t.accent : t.border}`,
        boxShadow: active || selected ? `0 0 0 2px ${t.accentMuted}` : 'none',
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

/** Segmented [Flow | Schema] control that drives the canvas view mode. */
function ViewModeToggle() {
  const t = useLayoutTokens();
  const { viewMode } = useStudioState();
  const wrapStyle: CSSProperties = {
    display: 'inline-flex',
    border: `1px solid ${t.border}`,
    borderRadius: 4,
    background: t.bgSidebar,
    overflow: 'hidden',
  };
  const item = (label: string, value: 'flow' | 'schema'): CSSProperties => ({
    padding: '3px 10px',
    fontSize: 11,
    fontWeight: 600,
    cursor: 'pointer',
    background: viewMode === value ? t.accent : 'transparent',
    color: viewMode === value ? '#ffffff' : t.textDim,
    borderRight: value === 'flow' ? `1px solid ${t.border}` : 'none',
    userSelect: 'none',
  });
  return (
    <div style={wrapStyle} title="Toggle view mode">
      <span style={item('flow', 'flow')} onClick={() => studio.setViewMode('flow')}>
        Flow
      </span>
      <span style={item('schema', 'schema')} onClick={() => studio.setViewMode('schema')}>
        Schema
      </span>
    </div>
  );
}

/** Bottom-left legend for the schema view — DB-type-aware. */
function SchemaLegend() {
  const t = useLayoutTokens();
  const { dbSummary } = useStudioState();
  const isNeo4j = dbSummary?.type === 'neo4j';
  const row = (color: string, label: string) => (
    <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <span style={{ width: 10, height: 6, borderRadius: 1, background: color }} />
      {label}
    </span>
  );
  return (
    <>
      {isNeo4j ? (
        <>
          {row(t.accent, 'label supernode')}
          {row('#22c55e', 'relationship edge')}
        </>
      ) : (
        <>
          {row(t.accent, 'PK column')}
          {row('#22c55e', 'foreign-key edge')}
        </>
      )}
    </>
  );
}

/** Text box at the top of the canvas: a live, bilingual BUSINESS summary of the
 *  active target database (LLM-generated, <=3 lines). Re-renders on DB switch
 *  (store) and on language change (i18next), so the text always matches the
 *  interface language setting. Falls back to raw table counts if the LLM fails. */
function DatabaseSummaryBox() {
  const t = useLayoutTokens();
  const {
    dbSummary,
    activeAssistantId,
    activeSqlDatabase, activeNeo4jDatabase,
  } = useStudioState();
  // The header shows the active DB for the current assistant type. Falls
  // back to SQL then to the summary's database field.
  const activeDatabase = activeAssistantId.startsWith('neo4j_')
    ? activeNeo4jDatabase
    : activeSqlDatabase;
  const { t: tr, i18n } = useTranslation('chat');
  const zh = i18n.language?.toLowerCase().startsWith('zh') ?? false;
  const mountedRef = useRef(false);

  // Regenerate the business summary in the new language on language switch.
  // Skip the first render — loadDatabases already fetched it on mount.
  useEffect(() => {
    if (!mountedRef.current) {
      mountedRef.current = true;
      return;
    }
    void studio.loadDatabaseSummary();
  }, [i18n.language]);

  const dbName = dbSummary?.database || activeDatabase || '—';
  const isNeo4j = dbSummary?.type === 'neo4j' || activeAssistantId.startsWith('neo4j_');

  // Counts line on the right — picks the right field set per type.
  const counts = (() => {
    if (!dbSummary) return '—';
    if (isNeo4j) {
      return zh
        ? `${dbSummary.labels?.length ?? 0} 种标签 · ${dbSummary.node_count?.toLocaleString() ?? 0} 节点 · ${dbSummary.edge_count?.toLocaleString() ?? 0} 边`
        : `${dbSummary.labels?.length ?? 0} labels · ${dbSummary.node_count?.toLocaleString() ?? 0} nodes · ${dbSummary.edge_count?.toLocaleString() ?? 0} edges`;
    }
    return zh
      ? `${dbSummary.table_count ?? 0} 张表 · ${(dbSummary.row_count ?? 0).toLocaleString()} 行`
      : `${dbSummary.table_count ?? 0} tables · ${(dbSummary.row_count ?? 0).toLocaleString()} rows`;
  })();

  // Preferred: the LLM business summary. Fallback: a technical one-liner
  // that matches the active DB type.
  let body = dbSummary?.summary ?? null;
  if (!body && dbSummary) {
    if (isNeo4j) {
      const topLabels = [...(dbSummary.labels ?? [])]
        .sort((a, b) => (b.nodes ?? 0) - (a.nodes ?? 0))
        .slice(0, 3)
        .map((x) => (zh ? `${x.name}（${x.nodes.toLocaleString()}）` : `${x.name} (${x.nodes.toLocaleString()})`))
        .join(zh ? '、' : ', ');
      const topRels = [...(dbSummary.rels ?? [])]
        .sort((a, b) => (b.edges ?? 0) - (a.edges ?? 0))
        .slice(0, 3)
        .map((x) => (zh ? `:${x.name}（${x.edges.toLocaleString()}）` : `:${x.name} (${x.edges.toLocaleString()})`))
        .join(zh ? '、' : ', ');
      if ((dbSummary.labels?.length ?? 0) === 0) {
        body = zh ? `图数据库 ${dbName} 目前没有节点。` : `Graph ${dbName} has no nodes yet.`;
      } else if (topLabels.length === 0) {
        body = zh ? '无法获取节点/边统计。' : 'Node/edge counts are unavailable.';
      } else {
        body = zh
          ? `共 ${dbSummary.labels?.length ?? 0} 种标签、${dbSummary.node_count?.toLocaleString() ?? 0} 节点、${dbSummary.edge_count?.toLocaleString() ?? 0} 边。主要标签：${topLabels}；主要关系：${topRels}。`
          : `${dbSummary.labels?.length ?? 0} labels, ${dbSummary.node_count?.toLocaleString() ?? 0} nodes, ${dbSummary.edge_count?.toLocaleString() ?? 0} edges. Top labels: ${topLabels}. Top rels: ${topRels}.`;
      }
    } else {
      const top = [...(dbSummary.tables ?? [])]
        .filter((x) => x.rows != null)
        .sort((a, b) => (b.rows ?? 0) - (a.rows ?? 0))
        .slice(0, 3)
        .map((x) => (zh ? `${x.name}（${x.rows!.toLocaleString()}）` : `${x.name} (${x.rows!.toLocaleString()})`))
        .join(zh ? '、' : ', ');
      if ((dbSummary.table_count ?? 0) === 0) {
        body = zh ? `数据库 ${dbName} 目前没有表。` : `Database ${dbName} has no tables yet.`;
      } else if (top.length === 0) {
        body = zh ? '无法获取各表的行数。' : 'Table row counts are unavailable.';
      } else {
        body = zh
          ? `共 ${dbSummary.table_count ?? 0} 张表、${(dbSummary.row_count ?? 0).toLocaleString()} 行数据。最大的表：${top}。`
          : `${dbSummary.table_count ?? 0} tables, ${(dbSummary.row_count ?? 0).toLocaleString()} rows in total. Largest: ${top}.`;
      }
    }
  }

  return (
    <div
      style={{
        margin: '8px 10px 0',
        padding: '8px 12px',
        background: t.bgSidebar,
        border: `1px solid ${t.border}`,
        borderRadius: 8,
        flexShrink: 0,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
        <span style={{ fontSize: 10.5, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.6, color: t.textDim }}>
          {tr('graph_db_summary')}
        </span>
        <span
          style={{
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
            fontSize: 11.5,
            fontWeight: 600,
            color: t.accent,
            whiteSpace: 'nowrap',
          }}
        >
          {dbName}
        </span>
        <span style={{ marginLeft: 'auto', fontSize: 11, color: t.textDim, whiteSpace: 'nowrap' }}>{counts}</span>
      </div>
      <div
        style={{
          fontSize: 12,
          color: t.textMuted,
          lineHeight: 1.5,
          whiteSpace: 'pre-wrap',
          display: '-webkit-box',
          WebkitLineClamp: 3,
          WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
        }}
      >
        {body ?? '—'}
      </div>
    </div>
  );
}

function GraphCanvasInner() {
  const t = useLayoutTokens();
  const { fitView } = useReactFlow();
  const { graph, viewMode, direction, runPath, running, activeNodeId } = useStudioState();
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
        data: { name: n.id, current: false, direction, selected: activeNodeId === n.id },
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

  // Reflect popup selection on the node visuals (separate from layout so a
  // direction toggle doesn't drop the highlight).
  useEffect(() => {
    setNodes((ns) =>
      ns.map((n) => ({ ...n, data: { ...n.data, selected: n.id === activeNodeId } })),
    );
  }, [activeNodeId, setNodes]);

  // Escape closes the node detail popup.
  useEffect(() => {
    if (!activeNodeId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') studio.selectNode(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [activeNodeId]);

  // Fit the fresh layout into view.
  useEffect(() => {
    if (!graph) return;
    const timer = setTimeout(() => fitView({ padding: 0.2, duration: 300 }), 60);
    return () => clearTimeout(timer);
  }, [graph, direction, fitView]);

  return (
    <div style={{ height: '100%', width: '100%', display: 'flex', flexDirection: 'column' }}>
      <DatabaseSummaryBox />
      {viewMode === 'flow' ? (
        graph ? (
          <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              nodeTypes={nodeTypes}
              onNodeClick={(_, node) => studio.selectNode(node.id)}
              fitView
              minZoom={0.2}
              maxZoom={2}
              proOptions={{ hideAttribution: true }}
            >
              <Background color={t.border} gap={24} variant={BackgroundVariant.Dots} style={{ opacity: 0.35 }} />
              {/* Place the ReactFlow zoom controls on the bottom-right so they
                  don't overlap with the SchemaLegend in the bottom-left. */}
              <Controls showInteractive={false} position="bottom-right" />
            </ReactFlow>

            {/* Overlay: view-mode toggle + direction toggle (flow only) + run status */}
            <div style={{ position: 'absolute', top: 10, left: 10, zIndex: 5, display: 'flex', alignItems: 'center', gap: 8 }}>
              <ViewModeToggle />
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

            {/* Node detail popup (floating overlay — deliberately not a dock) */}
            {activeNodeId && <NodePopup />}
          </div>
        ) : (
          <div
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: t.textDim,
              fontSize: 13,
            }}
          >
            Select an assistant to view its graph.
          </div>
        )
      ) : (
        <div style={{ flex: 1, minHeight: 0, position: 'relative', display: 'flex', flexDirection: 'column' }}>
          {/* Overlay: view-mode toggle only — schema view has its own toolbar */}
          <div style={{ position: 'absolute', top: 10, left: 10, zIndex: 5 }}>
            <ViewModeToggle />
          </div>
          <SchemaViewToolbar />
          <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
            <ErDiagramOrNeo4j />
            {/* Schema-view popup (separate from the Flow NodePopup) */}
            {activeNodeId && <SchemaNodePopup />}
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
            <SchemaLegend />
          </div>
        </div>
      )}
    </div>
  );
}

/** Pick the right schema-view component based on the active assistant's
 *  DB type. Falls back to ErDiagram if dbSummary hasn't loaded yet
 *  (which renders its own "loading / unavailable" placeholder). */
function ErDiagramOrNeo4j() {
  const { dbSummary } = useStudioState();
  return dbSummary?.type === 'neo4j' ? <Neo4jNetwork /> : <ErDiagram />;
}

// ---------------------------------------------------------------------------
// Node detail popup
// ---------------------------------------------------------------------------
const KIND_COLORS: Record<string, string> = {
  start: '#3f9e4d',
  end: '#e8a33d',
  function: '#3b82f6',
  tool: '#a855f7',
  subgraph: '#ec4899',
  unknown: '#6b7280',
};

function codeStyle(t: LayoutTokens): CSSProperties {
  return {
    margin: 0,
    padding: 8,
    borderRadius: 6,
    background: t.bgBase,
    border: `1px solid ${t.border}`,
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    fontSize: 11,
    lineHeight: 1.55,
    color: t.textPrimary,
    whiteSpace: 'pre',
    overflow: 'auto',
    maxHeight: 320,
  };
}

function SectionLabel({ t, children }: { t: LayoutTokens; children: ReactNode }) {
  return (
    <div
      style={{
        fontSize: 10,
        textTransform: 'uppercase',
        letterSpacing: 0.6,
        color: t.textDim,
        marginBottom: 4,
      }}
    >
      {children}
    </div>
  );
}

/** Floating card with the clicked node's metadata + source code. */
function NodePopup() {
  const t = useLayoutTokens();
  const { graph, activeNodeId } = useStudioState();
  // Drag position (null = anchored top-right until the user moves it).
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  const node = graph?.nodes.find((n) => n.id === activeNodeId);
  if (!node) return null;

  const d = node.data;
  const kind = d.kind ?? 'unknown';
  const chipColor = KIND_COLORS[kind] ?? KIND_COLORS.unknown;

  // "file.py:12-18" location string (or null when nothing is known).
  const location = (() => {
    const line =
      d.start_line != null
        ? `:${d.start_line}${d.end_line && d.end_line !== d.start_line ? `-${d.end_line}` : ''}`
        : '';
    return d.file ? `${d.file}${line}` : null;
  })();

  const hasContent = Boolean(location || d.code || (d.tools && d.tools.length > 0));

  // Drag the popup around the canvas from its header.
  const onHeaderMouseDown = (e: ReactMouseEvent) => {
    const rect = cardRef.current?.getBoundingClientRect();
    if (!rect) return;
    const startX = e.clientX - rect.left;
    const startY = e.clientY - rect.top;
    const startPos = { x: rect.left, y: rect.top };
    const onMove = (ev: MouseEvent) => {
      setPos({ x: startPos.x + ev.clientX - startX, y: startPos.y + ev.clientY - startY });
    };
    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };

  return (
    <>
      {/* Backdrop: any click outside the popup closes it */}
      <div
        style={{ position: 'absolute', inset: 0, zIndex: 9, background: 'transparent' }}
        onClick={() => studio.selectNode(null)}
      />
      <div
        data-node-popup
        ref={cardRef}
        style={{
          position: 'absolute',
          zIndex: 10,
          width: 912,
          height: 620,
          minWidth: 520,
          minHeight: 360,
          maxWidth: 'calc(100% - 20px)',
          maxHeight: 'calc(100% - 20px)',
          resize: 'both',
          overflow: 'auto',
          display: 'flex',
          flexDirection: 'column',
          background: t.bgContent,
          border: `1px solid ${t.border}`,
          borderRadius: 8,
          boxShadow: '0 8px 32px rgba(0,0,0,0.35)',
          ...(pos ? { left: pos.x, top: pos.y } : { top: 10, right: 10 }),
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          onMouseDown={onHeaderMouseDown}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '10px 12px',
            borderBottom: `1px solid ${t.border}`,
            background: t.bgSidebar,
            flexShrink: 0,
            cursor: 'move',
            userSelect: 'none',
          }}
        >
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: chipColor, flexShrink: 0 }} />
          <span
            style={{
              fontSize: 12.5,
              fontWeight: 600,
              color: t.textPrimary,
              fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {node.id}
          </span>
          <span
            style={{
              fontSize: 10,
              textTransform: 'uppercase',
              letterSpacing: 0.5,
              color: chipColor,
              background: `${chipColor}22`,
              border: `1px solid ${chipColor}55`,
              borderRadius: 4,
              padding: '1px 6px',
              flexShrink: 0,
            }}
          >
            {kind}
          </span>
          <button
            onClick={() => studio.selectNode(null)}
            title="Close (Esc)"
            style={{
              marginLeft: 'auto',
              width: 24,
              height: 24,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: 'none',
              background: 'transparent',
              color: t.textMuted,
              cursor: 'pointer',
              borderRadius: 4,
              flexShrink: 0,
            }}
          >
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <div
          style={{
            flex: 1,
            minHeight: 0,
            overflow: 'auto',
            padding: 12,
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
          }}
        >
          {location && (
            <div>
              <SectionLabel t={t}>source</SectionLabel>
              <div style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 11, color: t.textMuted, wordBreak: 'break-all' }}>
                {location}
              </div>
              {d.module && (
                <div style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 11, color: t.textDim, marginTop: 2 }}>
                  module: {d.module}
                </div>
              )}
            </div>
          )}

          {d.metadata && Object.keys(d.metadata).length > 0 && (
            <div>
              <SectionLabel t={t}>metadata</SectionLabel>
              <pre style={codeStyle(t)}>{JSON.stringify(d.metadata, null, 2)}</pre>
            </div>
          )}

          {d.code && (
            <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
              <SectionLabel t={t}>code</SectionLabel>
              <pre style={{ ...codeStyle(t), flex: 1, minHeight: 0, maxHeight: 'none' }}>{d.code}</pre>
            </div>
          )}

          {d.tools && d.tools.length > 0 && (
            <div>
              <SectionLabel t={t}>bound tools</SectionLabel>
              {d.tools.map((tool, i) => (
                <details
                  key={tool.name ?? i}
                  open={d.tools!.length === 1}
                  style={{
                    marginBottom: 8,
                    border: `1px solid ${t.border}`,
                    borderRadius: 6,
                    background: t.bgSidebar,
                    padding: '6px 8px',
                  }}
                >
                  <summary style={{ cursor: 'pointer', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 11.5, color: t.textPrimary }}>
                    {tool.name ?? '(unnamed tool)'}
                  </summary>
                  {tool.description && (
                    <div style={{ fontSize: 11, color: t.textMuted, margin: '6px 0 4px', lineHeight: 1.5 }}>
                      {tool.description}
                    </div>
                  )}
                  {tool.file && (
                    <div style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 10.5, color: t.textDim, marginBottom: 4 }}>
                      {tool.file}
                      {tool.start_line != null ? `:${tool.start_line}` : ''}
                    </div>
                  )}
                  {tool.code && <pre style={codeStyle(t)}>{tool.code}</pre>}
                </details>
              ))}
            </div>
          )}

          {!hasContent && (
            <div style={{ fontSize: 11.5, color: t.textDim, lineHeight: 1.5 }}>
              {kind === 'start' || kind === 'end'
                ? 'Graph boundary marker — no user code to show.'
                : 'No source metadata available for this node.'}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

export function GraphCanvas() {
  return (
    <ReactFlowProvider>
      <GraphCanvasInner />
    </ReactFlowProvider>
  );
}
