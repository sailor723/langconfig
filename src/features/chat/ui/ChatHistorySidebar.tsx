import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, MessageSquare, Trash2, PenLine, Search } from 'lucide-react';
import type { ChatSession } from '../types/chat';
import { useChat } from '../state/ChatContext';

interface ChatHistorySidebarProps {
  onNewSession: () => void;
}

export default function ChatHistorySidebar({ onNewSession }: ChatHistorySidebarProps) {
  const { t } = useTranslation('chat');
  const { sessions, currentSessionId, switchSession, endSession } = useChat();
  const [collapsed, setCollapsed] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [hoveredSession, setHoveredSession] = useState<string | null>(null);

  const conversationsWithMessages = sessions.filter((s: ChatSession) =>
    s.message_count > 0 || s.session_id === currentSessionId
  );

  const filteredSessions = searchQuery
    ? conversationsWithMessages.filter(s =>
        (s.last_message_preview || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
        s.agent_name.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : conversationsWithMessages;

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
          className="p-2 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors mb-4"
          title="Expand sidebar"
        >
          <MessageSquare className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
        </button>
        <div className="flex-1 overflow-y-auto space-y-1 px-1">
          {conversationsWithMessages.slice(0, 8).map((session) => (
            <button
              key={session.session_id}
              onClick={() => switchSession(session.session_id)}
              className={`w-8 h-8 rounded-lg flex items-center justify-center text-xs font-medium transition-colors ${
                currentSessionId === session.session_id
                  ? 'bg-primary text-white'
                  : 'hover:bg-gray-200 dark:hover:bg-gray-700'
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

  return (
    <div
      className="flex flex-col transition-all duration-200"
      style={{
        width: '280px',
        minWidth: '280px',
        backgroundColor: 'var(--color-panel, #f9fafb)',
        borderColor: 'var(--color-border-dark)',
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-5 py-3"
      >
        <h2
          className="text-xs font-semibold tracking-wide uppercase"
          style={{ color: 'var(--color-text-muted)' }}
        >
          {t('history')}
        </h2>
        <div className="flex items-center gap-1">
          <button
            onClick={onNewSession}
            className="p-1.5 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
            title={t('new_conversation')}
          >
            <Plus className="w-4 h-4" style={{ color: 'var(--color-primary)' }} />
          </button>
          <button
            onClick={() => setCollapsed(true)}
            className="p-1.5 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
            title={t('collapse_sidebar')}
          >
            <PenLine className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="px-3 py-2">
        <div
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm"
          style={{
            backgroundColor: 'var(--color-input-background, #f3f4f6)',
            color: 'var(--color-text-muted)',
          }}
        >
          <Search className="w-3.5 h-3.5" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('search_conversations')}
            className="w-full bg-transparent outline-none text-sm"
            style={{ color: 'var(--color-text-primary)' }}
          />
        </div>
      </div>

      {/* Session List */}
      <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-0.5">
        {filteredSessions.length === 0 ? (
          <div
            className="p-4 text-center text-xs"
            style={{ color: 'var(--color-text-muted)' }}
          >
            {searchQuery ? 'No matching conversations' : 'No conversations yet'}
          </div>
        ) : (
          filteredSessions.map((session: ChatSession) => {
            const isActive = currentSessionId === session.session_id;
            const isHovered = hoveredSession === session.session_id;
            return (
              <button
                key={session.session_id}
                onClick={() => switchSession(session.session_id)}
                onMouseEnter={() => setHoveredSession(session.session_id)}
                onMouseLeave={() => setHoveredSession(null)}
                className="w-full text-left px-1.5 py-2 rounded-lg transition-all group"
                style={{
                  backgroundColor: isActive
                    ? 'var(--color-primary)'
                    : isHovered
                    ? 'rgba(0,0,0,0.05)'
                    : 'transparent',
                }}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div
                      className="text-xs font-medium truncate"
                      style={{
                        color: isActive ? 'white' : 'var(--color-text-primary)',
                      }}
                    >
                      <span className="text-[10px] font-normal" style={{ color: isActive ? 'rgba(255,255,255,0.4)' : '#9ca3af' }}>
                        {formatTimestamp(session.updated_at)}
                      </span>
                      &nbsp;&nbsp;
                      {session.last_message_preview
                        ? session.last_message_preview.slice(0, 50)
                        : t('new_conversation')}
                    </div>
                  </div>
                  {isHovered && !isActive && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        endSession(session.session_id);
                      }}
                      className="p-1 rounded hover:bg-red-50 transition-colors flex-shrink-0 mt-0.5 opacity-0 group-hover:opacity-100"
                      title="End session"
                    >
                      <Trash2 className="w-3.5 h-3.5" style={{ color: '#ef4444' }} />
                    </button>
                  )}
                  {isActive && (
                    <div className="w-1.5 h-1.5 rounded-full bg-white mt-2 flex-shrink-0" />
                  )}
                </div>
              </button>
            );
          })
        )}
      </div>

      {/* Bottom Footer */}
      <div
        className="px-4 py-3 border-t text-xs"
        style={{
          borderColor: 'var(--color-border-dark)',
          color: 'var(--color-text-muted)',
        }}
      >
        {sessions.length} conversation{sessions.length !== 1 ? 's' : ''}
      </div>
    </div>
  );
}
