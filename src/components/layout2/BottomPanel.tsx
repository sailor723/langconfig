/**
 * BottomPanel — collapsible panel at the bottom of the workspace.
 *
 * Replaces the GlobalChatModal. Contains tabs for Chat, Logs, and Output.
 * Inspired by Obsidian's bottom panel pattern.
 */
import { useLayoutState } from './useLayout';
import { useLayoutTokens } from './tokens';
import { Terminal, MessageSquare, ListTree } from 'lucide-react';

type PanelTab = 'chat' | 'logs' | 'output';

const PANEL_TABS: { id: PanelTab; label: string; icon: React.ReactNode }[] = [
  { id: 'chat',   label: 'Chat',   icon: <MessageSquare size={14} /> },
  { id: 'logs',   label: 'Logs',   icon: <ListTree size={14} /> },
  { id: 'output', label: 'Output', icon: <Terminal size={14} /> },
];

export default function BottomPanel() {
  const { bottomPanelOpen, toggleBottomPanel, setBottomPanelOpen } = useLayoutState();
  const t = useLayoutTokens();

  return (
    <div
      style={{
        borderTop: `1px solid ${t.border}`,
        background: t.bgBase,
        display: 'flex',
        flexDirection: 'column',
        userSelect: 'none',
      }}
    >
      {/* Header row — always visible */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          height: 32,
          minHeight: 32,
          padding: '0 8px',
          gap: 2,
        }}
      >
        {PANEL_TABS.map(p => (
          <button
            key={p.id}
            onClick={() => {}}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              height: 26,
              padding: '0 8px',
              fontSize: 12,
              color: t.textMuted,
              background: 'transparent',
              border: 'none',
              borderRadius: 4,
              cursor: 'pointer',
            }}
          >
            {p.icon}
            {p.label}
          </button>
        ))}

        <div style={{ flex: 1 }} />

        {/* Toggle panel */}
        <button
          onClick={toggleBottomPanel}
          title={bottomPanelOpen ? 'Close panel' : 'Open panel'}
          style={{
            width: 26,
            height: 26,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'transparent',
            border: 'none',
            borderRadius: 4,
            color: t.textMuted,
            cursor: 'pointer',
          }}
        >
          <svg
            width="16" height="16" viewBox="0 0 24 24"
            fill="none" stroke="currentColor" strokeWidth="2"
            strokeLinecap="round"
            style={{ transform: bottomPanelOpen ? 'rotate(180deg)' : 'none' }}
          >
            <polyline points="18 15 12 9 6 15" />
          </svg>
        </button>
      </div>

      {/* Content — only visible when open */}
      {bottomPanelOpen && (
        <div
          style={{
            height: 240,
            minHeight: 240,
            background: t.bgContent,
            borderTop: `1px solid ${t.border}`,
            overflow: 'auto',
            padding: 12,
          }}
        >
          <p style={{ color: t.textMuted, fontSize: 13, fontStyle: 'italic' }}>
            Chat and execution output will appear here.
          </p>
        </div>
      )}
    </div>
  );
}
