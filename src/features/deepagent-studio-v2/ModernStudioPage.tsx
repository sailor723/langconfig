/**
 * ModernStudioPage — LangChain-style dark studio with neural visualization.
 * Route: /modern-studio
 */

import { useState } from 'react';
import { useChat } from '@/features/chat/state/ChatContext';
import ModernStudioCanvas from './ModernStudioCanvas';
import ModernAgentPicker from './components/ModernAgentPicker';
import ModernCapabilityBar from './components/ModernCapabilityBar';
import ModernDetailPanel from './components/ModernDetailPanel';
import { useAgentStructure } from './hooks/useAgentStructure';
import type { Node } from 'reactflow';

export default function ModernStudioPage() {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const { structure, loading, error } = useAgentStructure(selectedId);
  const { openChat } = useChat();

  const handleNodeClick = (_nodeId: string | null, node: Node | null) => {
    setSelectedNode(node);
  };

  return (
    <div
      className="w-full h-full flex flex-col"
      style={{ background: '#030710' }}
    >
      {/* Header — glass with gradient accent */}
      <div
        className="flex items-center justify-between px-6 py-3 flex-shrink-0"
        style={{
          background: 'linear-gradient(180deg, rgba(13, 19, 34, 0.95) 0%, rgba(3, 7, 16, 0.85) 100%)',
          borderBottom: '1px solid rgba(0, 109, 221, 0.3)',
          backdropFilter: 'blur(12px)',
        }}
      >
        <div className="flex items-center gap-4">
          {/* Logo + Title */}
          <div className="flex items-center gap-2.5">
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center"
              style={{
                background: 'linear-gradient(135deg, #006DDD 0%, #7FC8FF 100%)',
                boxShadow: '0 0 12px rgba(127, 200, 255, 0.4)',
              }}
            >
              <span style={{ color: '#FFFFFF', fontSize: 16 }}>🧠</span>
            </div>
            <div>
              <div className="text-sm font-semibold" style={{ color: '#F2FAFF' }}>
                DeepAgent Studio
              </div>
              <div className="text-[9px] uppercase tracking-wider" style={{ color: '#7FC8FF' }}>
                Neural Agent Topology
              </div>
            </div>
          </div>

          <div
            className="h-6 w-px"
            style={{ backgroundColor: 'rgba(0, 109, 221, 0.4)' }}
          />

          <ModernAgentPicker selectedId={selectedId} onSelect={(id) => {
            setSelectedId(id);
            setSelectedNode(null);
          }} />

          <div
            className="h-6 w-px"
            style={{ backgroundColor: 'rgba(0, 109, 221, 0.4)' }}
          />

          {/* Agent Creator button — select agent_id=112 to show in studio canvas */}
          <button
            onClick={() => {
              setSelectedId(112);
              setSelectedNode(null);
            }}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all"
            style={{
              background: 'linear-gradient(135deg, #7C3AED 0%, #A78BFA 100%)',
              color: '#FFFFFF',
              boxShadow: '0 0 16px rgba(124, 58, 237, 0.4)',
            }}
          >
            <span style={{ fontSize: 14 }}>✨</span>
            <span>Generate with AI</span>
          </button>

          {/* Skill Generator button — opens skill generator agent */}
          <button
            onClick={() => {
              setSelectedId(69);
              setSelectedNode(null);
            }}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all"
            style={{
              background: 'linear-gradient(135deg, #9333EA 0%, #C084FC 100%)',
              color: '#FFFFFF',
              boxShadow: '0 0 16px rgba(147, 51, 234, 0.4)',
            }}
          >
            <span style={{ fontSize: 14 }}>🧩</span>
            <span>Gen Skill with AI</span>
          </button>
        </div>

        <div className="flex items-center gap-2">
          {selectedId && (
            <>
              <button
                onClick={() => openChat(selectedId)}
                className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all"
                style={{
                  background: 'linear-gradient(135deg, #006DDD 0%, #7FC8FF 100%)',
                  color: '#FFFFFF',
                  boxShadow: '0 0 16px rgba(0, 109, 221, 0.4)',
                }}
              >
                <span style={{ fontSize: 12 }}>▶</span>
                <span>Test</span>
              </button>
            </>
          )}
        </div>
      </div>

      {/* Main area — canvas + detail panel */}
      <div className="flex-1 flex min-h-0">
        {/* Canvas */}
        <div className="flex-1 relative min-w-0" style={{ height: '100%' }}>
          {loading && (
            <div
              className="absolute inset-0 flex items-center justify-center z-10"
              style={{ background: 'rgba(3, 7, 16, 0.85)', pointerEvents: 'none' }}
            >
              <div style={{ color: '#7FC8FF' }} className="text-sm">
                Loading agent topology...
              </div>
            </div>
          )}
          {error && (
            <div
              className="absolute inset-0 flex items-center justify-center z-10"
              style={{ background: 'rgba(3, 7, 16, 0.85)' }}
            >
              <div style={{ color: '#ff6b6b' }} className="text-sm">
                Error: {error}
              </div>
            </div>
          )}
          {!selectedId && !loading && (
            <div className="absolute inset-0 flex items-center justify-center" style={{ pointerEvents: 'none' }}>
              <div className="text-center">
                <div
                  className="text-5xl mb-3"
                  style={{ filter: 'drop-shadow(0 0 16px rgba(127, 200, 255, 0.6))' }}
                >
                  🧠
                </div>
                <div className="text-base font-medium mb-1" style={{ color: '#F2FAFF' }}>
                  Select an agent to visualize
                </div>
                <div className="text-xs" style={{ color: '#99D3FF' }}>
                  Pick an agent from the dropdown above to see its topology
                </div>
              </div>
            </div>
          )}
          {selectedId && structure && (
            <div className="absolute inset-0" style={{ pointerEvents: 'all' }}>
              <ModernStudioCanvas structure={structure} onNodeClick={handleNodeClick} />
            </div>
          )}
        </div>

        {/* Detail Panel */}
        <ModernDetailPanel structure={structure} selectedNode={selectedNode} />
      </div>

      {/* Capability Bar */}
      <ModernCapabilityBar structure={structure} />
    </div>
  );
}
