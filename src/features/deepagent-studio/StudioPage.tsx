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
import SubAgentDetailModal from './components/SubAgentDetailModal';
import DeepAgentCanvas from './DeepAgentCanvas';
import { useAgentStructure } from './hooks/useAgentStructure';
import DeepAgentBuilder from '@/features/agents/ui/DeepAgentBuilder';
import { useChat } from '@/features/chat/state/ChatContext';
import apiClient from '@/lib/api-client';

export default function DeepAgentStudioPage() {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [showBuilder, setShowBuilder] = useState(false);
  const [editingConfig, setEditingConfig] = useState<any>(null);

  const { structure, loading, error } = useAgentStructure(selectedId);
  const { openChat } = useChat();

  const handleNodeSelect = useCallback((nodeId: string | null, _data: any) => {
    setSelectedNodeId(nodeId);
  }, []);

  const handleEdit = async (id: number) => {
    // Fetch full agent config and open DeepAgentBuilder modal
    try {
      const res = await apiClient.getDeepAgent(id);
      const agent = (res as any).data ?? res;
      setEditingConfig({ ...agent.config, _agent: agent });
      setShowBuilder(true);
    } catch {
      alert('Failed to load agent config for editing.');
    }
  };

  const handleSaveConfig = async (config: any) => {
    try {
      const agent = editingConfig?._agent;
      const payload = {
        config,
        lock_version: agent?.lock_version ?? 0,
      };
      await apiClient.updateDeepAgent(selectedId!, payload);
      setShowBuilder(false);
      setEditingConfig(null);
    } catch {
      alert('Failed to save agent.');
    }
  };

  const handleTest = (id: number) => {
    // Open global chat modal with the selected agent
    openChat(id);
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

      {/* Sub-agent detail modal (triggered by clicking a sub-agent node) */}
      <SubAgentDetailModal />

      {/* DeepAgentBuilder modal — opened via Edit button */}
      {showBuilder && editingConfig && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
        >
          <div
            className="border border-gray-200 dark:border-border-dark rounded-xl w-full max-w-5xl max-h-[90vh] overflow-y-auto shadow-2xl"
            style={{ backgroundColor: 'var(--color-panel-dark)' }}
            onClick={(e) => e.stopPropagation()}
          >
            <DeepAgentBuilder
              initialConfig={editingConfig}
              agentType="deep"
              onSave={handleSaveConfig}
              onClose={() => { setShowBuilder(false); setEditingConfig(null); }}
              onBack={() => { setShowBuilder(false); setEditingConfig(null); }}
            />
          </div>
        </div>
      )}
    </div>
  );
}