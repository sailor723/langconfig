/**
 * Network diagram for the active Neo4j database.
 *
 * Reads `dbSummary.network_diagram` from the store (populated by the
 * existing GET /api/graph-studio/databases/neo4j-summary endpoint).
 * One supernode per label (collapsed by default); one edge per
 * (label_a)-[:REL]->(label_b) group with the rel count as edge label.
 *
 * Generic: never references specific label or rel-type names.
 */
import { useEffect, useMemo, useState } from 'react';
import ReactFlow, {
  Background,
  BackgroundVariant,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  Position,
  ReactFlowProvider,
  getBezierPath,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type NodeProps,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { studio, useStudioState } from './studioStore';
import { subscribeSchemaFilter } from './SchemaViewToolbar';
import type {
  LabelNode as LabelNodeType,
  Neo4jNetworkDiagram,
  RelEdge,
} from './api';

const NODE_WIDTH = 180;
const NODE_HEIGHT = 64;
const CIRCLE_RADIUS = 220;
const CIRCLE_OFFSET_X = 40;
const CIRCLE_OFFSET_Y = 40;

interface LabelNodeData {
  label: LabelNodeType;
  selected: boolean;
}
type LabelNodeProps = NodeProps<LabelNodeData>;

function LabelSupernode({ data }: LabelNodeProps) {
  const t = useLayoutTokens();
  const { label, selected } = data;
  return (
    <div
      style={{
        width: NODE_WIDTH,
        minHeight: NODE_HEIGHT,
        padding: '10px 12px',
        background: t.bgSidebar,
        border: `1px solid ${selected ? t.accent : t.border}`,
        borderRadius: 8,
        boxShadow: selected ? `0 0 0 2px ${t.accentMuted}` : 'none',
        fontFamily: 'inherit',
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <span style={{ fontSize: 12, fontWeight: 600, color: t.textPrimary }}>
          {label.name}
        </span>
        <span style={{ fontSize: 10, color: t.textDim }}>
          {label.count.toLocaleString()} nodes
        </span>
      </div>
      <div
        style={{
          fontSize: 10,
          color: t.textMuted,
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
        title={label.properties.join(', ')}
      >
        {label.properties.length === 0
          ? '(no properties)'
          : label.properties.slice(0, 4).join(' · ')}
        {label.properties.length > 4
          ? ` …+${label.properties.length - 4}`
          : ''}
      </div>
      <Handle
        type="target"
        position={Position.Left}
        style={{ background: t.textDim, width: 5, height: 5 }}
      />
      <Handle
        type="source"
        position={Position.Right}
        style={{ background: t.textDim, width: 5, height: 5 }}
      />
    </div>
  );
}

const nodeTypes = { neo4jLabel: LabelSupernode };

/**
 * Custom edge that respects `data.labelYOffset` so parallel edges between
 * the same node pair (e.g. Person->Movie ACTED_IN/DIRECTED/PRODUCED/...)
 * don't all stack their labels on the same point.
 *
 * Why a custom edge instead of the default `default` (Bezier) edge:
 * ReactFlow's BezierEdge IGNORES the `labelY` prop and always places
 * the label at the bezier midpoint. The fix is to compute the bezier
 * path ourselves, then use BaseEdge with an explicit `labelY` that
 * accounts for our offset.
 */
function SchemaEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style,
  markerEnd,
  data,
  label,
  labelStyle,
  labelBgStyle,
  labelBgPadding,
}: EdgeProps) {
  const offsetY = (data && typeof data === 'object' && 'labelYOffset' in data
    ? Number((data as { labelYOffset?: number }).labelYOffset)
    : 0) || 0;

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    curvature: 0,
  });

  const finalLabelY = (labelY ?? 0) + offsetY;

  return (
    <BaseEdge
      id={id}
      path={edgePath}
      labelX={labelX}
      labelY={finalLabelY}
      label={label as string | undefined}
      labelStyle={labelStyle}
      labelShowBg
      labelBgStyle={labelBgStyle}
      labelBgPadding={labelBgPadding}
      style={style}
      markerEnd={markerEnd}
    />
  );
}

const edgeTypes = { schemaEdge: SchemaEdge };

/**
 * Circular layout for small label sets (<= 12). For larger sets, falls
 * back to a two-ring layout (high-degree outer, low-degree inner).
 *
 * No force simulation — labels are "buckets" not individual nodes, so a
 * circular arrangement reads better than physics-jiggled positions.
 */
function computeNeo4jLayout(
  diag: Neo4jNetworkDiagram
): Record<string, { x: number; y: number }> {
  const labels = diag.label_nodes;
  const positions: Record<string, { x: number; y: number }> = {};
  if (labels.length === 0) return positions;

  // Degree per label (in + out rels).
  const deg: Record<string, number> = Object.fromEntries(
    labels.map((l) => [l.name, 0])
  );
  for (const r of diag.rel_edges) {
    deg[r.from_label] = (deg[r.from_label] ?? 0) + 1;
    deg[r.to_label] = (deg[r.to_label] ?? 0) + 1;
  }
  // Sort by degree desc; place the most-connected label at top.
  const sorted = [...labels].sort(
    (a, b) => (deg[b.name] ?? 0) - (deg[a.name] ?? 0)
  );

  const cx = CIRCLE_OFFSET_X + CIRCLE_RADIUS;
  const cy = CIRCLE_OFFSET_Y + CIRCLE_RADIUS;

  if (sorted.length <= 12) {
    sorted.forEach((l, i) => {
      const angle = (i / sorted.length) * Math.PI * 2 - Math.PI / 2;
      positions[l.name] = {
        x: cx + CIRCLE_RADIUS * Math.cos(angle) - NODE_WIDTH / 2,
        y: cy + CIRCLE_RADIUS * Math.sin(angle) - NODE_HEIGHT / 2,
      };
    });
  } else {
    // Two-ring layout: high-degree outer, low-degree inner.
    const half = Math.ceil(sorted.length / 2);
    const outer = sorted.slice(0, half);
    const inner = sorted.slice(half);
    outer.forEach((l, i) => {
      const angle = (i / outer.length) * Math.PI * 2 - Math.PI / 2;
      positions[l.name] = {
        x: cx + CIRCLE_RADIUS * Math.cos(angle) - NODE_WIDTH / 2,
        y: cy + CIRCLE_RADIUS * Math.sin(angle) - NODE_HEIGHT / 2,
      };
    });
    const innerR = CIRCLE_RADIUS * 0.45;
    inner.forEach((l, i) => {
      const angle = (i / inner.length) * Math.PI * 2 - Math.PI / 2;
      positions[l.name] = {
        x: cx + innerR * Math.cos(angle) - NODE_WIDTH / 2,
        y: cy + innerR * Math.sin(angle) - NODE_HEIGHT / 2,
      };
    });
  }
  return positions;
}

/** Group rels by (from_label, to_label) so parallel edges between the
 *  same node pair get distinct curvature values AND distinct label
 *  positions — otherwise they stack on top of each other and visually
 *  merge into one fat line, hiding all but the topmost label. */
function _groupKey(r: RelEdge): string {
  return r.from_label === r.to_label
    ? `loop:${r.from_label}:${r.type}`      // self-loop: one per type
    : `${r.from_label}->${r.to_label}`;      // all parallel edges together
}

/**
 * Compute a perpendicular offset for the label of a parallel edge so
 * each label lands on its own visual lane. Without this, multiple
 * Person→Movie edges (ACTED_IN, DIRECTED, PRODUCED, WROTE, REVIEWED)
 * all sit at the same midpoint and obscure each other.
 *
 * `labelOffset` is in pixels along the Y axis (assumes left→right
 * source→target). For self-loops we apply a circular offset instead.
 */
function _labelOffsetFor(r: RelEdge, idx: number, groupSize: number): { labelX?: number; labelY?: number } {
  if (r.from_label === r.to_label) {
    // Self-loop: rotate around the source node. idx=0 -> top, others
    // fan out below. We achieve this with a curved path plus a label
    // offset. For simplicity, leave self-loop labels at default position.
    return {};
  }
  if (groupSize <= 1) return {};
  // Symmetric Y offset: step=22px gives readable spacing for label height ~14px.
  const step = 22;
  const center = (groupSize - 1) / 2;
  const dy = (idx - center) * step;
  return { labelY: dy };
}

function buildEdges(
  rels: RelEdge[],
  labelExists: (name: string) => boolean,
  t: ReturnType<typeof useLayoutTokens>
): Edge[] {
  // First pass: group by parallel-edge key. Each group gets a stable
  // 0..n-1 index assigned IN ORDER OF APPEARANCE. We use a counter map
  // that's incremented per group, so each edge in the group gets a
  // distinct index that matches its position in the original array.
  const filtered = rels.filter(
    (r) => labelExists(r.from_label) && labelExists(r.to_label)
  );
  const groupSize: Record<string, number> = {};
  for (const r of filtered) {
    const k = _groupKey(r);
    groupSize[k] = (groupSize[k] ?? 0) + 1;
  }

  // The map below is a counter — read+increment per edge, so each
  // group yields idx 0, 1, 2, ... in order. (Previous version tried to
  // do this in two passes but groupIndex[key] held the FINAL value
  // after the pass, not the per-edge value, so all edges got idx=last.)
  const groupCounter: Record<string, number> = {};

  return filtered.map((r, i) => {
    const key = _groupKey(r);
    const n = groupSize[key];
    const idx = groupCounter[key] ?? 0;
    groupCounter[key] = idx + 1;

    // Spread parallel edges with distinct curvature values so they don't
    // all stack at the same Bezier control point.
    let curvature = 0;
    if (n > 1) {
      const step = 0.4;
      const center = (n - 1) / 2;
      curvature = (idx - center) * step;
    }

    // ALSO spread the label position perpendicular to the edge so labels
    // for parallel edges don't overlap. labelY is in pixels relative to
    // the edge midpoint.
    const labelOffset = _labelOffsetFor(r, idx, n);

    return {
      id: `rel:${r.from_label}-${r.type}->${r.to_label}#${i}`,
      source: r.from_label,
      target: r.to_label,
      // Custom edge component (see SchemaEdge above). It renders a
      // Bezier path then explicitly applies data.labelYOffset so labels
      // for parallel edges (e.g. 5x Person->Movie) sit on separate
      // visual lanes instead of stacking at the same midpoint.
      type: 'schemaEdge',
      animated: false,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: '#22c55e',
        width: 14,
        height: 14,
      },
      style: { stroke: '#22c55e', strokeWidth: 1.4, opacity: 0.75 },
      // Self-loops: render the type only.
      label:
        r.from_label === r.to_label
          ? `:${r.type} (${r.count.toLocaleString()})`
          : `:${r.type}  (${r.count.toLocaleString()})`,
      labelStyle: {
        fontSize: 10,
        fill: t.textMuted,
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      },
      labelBgStyle: { fill: t.bgSidebar, fillOpacity: 0.85 },
      labelBgPadding: [4, 2] as [number, number],
      // labelYOffset is read by SchemaEdge and applied on top of the
      // auto-computed labelY (which sits on the path midpoint).
      data: { kind: 'rel', rel: r, labelYOffset: labelOffset.labelY ?? 0 },
    };
  });
}

