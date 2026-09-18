/**
 * WorkflowEditor — a minimal ReactFlow canvas for editing a workflow.
 *
 * Used as the content component for workflow-type tabs. Each tab gets its
 * own editor instance so users can edit multiple workflows in parallel.
 *
 * Features:
 * - Add nodes (agent/tool)
 * - Drag to connect
 * - Edit node name via inline input
 * - Save → marks tab as dirty
 */
import { useCallback, useState, useRef } from 'react';
import ReactFlow, {
  Node,
  Edge,
  addEdge,
  Controls,
  Background,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  Connection,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useLayoutTokens } from './tokens';
import { ToolbarButton } from './ui-system';
import { Plus, Save, Trash2 } from 'lucide-react';
import type { Tab } from './useLayout';

interface Props {
  tab: Tab;
}

// Simple custom node — displays label and an editable name input
function EditorNode({ data, selected, id }: any) {
  const t = useLayoutTokens();
  return (
    <div
      style={{
        padding: 10,
        background: t.bgBase,
        border: `2px solid ${selected ? t.accent : t.border}`,
        borderRadius: 8,
        minWidth: 180,
        boxShadow: selected ? `0 0 0 2px ${t.accentMuted}` : 'none',
        color: t.textPrimary,
      }}
    >
      <div style={{ fontSize: 10, textTransform: 'uppercase', color: t.textMuted, marginBottom: 4 }}>
        {data.kind ?? 'agent'}
      </div>
      <input
        type="text"
        value={data.name ?? ''}
        placeholder="Node name..."
        onChange={e => data.onChangeName?.(id, e.target.value)}
        style={{
          width: '100%',
          background: t.bgInput,
          border: `1px solid ${t.border}`,
          borderRadius: 4,
          color: t.textPrimary,
          fontSize: 13,
          padding: '4px 6px',
          outline: 'none',
        }}
      />
    </div>
  );
}

const nodeTypes = { editor: EditorNode };

export default function WorkflowEditor({ tab }: Props) {
  const t = useLayoutTokens();
  const wrapperRef = useRef<HTMLDivElement>(null);

  const initialNodes: Node[] = [];
  const initialEdges: Edge[] = [];

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [nodeCounter, setNodeCounter] = useState(0);

  const onConnect = useCallback(
    (params: Connection) => setEdges(eds => addEdge({ ...params, animated: true }, eds)),
    [setEdges]
  );

  const handleAddNode = useCallback((kind: string) => {
    const id = `node-${Date.now()}-${nodeCounter}`;
    const newNode: Node = {
      id,
      type: 'editor',
      position: {
        x: 200 + Math.random() * 200,
        y: 100 + Math.random() * 200,
      },
      data: {
        kind,
        name: `${kind} ${nodeCounter + 1}`,
        onChangeName: (nid: string, name: string) => {
          setNodes(nds => nds.map(n => n.id === nid ? { ...n, data: { ...n.data, name } } : n));
        },
      },
    };
    setNodes(nds => [...nds, newNode]);
    setNodeCounter(c => c + 1);
  }, [nodeCounter, setNodes]);

  const handleDelete = useCallback(() => {
    if (!selectedNodeId) return;
    setNodes(nds => nds.filter(n => n.id !== selectedNodeId));
    setEdges(eds => eds.filter(e => e.source !== selectedNodeId && e.target !== selectedNodeId));
    setSelectedNodeId(null);
  }, [selectedNodeId, setNodes, setEdges]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, color: t.textPrimary }}>
      {/* ── Toolbar ─────────────────────────────────────── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 4,
        padding: '8px 12px',
        borderBottom: `1px solid ${t.border}`,
        background: t.bgBase,
      }}>
        <span style={{ fontSize: 13, fontWeight: 600, marginRight: 8 }}>{tab.label}</span>

        <ToolbarButton onClick={() => handleAddNode('agent')} t={t} title="Add agent node">
          <Plus size={14} /> Agent
        </ToolbarButton>
        <ToolbarButton onClick={() => handleAddNode('tool')} t={t} title="Add tool node">
          <Plus size={14} /> Tool
        </ToolbarButton>

        <div style={{ flex: 1 }} />

        {selectedNodeId && (
          <ToolbarButton onClick={handleDelete} t={t} title="Delete selected node" danger>
            <Trash2 size={14} /> Delete
          </ToolbarButton>
        )}
        <ToolbarButton onClick={() => alert('Save (placeholder) — wired into backend in next step')} t={t} title="Save workflow">
          <Save size={14} /> Save
        </ToolbarButton>
      </div>

      {/* ── Canvas ─────────────────────────────────────── */}
      <div ref={wrapperRef} style={{ flex: 1, minHeight: 0, background: t.bgContent }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={(_, node) => setSelectedNodeId(node.id)}
          onPaneClick={() => setSelectedNodeId(null)}
          nodeTypes={nodeTypes}
          fitView
        >
          <Background variant={BackgroundVariant.Dots} gap={16} size={1} color={t.textDim} />
          <Controls />
        </ReactFlow>
      </div>
    </div>
  );
}

