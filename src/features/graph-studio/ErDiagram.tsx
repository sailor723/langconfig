/**
 * ER diagram for the active Postgres database.
 *
 * Reads `dbSummary.er_diagram` from the store (populated by the existing
 * GET /api/graph-studio/databases/summary endpoint via the backend patch).
 * Renders one node per table with its column list inside; one edge per FK.
 *
 * Generic: never references specific table or column names. Works on any
 * Postgres schema the user has connected.
 */
import { useEffect, useMemo, useState } from 'react';
import ReactFlow, {
  Background,
  BackgroundVariant,
  BaseEdge,
  Controls,
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
import {
  subscribeSchemaFilter,
} from './SchemaViewToolbar';
import type {
  ErDiagram as ErDiagramType,
  ForeignKey,
  TableNode as TableNodeType,
  TableColumn,
} from './api';

const TABLE_NODE_WIDTH = 240;
const TABLE_NODE_HEIGHT_PER_ROW = 22;
const TABLE_NODE_HEADER = 32;
const COLUMN_GAP_X = 280;
const COLUMN_GAP_Y = 32;
const LAYER_OFFSET = 40;

interface TableNodeData {
  table: TableNodeType;
  selected: boolean;
}
type TableNodeProps = NodeProps<TableNodeData>;

function TableCard({ data }: TableNodeProps) {
  const t = useLayoutTokens();
  const { table, selected } = data;
  const cols = table.columns;
  const height =
    TABLE_NODE_HEADER +
    Math.max(1, cols.length) * TABLE_NODE_HEIGHT_PER_ROW;
  return (
    <div
      style={{
        width: TABLE_NODE_WIDTH,
        minHeight: height,
        background: t.bgSidebar,
        border: `1px solid ${selected ? t.accent : t.border}`,
        borderRadius: 6,
        boxShadow: selected ? `0 0 0 2px ${t.accentMuted}` : 'none',
        fontFamily: 'inherit',
        overflow: 'hidden',
      }}
    >
      {/* Header: table name + row count */}
      <div
        style={{
          padding: '6px 10px',
          background: t.bgTabBar,
          borderBottom: `1px solid ${t.border}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <span style={{ fontSize: 12, fontWeight: 600, color: t.textPrimary }}>
          {table.name}
        </span>
        <span style={{ fontSize: 10, color: t.textDim }}>
          {table.row_count == null
            ? '— rows'
            : `${table.row_count.toLocaleString()} rows`}
        </span>
      </div>
      {/* Columns */}
      <div>
        {cols.length === 0 ? (
          <div
            style={{
              padding: '6px 10px',
              fontSize: 10.5,
              color: t.textDim,
              fontStyle: 'italic',
            }}
          >
            no columns
          </div>
        ) : (
          cols.map((c) => <ColumnRow key={c.name} col={c} />)
        )}
      </div>
      {/* ReactFlow handles — only on the side, columns are the "ports". */}
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

function ColumnRow({ col }: { col: TableColumn }) {
  const t = useLayoutTokens();
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '4px 10px',
        fontSize: 11,
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
        borderTop: `1px solid ${t.border}11`,
        background: col.pk ? `${t.accent}11` : 'transparent',
        color: t.textPrimary,
      }}
      title={`${col.name} ${col.type}${col.pk ? ' PK' : ''}${
        col.nullable ? '' : ' NOT NULL'
      }`}
    >
      <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        {col.pk && (
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: t.accent,
              flexShrink: 0,
            }}
            title="Primary key"
          />
        )}
        <span>{col.name}</span>
      </span>
      <span
        style={{ fontSize: 10, color: t.textDim, whiteSpace: 'nowrap' }}
      >
        {col.type}
      </span>
    </div>
  );
}

const nodeTypes = { erTable: TableCard };

/**
 * Custom edge that respects `data.labelYOffset` so parallel FKs (e.g.
 * track -> album / track -> genre / track -> mediatype) don't all stack
 * their labels on the same point.
 *
 * Same approach as SchemaEdge in Neo4jNetwork: compute the bezier path
 * ourselves, then use BaseEdge with explicit labelX/labelY so the
 * default BezierEdge's auto-label-at-midpoint behavior doesn't override
 * our offset.
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
 * Hierarchical layered layout for ER diagrams:
 * - Compute in-degree per table = number of incoming FKs.
 * - Roots = tables with no incoming FKs.
 * - Layer per node = longest path from any root to it (FK dependency depth).
 * - Within a layer, stack vertically.
 * - Tables with no FKs at all form their own "isolated" cluster at layer 0.
 */
function computeErLayout(
  diag: ErDiagramType
): Record<string, { x: number; y: number }> {
  const tableNames = diag.tables.map((t) => t.name);
  const incoming: Record<string, number> = Object.fromEntries(
    tableNames.map((n) => [n, 0])
  );
  for (const fk of diag.foreign_keys) {
    incoming[fk.to_table] = (incoming[fk.to_table] ?? 0) + 1;
  }

  // Forward adjacency from FK edges.
  const adj: Record<string, string[]> = Object.fromEntries(
    tableNames.map((n) => [n, []])
  );
  for (const fk of diag.foreign_keys) {
    if (adj[fk.from_table]) adj[fk.from_table].push(fk.to_table);
  }

  // Layer per node = longest path from any root.
  const layer: Record<string, number> = {};
  function visit(n: string, depth: number, stack: Set<string>): void {
    if (stack.has(n)) return; // cycle guard
    stack.add(n);
    layer[n] = Math.max(layer[n] ?? 0, depth);
    for (const t of adj[n] ?? []) visit(t, depth + 1, stack);
    stack.delete(n);
  }
  const stack = new Set<string>();
  const roots = tableNames.filter((n) => incoming[n] === 0);
  for (const r of roots) visit(r, 0, stack);
  // Isolated tables (no FKs at all) land in layer 0.
  for (const n of tableNames) if (layer[n] == null) layer[n] = 0;

  // Group by layer.
  const groups: Record<number, string[]> = {};
  for (const n of tableNames) {
    const l = layer[n];
    (groups[l] ??= []).push(n);
  }
  const maxCount = Math.max(
    1,
    ...Object.values(groups).map((g) => g.length)
  );
  const mid = (maxCount - 1) / 2;

  const positions: Record<string, { x: number; y: number }> = {};
  for (const [lStr, ids] of Object.entries(groups)) {
    const l = Number(lStr);
    ids.forEach((id, i) => {
      positions[id] = {
        x: LAYER_OFFSET + l * COLUMN_GAP_X,
        y: LAYER_OFFSET + (i - mid) * COLUMN_GAP_Y,
      };
    });
  }
  return positions;
}

/**
 * For a parallel-FK group (n edges from same source to same target),
 * compute a Y offset for the edge label so each label lands on its own
 * lane. Without this, e.g. track->album / track->genre / track->mediatype
 * all stack at the same midpoint and obscure each other.
 */
function _fkLabelOffset(idx: number, n: number): { labelY: number } {
  if (n <= 1) return { labelY: 0 };
  const step = 22; // px — readable for ~14px-tall labels
  const center = (n - 1) / 2;
  return { labelY: (idx - center) * step };
}

function buildEdges(
  fks: ForeignKey[],
  tableExists: (name: string) => boolean,
  t: ReturnType<typeof useLayoutTokens>
): Edge[] {
  // Filter + group parallel FKs (same from_table -> to_table) so each
  // one gets its own visual lane via curvature AND a labelY offset.
  // Without this, multiple FKs from the same table to the same target
  // (e.g. track -> album, track -> genre, track -> mediatype) all stack
  // on top of each other and visually merge into one fat line.
  const filtered = fks.filter(
    (fk) => tableExists(fk.from_table) && tableExists(fk.to_table)
  );
  const groupSize: Record<string, number> = {};
  for (const fk of filtered) {
    const k = `${fk.from_table}->${fk.to_table}`;
    groupSize[k] = (groupSize[k] ?? 0) + 1;
  }

  // Counter map — incremented per edge, so each edge in a parallel
  // group gets a distinct 0..n-1 index matching its position in the
  // original array. (Previous version built groupIndex in a second
  // pass and then read its FINAL value at map time, so every edge
  // ended up at the last index — same bug we fixed in Neo4jNetwork.)
  const groupCounter: Record<string, number> = {};

  return filtered.map((fk, i) => {
    const key = `${fk.from_table}->${fk.to_table}`;
    const n = groupSize[key];
    const idx = groupCounter[key] ?? 0;
    groupCounter[key] = idx + 1;

    // Spread parallel edges with distinct curvature values so the curves
    // themselves don't overlap.
    let curvature = 0;
    if (n > 1) {
      const step = 0.4;
      const center = (n - 1) / 2;
      curvature = (idx - center) * step;
    }

    // ALSO offset the label perpendicular to the edge so labels for
    // parallel edges don't sit at the same midpoint.
    const { labelY } = _fkLabelOffset(idx, n);

    return {
      id: `fk:${fk.constraint_name}#${i}`,
      source: fk.from_table,
      target: fk.to_table,
      // Custom edge component (see SchemaEdge above). It renders a
      // Bezier path then explicitly applies data.labelYOffset so labels
      // for parallel FKs sit on separate visual lanes.
      type: 'schemaEdge',
      animated: false,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: t.accent,
        width: 14,
        height: 14,
      },
      style: {
        stroke: '#22c55e',
        strokeWidth: 1.4,
        opacity: 0.75,
      },
      label: `${fk.from_column} → ${fk.to_column}`,
      labelStyle: {
        fontSize: 10,
        fill: t.textMuted,
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      },
      labelBgStyle: { fill: t.bgSidebar, fillOpacity: 0.85 },
      labelBgPadding: [4, 2] as [number, number],
      // labelYOffset is read by SchemaEdge and applied on top of the
      // auto-computed labelY (which sits on the path midpoint).
      data: { kind: 'fk', fk, labelYOffset: labelY },
    };
  });
}

