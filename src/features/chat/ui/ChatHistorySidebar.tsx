/**
 * ChatHistorySidebar — Codex-style compact sidebar.
 *
 * Layout:
 *   ┌─────────────────────┐
 *   │ [🗨] [🔍] [📅] [🧩] │  Top nav
 *   ├─────────────────────┤
 *   │ ▸ Projects          │
 *   │   my-agent ▸        │  Current project badge
 *   ├─────────────────────┤
 *   │ Chats               │
 *   │ title...        2d  │  Minimal rows
 *   │ title...        3w  │
 *   │ title...       15m  │
 *   ├─────────────────────┤
 *   │ ⚙ Settings          │  Bottom
 *   └─────────────────────┘
 */
import { useState } from 'react';
import { Plus, MessageSquare, Search, ChevronDown, ChevronRight, Settings, Calendar, Puzzle } from 'lucide-react';
import type { ChatSession } from '../types/chat';
import { useChat } from '../state/ChatContext';

interface ChatHistorySidebarProps {
  onNewSession: () => void;
}

export default function ChatHistorySidebar({ onNewSession }: ChatHistorySidebarProps) {
  const { sessions, currentSessionId, switchSession } = useChat();
  const [collapsed, setCollapsed] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [showProjects, setShowProjects] = useState(true);

  const activeSessions = sessions.filter(
    (s: ChatSession) => s.message_count > 0 || s.session_id === currentSessionId
  );

  const filteredSessions = searchQuery
    ? activeSessions.filter((s: ChatSession) =>
        (s.last_message_preview || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
        s.agent_name.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : activeSessions;

  const formatTimestamp = (timestamp: string) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMinutes = Math.floor((now.getTime() - date.getTime()) / (1000 * 60));
    if (diffMinutes < 1) return 'now';
    if (diffMinutes < 60) return `${diffMinutes}m`;
    if (diffMinutes < 1440) return `${Math.floor(diffMinutes / 60)}h`;
    const diffDays = Math.floor(diffMinutes / 1440);
    if (diffDays < 7) return `${diffDays}d`;
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  };

  // ── Collapsed state ────────────────────────────────────────────

  if (collapsed) {
    return (
      <div
        className="flex flex-col items-center py-3 border-r transition-all duration-200"
        style={{
          width: '48px',
          backgroundColor: 'var(--color-panel, #f9fafb)',
          borderColor: 'var(--color-border-dark)',
        }}
      >
        <button
          onClick={() => setCollapsed(false)}
          className="p-2 rounded-lg hover:bg-black/5 transition-colors mb-4"
          title="Expand sidebar"
        >
          <MessageSquare className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
        </button>
        <div className="flex-1 overflow-y-auto space-y-1 px-1">
          {activeSessions.slice(0, 8).map((session: ChatSession) => (
            <button
              key={session.session_id}
              onClick={() => switchSession(session.session_id)}
              className={`w-8 h-8 rounded-lg flex items-center justify-center text-xs font-medium transition-colors ${
                currentSessionId === session.session_id
                  ? 'bg-primary text-white'
                  : 'hover:bg-black/5'
              }`}
              style={{
                color: currentSessionId === session.session_id ? 'white' : 'var(--color-text-muted)',
              }}
              title={session.agent_name}
            >
              {session.agent_name.charAt(0).toUpperCase()}
            </button>
          ))}
        </div>
      </div>
    );
  }

  // ── Expanded state ─────────────────────────────────────────────

  return (
    <div
      className="flex flex-col transition-all duration-200 border-r"
      style={{
        backgroundColor: 'var(--color-panel-dark, var(--color-panel, #f9fafb))',
        borderColor: 'var(--color-border-dark)',
      }}
    >
      {/* ── Top nav: New / Search / Scheduled / Plugins ──────────── */}
      <div className="flex items-center gap-0.5 px-3 py-2.5 border-b" style={{ borderColor: 'var(--color-border-dark)' }}>
        <button
          onClick={onNewSession}
          className="p-1.5 rounded-lg hover:bg-black/5 transition-colors"
          title="New chat"
        >
          <Plus className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
        </button>
        <button
          onClick={() => setSearchQuery('')}
          className="p-1.5 rounded-lg hover:bg-black/5 transition-colors"
          title="Search"
        >
          <Search className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
        </button>
        <button
          className="p-1.5 rounded-lg hover:bg-black/5 transition-colors"
          title="Scheduled"
        >
          <Calendar className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
        </button>
        <button
          className="p-1.5 rounded-lg hover:bg-black/5 transition-colors"
          title="Plugins"
        >
          <Puzzle className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
        </button>

        <div className="flex-1" />

        <button
          onClick={() => setCollapsed(true)}
          className="p-1.5 rounded-lg hover:bg-black/5 transition-colors"
          title="Collapse"
        >
          <ChevronRight className="w-3.5 h-3.5" style={{ color: 'var(--color-text-muted)' }} />
        </button>
      </div>

      {/* ── Projects section ─────────────────────────────────────── */}
      <div className="px-3 pt-3 pb-1">
        <button
          onClick={() => setShowProjects(!showProjects)}
          className="flex items-center gap-1 w-full text-left text-xs font-medium"
          style={{ color: 'var(--color-text-muted)' }}
        >
          {showProjects ? (
            <ChevronDown className="w-3 h-3" />
          ) : (
            <ChevronRight className="w-3 h-3" />
          )}
          Projects
        </button>
        {showProjects && (
          <div className="mt-1 px-4 py-1.5 rounded-lg text-xs flex items-center justify-between hover:bg-black/5 transition-colors cursor-pointer"
            style={{ color: 'var(--color-text-primary)' }}
          >
            <span className="font-medium truncate">
              {currentSessionId
                ? sessions.find((s: ChatSession) => s.session_id === currentSessionId)?.agent_name || 'my-agent'
                : 'my-agent'}
            </span>
            <ChevronDown className="w-3 h-3 opacity-50" />
          </div>
        )}
      </div>

      {/* ── Chats section ─────────────────────────────────────────── */}
      <div className="px-3 pt-2 pb-1 flex items-center justify-between">
        <span className="text-xs font-medium" style={{ color: 'var(--color-text-muted)' }}>
          Chats
        </span>
        <span className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
          {activeSessions.length}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-0.5">
        {filteredSessions.length === 0 ? (
          <div className="p-4 text-center text-xs" style={{ color: 'var(--color-text-muted)' }}>
            {searchQuery ? 'No matching conversations' : 'No conversations yet'}
          </div>
        ) : (
          filteredSessions.map((session: ChatSession) => {
            const isActive = currentSessionId === session.session_id;
            return (
              <button
                key={session.session_id}
                onClick={() => switchSession(session.session_id)}
                className="w-full text-left px-2 py-2 rounded-lg transition-all group"
                style={{
                  backgroundColor: isActive ? 'var(--color-primary)' : 'transparent',
                }}
                onMouseEnter={(e) => {
                  if (!isActive) e.currentTarget.style.backgroundColor = 'rgba(0,0,0,0.04)';
                }}
                onMouseLeave={(e) => {
                  if (!isActive) e.currentTarget.style.backgroundColor = 'transparent';
                }}
              >
                <div className="flex items-center justify-between gap-2">
                  <span
                    className="text-xs truncate"
                    style={{
                      color: isActive ? 'white' : 'var(--color-text-primary)',
                    }}
                  >
                    {session.last_message_preview
                      ? session.last_message_preview.slice(0, 60)
                      : 'New conversation'}
                  </span>
                  <span
                    className="text-[10px] flex-shrink-0"
                    style={{
                      color: isActive ? 'rgba(255,255,255,0.6)' : 'var(--color-text-muted)',
                    }}
                  >
                    {formatTimestamp(session.updated_at)}
                  </span>
                </div>
              </button>
            );
          })
        )}
      </div>

      {/* ── Bottom: Settings ────────────────────────────────────── */}
      <div
        className="flex items-center gap-2 px-4 py-3 border-t text-xs cursor-pointer hover:bg-black/5 transition-colors"
        style={{
          borderColor: 'var(--color-border-dark)',
          color: 'var(--color-text-muted)',
        }}
      >
        <Settings className="w-3.5 h-3.5" />
        <span>Settings</span>
      </div>
    </div>
  );
}