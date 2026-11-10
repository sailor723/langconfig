/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useRef, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Activity, Copy, CheckCircle, AlertCircle, X, Brain, User, ChevronDown, ChevronRight, Wrench, Download } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { ChatMessage, ContextOccupancy, CustomEventPayload, InterruptData, SessionDocument, ToolCall } from '../types/chat';
import { formatCompactDateTime, formatFullDateTime } from '../utils/formatChatTime';
import CodexMessageInput, { COMPOSER_MAX_WIDTH } from './CodexMessageInput';
import HitlApprovalPanel from './HitlApprovalPanel';
import { ContentBlockRenderer } from '@/components/common/ContentBlockRenderer';
import type { ThinkingStep } from './ThinkingBlock';
import { ProgressCard, StatusBadge, FileOperationCard } from '@/features/workflows/execution/CustomEventCards';
import type { ProgressEvent, StatusEvent, FileStatusEvent } from '@/hooks/useCustomEvents';

interface MessagesPanelProps {
  messages: ChatMessage[];
  /** Pending HITL review: rendered as one more assistant turn, not an overlay. */
  pendingInterrupt?: InterruptData | null;
  isResuming?: boolean;
  onResume?: (
    action: 'approve' | 'reject' | 'edit' | 'respond',
    value?: string,
    editedAction?: { name: string; args: Record<string, unknown> },
  ) => void;
  isStreaming: boolean;
  error: string | null;
  onSendMessage: (message: string) => void;
  /** Stop the in-flight run (the composer's send button becomes this). */
  onStop?: () => void;
  onClearError: () => void;
  disabled?: boolean;
  sessionId?: string | null;
  projectId?: number | null;
  activeToolCalls?: ToolCall[];
  customEvents?: Map<string, CustomEventPayload>;
  thinkingTraces?: ThinkingStep[][];
  thinkingBuffer?: string;
  /**
   * Workspace (project) this conversation runs in. The empty-state heading asks
   * "what should we build in X?" — X is the workspace, not the agent. Feeds
   * `projectName` below.
   */
  workspaceName?: string;
  /**
   * Agent the composer sends to. Shown in the composer's control row, which
   * used to carry the workspace name instead. Separate from `workspaceName`,
   * which still feeds the empty-state heading.
   */
  agentName?: string;
  /** Context occupancy for the composer's meter. */
  context?: ContextOccupancy | null;
  /**
   * Session stats for the line under the composer — the same facts the window's
   * bottom bar used to carry, moved onto the composer's axis the way DSH's
   * stats strip sits under its input. Null while there is no session.
   */
  stats?: { tokens: number; toolCalls: number; theme?: string } | null;
}

/**
 * Kick the agent off after a document upload.
 *
 * An upload is a request: the file is already in the workspace, so waiting for
 * the user to also type "please read it" is a step that exists only because the
 * UI stayed quiet. Data files keep their dashboard path (handled separately).
 */
const DOC_UPLOAD_EXTS = ['pdf', 'md', 'markdown', 'txt', 'docx', 'pptx', 'xlsx', 'xls', 'html', 'htm', 'json', 'rtf'];

const isDocumentUpload = (filename: string) => {
  const ext = filename.split('.').pop()?.toLowerCase() || '';
  return DOC_UPLOAD_EXTS.includes(ext);
};

const uploadKickoffMessage = (filenames: string[]) => {
  const what = filenames.length === 1
    ? `附件「${filenames[0]}」`
    : ` ${filenames.length} 个附件（${filenames.join('、')}）`;
  return `我已上传${what}。请先用一行确认你收到了，然后立刻开始处理：能读就直接读并给出它的结构与关键信息；`
    + `读不了就直接说明原因和缺什么工具。不要反问我是否需要读。`;
};

