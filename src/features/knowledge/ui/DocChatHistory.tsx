/**
 * DocChatHistory — collapsed drawer showing past conversations.
 *
 * Each row shows the conversation's message count and last-updated time.
 * Click a row to load it, click the trash to delete it.
 *
 * Adapted from agent-workspace's DocChatHistory.
 */
import { useState } from 'react';
import { Trash2, MessageSquare, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useLayoutTokens } from '../../../components/layout2/tokens';
import type { DocChatConversation } from '../../../lib/api-doc-chat';

interface DocChatHistoryProps {
  conversations: DocChatConversation[];
  activeConversationId: string | null;
  onLoad: (conversationId: string) => void;
  onDelete: (conversationId: string) => void;
  onRefresh: () => void;
}

function formatRelative(ts: number | null, tr: (k: string, o?: any) => string): string {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const diff = Date.now() - d.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return tr('dc_just_now');
  if (mins < 60) return tr('dc_minutes_ago', { count: mins });
  const hours = Math.floor(mins / 60);
  if (hours < 24) return tr('dc_hours_ago', { count: hours });
  return d.toLocaleDateString();
}

const DocChatHistory = ({
  conversations,
  activeConversationId,
  onLoad,
  onDelete,
  onRefresh,
}: DocChatHistoryProps) => {
  const t = useLayoutTokens();
  const { t: tr } = useTranslation('chat');
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  return (
    <div
      style={{
        background: t.bgBase,
        border: `1px solid ${t.border}`,
        display: 'flex',
        flexDirection: 'column',
        maxHeight: 280,
        minWidth: 240,
      }}
    >
      {/* Drawer header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          padding: '6px 10px',
          borderBottom: `1px solid ${t.border}`,
          color: t.textMuted,
          fontSize: 11,
          textTransform: 'uppercase',
          letterSpacing: 0.5,
        }}
      >
        <MessageSquare size={11} style={{ marginRight: 6 }} />
        <span>History ({conversations.length})</span>
        <button
          title={tr('kb_refresh')}
          onClick={onRefresh}
          style={{
            marginLeft: 'auto',
            background: 'transparent',
            border: 'none',
            color: t.textMuted,
            cursor: 'pointer',
            padding: 2,
            display: 'flex',
            alignItems: 'center',
          }}
        >
          <RefreshCw size={11} />
        </button>
      </div>

      {/* Conversation rows */}
      <div className="overflow-auto">
        {conversations.length === 0 ? (
          <div
            style={{
              padding: 14,
              color: t.textMuted,
              fontSize: 12,
              textAlign: 'center',
            }}
          >
            {tr('dc_no_conversations')}
          </div>
        ) : (
          conversations
            .slice()
            .sort((a, b) => (b.last_updated ?? 0) - (a.last_updated ?? 0))
            .map((conv) => {
              const isActive = conv.conversation_id === activeConversationId;
              const isHover = hoveredId === conv.conversation_id;
              return (
                <div
                  key={conv.conversation_id}
                  onClick={() => onLoad(conv.conversation_id)}
                  onMouseEnter={() => setHoveredId(conv.conversation_id)}
                  onMouseLeave={() => setHoveredId(null)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    height: 28,
                    padding: '0 8px',
                    cursor: 'pointer',
                    background: isActive
                      ? t.bgSelected
                      : isHover
                        ? t.bgHover
                        : 'transparent',
                    color: t.textPrimary,
                    fontSize: 12,
                    gap: 8,
                  }}
                >
                  <span
                    style={{
                      flex: 1,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                    title={tr('dc_messages_count', { count: conv.message_count })}
                  >
                    {tr('dc_messages_count', { count: conv.message_count })}
                  </span>
                  <span style={{ color: t.textMuted, fontSize: 11 }}>
                    {formatRelative(conv.last_updated, tr)}
                  </span>
                  <button
                    title={tr('kb_delete')}
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(conv.conversation_id);
                    }}
                    style={{
                      background: 'transparent',
                      border: 'none',
                      color: t.textMuted,
                      cursor: 'pointer',
                      padding: 2,
                      display: 'flex',
                      alignItems: 'center',
                    }}
                    onMouseEnter={(e) => {
                      (e.currentTarget as HTMLElement).style.color = t.textPrimary;
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLElement).style.color = t.textMuted;
                    }}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              );
            })
        )}
      </div>
    </div>
  );
};

export default DocChatHistory;