function ErDiagramInner() {
  const t = useLayoutTokens();
  const { dbSummary, activeNodeId } = useStudioState();
  const { fitView } = useReactFlow();
  const diag: ErDiagramType | null = dbSummary?.er_diagram ?? null;

  const [filter, setFilter] = useState('');

  // Subscribe to the toolbar's filter input.
  useEffect(() => {
    return subscribeSchemaFilter((q) => setFilter(q));
  }, []);

  const filteredTables = useMemo(() => {
    if (!diag) return [];
    if (!filter.trim()) return diag.tables;
    const f = filter.trim().toLowerCase();
    return diag.tables.filter(
      (tbl) =>
        tbl.name.toLowerCase().includes(f) ||
        tbl.columns.some((c) => c.name.toLowerCase().includes(f))
    );
  }, [diag, filter]);

  // Lay out whatever set of tables is visible. When the filter hides
  // everything, fall back to the full set so the layout doesn't collapse.
  const layoutInput = useMemo(
    () =>
      diag
        ? {
            ...diag,
            tables: filteredTables.length ? filteredTables : diag.tables,
          }
        : null,
    [diag, filteredTables]
  );
  const positions = useMemo(
    () => (layoutInput ? computeErLayout(layoutInput) : {}),
    [layoutInput]
  );

  const [nodes, setNodes, onNodesChange] = useNodesState<TableNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<{
    kind: 'fk';
    fk: ForeignKey;
  }>([]);

  // Derive the nodes/edges arrays with useMemo so they only get a new
  // reference when the underlying inputs actually change. ReactFlow's
  // internal StoreUpdater does `useEffect([nodes], setStoreState)` — if we
  // hand it a fresh array on every render, the store update triggers a
  // re-render which calls setNodes again with another fresh array…
  // infinite loop. useMemo fixes that.
  const reactFlowNodes = useMemo(() => {
    if (!diag) return [];
    return filteredTables.map((tbl) => ({
      id: tbl.name,
      type: 'erTable',
      position: positions[tbl.name] ?? { x: 40, y: 40 },
      data: { table: tbl, selected: activeNodeId === tbl.name },
    }));
  }, [diag, filteredTables, positions, activeNodeId]);

  const reactFlowEdges = useMemo(() => {
    if (!diag) return [];
    const tableSet = new Set(filteredTables.map((t2) => t2.name));
    return buildEdges(
      diag.foreign_keys.filter(
        (fk) => tableSet.has(fk.from_table) && tableSet.has(fk.to_table)
      ),
      (n) => tableSet.has(n),
      t
    );
    // t is read here but is stable across renders (useLayoutTokens returns
    // memoized refs); including it would re-create edges on every render
    // and re-trigger the loop above. Acceptable to omit because tokens
    // don't change at runtime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [diag, filteredTables]);

  // Sync the derived arrays into ReactFlow's state only when they change.
  useEffect(() => {
    setNodes(reactFlowNodes);
  }, [reactFlowNodes, setNodes]);

  useEffect(() => {
    setEdges(reactFlowEdges);
  }, [reactFlowEdges, setEdges]);

  // Fit view when the diagram first renders / when filter changes.
  useEffect(() => {
    if (!diag || reactFlowNodes.length === 0) return;
    const timer = setTimeout(
      () => fitView({ padding: 0.18, duration: 250 }),
      60
    );
    return () => clearTimeout(timer);
  }, [diag, filteredTables, nodes.length, fitView]);

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
          ? 'Loading schema…'
          : 'Schema view unavailable. The active database could not be introspected.'}
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
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

export function ErDiagram() {
  return (
    <ReactFlowProvider>
      <ErDiagramInner />
    </ReactFlowProvider>
  );
}