export default function MessagesPanel({
  messages,
  pendingInterrupt = null,
  isResuming = false,
  onResume,
  isStreaming,
  error,
  onSendMessage,
  onStop,
  onClearError,
  disabled = false,
  sessionId = null,
  projectId = null,
  activeToolCalls = [],
  customEvents = new Map(),
  thinkingTraces = [],
  thinkingBuffer = '',
  workspaceName,
  agentName,
  context,
  stats = null,
}: MessagesPanelProps) {
  const { t: tr } = useTranslation('chat');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [showThinking, setShowThinking] = useState(true);
  const streamingStartRef = useRef<number>(0);
  const [elapsedMs, setElapsedMs] = useState(0);
  // Analysis panel state — dashboard auto-generated after CSV upload

  // Codex-style heading: the workspace is the "where", the agent is the "who".
  // This used to render the AGENT name under the word "in", which labelled an
  // agent as a workspace — the platform's hierarchy is workspace > agent > chat.
  const projectName = workspaceName || 'this workspace';

  // Live timer for streaming thinking duration
  useEffect(() => {
    if (!isStreaming) {
      setElapsedMs(0);
      return;
    }
    if (streamingStartRef.current === 0) streamingStartRef.current = Date.now();
    const interval = setInterval(() => {
      setElapsedMs(Date.now() - streamingStartRef.current);
    }, 100);
    return () => clearInterval(interval);
  }, [isStreaming]);

  // Auto-scroll to bottom as new content arrives. During streaming the
  // assistant's message grows one chunk at a time, so we follow it live with an
  // instant jump (`auto`) instead of a smooth scroll — smooth scrolling on every
  // token queues up animations and lags behind the output. Once the run
  // finishes, the final message settles in with a smooth scroll.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: isStreaming ? 'auto' : 'smooth' });
  }, [messages, isStreaming]);

  const copyToClipboard = (text: string, index: number) => {
    navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 2000);
  };
  const downloadAsFile = (text: string, filename: string) => {
    navigator.clipboard.writeText(text);
    const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  // ── Upload handler — announce, do not build a dashboard ─────────
  /** Announce an upload in one turn so the agent starts reading immediately.
   *
   * `handleCsvUpload` used to live here: it POSTed `/api/analysis/init` and showed
   * the generated page. That is gone — a chat upload is not a dashboard request,
   * and the page it produced was hand-written HTML from an LLM rather than the
   * dashboard agent's deterministic generator. Data files are announced like any
   * other document; the agent reads the CSV text that is already in the
   * conversation.
   */
  const announceUploads = (files: SessionDocument[]) => {
    const docs = (files || []).filter(f => isDocumentUpload(f.filename));
    if (docs.length) onSendMessage(uploadKickoffMessage(docs.map(f => f.filename)));
  };

  // ── Empty state ───────────────────────────────────────────────
  // Toggle Codex-style layout — true by default for new sessions
  const useCodexLayout = true; // messages.length === 0;

  return (
    <div className="flex-1 flex flex-col min-w-0" style={{ backgroundColor: 'var(--color-background-light)' }}>
      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto px-6 pt-4 pb-2">
        {messages.length === 0 && !disabled && useCodexLayout ? (
          // Codex-style empty state: centered heading + composer
          <div className="flex flex-col items-center justify-center h-full min-h-full">
            {/* No width cap here: the composer card carries the width rule, and
                applying the same percentage at this level too would compound —
                62% of 62% — leaving the box pinned to its floor in the empty
                state while it grew in a conversation. */}
            <div className="w-full">
              <h1 className="text-xl font-semibold mb-2 text-center" style={{ color: 'var(--color-text-primary)' }}>
                What should we build in <span className="font-bold">{projectName}</span>?
              </h1>
              <CodexMessageInput
                onSendMessage={onSendMessage}
                onStop={onStop}
                disabled={disabled}
                isStreaming={isStreaming}
                placeholder={disabled ? "No agent selected" : "Do anything"}
                sessionId={sessionId}
                projectId={projectId}
                onFileUploaded={(file) => {
                  // Every upload gets the same treatment: announce it so the agent
                  // reads it now. CSV/SQLite used to branch into dashboard
                  // generation — that branch is gone (dashboards belong to the
                  // dashboard agent).
                  announceUploads([file]);
                }}
                onMultipleUploaded={announceUploads}
                agentName={agentName}
                context={context}
              />
            </div>
          </div>
        ) : messages.length === 0 && !disabled ? (
          // Original empty state
          <div
            className="flex items-center justify-center h-full min-h-full"
            style={{ color: 'var(--color-text-muted)' }}
          >
            <div className="text-center max-w-md px-6">
              <div
                className="w-12 h-12 mx-auto mb-5 rounded-xl flex items-center justify-center"
                style={{
                  backgroundColor: 'var(--color-primary)',
                  color: 'white',
                  fontSize: '1rem',
                }}
              >
                ✦
              </div>
              <p className="text-base font-medium mb-1" style={{ color: 'var(--color-text-primary)' }}>
                Start a conversation
              </p>
              <p className="text-xs leading-relaxed">
                Ask anything about your documents — graphindex routes your
                query to the right ones, loads them, and answers from their
                content.
              </p>
            </div>
          </div>
        ) : (
          <div className="w-full space-y-3 px-8">

          {messages.map((message, index) => (
            <div
              key={index}
              className="flex items-start gap-2 mb-4 group"
            >
              {/* AI avatar — left side */}
              {message.role === 'assistant' && (
                <div
                  className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0"
                  style={{
                    backgroundColor: 'rgba(59, 130, 246, 0.15)',
                    color: '#3b82f6',
                    marginTop: 2,
                  }}
                >
                  <Brain size={14} strokeWidth={2} />
                </div>
              )}

              <div className={`min-w-0 ${message.role === 'user' ? 'max-w-[60%] ml-auto' : 'max-w-[80%]'}`}>
                <div className={`${message.role === 'system' || (message as any).role === 'handoff' ? 'text-center w-full' : 'max-w-6xl'}`}>
                  {(message as any).role === 'handoff' ? (
                    <div
                      className="text-xs px-3 py-1.5 rounded-lg inline-flex items-center gap-2"
                      style={{
                        color: 'var(--color-text-primary)',
                        backgroundColor: 'rgba(245, 158, 11, 0.12)',
                        border: '1px solid rgba(245, 158, 11, 0.35)',
                      }}
                    >
                      {/* The hop is an edge: show both ends. A single target
                          ("转交给 finance") hides who handed over, which is the
                          half of the transfer the reader needs to follow it. */}
                      {(message as any).from_label || (message as any).from_step ? (
                        <span className="inline-flex items-center gap-1.5">
                          <span>{((message as any).from_label || (message as any).from_step)}</span>
                          <span aria-hidden>→</span>
                          <span>{((message as any).to_label || (message as any).to || '另一角色')}</span>
                        </span>
                      ) : (
                        <span>转交给「{(message as any).to_label || (message as any).to || '另一角色'}」</span>
                      )}
                      {(message as any).reason && (
                        <span style={{ color: 'var(--color-text-muted)' }}>· {(message as any).reason}</span>
                      )}
                    </div>
                  ) : message.role === 'system' ? (
                    <div
                      className="text-xs px-3 py-1.5 rounded-lg inline-block"
                      style={{
                        color: 'var(--color-text-muted)',
                        backgroundColor: 'var(--color-input-background, #e5e7eb)',
                      }}
                    >
                      {message.content}
                    </div>
                  ) : (
                    <>
                      {/* Message Content */}
                      <div
                          style={{
                            padding: message.role === 'user' ? '8px 12px' : '4px 0',
                            marginLeft: message.role === 'user' ? '0' : '0',
                            minWidth: 0,
                            overflowWrap: 'anywhere',
                            wordBreak: 'break-word',
                            // The user's own turn gets a bubble; the assistant's
                            // stays plain text on the panel. The fill and the
                            // 22px radius live in index.css (.chat-user-bubble):
                            // an inline var(--color-background-dark) is rewritten
                            // to panelDark by the theme layer, which made the
                            // bubble the same colour as the panel — no box at all.
                            backgroundColor: 'transparent',
                            border: 'none',
                        }}
                        className={message.role === 'user' ? 'chat-user-bubble' : ''}
                      >
                        <div
                          className="prose prose-sm max-w-none"
                          style={{
                            color: message.role === 'user' ? 'var(--color-text-primary)' : 'inherit',
                            lineHeight: '1.55',
                            fontSize: '0.75rem',
                          }}
                        >
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            components={{
                              code({ node, inline, className, children, ...props }: any) {
                                const match = /language-(\w+)/.exec(className || '');
                                return !inline && match ? (
                                  <div className="relative group my-2" style={{ maxWidth: '100%', minWidth: 0, overflowX: 'auto' }}>
                                    <SyntaxHighlighter
                                      style={vscDarkPlus}
                                      language={match[1]}
                                      PreTag="div"
                                      customStyle={{
                                        margin: 0,
                                        borderRadius: '0.375rem',
                                        fontSize: '0.7rem',
                                      }}
                                      {...props}
                                    >
                                      {String(children).replace(/\n$/, '')}
                                    </SyntaxHighlighter>
                                  </div>
                                ) : (
                                  <code
                                    className={`${className} px-1 py-0.5 rounded text-[0.75rem]`}
                                    style={{
                                      backgroundColor: 'var(--color-input-background, #f3f4f6)',
                                      color: 'var(--color-text-primary, #1f2937)',
                                      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
                                    }}
                                    {...props}
                                  >
                                    {children}
                                  </code>
                                );
                              },
                              p({ children }) {
                                return <p style={{ marginBottom: '0.5rem', marginTop: '0.5rem' }}>{children}</p>;
                              },
                              ul({ children }) {
                                return <ul style={{ marginLeft: '1.1rem', marginBottom: '0.5rem' }}>{children}</ul>;
                              },
                              ol({ children }) {
                                return <ol style={{ marginLeft: '1.1rem', marginBottom: '0.5rem' }}>{children}</ol>;
                              },
                              h1({ children }) {
                                return <h1 style={{ fontSize: '1rem', fontWeight: '600', marginTop: '0.6rem', marginBottom: '0.3rem' }}>{children}</h1>;
                              },
                              h2({ children }) {
                                return <h2 style={{ fontSize: '0.875rem', fontWeight: '600', marginTop: '0.55rem', marginBottom: '0.3rem' }}>{children}</h2>;
                              },
                              h3({ children }) {
                                return <h3 style={{ fontSize: '0.8rem', fontWeight: '600', marginTop: '0.5rem', marginBottom: '0.3rem' }}>{children}</h3>;
                              },
                              // Table components for GFM tables
                              table({ children }) {
                                return (
                                  <div className="overflow-x-auto my-2">
                                    <table
                                      style={{
                                        width: '100%',
                                        borderCollapse: 'collapse',
                                        fontSize: '0.75rem',
                                        border: '1px solid var(--color-border-dark, #e5e7eb)',
                                        borderRadius: '0.375rem',
                                        overflow: 'hidden',
                                      }}
                                    >
                                      {children}
                                    </table>
                                  </div>
                                );
                              },
                              thead({ children }) {
                                return (
                                  <thead style={{ backgroundColor: 'var(--color-input-background, #f9fafb)' }}>
                                    {children}
                                  </thead>
                                );
                              },
                              tbody({ children }) {
                                return <tbody>{children}</tbody>;
                              },
                              tr({ children }) {
                                return (
                                  <tr style={{ borderBottom: '1px solid var(--color-border-dark, #e5e7eb)' }}>
                                    {children}
                                  </tr>
                                );
                              },
                              th({ children }) {
                                return (
                                  <th
                                    style={{
                                      padding: '0.35rem 0.5rem',
                                      textAlign: 'left',
                                      fontWeight: '600',
                                      color: 'var(--color-text-primary, #374151)',
                                      borderBottom: '2px solid var(--color-border-dark, #e5e7eb)',
                                    }}
                                  >
                                    {children}
                                  </th>
                                );
                              },
                              td({ children }) {
                                return (
                                  <td
                                    style={{
                                      padding: '0.35rem 0.5rem',
                                      color: 'var(--color-text-primary, #4b5563)',
                                    }}
                                  >
                                    {children}
                                  </td>
                                );
                              },
                            }}
                          >
                            {message.content}
                          </ReactMarkdown>
                        </div>

                        {/* Multimodal Content Blocks (images, audio, files from MCP tools) */}
                        {message.has_multimodal && message.content_blocks && message.content_blocks.length > 0 && (
                          <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-700">
                            <ContentBlockRenderer blocks={message.content_blocks} />
                          </div>
                        )}

                        {/* Artifacts (UI-only content, not sent to LLM) */}
                        {message.artifacts && message.artifacts.length > 0 && (
                          <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-700">
                            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2 font-medium">{tr('mg_generated_content')}</p>
                            <ContentBlockRenderer blocks={message.artifacts} />
                          </div>
                        )}
                      </div>

                      {/* Thinking & Tool Calls toggle */}
                      {message.role === 'assistant' && index === messages.length - 1 && isStreaming && (
                        <div className="mt-2">
                          {/* Toggle button */}
                          <button
                            onClick={() => setShowThinking(v => !v)}
                            className="flex items-center gap-1.5 text-[11px] font-medium transition-colors rounded-md px-2 py-1 hover:bg-black/5"
                            style={{ color: 'var(--color-text-muted)' }}
                          >
                            {showThinking ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                            <Brain className="w-3 h-3" />
                            <span>
                              {activeToolCalls.length > 0
                                ? `Thinking (${activeToolCalls.length} step${activeToolCalls.length !== 1 ? 's' : ''})`
                                : tr('mg_thinking')}
                            </span>
                            <span className="text-[10px] ml-0.5">{(elapsedMs / 1000).toFixed(1)}s</span>
                            {!showThinking && activeToolCalls.some(t => t.status === 'running') && (
                              <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse ml-1" />
                            )}
                          </button>

                          {/* Expanded content */}
                          {showThinking && (
                            <div className="mt-1.5 rounded-lg border-l-2 p-2.5 text-xs space-y-1.5"
                              style={{
                                borderLeftColor: 'var(--color-primary)',
                                borderColor: 'var(--color-border-dark, #e5e7eb)',
                                backgroundColor: 'var(--color-input-background, #f9fafb)',
                              }}
                            >
                              {/* Thinking buffer (current work) */}
                              {thinkingBuffer && (
                                <div className="flex items-start gap-1.5">
                                  <span className="text-muted flex-shrink-0 mt-0.5">💡</span>
                                  <div style={{ color: 'var(--color-text-muted)' }} className="text-[11px] leading-relaxed">{thinkingBuffer}</div>
                                </div>
                              )}
                              {/* Todo steps from planning */}
                              {(() => {
                                const steps = Array.from(customEvents.entries())
                                  .filter(([_, ev]) => ev.event_type === 'progress' || ev.event_type === 'status')
                                  .map(([id, ev]) => ({
                                    id,
                                    label: ev.payload.label || ev.event_type,
                                    status: ev.event_type === 'progress'
                                      ? (ev.payload.status || 'running')
                                      : (ev.payload.status || 'pending'),
                                    message: ev.payload.message || '',
                                  }));
                                if (steps.length === 0) return null;
                                const runningCount = steps.filter(s => s.status === 'running').length;
                                const doneCount = steps.filter(s => s.status === 'success').length;
                                return (
                                  <div className="space-y-0.5 mb-1">
                                    <div className="text-[10px] font-medium mb-1" style={{ color: 'var(--color-text-muted)' }}>
                                      Plan ({doneCount}/{steps.length})
                                    </div>
                                    {steps.map((step) => (
                                      <div key={step.id} className="flex items-center gap-1.5 text-[11px]">
                                        <span className="flex-shrink-0">
                                          {step.status === 'success' ? '✅' :
                                           step.status === 'running' ? '🔄' :
                                           step.status === 'error' ? '❌' : '⏳'}
                                        </span>
                                        <span style={{ color: 'var(--color-text-primary)' }}>{step.label}</span>
                                        {step.status === 'running' && (
                                          <span className="text-blue-500 text-[10px] animate-pulse">{tr('mg_in_progress')}</span>
                                        )}
                                        {step.message && step.status !== 'running' && (
                                          <span className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>{step.message}</span>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                );
                              })()}
                              {/* Tool calls (action steps) */}
                              {activeToolCalls.map((tc, i) => (
                                <div key={i} className="flex items-start gap-1.5">
                                  <span className="flex-shrink-0 mt-0.5">{tc.status === 'running' ? '🔧' : '✅'}</span>
                                  <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2">
                                      <span className="font-mono font-medium text-xs" style={{ color: 'var(--color-text-primary)' }}>
                                        {tc.tool_name}
                                      </span>
                                      {tc.status === 'running' ? (
                                        <span className="text-blue-500 text-[10px] animate-pulse">{tr('mg_running')}</span>
                                      ) : (
                                        <span style={{ color: '#10b981' }} className="text-[10px]">{tr('mg_done')}</span>
                                      )}
                                      <span className="text-[10px] ml-auto" style={{ color: 'var(--color-text-muted)' }}>
                                        {tc.timestamp ? ((Date.now() - new Date(tc.timestamp).getTime()) / 1000).toFixed(1) + 's' : ''}
                                      </span>
                                    </div>
                                    {tc.arguments && Object.keys(tc.arguments).length > 0 && Object.values(tc.arguments).some(v => v) && (
                                      <div className="text-[10px] truncate mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
                                        {JSON.stringify(tc.arguments).slice(0, 120)}
                                      </div>
                                    )}
                                  </div>
                                </div>
                              ))}
                              {/* Total elapsed */}
                              <div className="text-[10px] pt-1 border-t" style={{ color: 'var(--color-text-muted)', borderColor: 'var(--color-border-dark)' }}>
                                Total: {(elapsedMs / 1000).toFixed(1)}s
                              </div>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Message Footer. Messages stored before the streaming
                          endpoint stamped a timestamp carry none, and
                          `new Date(undefined).toLocaleTimeString()` printed
                          "Invalid Date" under every one of them — so the time is
                          rendered only when it parses, and the shared formatter
                          returns '' otherwise. */}
                      <div className="flex items-center gap-3 mt-1 px-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <span
                          className="text-[11px]"
                          style={{ color: 'var(--color-text-muted)' }}
                          title={formatFullDateTime(message.timestamp) || undefined}
                        >
                          {message.role === 'user' ? tr('mg_you') : message.role === 'assistant' ? tr('mg_assistant') : tr('mg_system')}
                          {formatCompactDateTime(message.timestamp) && ` · ${formatCompactDateTime(message.timestamp)}`}
                        </span>
                        <button
                          onClick={() => copyToClipboard(message.content, index)}
                          className="p-1 hover:bg-gray-200 rounded transition-colors"
                          title={tr('mg_copy')}
                          style={{ color: 'var(--color-text-muted)' }}
                        >
                          {copiedIndex === index ? (
                            <CheckCircle className="w-3 h-3" style={{ color: '#10b981' }} />
                          ) : (
                            <Copy className="w-3 h-3" />
                          )}
                        </button>
                        <button
                          onClick={() => downloadAsFile(message.content, `${message.role === 'assistant' ? 'answer' : 'question'}-${index}.md`)}
                          className="p-1 hover:bg-gray-200 rounded transition-colors"
                          title={tr('mg_download')}
                          style={{ color: 'var(--color-text-muted)' }}
                        >
                          <Download className="w-3 h-3" />
                        </button>
                      </div>
                    </>
                  )}
                </div>
              </div>

              {/* User avatar — right side */}
              {message.role === 'user' && (
                <div
                  className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0"
                  style={{
                    backgroundColor: 'rgba(156, 163, 175, 0.2)',
                    color: '#6b7280',
                    marginTop: 2,
                  }}
                >
                  <User size={14} strokeWidth={2} />
                </div>
              )}
            </div>
          ))}
          {/* Custom Events (LangGraph-style progress, status, file operations) */}
          {customEvents.size > 0 && (
            <div className="flex-1">
              <div
                className="px-3 py-2 space-y-2"
                style={{
                  borderLeft: '2px solid var(--color-primary)',
                  paddingLeft: '12px',
                }}
              >
                  {Array.from(customEvents.values()).map((event, idx) => {
                    const eventId = event.event_id || `custom-${idx}`;

                    // Convert CustomEventPayload to the component-specific event format
                    if (event.event_type === 'progress') {
                      const progressEvent: ProgressEvent = {
                        id: eventId,
                        data: {
                          label: event.payload.label || tr('mg_progress'),
                          value: event.payload.value || 0,
                          total: event.payload.total,
                          message: event.payload.message,
                        },
                        toolName: event.tool_name,
                        agentLabel: event.agent_label,
                        nodeId: event.node_id,
                        timestamp: event.timestamp || new Date().toISOString(),
                      };
                      return <ProgressCard key={eventId} event={progressEvent} compact />;
                    }

                    if (event.event_type === 'status') {
                      const statusEvent: StatusEvent = {
                        id: eventId,
                        data: {
                          label: event.payload.label || 'Status',
                          status: event.payload.status || 'running',
                          message: event.payload.message,
                        },
                        toolName: event.tool_name,
                        agentLabel: event.agent_label,
                        nodeId: event.node_id,
                        timestamp: event.timestamp || new Date().toISOString(),
                      };
                      return <StatusBadge key={eventId} event={statusEvent} compact />;
                    }

                    if (event.event_type === 'file_status') {
                      const fileEvent: FileStatusEvent = {
                        id: eventId,
                        data: {
                          filename: event.payload.filename || 'file',
                          operation: event.payload.operation || 'reading',
                          size_bytes: event.payload.size_bytes,
                          message: event.payload.message,
                        },
                        toolName: event.tool_name,
                        agentLabel: event.agent_label,
                        nodeId: event.node_id,
                        timestamp: event.timestamp || new Date().toISOString(),
                      };
                      return <FileOperationCard key={eventId} event={fileEvent} compact />;
                    }

                    // Generic custom event - show as simple badge
                    return (
                      <div
                        key={eventId}
                        className="text-xs px-2 py-1 rounded"
                        style={{
                          backgroundColor: 'var(--color-background-dark)',
                          color: 'var(--color-text-primary)'
                        }}
                      >
                        {event.event_type}: {JSON.stringify(event.payload)}
                      </div>
                    );
                  })}
                </div>
              </div>
          )}

          <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Error Display */}
      {error && (
        <div className="mx-4 mb-2 p-3 rounded-lg flex items-center gap-2 border">
          <div
            style={{
              backgroundColor: 'rgba(239, 68, 68, 0.1)',
              borderColor: 'rgba(239, 68, 68, 0.5)',
              color: 'rgb(239, 68, 68)',
            }}
            className="flex-1 flex items-center gap-2"
          >
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span className="text-sm flex-1">{error}</span>
            <button
              onClick={onClearError}
              className="hover:opacity-70 transition-opacity"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Composer block: the box and its stats line, at the foot of the chat
          area. pb-2 rather than the old pb-6 — that 24px read as dead space
          under the box, which now sits a few pixels above the window's bottom
          bar, the way DSH ends its column. */}
      {pendingInterrupt && onResume ? (
        <div className="px-6 pt-4 pb-2">
          <HitlApprovalPanel
            pendingInterrupt={pendingInterrupt}
            isResuming={Boolean(isResuming)}
            onResume={onResume}
          />
        </div>
      ) : (messages.length > 0 || disabled) && (
      <div className="px-6 pt-4 pb-2">
        <CodexMessageInput
          onSendMessage={onSendMessage}
          onStop={onStop}
          disabled={disabled}
          isStreaming={isStreaming}
          placeholder={disabled ? "No agent selected" : "Do anything"}
          sessionId={sessionId}
          projectId={projectId}
          agentName={agentName}
          context={context}
          onFileUploaded={(file) => {
            console.log('File uploaded:', file);
            // NO dashboard on upload (2026-11-04).
            //
            // This used to call `/api/analysis/init` for CSV/SQLite and then open
            // the Analysis panel with a freshly generated page. That made the CHAT
            // agent look like a dashboard builder, and it produced a hand-written
            // Plotly page nobody asked for (see `api/analysis/routes.py`). The CSV's
            // text is already appended to this conversation, which is all the chat
            // agent needs; dashboards have one producer — the dashboard agent.
            // Everything else that is a document: acknowledge and start reading
            // now, in the same turn, rather than waiting for the user to ask.
            if (isDocumentUpload(file.filename)) {
              announceUploads([file]);
            }
          }}
          onMultipleUploaded={announceUploads}
        />
        {/* Stats strip: centred on the composer's axis, directly under the box.
            DSH's own line excludes context occupancy on purpose — that number
            has one home, the ring beside send. */}
        {stats && (
          <div
            className="mx-auto w-full mt-2 text-center text-[11px]"
            style={{ maxWidth: COMPOSER_MAX_WIDTH, color: 'var(--color-text-muted)' }}
          >
            <span>
              <span className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
                {stats.tokens.toLocaleString()}
              </span>{' '}
              tokens
            </span>
            {/* No tool-call count here: the Metrics panel owns that number
                (with the call list), and repeating it under the composer read
                as a second, disagreeing source. */}
            <span className="mx-2">·</span>
            <span>{messages.length} message{messages.length !== 1 ? 's' : ''}</span>
            {stats.theme && (
              <>
                <span className="mx-2">·</span>
                <span className="capitalize">{stats.theme}</span>
              </>
            )}
          </div>
        )}
      </div>
      )}
    </div>
  );
}
