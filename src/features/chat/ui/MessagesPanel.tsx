/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useRef, useEffect, useState } from 'react';
import { Activity, Copy, CheckCircle, AlertCircle, X, Brain, ChevronDown, ChevronRight, Wrench, BarChart3, Loader2, Download } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { ChatMessage, CustomEventPayload, ToolCall } from '../types/chat';
import CodexMessageInput from './CodexMessageInput';
import SessionDocumentsPanel from './SessionDocumentsPanel';
import AnalysisPanel from './AnalysisPanel';
import { ContentBlockRenderer } from '@/components/common/ContentBlockRenderer';
import type { ThinkingStep } from './ThinkingBlock';
import { ProgressCard, StatusBadge, FileOperationCard } from '@/features/workflows/execution/CustomEventCards';
import type { ProgressEvent, StatusEvent, FileStatusEvent } from '@/hooks/useCustomEvents';

interface MessagesPanelProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  error: string | null;
  onSendMessage: (message: string) => void;
  onClearError: () => void;
  disabled?: boolean;
  sessionId?: string | null;
  projectId?: number | null;
  activeToolCalls?: ToolCall[];
  customEvents?: Map<string, CustomEventPayload>;
  thinkingTraces?: ThinkingStep[][];
  thinkingBuffer?: string;
  /** Optional agent name shown in composer footer (Codex style) */
  agentName?: string;
}

