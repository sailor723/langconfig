/**
 * DocChatPanel — Obsidian-style doc chat thread.
 *
 * Features:
 *   - Conversation history dropdown
 *   - ContextChip showing "Loaded N files · M chars"
 *   - Citation rendering with clickable chips
 *   - Message actions (copy, download, regenerate, edit-and-resend)
 *   - Cancel button during streaming
 *   - Auto-growing textarea
 *
 * Adapted from agent-workspace's DocChatPanel.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  FolderOpen,
  Bot,
  User,
  Send,
  Square,
  Copy,
  Check,
  Download,
  RotateCcw,
  Pencil,
  History,
  X,
  Loader,
  Code2,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useLayoutTokens } from '../../../components/layout2/tokens';
import { useDocChat } from '../useDocChat';
import type { DocChatMessage } from '../../../lib/api-doc-chat';
import { getDocChatCode } from '../../../lib/api-doc-chat';
import { scopeOptionLabel, type ScopeOption } from '../knowledgeScope';
import DocChatHistory from './DocChatHistory';
import CodeViewerModal from '../../../components/layout2/CodeViewerModal';

// ── Constants ─────────────────────────────────────────

const INPUT_MAX_HEIGHT = 180;

/** Regex that matches `[Source: filename.md]` (with optional trailing
 *  punctuation) at the end of a sentence, or as a standalone token. */
const CITATION_RE = /\[Source:\s*([^\]]+\.\w+)\]\s*/g;

// ── Props ─────────────────────────────────────────────

interface DocChatPanelProps {
  /** Knowledge base folder name. There is no project: knowledge is a folder on disk. */
  knowledge: string;
  /** Folder inside it to scope the chat to (e.g. "business_model/tesla"). "" is the root. */
  folderPath: string;
  /** Every scope to choose from — each knowledge base and every folder beneath it. */
  scopeOptions?: ScopeOption[];
  /** The current scope as one path, e.g. "langconfig-test/eyewear_industry". */
  scope?: string;
  /** Called with the chosen scope path. The selection is shared, not local to this panel. */
  onScopeChange?: (path: string) => void;
  /** Called when the user clicks a citation chip. */
  onOpenDoc?: (docName: string) => void;
}

// ── Helper: render citations inline ───────────────────

/** Render message content with clickable citation chips. */
function renderCitations(
  content: string,
  openTitle: (docName: string) => string,
  onCitationClick?: (docName: string) => void,
) {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  // Reset regex state (important for global exec)
  CITATION_RE.lastIndex = 0;

  while ((match = CITATION_RE.exec(content)) !== null) {
    // Text before this citation
    if (match.index > lastIndex) {
      parts.push(content.slice(lastIndex, match.index));
    }
    // Citation chip
    const docName = match[1];
    parts.push(
      <button
        key={`cite-${match.index}`}
        onClick={(e) => {
          e.stopPropagation();
          onCitationClick?.(docName);
        }}
        className="citation-chip"
        style={{
          display: 'inline',
          background: '#a855f722',
          border: '1px solid #a855f744',
          borderRadius: 3,
          color: '#c084fc',
          cursor: 'pointer',
          fontSize: 'inherit',
          fontFamily: 'inherit',
          padding: '0 4px',
          margin: '0 1px',
          whiteSpace: 'nowrap',
        }}
        title={openTitle(docName)}
      >
        {docName}
      </button>,
    );
    lastIndex = match.index + match[0].length;
  }

  // Remaining text after last citation
  if (lastIndex < content.length) {
    parts.push(content.slice(lastIndex));
  }

  return parts.length > 0 ? parts : content;
}

// ── Helper: download assistant message as a .md file ──

/** A filename that says which knowledge base and when, not just a timestamp. */
function downloadName(knowledge: string, at: Date): string {
  const safe = (knowledge || 'knowledge').replace(/[^\w.\u4e00-\u9fff-]+/g, '-').replace(/^-+|-+$/g, '');
  const pad = (n: number) => String(n).padStart(2, '0');
  const stamp = `${at.getFullYear()}${pad(at.getMonth() + 1)}${pad(at.getDate())}-${pad(at.getHours())}${pad(at.getMinutes())}`;
  return `doc-chat-${safe}-${stamp}.md`;
}

