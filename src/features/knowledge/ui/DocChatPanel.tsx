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
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  FolderOpen,
  Bot,
  User,
  Send,
  Square,
  Copy,
  Download,
  RotateCcw,
  Pencil,
  History,
  X,
  Loader,
  SlidersHorizontal,
  Code2,
} from 'lucide-react';
import { useLayoutTokens } from '../../../components/layout2/tokens';
import { useDocChat } from '../useDocChat';
import type { DocChatMessage, DocChatLlmOptions } from '../../../lib/api-doc-chat';
import { listDocChatFolders, getDocChatCode } from '../../../lib/api-doc-chat';
import DocChatHistory from './DocChatHistory';
import CodeViewerModal from '../../../components/layout2/CodeViewerModal';
import { useAvailableModels } from '../../../hooks/useAvailableModels';

// ── Constants ─────────────────────────────────────────

const INPUT_MAX_HEIGHT = 180;

/** Regex that matches `[Source: filename.md]` (with optional trailing
 *  punctuation) at the end of a sentence, or as a standalone token. */
const CITATION_RE = /\[Source:\s*([^\]]+\.\w+)\]\s*/g;

// ── Props ─────────────────────────────────────────────

interface DocChatPanelProps {
  /** Folder path to scope the chat to (e.g. "industry/player"). */
  folderPath: string;
  projectId?: number | null;
  /** Called when the user clicks a citation chip. */
  onOpenDoc?: (docName: string) => void;
}

// ── Helper: render citations inline ───────────────────

/** Render message content with clickable citation chips. */
function renderCitations(
  content: string,
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
        title={`Open ${docName}`}
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

function downloadAsMarkdown(content: string) {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `doc-chat-response-${Date.now()}.md`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Helper: copy to clipboard ─────────────────────────

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text).catch(() => {
    // Fallback: ignore
  });
}

// ── Component ─────────────────────────────────────────