function Neo4jNetworkInner() {
  const t = useLayoutTokens();
  const { dbSummary, activeNodeId } = useStudioState();
  const { fitView } = useReactFlow();
  const diag: Neo4jNetworkDiagram | null =
    dbSummary?.network_diagram ?? null;

  const [filter, setFilter] = useState('');

  // Subscribe to the toolbar's filter input.
  useEffect(() => {
    return subscribeSchemaFilter((q) => setFilter(q));
  }, []);

  const filteredLabels = useMemo(() => {
    if (!diag) return [];
    if (!filter.trim()) return diag.label_nodes;
    const f = filter.trim().toLowerCase();
    return diag.label_nodes.filter(
      (l) =>
        l.name.toLowerCase().includes(f) ||
        l.properties.some((p) => p.toLowerCase().includes(f))
    );
  }, [diag, filter]);

  const labelExists = useMemo(() => {
    const s = new Set<string>(filteredLabels.map((l) => l.name));
    return (n: string) => s.has(n);
  }, [filteredLabels]);

  const [nodes, setNodes, onNodesChange] = useNodesState<LabelNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<{
    kind: 'rel';
    rel: RelEdge;
  }>([]);

  // Lay out whatever set of labels is visible. Hide edges that touch a
  // filtered-out label so the diagram stays coherent.
  const layoutInput = useMemo(
    () =>
      diag
        ? {
            ...diag,
            label_nodes: filteredLabels.length
              ? filteredLabels
              : diag.label_nodes,
          }
        : null,
    [diag, filteredLabels]
  );
  const positions = useMemo(
    () => (layoutInput ? computeNeo4jLayout(layoutInput) : {}),
    [layoutInput]
  );

  // Derive nodes/edges with useMemo so ReactFlow's internal StoreUpdater
  // doesn't trigger a re-render -> setNodes -> re-render loop on every
  // render. Same fix as ErDiagram.tsx — see that file for the explanation.
  const reactFlowNodes = useMemo(() => {
    if (!diag) return [];
    return filteredLabels.map((l) => ({
      id: l.name,
      type: 'neo4jLabel',
      position: positions[l.name] ?? { x: 40, y: 40 },
      data: { label: l, selected: activeNodeId === l.name },
    }));
  }, [diag, filteredLabels, positions, activeNodeId]);

  const reactFlowEdges = useMemo(() => {
    if (!diag) return [];
    return buildEdges(diag.rel_edges, labelExists, t);
    // t is read for the edge label color but is stable at runtime;
    // including it would re-create edges on every render and re-trigger
    // the loop above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [diag, labelExists]);

  // Sync the derived arrays into ReactFlow's state only when they change.
  useEffect(() => {
    setNodes(reactFlowNodes);
  }, [reactFlowNodes, setNodes]);

  useEffect(() => {
    setEdges(reactFlowEdges);
  }, [reactFlowEdges, setEdges]);

  // Fit view on first render and on filter changes.
  useEffect(() => {
    if (!diag || reactFlowNodes.length === 0) return;
    const timer = setTimeout(
      () => fitView({ padding: 0.18, duration: 250 }),
      60
    );
    return () => clearTimeout(timer);
  }, [diag, filteredLabels, reactFlowNodes.length, fitView]);

  if (!diag) {
    return (
      <div
        style={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: t.textDim,
          fontSize: 13,
          padding: 24,
          textAlign: 'center',
        }}
      >
        {dbSummary == null
          ? 'Loading graph…'
          : 'Network view unavailable. The active database could not be introspected.'}
      </div>
    );
  }

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      onNodeClick={(_, node) => studio.selectNode(node.id)}
      fitView
      minZoom={0.15}
      maxZoom={2}
      proOptions={{ hideAttribution: true }}
    >
      <Background
        color={t.border}
        gap={24}
        variant={BackgroundVariant.Dots}
        style={{ opacity: 0.35 }}
      />
      {/* bottom-right so the legend overlay (rendered by GraphCanvas) in
          bottom-left doesn't collide with the zoom controls. */}
      <Controls showInteractive={false} position="bottom-right" />
    </ReactFlow>
  );
}

export function Neo4jNetwork() {
  return (
    <ReactFlowProvider>
      <Neo4jNetworkInner />
    </ReactFlowProvider>
  );
}