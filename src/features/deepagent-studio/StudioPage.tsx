/**
 * DeepAgentStudioPage — top-level page at route /deepagent-studio
 *
 * Phase 8 Day 1: Read-only visualization.
 * - Agent picker (top)
 * - Center canvas (ReactFlow, no drag)
 * - Detail panel (right, read-only)
 * - Capability bar (bottom)
 */

import { useState, useCallback } from 'react';
import AgentPicker from './components/AgentPicker';
import CapabilityBar from './components/CapabilityBar';
import DetailPanel from './components/DetailPanel';
import DeepAgentCanvas from './DeepAgentCanvas';
import { useAgentStructure } from './hooks/useAgentStructure';

export default function DeepAgentStudioPage() {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const { structure, loading, error } = useAgentStructure(selectedId);

  const handleNodeSelect = useCallback((nodeId: string | null, _data: any) => {
    setSelectedNodeId(nodeId);
  }, []);

  const handleEdit = (id: number) => {
    // Day 2 will implement DeepAgentStudioBuilder side panel.
    // For now just alert so the user knows the click works.
    alert(
      `Edit panel for agent ${id} — DeepAgentStudioBuilder will open here in Day 2.\n` +
      `(Isolated from existing DeepAgentBuilder modal)`
    );
  };

  const handleTest = (_id: number) => {
    // Day 2: hook up real-time execution + Skill Router highlight
    alert('▶ Test will trigger Skill Router in Day 2.\nWatch the picked sub-agent highlight in real-time!');
  };

  return (
    <div className="flex flex-col h-full" style={{ backgroundColor: 'var(--color-canvas-bg)' }}>
      {/* Header bar */}
      <div
        className="flex items-center gap-3 px-4 py-2 border-b"
        style={{ backgroundColor: 'var(--color-panel-dark)', borderColor: 'var(--color-border)' }}
      >
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-lg" style={{ color: 'var(--color-primary)' }}>
            hub
          </span>
          <span className="text-sm font-semibold" style={{ color: 'var(--color-text-primary)' }}>
            DeepAgent Studio
          </span>
          <span className="text-[10px] px-1.5 py-0.5 rounded font-bold uppercase"
            style={{ backgroundColor: 'var(--color-primary)', color: '#fff' }}>
            Phase 8
          </span>
        </div>

        <div className="h-4 w-px" style={{ backgroundColor: 'var(--color-border)' }} />

        <AgentPicker
          selectedId={selectedId}
          onSelect={setSelectedId}
          onEdit={handleEdit}
          onTest={handleTest}
        />

        <div className="text-[10px] ml-auto" style={{ color: 'var(--color-text-muted)' }}>
          Read-only · v1.0
        </div>
      </div>

      {/* Body: canvas + detail panel */}
      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1 flex flex-col min-w-0">
          {error && (
            <div className="px-4 py-2 text-xs" style={{ backgroundColor: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>
              ⚠ {error}
            </div>
          )}
          {loading && (
            <div className="px-4 py-2 text-xs" style={{ color: 'var(--color-text-muted)' }}>
              Loading structure…
            </div>
          )}

          <div className="flex-1 min-h-0">
            <DeepAgentCanvas
              structure={structure}
              selectedNodeId={selectedNodeId}
              onNodeSelect={handleNodeSelect}
            />
          </div>

          <CapabilityBar capabilities={structure?.capabilities ?? []} />
        </div>

        <DetailPanel structure={structure} selectedNodeId={selectedNodeId} />
      </div>
    </div>
  );
}