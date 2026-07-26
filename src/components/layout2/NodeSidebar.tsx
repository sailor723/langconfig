/**
 * NodeSidebar — VS Code-style right panel.
 *
 * Always visible. Shows Chat by default.
 * When a canvas node is selected, a Properties tab appears.
 */
import { useState, type ReactNode } from 'react';
import { useLayoutState } from './useLayout';
import { useLayoutTokens } from './tokens';
import { MessageSquare, Settings, X } from 'lucide-react';

interface NodeSidebarProps {
  children?: ReactNode;
}

export default function NodeSidebar({ children }: NodeSidebarProps) {
  const { rightPanelOpen, rightPanelContent, closeRightPanel } = useLayoutState();
  const t = useLayoutTokens();
  const [localTab, setLocalTab] = useState<'chat' | 'properties'>('chat');

  // When a node is selected (rightPanelContent set), switch to Properties tab
  const activeTab = rightPanelContent ? 'properties' : localTab;

  const tabs: { id: 'chat' | 'properties'; label: string; icon: React.ReactNode }[] = [
    { id: 'chat', label: 'Chat', icon: <MessageSquare size={13} /> },
    ...(rightPanelContent ? [{ id: 'properties' as const, label: 'Properties', icon: <Settings size={13} /> }] : []),
  ];

  return (
    <div
      style={{
        width: 300,
        minWidth: 300,
        background: t.bgSidebar,
        borderLeft: `1px solid ${t.border}`,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        userSelect: 'none',
      }}
    >
      {/* ── Tab bar ────────────────────────────────── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          height: 35,
          padding: '0 8px',
          borderBottom: `1px solid ${t.border}`,
          gap: 0,
        }}
      >
        {tabs.map(tab => {
          const isActive = tab.id === activeTab;
          return (
            <button
              key={tab.id}
              onClick={() => {
                setLocalTab(tab.id);
                if (tab.id === 'properties' && !rightPanelOpen) {
                  // Already handled by rightPanelContent
                }
              }}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                height: 35,
                padding: '0 10px',
                fontSize: 12,
                color: isActive ? t.textPrimary : t.textMuted,
                background: 'transparent',
                border: 'none',
                borderBottom: isActive ? `2px solid ${t.accent}` : '2px solid transparent',
                cursor: 'pointer',
              }}
            >
              {tab.icon}
              {tab.label}
            </button>
          );
        })}

        <div style={{ flex: 1 }} />

        {/* Close button (only when properties/child content shown) */}
        {rightPanelContent && (
          <button
            onClick={closeRightPanel}
            title="Close"
            style={{
              width: 24,
              height: 24,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: 'transparent',
              border: 'none',
              color: t.textMuted,
              cursor: 'pointer',
            }}
          >
            <X size={14} />
          </button>
        )}
      </div>

      {/* ── Content ─────────────────────────────────── */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        {activeTab === 'properties' && (children ?? <DefaultNodePanel />)}
        {activeTab === 'chat' && <ChatSidebar t={t} />}
      </div>
    </div>
  );
}

// ── Chat sidebar content ────────────────────────────────

function ChatSidebar({ t }: { t: ReturnType<typeof useLayoutTokens> }) {
  const [messages, setMessages] = useState<string[]>([]);
  const [input, setInput] = useState('');

  const handleSend = () => {
    if (!input.trim()) return;
    setMessages(prev => [...prev, input.trim()]);
    setInput('');
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 8, padding: 10 }}>
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6 }}>
        {messages.length === 0 && (
          <p style={{ color: t.textMuted, fontSize: 12, fontStyle: 'italic', padding: 8 }}>
            Start a conversation with the agent.
          </p>
        )}
        {messages.map((msg, i) => (
          <div key={i} style={{ padding: '8px 10px', background: t.bgHover, fontSize: 12, color: t.textPrimary, borderRadius: 4 }}>
            {msg}
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') handleSend(); }}
          placeholder="Type a message..."
          style={{
            flex: 1,
            padding: '5px 8px',
            fontSize: 12,
            background: t.bgInput,
            border: `1px solid ${t.border}`,
            color: t.textPrimary,
            outline: 'none',
          }}
        />
        <button
          onClick={handleSend}
          style={{
            padding: '5px 12px',
            fontSize: 12,
            background: t.accent,
            color: '#fff',
            border: 'none',
            cursor: 'pointer',
          }}
        >
          Send
        </button>
      </div>
    </div>
  );
}

// ── Default node properties panel ───────────────────────

function DefaultNodePanel() {
  const t = useLayoutTokens();
  return (
    <div style={{ padding: 10 }}>
      <div style={{ marginBottom: 12 }}>
        <label style={{ display: 'block', fontSize: 11, color: t.textMuted, marginBottom: 4 }}>
          Model
        </label>
        <select
          style={{
            width: '100%',
            padding: '5px 8px',
            border: `1px solid ${t.border}`,
            background: t.bgInput,
            color: t.textPrimary,
            fontSize: 12,
          }}
        >
          <option>GPT-4o</option>
          <option>GPT-4o-mini</option>
          <option>Claude 3.5 Sonnet</option>
        </select>
      </div>
    </div>
  );
}