export default function DocChatPanel({
  folderPath,
  projectId,
  onOpenDoc,
}: DocChatPanelProps) {
  const t = useLayoutTokens();
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

  // Scope options derived from filesystem folder scanning
  const [scopeOptions, setScopeOptions] = useState<Array<{ value: string; label: string }>>([]);
  const [overrideScope, setOverrideScope] = useState<string | null>(null);

  useEffect(() => {
    listDocChatFolders(projectId ?? 1).then((folderPaths) => {
      const opts = folderPaths.map((p) => ({
        value: p,
        label: p.replace(/_/g, ' ').replace(/\//g, ' / '),
      }));
      setScopeOptions(opts);
    });
  }, [projectId]);

  // Active scope: overrideScope > folderPath
  const activeScope = overrideScope ?? folderPath;

  const [input, setInput] = useState('');
  const [showHistory, setShowHistory] = useState(false);
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [editText, setEditText] = useState('');

  // ── LLM settings ──────────────────────────────────
  // The model picker + params are sent to the backend on every request so
  // Doc Chat honors the same LLM settings as the rest of the app.
  const { models: availableModels } = useAvailableModels();
  const [llmModel, setLlmModel] = useState<string>('');   // '' = app default model
  const [temperature, setTemperature] = useState(0.0);
  const [maxTokens, setMaxTokens] = useState<string>(''); // '' = model default
  const [showParams, setShowParams] = useState(false);
  const [codeModal, setCodeModal] = useState<{ filename: string; code: string } | null>(null);
  const [loadingCode, setLoadingCode] = useState(false);

  const llmOptions = useMemo<DocChatLlmOptions>(
    () => ({
      model: llmModel || undefined,
      temperature,
      max_tokens: maxTokens ? Number(maxTokens) : undefined,
    }),
    [llmModel, temperature, maxTokens],
  );

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
    if (!input.trim() || !activeScope || isStreaming) return;
    send(input.trim(), activeScope, projectId ?? undefined, llmOptions);
    setInput('');
  }, [input, activeScope, isStreaming, send, projectId, llmOptions]);

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
    if (!activeScope) return;
    regenerate(activeScope, projectId ?? undefined, llmOptions);
  }, [activeScope, regenerate, projectId, llmOptions]);

  const handleEditStart = useCallback((msg: DocChatMessage) => {
    setEditingMessageId(msg.id);
    setEditText(msg.content);
  }, []);

  const handleEditCancel = useCallback(() => {
    setEditingMessageId(null);
    setEditText('');
  }, []);

  const handleEditSubmit = useCallback(() => {
    if (!editingMessageId || !activeScope) return;
    editAndResend(editingMessageId, editText, activeScope, projectId ?? undefined, llmOptions);
    setEditingMessageId(null);
    setEditText('');
  }, [editingMessageId, editText, activeScope, editAndResend, projectId, llmOptions]);

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
    statusLabel = `Reading ${status.folderPath}...`;
  } else if (status.kind === 'streaming') {
    statusLabel = 'Thinking...';
  }

  // ── Render: Message actions row ─────────────────────

  const MessageActions = ({ msg }: { msg: DocChatMessage }) => {
    const [show, setShow] = useState(false);
    return (
      <div
        style={{
          display: 'flex',
          gap: 4,
          opacity: show ? 1 : 0,
          transition: 'opacity 0.12s',
          marginTop: 4,
        }}
        onMouseEnter={() => setShow(true)}
        onMouseLeave={() => setShow(false)}
      >
        <button
          title="Copy"
          onClick={() => copyToClipboard(msg.content)}
          style={btnMiniStyle(t)}
        >
          <Copy size={10} />
        </button>
        {msg.role === 'assistant' && (
          <>
            <button
              title="Download"
              onClick={() => downloadAsMarkdown(msg.content)}
              style={btnMiniStyle(t)}
            >
              <Download size={10} />
            </button>
            <button
              title="Regenerate"
              onClick={handleRegenerate}
              style={btnMiniStyle(t)}
            >
              <RotateCcw size={10} />
            </button>
          </>
        )}
        {msg.role === 'user' && (
          <button
            title="Edit and resend"
            onClick={() => handleEditStart(msg)}
            style={btnMiniStyle(t)}
          >
            <Pencil size={10} />
          </button>
        )}
      </div>
    );
  };

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
        <span style={{ fontSize: 11, flexShrink: 0 }}>Scope:</span>
        {scopeOptions.length > 0 ? (
          <select
            value={activeScope}
            onChange={(e) => setOverrideScope(e.target.value === folderPath ? null : e.target.value)}
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
            title={activeScope}
          >
            {scopeOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        ) : (
          <span
            style={{
              color: t.textPrimary,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              flex: 1,
              fontSize: 12,
            }}
            title={folderPath}
          >
            {folderPath || '(ungrouped)'}
          </span>
        )}
        {/* Model picker — LLM used to answer ('' = app default model) */}
        <select
          value={llmModel}
          onChange={(e) => setLlmModel(e.target.value)}
          title="LLM model (Default = the app's default model)"
          style={{
            maxWidth: 120,
            background: 'transparent',
            border: 'none',
            color: t.textPrimary,
            fontSize: 12,
            outline: 'none',
            cursor: 'pointer',
            flexShrink: 0,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          <option value="">Default</option>
          {availableModels.map((m) => (
            <option key={m.id} value={m.id}>{m.name}</option>
          ))}
        </select>

        {/* LLM params (temperature / max tokens) */}
        <div style={{ position: 'relative' }}>
          <button
            title="LLM settings"
            onClick={() => setShowParams((v) => !v)}
            style={{
              background: 'transparent',
              border: 'none',
              color: showParams ? '#a855f7' : t.textMuted,
              cursor: 'pointer',
              padding: 2,
              display: 'flex',
              alignItems: 'center',
            }}
          >
            <SlidersHorizontal size={13} />
          </button>
          {showParams && (
            <div
              style={{
                position: 'absolute',
                top: 30,
                right: 0,
                zIndex: 30,
                background: t.bgSidebar,
                border: `1px solid ${t.border}`,
                borderRadius: 6,
                boxShadow: '0 8px 24px rgba(0,0,0,0.45)',
                padding: 10,
                width: 200,
                display: 'flex',
                flexDirection: 'column',
                gap: 10,
              }}
            >
              <div>
                <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4 }}>
                  Temperature
                </div>
                <input
                  type="range"
                  min={0}
                  max={2}
                  step={0.1}
                  value={temperature}
                  onChange={(e) => setTemperature(Number(e.target.value))}
                  style={{ width: '100%', accentColor: '#a855f7' }}
                />
                <div style={{ fontSize: 11, fontFamily: 'monospace', color: t.textPrimary, textAlign: 'right' }}>
                  {temperature.toFixed(1)}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4 }}>
                  Max tokens
                </div>
                <input
                  type="number"
                  min={0}
                  step={256}
                  value={maxTokens}
                  placeholder="Model default"
                  onChange={(e) => setMaxTokens(e.target.value)}
                  style={{
                    width: '100%',
                    background: t.bgInput,
                    border: `1px solid ${t.border}`,
                    borderRadius: 4,
                    padding: '3px 6px',
                    fontSize: 12,
                    color: t.textPrimary,
                    outline: 'none',
                    fontFamily: 'inherit',
                  }}
                />
              </div>
            </div>
          )}
        </div>

        {/* View code — shows the backend doc-chat implementation */}
        <button
          title="View code"
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
          title="History"
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
          title="New chat"
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
              Ask a question about the documents in this folder.
            </p>
            <p style={{ margin: 0, fontSize: 11 }}>
              The LLM will read matching files from{' '}
              <code
                style={{
                  background: t.bgHover,
                  padding: '1px 5px',
                  borderRadius: 3,
                  fontSize: 11,
                }}
              >
                {folderPath}
              </code>{' '}
              and answer from context.
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
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: isUser ? 'flex-end' : 'flex-start',
                  marginBottom: 12,
                }}
                onMouseEnter={(e) => {
                  const actions = e.currentTarget.querySelector('.msg-actions') as HTMLElement;
                  if (actions) actions.style.opacity = '1';
                }}
                onMouseLeave={(e) => {
                  const actions = e.currentTarget.querySelector('.msg-actions') as HTMLElement;
                  if (actions) actions.style.opacity = '0';
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
                  <span>{isUser ? 'You' : 'Assistant'}</span>
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
                    Loaded {msg.contextChip.fileCount} files · {msg.contextChip.charCount.toLocaleString()} chars
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
                          Save
                        </button>
                        <button onClick={handleEditCancel} style={btnSmallStyle(t)}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      {msg.content ? (
                        isAssistant ? (
                          renderCitations(msg.content, onOpenDoc)
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

                {/* Message actions (hover-revealed) */}
                {!isEditing && !msg.streaming && (
                  <div className="msg-actions" style={{ opacity: 0, transition: 'opacity 0.15s' }}>
                    <MessageActions msg={msg} />
                  </div>
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
            placeholder="Ask about the documents..."
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
              title="Cancel"
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
              title="Send"
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