export default function MessagesPanel({
  messages,
  isStreaming,
  error,
  onSendMessage,
  onClearError,
  disabled = false,
  sessionId = null,
  projectId = null,
  activeToolCalls = [],
  customEvents = new Map(),
  thinkingTraces = [],
  thinkingBuffer = '',
  agentName,
}: MessagesPanelProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [documentsRefreshKey, setDocumentsRefreshKey] = useState(0);
  const [showThinking, setShowThinking] = useState(false);
  const streamingStartRef = useRef<number>(0);
  const [elapsedMs, setElapsedMs] = useState(0);
  // Analysis panel state — dashboard auto-generated after CSV upload
  const [dashboardUrl, setDashboardUrl] = useState('');
  const [showAnalysis, setShowAnalysis] = useState(false);
  const [analysisMeta, setAnalysisMeta] = useState<{rowCount: number; colCount: number} | null>(null);
  const [csvUploading, setCsvUploading] = useState(false);

  // Derive project name for Codex empty state heading
  const projectName = agentName || 'my workspace';

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

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    if (isStreaming) return;
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
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

  // ── CSV upload handler — calls /api/analysis/init + shows dashboard ─
  const handleCsvUpload = (filename: string) => {
    setShowAnalysis(false);
    setCsvUploading(true);
    const csvPath = `outputs/default/${filename}`;
    fetch('/api/analysis/init', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        csv_path: csvPath,
        table_name: filename.replace(/\.csv$/i, '').replace(/[^a-zA-Z0-9_]/g, '_'),
      }),
    })
      .then((res) => res.json())
      .then((data) => {
        setDashboardUrl(data.dashboard_file || '');
        setAnalysisMeta({ rowCount: data.row_count, colCount: data.col_count });
        setShowAnalysis(true);
        setCsvUploading(false);
        if (onSendMessage) {
          onSendMessage(
            `I loaded ${filename} (${data.row_count} rows, ${data.col_count} columns). ` +
              `Here's a quick overview: what columns and data types does it have? ` +
              `Then summarize the key metrics.`
          );
        }
      })
      .catch((err) => {
        console.error('Analysis init failed:', err);
        setCsvUploading(false);
        if (onSendMessage) {
          onSendMessage(
            `I loaded ${filename}. ` +
              `Here's a quick overview: what columns and data types does it have? ` +
              `Then summarize the key metrics.`
          );
        }
      });
  };

  // ── Empty state ───────────────────────────────────────────────
  // Toggle Codex-style layout — true by default for new sessions
  const useCodexLayout = true; // messages.length === 0;

  return (
    <div className="flex-1 flex flex-col min-w-0" style={{ backgroundColor: 'var(--color-background-light)' }}>
      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        {messages.length === 0 && !disabled && useCodexLayout ? (
          // Codex-style empty state: centered heading + composer
          <div className="flex flex-col items-center justify-center h-full min-h-full px-6">
            <div className="w-full max-w-xl">
              <h1 className="text-xl font-semibold mb-2 text-center" style={{ color: 'var(--color-text-primary)' }}>
                What should we build in <span className="font-bold">{projectName}</span>?
              </h1>
              <CodexMessageInput
                onSendMessage={onSendMessage}
                disabled={disabled}
                isStreaming={isStreaming}
                placeholder={disabled ? "No agent selected" : "Do anything"}
                sessionId={sessionId}
                projectId={projectId}
                onFileUploaded={(file) => {
                  handleCsvUpload(file.filename);
                  onSendMessage(
                    `A new document "${file.filename}" has been uploaded. Please read it and provide a briefing.`
                  );
                }}
                agentName={agentName}
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
          <div className="w-full space-y-3 mx-8">

          {messages.map((message, index) => (
            <div
              key={index}
              className="mb-3 group"
            >


              {/* Message Content */}
              <div className={`${message.role === 'user' ? 'max-w-[60%] ml-auto' : 'max-w-[80%]'}`}>
                <div className={`${message.role === 'system' ? 'text-center w-full' : 'max-w-6xl'}`}>
                  {message.role === 'system' ? (
                    <div
                      className="text-xs px-3 py-1.5 rounded-lg inline-block"
                      style={{
                        color: 'var(--color-text-muted)',
                        backgroundColor: '#e5e7eb',
                      }}
                    >
                      {message.content}
                    </div>
                  ) : (
                    <>
                      {/* Message Content */}
                      <div
                        style={{
                          padding: message.role === 'user' ? '6px 10px' : '4px 0',
                          marginLeft: message.role === 'user' ? '0' : '0',
                          // User messages: just a thin border + light
                          // text — no shaded background bubble. The
                          // user asked for a cleaner, less tinted look.
                          backgroundColor: message.role === 'user' ? 'transparent' : 'transparent',
                          border: message.role === 'user' ? '1px solid #cbd5e1' : 'none',
                          paddingLeft: message.role === 'user' ? '10px' : '12px',
                          borderRadius: message.role === 'user' ? '6px' : '0',
                        }}
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
                                  <div className="relative group my-2">
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
                                      backgroundColor: message.role === 'user' ? '#f1f5f9' : '#f3f4f6',
                                      color: message.role === 'user' ? '#334155' : '#1f2937',
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
                                        border: '1px solid #e5e7eb',
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
                                  <thead style={{ backgroundColor: '#f9fafb' }}>
                                    {children}
                                  </thead>
                                );
                              },
                              tbody({ children }) {
                                return <tbody>{children}</tbody>;
                              },
                              tr({ children }) {
                                return (
                                  <tr style={{ borderBottom: '1px solid #e5e7eb' }}>
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
                                      color: '#374151',
                                      borderBottom: '2px solid #e5e7eb',
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
                                      color: '#4b5563',
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
                            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2 font-medium">Generated Content:</p>
                            <ContentBlockRenderer blocks={message.artifacts} />
                          </div>
                        )}
                      </div>

                      {/* Thinking & Tool Calls toggle */}
                      {message.role === 'assistant' && index === messages.length - 1 && (isStreaming && (activeToolCalls.length > 0 || thinkingBuffer)) && (
                        <div className="mt-2">
                          {/* Toggle button */}
                          <button
                            onClick={() => setShowThinking(v => !v)}
                            className="flex items-center gap-1.5 text-[11px] font-medium transition-colors rounded-md px-2 py-1 hover:bg-black/5"
                            style={{ color: 'var(--color-text-muted)' }}
                          >
                            {showThinking ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                            <Brain className="w-3 h-3" />
                            <span>Thinking ({activeToolCalls.length} step{activeToolCalls.length !== 1 ? 's' : ''})</span>
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
                                          <span className="text-blue-500 text-[10px] animate-pulse">in progress...</span>
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
                                        <span className="text-blue-500 text-[10px] animate-pulse">running...</span>
                                      ) : (
                                        <span style={{ color: '#10b981' }} className="text-[10px]">done</span>
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

                      {/* Message Footer */}
                      <div className="flex items-center gap-3 mt-1 px-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <span
                          className="text-[11px]"
                          style={{ color: 'var(--color-text-muted)' }}
                        >
                          {message.role === 'user' ? 'You' : message.role === 'assistant' ? 'Assistant' : 'System'} · {new Date(message.timestamp).toLocaleTimeString()}
                        </span>
                        <button
                          onClick={() => copyToClipboard(message.content, index)}
                          className="p-1 hover:bg-gray-200 rounded transition-colors"
                          title="Copy message"
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
                          title="Download as file"
                          style={{ color: 'var(--color-text-muted)' }}
                        >
                          <Download className="w-3 h-3" />
                        </button>
                      </div>
                    </>
                  )}
                </div>
              </div>
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
                          label: event.payload.label || 'Progress',
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

      {/* Session Documents Panel */}
      <SessionDocumentsPanel sessionId={sessionId} refreshKey={documentsRefreshKey} />

      {/* Data Analysis Button — generate interactive dashboard via current agent */}
      {typeof onSendMessage === 'function' && (
        <div className="px-4 pb-2">
          {csvUploading && (
            <div className="flex items-center justify-center gap-2 py-3 text-sm text-gray-400">
              <Loader2 className="w-4 h-4 animate-spin" />
              Processing CSV &amp; generating dashboard...
            </div>
          )}
          {showAnalysis && dashboardUrl !== '' && (
            <AnalysisPanel
              sessionId={sessionId || ''}
              dashboardUrl={dashboardUrl}
              rowCount={analysisMeta?.rowCount}
              colCount={analysisMeta?.colCount}
              onClose={() => setShowAnalysis(false)}
            />
          )}
          {showAnalysis && dashboardUrl === '' && !csvUploading && (
            <button
              onClick={() => {
                setShowAnalysis(false);
                setTimeout(() => setShowAnalysis(true), 100);
              }}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 
                         bg-blue-50 border border-blue-200 text-blue-700 
                         rounded-lg text-sm font-medium hover:bg-blue-100 transition-all"
            >
              <BarChart3 className="w-4 h-4" />
              Dashboard (regenerate)
            </button>
          )}
        </div>
      )}

      {(messages.length > 0 || disabled) && (
      <div className="px-4 pb-4">
        <CodexMessageInput
          onSendMessage={onSendMessage}
          disabled={disabled}
          isStreaming={isStreaming}
          placeholder={disabled ? "No agent selected" : "Do anything"}
          sessionId={sessionId}
          projectId={projectId}
          agentName={agentName}
          onFileUploaded={(file) => {
            console.log('File uploaded:', file);
            setDocumentsRefreshKey(k => k + 1);
            // Auto-trigger briefing after document upload
            const docExt = file.filename.split('.').pop()?.toLowerCase() || '';
            const briefingExts = ['pdf', 'md', 'txt', 'docx', 'pptx'];
            if (briefingExts.includes(docExt) && onSendMessage) {
              setTimeout(() => {
                onSendMessage(
                  `A new document "${file.filename}" has been uploaded. Please read it and provide a briefing.`
                );
              }, 500);
            }
            // Auto-trigger data analysis after CSV upload
            if (docExt === 'csv') {
              setShowAnalysis(false); // reset if previously open
              setCsvUploading(true);
              // File was saved to sandbox by FileUploadButton
              // Call /api/analysis/init to convert + auto-generate dashboard
              const csvPath = `outputs/default/${file.filename}`;
              fetch('/api/analysis/init', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  session_id: sessionId,
                  csv_path: csvPath,
                  table_name: file.filename.replace(/\.csv$/i, '').replace(/[^a-zA-Z0-9_]/g, '_'),
                }),
              })
                .then(res => res.json())
                .then(data => {
                  setDashboardUrl(data.dashboard_file || '');
                  setAnalysisMeta({ rowCount: data.row_count, colCount: data.col_count });
                  setShowAnalysis(true);
                  setCsvUploading(false);
                  // Send a message to the chat agent for schema overview
                  if (onSendMessage) {
                    onSendMessage(
                      `I loaded ${file.filename} (${data.row_count} rows, ${data.col_count} columns). ` +
                      `Here's a quick overview: what columns and data types does it have? ` +
                      `Then summarize the key metrics.`
                    );
                  }
                })
                .catch(err => {
                  console.error('Analysis init failed:', err);
                  setCsvUploading(false);
                  // Fall back — agent analyzes from sandbox
                  if (onSendMessage) {
                    onSendMessage(
                      `I loaded ${file.filename}. ` +
                      `Here's a quick overview: what columns and data types does it have? ` +
                      `Then summarize the key metrics.`
                    );
                  }
                });
            }
          }}
        />
      </div>
      )}
    </div>
  );
}
