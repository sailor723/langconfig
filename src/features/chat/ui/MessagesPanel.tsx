/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useRef, useEffect, useState } from 'react';
import { Activity, Copy, CheckCircle, AlertCircle, X, Brain, ChevronDown, ChevronRight, Wrench, BarChart3, Loader2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { ChatMessage, CustomEventPayload, ToolCall } from '../types/chat';
import CodexMessageInput from './CodexMessageInput';
import SessionDocumentsPanel from './SessionDocumentsPanel';
import ThinkingBlock from './ThinkingBlock';
import AnalysisPanel from './AnalysisPanel';
import type { ThinkingStep } from './ThinkingBlock';
import { ContentBlockRenderer } from '@/components/common/ContentBlockRenderer';
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
  // Analysis panel state — dashboard auto-generated after CSV upload
  const [dashboardUrl, setDashboardUrl] = useState('');
  const [showAnalysis, setShowAnalysis] = useState(false);
  const [analysisMeta, setAnalysisMeta] = useState<{rowCount: number; colCount: number} | null>(null);
  const [csvUploading, setCsvUploading] = useState(false);

  // Derive project name for Codex empty state heading
  const projectName = agentName || 'my workspace';

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isStreaming]);

  const copyToClipboard = (text: string, index: number) => {
    navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 2000);
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
              <h1 className="text-2xl font-semibold mb-2 text-center" style={{ color: 'var(--color-text-primary)' }}>
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
                  fontSize: '1.25rem',
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
              className="mb-3"
            >


              {/* Message Content */}
              <div className="w-full">
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
                          padding: '4px 0',
                          marginLeft: message.role === 'user' ? '0' : '0',
                          borderLeft: message.role === 'user' ? '2px solid var(--color-primary)' : '2px solid transparent',
                          paddingLeft: '12px',
                        }}
                      >
                        <div
                          className="prose prose-xs max-w-none"
                          style={{
                            color: message.role === 'user' ? 'white' : 'inherit',
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
                                    className={`${className} px-1 py-0.5 rounded text-[0.7rem]`}
                                    style={{
                                      backgroundColor: message.role === 'user' ? 'rgba(255,255,255,0.2)' : '#f3f4f6',
                                      color: message.role === 'user' ? 'white' : '#1f2937',
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
                                return <h1 style={{ fontSize: '0.95rem', fontWeight: '600', marginTop: '0.6rem', marginBottom: '0.3rem' }}>{children}</h1>;
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
                                        fontSize: '0.7rem',
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

                      {/* Thinking Block — show tool calls for this assistant message */}
                      {message.role === 'assistant' && (() => {
                        const aiIdx = messages.slice(0, index + 1).filter(m => m.role === 'assistant').length - 1;
                        const trace = thinkingTraces[aiIdx] || [];
                        return <ThinkingBlock steps={trace} />;
                      })()}

                      {/* During streaming: thinking toggle inside the last assistant message */}
                      {isStreaming && message.role === 'assistant' && index === messages.length - 1 && (activeToolCalls.length > 0 || thinkingBuffer) && (
                        <div className="mt-1 px-2">
                          <button
                            onClick={() => setShowThinking(v => !v)}
                            className="flex items-center gap-1 text-xs transition-colors rounded px-1.5 py-0.5 hover:bg-black/5"
                            style={{ color: 'var(--color-text-muted)' }}
                          >
                            {showThinking ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                            <Brain className="w-3 h-3" />
                            <span>{showThinking ? 'Hide thinking' : `Show thinking (${activeToolCalls.length} active)`}</span>
                          </button>
                          {/* Expanded: show thinking text */}
                          {showThinking && thinkingBuffer && (
                            <div
                              className="mt-1 rounded-lg border p-3 text-xs whitespace-pre-wrap"
                              style={{
                                backgroundColor: 'rgba(99,102,241,0.04)',
                                borderColor: 'var(--color-border-dark, #e5e7eb)',
                                color: 'var(--color-text-muted)',
                              }}
                            >
                              {thinkingBuffer}
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
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>
          ))}

          {/* Streaming Indicator */}
          {isStreaming && messages.length > 0 && messages[messages.length - 1].role === 'user' && (
            <div className="flex-1 min-w-0 ml-1">
                {/* Compact toggle — no big bubble */}
                <button
                  onClick={() => setShowThinking(v => !v)}
                  className="flex items-center gap-1.5 text-xs transition-colors rounded-md px-2 py-1 hover:bg-black/5"
                  style={{ color: 'var(--color-text-muted)' }}
                >
                  {showThinking ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                  <Brain className="w-3 h-3" />
                  <span>{showThinking ? 'Hide thinking' : `Show thinking (${activeToolCalls.length} active)`}</span>
                  {!showThinking && activeToolCalls.length > 0 && <span className="ml-1 text-xs opacity-60 animate-pulse">Thinking...</span>}
                  {!showThinking && activeToolCalls.length === 0 && <span className="ml-1 text-xs opacity-60 animate-pulse">Processing...</span>}
                </button>

                {/* Expanded: show thinking text + active tool calls */}
                {showThinking && (
                  <div className="mt-2">
                    {thinkingBuffer && (
                      <div
                        className="rounded-lg border p-3 text-xs whitespace-pre-wrap mb-2"
                        style={{
                          backgroundColor: 'rgba(99,102,241,0.04)',
                          borderColor: 'var(--color-border-dark, #e5e7eb)',
                          color: 'var(--color-text-muted)',
                        }}
                      >
                        {thinkingBuffer}
                      </div>
                    )}
                    {activeToolCalls.length === 0 ? (
                      !thinkingBuffer && (
                        <div className="text-xs italic px-2" style={{ color: 'var(--color-text-muted)' }}>
                          Waiting for tool calls...
                        </div>
                      )
                    ) : (
                      <div
                        className="rounded-lg border text-xs font-mono overflow-hidden"
                        style={{
                          backgroundColor: 'var(--color-background-dark, #f9fafb)',
                          borderColor: 'var(--color-border-dark, #e5e7eb)',
                        }}
                      >
                        <div className="max-h-72 overflow-y-auto p-3 space-y-2">
                          {activeToolCalls.map((tc, i) => (
                            <div key={i} className="flex items-start gap-2">
                              <Wrench className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-blue-500" />
                              <div className="flex-1 min-w-0">
                                <div className="font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                                  🔧 {tc.tool_name} <span className="text-xs opacity-60">{tc.status === 'running' ? '...' : '✓'}</span>
                                </div>
                                {tc.arguments && (
                                  <pre className="mt-0.5 p-1.5 rounded text-[11px] whitespace-pre-wrap overflow-x-auto" style={{ backgroundColor: 'rgba(0,0,0,0.03)', color: 'var(--color-text-muted)' }}>
                                    {JSON.stringify(tc.arguments, null, 2).slice(0, 200)}
                                  </pre>
                                )}
                                {tc.result && (
                                  <div className="mt-0.5 p-1.5 rounded text-[11px]" style={{ backgroundColor: 'rgba(16,185,129,0.06)', color: 'var(--color-text-muted)' }}>
                                    {tc.result.slice(0, 200)}
                                    {tc.result.length > 200 && '...'}
                                  </div>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
          )}

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

      {/* Input Area — Codex-style composer */}
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
    </div>
  );
}