/**
 * Save one answer as Markdown, with where it came from at the top.
 *
 * The provenance block is the point of downloading rather than copying: a saved answer with no
 * record of which knowledge base, which scope and how many documents produced it is unverifiable
 * a week later.
 */
function downloadAsMarkdown(content: string, filename: string, provenance: string) {
  const body = provenance ? `${provenance}\n\n---\n\n${content}\n` : `${content}\n`;
  const blob = new Blob([body], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Helper: copy to clipboard ─────────────────────────

/**
 * Copy text, and report whether it worked.
 *
 * Reporting matters: a copy button that silently does nothing is indistinguishable from a broken
 * one, which is exactly how these buttons were reported. The legacy path is not vestigial either —
 * `navigator.clipboard` is undefined on an insecure origin, which is what the app is served from
 * when it is opened over plain http from another machine.
 */
async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Permission denied or not a secure context — fall through to the legacy path.
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.top = '-1000px';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

// ── Message action row ────────────────────────────────
//
// Hover-revealed by the MESSAGE, via `group-hover` on the message wrapper — the same pattern
// MessagesPanel uses. Two things were wrong with the previous version, and together they made copy
// and download unreachable: the row was declared inside DocChatPanel's body (so React treated it as
// a new component type on every render and remounted it), and it carried a SECOND opacity of its
// own on top of the wrapper's. The wrapper revealed the outer row, but the inner one stayed at
// opacity 0 until the pointer entered it — an invisible strip you had to find by luck. One
// visibility rule, owned by the wrapper, and it works: move onto the message, the buttons appear.

type ActionState = 'idle' | 'copied' | 'failed';

function MessageActions({
  msg,
  knowledge,
  folderPath,
  onRegenerate,
  onEditStart,
  t,
}: {
  msg: DocChatMessage;
  knowledge: string;
  folderPath: string;
  onRegenerate: () => void;
  onEditStart: (msg: DocChatMessage) => void;
  t: ReturnType<typeof useLayoutTokens>;
}) {
  const [state, setState] = useState<ActionState>('idle');
  const { t: tr } = useTranslation('chat');

  // The "Copied" label is a timer, and it must not outlive the row it belongs to.
  useEffect(() => {
    if (state === 'idle') return;
    const id = setTimeout(() => setState('idle'), 2000);
    return () => clearTimeout(id);
  }, [state]);

  const handleCopy = useCallback(async () => {
    setState((await copyToClipboard(msg.content)) ? 'copied' : 'failed');
  }, [msg.content]);

  const handleDownload = useCallback(() => {
    const provenance = [
      `# ${tr('dc_settings_title')}`,
      ``,
      `- **${tr('kb_base')}:** ${knowledge || '(none)'}`,
      `- **${tr('dc_scope')}** ${folderPath || tr('dc_whole_base')}`,
      msg.contextChip
        ? `- **${tr('dc_context_chip', { files: msg.contextChip.fileCount, chars: msg.contextChip.charCount.toLocaleString() })}**`
        : null,
    ].filter((line) => line !== null).join('\n');
    downloadAsMarkdown(msg.content, downloadName(knowledge, new Date()), provenance);
  }, [msg.content, msg.contextChip, knowledge, folderPath, tr]);

  return (
    <div className="flex items-center gap-1 mt-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
      <button
        type="button"
        title={state === 'failed' ? tr('dc_copy_failed') : tr('dc_copy_message')}
        aria-label={tr('dc_copy_message')}
        onClick={handleCopy}
        style={btnMiniStyle(t)}
      >
        {state === 'copied' ? <Check size={10} /> : <Copy size={10} />}
      </button>

      {msg.role === 'assistant' && (
        <>
          <button
            type="button"
            title={tr('dc_download_answer')}
            aria-label={tr('dc_download_answer')}
            onClick={handleDownload}
            style={btnMiniStyle(t)}
          >
            <Download size={10} />
          </button>
          <button
            type="button"
            title={tr('dc_regenerate')}
            aria-label={tr('dc_regenerate')}
            onClick={onRegenerate}
            style={btnMiniStyle(t)}
          >
            <RotateCcw size={10} />
          </button>
        </>
      )}

      {msg.role === 'user' && (
        <button
          type="button"
          title={tr('dc_edit_resend')}
          aria-label={tr('dc_edit_resend')}
          onClick={() => onEditStart(msg)}
          style={btnMiniStyle(t)}
        >
          <Pencil size={10} />
        </button>
      )}

      {/* Last in the row, so the label appearing does not shove the other buttons sideways. */}
      {state !== 'idle' && (
        <span
          role="status"
          style={{
            fontSize: 10,
            color: state === 'copied' ? '#22c55e' : '#e5484d',
            marginLeft: 2,
          }}
        >
          {state === 'copied' ? tr('dc_copied') : tr('dc_copy_failed')}
        </span>
      )}
    </div>
  );
}

// ── Component ─────────────────────────────────────────

export default function DocChatPanel({
  knowledge,
  folderPath,
  scopeOptions = [],
  scope = '',
  onScopeChange,
  onOpenDoc,
}: DocChatPanelProps) {
  const t = useLayoutTokens();
  // `t` is this file's design-token object, so the translator is `tr` throughout.
  const { t: tr } = useTranslation('chat');
  const {
    messages,
    conversationId,
    isStreaming,
    status,
    error,
    conversations,
    send,
    cancel,
    regenerate,
    editAndResend,
    clearMessages,
    loadConversation,
    deleteConversation,
    refreshConversations,
  } = useDocChat();

  // The chat's scope is the shared selection, chosen in the dropdown above and in scope of this
  // component: `knowledge` is the base and `folderPath` the folder inside it, both derived from
  // the one scope path by the caller. There is no local copy to fall out of step with.
  const activeScope = folderPath;

  const [input, setInput] = useState('');
  const [showHistory, setShowHistory] = useState(false);
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [editText, setEditText] = useState('');

  // ── LLM settings ──────────────────────────────────
  // Doc Chat carries no LLM settings of its own. It answers with the app's default model and its
  // default sampling, both resolved server-side, so the request omits them entirely. Per-panel
  // overrides meant this one panel could answer with a different model and temperature from
  // everywhere else, which is a second source of truth for a setting that should have one.
  const [codeModal, setCodeModal] = useState<{ filename: string; code: string } | null>(null);
  const [loadingCode, setLoadingCode] = useState(false);

  // Scroll to bottom when new messages arrive
  const messagesEndRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Textarea auto-grow
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const ta = textareaRef.current;
    if (ta) {
      ta.style.height = 'auto';
      ta.style.height = Math.min(ta.scrollHeight, INPUT_MAX_HEIGHT) + 'px';
    }
  }, [input]);

  // ── Handlers ────────────────────────────────────────

  const handleSend = useCallback(() => {
    // NOT `!activeScope`. The scope is a string, and "" is a real scope meaning the whole knowledge
    // base — the most common one. Treating it as "no scope" made Send do nothing at all, silently:
    // the button looked live, the click ran, and the guard returned. Chatting with the whole base
    // is the default, so this broke the default case.
    if (!input.trim() || isStreaming) return;
    send(input.trim(), activeScope, knowledge);
    setInput('');
  }, [input, activeScope, isStreaming, send, knowledge]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const handleCancel = useCallback(() => {
    cancel();
    setEditingMessageId(null);
  }, [cancel]);

  const handleRegenerate = useCallback(() => {
    // "" is the whole base, not a missing scope. See handleSend.
    regenerate(activeScope, knowledge);
  }, [activeScope, regenerate, knowledge]);

  const handleEditStart = useCallback((msg: DocChatMessage) => {
    setEditingMessageId(msg.id);
    setEditText(msg.content);
  }, []);

  const handleEditCancel = useCallback(() => {
    setEditingMessageId(null);
    setEditText('');
  }, []);

  const handleEditSubmit = useCallback(() => {
    // "" is the whole base, not a missing scope. See handleSend.
    if (!editingMessageId) return;
    editAndResend(editingMessageId, editText, activeScope, knowledge);
    setEditingMessageId(null);
    setEditText('');
  }, [editingMessageId, editText, activeScope, editAndResend, knowledge]);

  /** Fetch the backend doc-chat source and show it in the code viewer. */
  const handleViewCode = useCallback(async () => {
    if (loadingCode) return;
    setLoadingCode(true);
    try {
      const { file, code } = await getDocChatCode();
      setCodeModal({ filename: file, code });
    } catch (err) {
      console.error('Failed to load doc-chat code:', err);
    } finally {
      setLoadingCode(false);
    }
  }, [loadingCode]);

  // ── Derived status label ────────────────────────────

  let statusLabel: string | null = null;
  if (status.kind === 'reading') {
    statusLabel = tr('dc_reading', { path: status.folderPath });
  } else if (status.kind === 'streaming') {
    statusLabel = tr('dc_thinking');
  }

  // ── Render ──────────────────────────────────────────

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflow: 'hidden',
        background: t.bgContent,
      }}
    >
      {/* ── Header ──────────────────────────────────── */}
      <div
        style={{
          height: 36,
          display: 'flex',
          alignItems: 'center',
          padding: '0 10px',
          borderBottom: `1px solid ${t.border}`,
          background: t.bgBase,
          gap: 8,
          fontSize: 12,
          color: t.textMuted,
          flexShrink: 0,
        }}
      >
        <FolderOpen size={12} style={{ color: '#a855f7', flexShrink: 0 }} />
        <span style={{ fontSize: 11, flexShrink: 0 }}>{tr('dc_scope')}</span>
        {/* The full list, at every level — every knowledge base and every folder inside it. The
            scope is chosen here, next to the chat it affects, and published to shared state so
            the Knowledge sidebar's browser and document list follow the same one. */}
        <select
          value={scope}
          onChange={(ev) => onScopeChange?.(ev.target.value)}
          title={scope}
          style={{
            flex: 1,
            background: 'transparent',
            border: 'none',
            color: t.textPrimary,
            fontSize: 12,
            outline: 'none',
            cursor: 'pointer',
            minWidth: 0,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {scopeOptions.map((opt) => (
            <option key={opt.path} value={opt.path}>{scopeOptionLabel(opt)}</option>
          ))}
          {/* A scope that exists on disk but is not in the fetched tree yet — a folder uploaded a
              moment ago — still has to be representable. */}
          {scope && !scopeOptions.some((opt) => opt.path === scope) && (
            <option value={scope}>{scope}</option>
          )}
        </select>

        {/* View code — shows the backend doc-chat implementation */}
        <button
          title={tr('dc_view_code')}
          onClick={handleViewCode}
          disabled={loadingCode}
          style={{
            background: 'transparent',
            border: 'none',
            color: t.textMuted,
            cursor: loadingCode ? 'default' : 'pointer',
            padding: 2,
            display: 'flex',
            alignItems: 'center',
            opacity: loadingCode ? 0.5 : 1,
          }}
        >
          <Code2 size={13} />
        </button>

        <button
          title={tr('history')}
          onClick={() => setShowHistory((v) => !v)}
          style={{
            background: 'transparent',
            border: 'none',
            color: t.textMuted,
            cursor: 'pointer',
            padding: 2,
            display: 'flex',
            alignItems: 'center',
            position: 'relative',
          }}
        >
          <History size={13} />
          {conversations.length > 0 && (
            <span
              style={{
                position: 'absolute',
                top: -4,
                right: -4,
                background: '#a855f7',
                color: '#fff',
                fontSize: 9,
                borderRadius: 8,
                width: 14,
                height: 14,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {conversations.length}
            </span>
          )}
        </button>
        <button
          title={tr('dc_new_chat')}
          onClick={clearMessages}
          style={{
            background: 'transparent',
            border: 'none',
            color: t.textMuted,
            cursor: 'pointer',
            padding: 2,
            display: 'flex',
            alignItems: 'center',
          }}
        >
          <X size={12} />
        </button>
      </div>

      {/* ── History drawer overlay ──────────────────── */}
      {showHistory && (
        <div
          style={{
            position: 'absolute',
            top: 36,
            right: 10,
            zIndex: 10,
            boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
          }}
        >
          <DocChatHistory
            conversations={conversations}
            activeConversationId={conversationId}
            onLoad={(id) => {
              loadConversation(id, activeScope);
              setShowHistory(false);
            }}
            onDelete={deleteConversation}
            onRefresh={refreshConversations}
          />
        </div>
      )}

      {/* ── Messages area ───────────────────────────── */}
      <div
        style={{
          flex: 1,
          overflow: 'auto',
          padding: '8px 10px',
          position: 'relative',
        }}
      >
        {/* Status banner */}
        {statusLabel && (
          <div
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              padding: '4px 10px',
              background: '#a855f722',
              color: '#c084fc',
              fontSize: 11,
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              zIndex: 2,
            }}
          >
            <Loader size={10} style={{ animation: 'spin 1s linear infinite' }} />
            {statusLabel}
          </div>
        )}

        {messages.length === 0 ? (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              color: t.textMuted,
              fontSize: 13,
              textAlign: 'center',
              gap: 8,
            }}
          >
            <Bot size={24} style={{ opacity: 0.3 }} />
            <p style={{ margin: 0 }}>
              {tr('dc_empty_prompt')}
            </p>
            {/* One sentence with the path interpolated, rather than text wrapped around a <code>
                element: splitting a sentence on a mid-sentence value is untranslatable, because
                word order around it is language-specific. */}
            <p style={{ margin: 0, fontSize: 11 }}>
              {tr('dc_empty_hint', { path: folderPath || tr('dc_whole_base') })}
            </p>
          </div>
        ) : (
          messages.map((msg) => {
            const isUser = msg.role === 'user';
            const isAssistant = msg.role === 'assistant';
            const isEditing = editingMessageId === msg.id;

            return (
              <div
                key={msg.id}
                /* `group` is what the actions row keys its `group-hover` off — hover the message,
                   the buttons appear. */
                className="group"
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: isUser ? 'flex-end' : 'flex-start',
                  marginBottom: 12,
                }}
              >
                {/* Role indicator */}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                    fontSize: 10,
                    color: t.textMuted,
                    marginBottom: 2,
                    marginLeft: isUser ? 'auto' : 0,
                    marginRight: isUser ? 0 : 'auto',
                  }}
                >
                  {isAssistant && <Bot size={10} />}
                  {isUser && <User size={10} />}
                  <span>{isUser ? tr('dc_role_you') : tr('dc_role_assistant')}</span>
                </div>

                {/* Context chip (assistant only) */}
                {isAssistant && msg.contextChip && (
                  <div
                    style={{
                      fontSize: 10,
                      color: t.textMuted,
                      background: t.bgHover,
                      padding: '2px 8px',
                      borderRadius: 4,
                      marginBottom: 4,
                    }}
                  >
                    {tr('dc_context_chip', { files: msg.contextChip.fileCount, chars: msg.contextChip.charCount.toLocaleString() })}
                  </div>
                )}

                {/* Bubble */}
                <div
                  style={{
                    maxWidth: '90%',
                    padding: '8px 12px',
                    borderRadius: 8,
                    background: isUser ? '#a855f7' : t.bgBase,
                    color: isUser ? '#fff' : t.textPrimary,
                    fontSize: 13,
                    lineHeight: 1.5,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    border: isUser ? 'none' : `1px solid ${t.border}`,
                  }}
                >
                  {isEditing ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      <textarea
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && !e.shiftKey) {
                            e.preventDefault();
                            handleEditSubmit();
                          }
                          if (e.key === 'Escape') handleEditCancel();
                        }}
                        autoFocus
                        style={{
                          width: '100%',
                          minHeight: 60,
                          background: t.bgInput,
                          border: `1px solid ${t.border}`,
                          borderRadius: 4,
                          padding: '6px 8px',
                          color: t.textPrimary,
                          fontSize: 13,
                          fontFamily: 'inherit',
                          resize: 'vertical',
                          outline: 'none',
                        }}
                      />
                      <div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end' }}>
                        <button onClick={handleEditSubmit} style={btnSmallStyle(t)}>
                          {tr('dc_save')}
                        </button>
                        <button onClick={handleEditCancel} style={btnSmallStyle(t)}>
                          {tr('cancel')}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      {msg.content ? (
                        isAssistant ? (
                          renderCitations(msg.content, (name) => tr('dc_open_source', { name }), onOpenDoc)
                        ) : (
                          msg.content
                        )
                      ) : (
                        msg.streaming && (
                          <span className="typing-cursor" style={{ opacity: 0.6 }}>
                            ▌
                          </span>
                        )
                      )}
                    </>
                  )}
                </div>

                {/* Message actions — always visible, dimmed until pointed at. They used to be
                    hidden behind a second, inner opacity that only the row itself could clear,
                    which left copy and download unreachable in practice. */}
                {!isEditing && !msg.streaming && (
                  <MessageActions
                    msg={msg}
                    knowledge={knowledge}
                    folderPath={folderPath}
                    onRegenerate={handleRegenerate}
                    onEditStart={handleEditStart}
                    t={t}
                  />
                )}
              </div>
            );
          })
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Error banner */}
      {error && (
        <div
          style={{
            padding: '6px 10px',
            background: '#e5484d22',
            color: '#e5484d',
            fontSize: 11,
            borderTop: `1px solid #e5484d44`,
            flexShrink: 0,
          }}
        >
          {error}
        </div>
      )}

      {/* ── Input row ───────────────────────────────── */}
      <div
        style={{
          borderTop: `1px solid ${t.border}`,
          padding: '8px 10px',
          background: t.bgBase,
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', gap: 6, alignItems: 'flex-end' }}>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={tr('dc_input_placeholder')}
            rows={1}
            disabled={isStreaming}
            style={{
              flex: 1,
              minHeight: 32,
              maxHeight: INPUT_MAX_HEIGHT,
              background: t.bgContent,
              border: `1px solid ${t.border}`,
              borderRadius: 6,
              padding: '6px 10px',
              color: t.textPrimary,
              fontSize: 13,
              fontFamily: 'inherit',
              resize: 'none',
              outline: 'none',
              lineHeight: 1.4,
            }}
          />
          {isStreaming ? (
            <button
              title={tr('cancel')}
              onClick={handleCancel}
              style={{
                height: 32,
                width: 32,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: '#e5484d',
                border: 'none',
                borderRadius: 6,
                color: '#fff',
                cursor: 'pointer',
                flexShrink: 0,
              }}
            >
              <Square size={12} />
            </button>
          ) : (
            <button
              title={tr('dc_send')}
              onClick={handleSend}
              disabled={!input.trim()}
              style={{
                height: 32,
                width: 32,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: input.trim() ? '#a855f7' : t.textMuted,
                border: 'none',
                borderRadius: 6,
                color: '#fff',
                cursor: input.trim() ? 'pointer' : 'default',
                opacity: input.trim() ? 1 : 0.4,
                flexShrink: 0,
              }}
            >
              <Send size={12} />
            </button>
          )}
        </div>
      </div>

      {/* ── Code viewer modal ── */}
      {codeModal && (
        <CodeViewerModal
          filename={codeModal.filename}
          code={codeModal.code}
          onClose={() => setCodeModal(null)}
        />
      )}
    </div>
  );
}

// ── Shared button styles ─────────────────────────────

function btnMiniStyle(t: ReturnType<typeof useLayoutTokens>): React.CSSProperties {
  return {
    background: 'transparent',
    border: 'none',
    color: t.textMuted,
    cursor: 'pointer',
    padding: 2,
    display: 'flex',
    alignItems: 'center',
  };
}

function btnSmallStyle(t: ReturnType<typeof useLayoutTokens>): React.CSSProperties {
  return {
    padding: '2px 8px',
    fontSize: 11,
    background: t.bgContent,
    border: `1px solid ${t.border}`,
    borderRadius: 4,
    color: t.textPrimary,
    cursor: 'pointer',
    fontFamily: 'inherit',
  };
}
