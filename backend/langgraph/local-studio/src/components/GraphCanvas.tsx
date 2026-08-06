/**
 * Graph canvas: renders a LangGraph spec (nodes + edges) with React Flow.
 * - BFS layered layout, user-toggleable direction (lr / tb).
 * - Nodes are draggable; dragged positions survive stream updates.
 * - During a run, the currently-executing node pulses, executed nodes glow,
 *   and traversed edges animate — all driven by `updates` stream events.
 * - Conditional edges stay dotted/amber so they remain visually distinct.
 */
import { useEffect } from 'react'
import {
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useNodesState,
  useEdgesState,
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { MoveHorizontal, MoveVertical } from 'lucide-react'
import { useStudioStore } from '@/store/studioStore'
import type { GraphSpec } from '@/api/client'

type NodeKind = 'start' | 'end' | 'tool' | 'node'
type Direction = 'lr' | 'tb'

interface GraphNodeData extends Record<string, unknown> {
  label: string
  kind: NodeKind
  /** True if this node executed during the current run */
  active: boolean
  /** True if this node is executing right now (last node in runPath) */
  current: boolean
  direction: Direction
}

interface FlowEdgeData extends Record<string, unknown> {
  /** The spec's original conditional flag (kept so styling survives streaming) */
  conditional: boolean
}

const LAYER_GAP = 240
const IN_LAYER_GAP = 110

// Three named columns matching sql_agent_graph.png:
//   spine: the linear preamble chain + generate_query (vertical in tb)
//   side:  generate_query's fan-out (check_query / memory_tools / __end__)
//   loop:  run_query drops below generate_query in the spine column
// The runtime layout (computeLayout below) places nodes by name; any
// unrecognised node (e.g. extras in other graphs) falls into a fallback
// column past the named ones.
const PNG_LAYOUT = {
  spine: [
    '__start__',
    'list_tables',
    'call_get_schema',
    'get_schema',
    'generate_query',
  ],
  side: ['check_query', 'memory_tools', '__end__'],
  loop: ['run_query'],
} as const

// Edge styles: traversed = teal animated; conditional = amber dotted; else gray
const ACTIVE_EDGE = { stroke: '#2dd4bf', strokeWidth: 2 }
const CONDITIONAL_EDGE = { stroke: '#e8a33d', strokeWidth: 1.5, strokeDasharray: '5 4' }
const DEFAULT_EDGE = { stroke: '#3a4250', strokeWidth: 1.2 }

// Three-column layout matching sql_agent_graph.png exactly:
//   spine (left, vertical): __start__ → list_tables → call_get_schema →
//     get_schema → generate_query (then run_query drops below)
//   side  (right of generate_query, vertical):
//     check_query / memory_tools / __end__
//   loop: run_query is below generate_query in the spine column; the
//     run_query → generate_query edge closes back upward.
//
// In tb mode the spine flows top→bottom (Top/Bottom handles). In lr mode
// the same chain flows left→right (Left/Right handles) — we transpose.
function computeLayout(
  spec: GraphSpec,
  direction: Direction,
): { nodes: Node<GraphNodeData>[]; edges: Edge<FlowEdgeData>[] } {
  const isTb = direction === 'tb'
  const step = isTb ? LAYER_GAP : IN_LAYER_GAP
  const sideStep = isTb ? LAYER_GAP : IN_LAYER_GAP
  const sideOffset = step * 1.6

  const position = new Map<string, { x: number; y: number }>()
  const covered = new Set<string>()

  // (along, cross) — tb: along = y, cross = x. lr: along = x, cross = y.
  const placeAlong = (id: string, along: number, cross: number) => {
    position.set(id, isTb ? { x: cross, y: along } : { x: along, y: cross })
    covered.add(id)
  }

  // Geometry constants — node size is 190x46 px (see GraphNodeComponent).
  const NODE_W = 190

  // Spine: spread along the flow axis, fixed on the cross axis (x=40).
  PNG_LAYOUT.spine.forEach((id, i) => {
    placeAlong(id, 40 + i * step, 40)
  })

  // Side column: cross axis fixed at generate_query's x + sideOffset (to
  // the right of the spine); along axis is centred on generate_query's y
  // and the three nodes stack vertically (memory_tools aligned with
  // generate_query, check_query above, __end__ below — matching the PNG).
  const genIndex = PNG_LAYOUT.spine.indexOf('generate_query')
  const genAlong = 40 + genIndex * step
  const sideTotal = (PNG_LAYOUT.side.length - 1) * sideStep
  // sideOffset is the horizontal gap from the spine's right edge to the
  // side column's left edge. Spine nodes are NODE_W wide, so step past it.
  const sideX = 40 + NODE_W + sideOffset
  PNG_LAYOUT.side.forEach((id, i) => {
    placeAlong(id, genAlong + i * sideStep - sideTotal / 2, sideX)
  })

  // Loop: run_query drops below generate_query in tb, sits to its right in lr.
  PNG_LAYOUT.loop.forEach((id) => {
    placeAlong(id, genAlong + step, 40)
  })

  // Fallback: any unknown node gets stacked past the named columns.
  let fallbackIdx = 0
  spec.nodes.forEach((n) => {
    if (!covered.has(n.id)) {
      placeAlong(n.id, 40 + (PNG_LAYOUT.spine.length + 2 + fallbackIdx) * step, 40)
      fallbackIdx += 1
    }
  })

  const kindFor = (id: string): NodeKind => {
    if (id === '__start__') return 'start'
    if (id === '__end__') return 'end'
    return 'node'
  }

  const nodes: Node<GraphNodeData>[] = spec.nodes.map((n) => {
    const pos = position.get(n.id) ?? { x: 0, y: 0 }
    return {
      id: n.id,
      type: 'graphNode',
      position: pos,
      data: {
        label: n.data?.name ?? n.id,
        kind: kindFor(n.id),
        active: false,
        current: false,
        direction,
      },
    }
  })

  const edges: Edge<FlowEdgeData>[] = spec.edges.map((e, i) => {
    // Decide which handle pair to use. Most edges flow along the dominant
    // axis (tb: vertical, lr: horizontal) — those use the axis handles so
    // they line up cleanly with the spine. Cross-axis edges (e.g. the long
    // dashed __start__ -> generate_query, or generate_query -> side nodes)
    // use the cross handles so they exit the box on the correct side.
    const sourcePos = position.get(e.source)
    const targetPos = position.get(e.target)
    const sameRow = sourcePos && targetPos && isTb
      ? Math.abs(sourcePos.y - targetPos.y) < 5
      : sourcePos && targetPos && Math.abs(sourcePos.x - targetPos.x) < 5
    const crossAxis = e.conditional || sameRow
    return {
      id: `e-${i}-${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      sourceHandle: crossAxis ? 's-cross' : 's-axis',
      targetHandle: crossAxis ? 't-cross' : 't-axis',
      type: 'smoothstep',
      data: { conditional: Boolean(e.conditional) },
      style: e.conditional ? CONDITIONAL_EDGE : DEFAULT_EDGE,
    }
  })

  return { nodes, edges }
}

// Edges actually traversed: consecutive pairs in runPath, plus the edge into
// the first executed node from __start__.
function traversedPairs(runPath: string[]): Set<string> {
  const pairs = new Set<string>()
  for (let i = 1; i < runPath.length; i++) {
    pairs.add(`${runPath[i - 1]} -> ${runPath[i]}`)
  }
  if (runPath.length > 0) pairs.add(`__start__ -> ${runPath[0]}`)
  return pairs
}

function GraphNodeComponent({ data, selected }: NodeProps<Node<GraphNodeData>>) {
  const kindStyles: Record<NodeKind, string> = {
    start: 'border-pulse/60 text-pulse',
    end: 'border-signal/60 text-signal',
    tool: 'border-ink-400/60 text-ink-100',
    node: 'border-ink-400/60 text-ink-100',
  }
  const badge: Record<NodeKind, string> = {
    start: 'START',
    end: 'END',
    tool: 'NODE',
    node: 'NODE',
  }
  // Handles on all four sides so React Flow can route long edges around
  // the spine (e.g. __start__ -> generate_query) without overlapping nodes.
  // Direction only controls which pair is used for the dominant flow:
  // tb -> top/bottom, lr -> left/right.
  const isTb = data.direction === 'tb'
  const axisTarget = isTb ? Position.Top : Position.Left
  const axisSource = isTb ? Position.Bottom : Position.Right
  const crossTarget = isTb ? Position.Left : Position.Top
  const crossSource = isTb ? Position.Right : Position.Bottom
  const handleCls = '!bg-ink-400 !w-1.5 !h-1.5 !border-none'

  return (
    <div
      className={`group flex h-[46px] w-[190px] items-center gap-2 rounded-md border bg-ink-850 px-3
        ${kindStyles[data.kind]}
        ${data.current ? 'animate-pulse !border-pulse shadow-glow' : ''}
        ${!data.current && data.active ? '!border-signal/80 shadow-glow' : 'shadow-panel'}
        ${selected ? 'shadow-glow' : ''}
        transition-shadow`}
    >
      <Handle id="t-axis" type="target" position={axisTarget} className={handleCls} />
      <Handle id="t-cross" type="target" position={crossTarget} className={handleCls} />
      <span
        className={`font-mono text-[9px] tracking-[0.14em] px-1.5 py-0.5 rounded-sm border
          ${data.kind === 'start' ? 'border-pulse/50 text-pulse'
            : data.kind === 'end' ? 'border-signal/50 text-signal'
            : 'border-ink-500/60 text-ink-300'}`}
      >
        {badge[data.kind]}
      </span>
      <span className="truncate font-mono text-xs text-ink-50">{data.label}</span>
      <Handle id="s-axis" type="source" position={axisSource} className={handleCls} />
      <Handle id="s-cross" type="source" position={crossSource} className={handleCls} />
    </div>
  )
}

const nodeTypes = { graphNode: GraphNodeComponent }

// Fit options shared by every (re)fit call
const FIT_OPTIONS = { padding: 0.25, maxZoom: 1.25, duration: 350 } as const

/**
 * Inner view (must live inside <ReactFlowProvider> to use useReactFlow).
 * - Layout is (re)computed only when the graph or direction changes, so
 *   manually dragged node positions survive stream updates.
 * - Stream updates only re-style existing nodes/edges (active/current).
 */
function GraphView() {
  const graph = useStudioStore((s) => s.graph)
  const direction = useStudioStore((s) => s.direction)
  const runPath = useStudioStore((s) => s.runPath)
  const running = useStudioStore((s) => s.running)
  const { fitView } = useReactFlow()

  const [nodes, setNodes, onNodesChange] = useNodesState<Node<GraphNodeData>>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge<FlowEdgeData>>([])

  // Recompute layout on graph/direction change (dragged positions reset here)
  useEffect(() => {
    if (!graph) return
    const { nodes: layoutNodes, edges: layoutEdges } = computeLayout(graph, direction)
    setNodes(layoutNodes)
    setEdges(layoutEdges)
    // Small delay lets React Flow measure the new nodes before fitting
    const timer = setTimeout(() => fitView(FIT_OPTIONS), 60)
    return () => clearTimeout(timer)
  }, [graph, direction, setNodes, setEdges, fitView])

  // Stream updates: re-style existing nodes/edges without moving them
  useEffect(() => {
    const currentId = running ? runPath[runPath.length - 1] : undefined
    setNodes((nds) =>
      nds.map((n) => ({
        ...n,
        data: {
          ...n.data,
          active: runPath.includes(n.id),
          current: n.id === currentId,
        },
      })),
    )

    const pairs = traversedPairs(runPath)
    setEdges((eds) =>
      eds.map((e) => {
        const isActive = pairs.has(`${e.source} -> ${e.target}`)
        return {
          ...e,
          animated: isActive,
          style: isActive
            ? ACTIVE_EDGE
            : e.data?.conditional
              ? CONDITIONAL_EDGE
              : DEFAULT_EDGE,
        }
      }),
    )
  }, [runPath, running, setNodes, setEdges])

  useEffect(() => {
    const onResize = () => fitView(FIT_OPTIONS)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [fitView])

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      minZoom={0.1}
      maxZoom={1.8}
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#232830" />
      <Controls
        position="bottom-right"
        className="!border-ink-600 !bg-ink-850 [&>button]:!border-ink-600 [&>button]:!bg-ink-850 [&>button]:!text-ink-200 [&>button:hover]:!bg-ink-700"
      />
    </ReactFlow>
  )
}

/** Legend explaining node/edge activity colors. */
function ActivityLegend() {
  const runPath = useStudioStore((s) => s.runPath)
  const running = useStudioStore((s) => s.running)
  const hasActivity = runPath.length > 0

  return (
    <div className="absolute bottom-3 left-3 flex flex-col gap-1.5 rounded-md border border-ink-600/70 bg-ink-850/90 px-2.5 py-2 font-mono text-[10px] text-ink-300 shadow-panel backdrop-blur-sm">
      <span className="flex items-center gap-2">
        <span className="h-2 w-2 rounded-full bg-pulse shadow-glow" />
        {running ? 'running node…' : 'current node'}
      </span>
      <span className={`flex items-center gap-2 ${hasActivity ? '' : 'opacity-40'}`}>
        <span className="h-2 w-2 rounded-full bg-signal" />
        executed
      </span>
      <span className="flex items-center gap-2">
        <span className="h-0 w-4 border-t-2 border-dashed border-[#e8a33d]" />
        conditional edge
      </span>
      <span className="flex items-center gap-2">
        <span className="h-0 w-4 border-t-2 border-solid border-ink-500" />
        regular edge
      </span>
    </div>
  )
}

export default function GraphCanvas() {
  const direction = useStudioStore((s) => s.direction)
  const toggleDirection = useStudioStore((s) => s.toggleDirection)

  return (
    <div className="relative h-full w-full dot-grid bg-ink-900">
      <ReactFlowProvider>
        <GraphView />
      </ReactFlowProvider>
      <ActivityLegend />
      {/* Layout direction toggle (lr <-> tb) */}
      <button
        type="button"
        onClick={toggleDirection}
        title={direction === 'lr' ? 'Switch to vertical layout' : 'Switch to horizontal layout'}
        className="absolute top-3 right-3 z-10 flex h-8 w-8 items-center justify-center rounded-md border border-ink-600 bg-ink-850 text-ink-200 shadow-panel transition-colors hover:bg-ink-700"
      >
        {direction === 'lr' ? <MoveVertical size={15} /> : <MoveHorizontal size={15} />}
      </button>
    </div>
  )
}
