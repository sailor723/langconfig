/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useRef, useEffect, useState } from 'react';
import { Activity, Copy, CheckCircle, AlertCircle, X, User } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { ChatMessage, SessionDocument, CustomEventPayload } from '../types/chat';
import MessageInput from './MessageInput';
import SessionDocumentsPanel from './SessionDocumentsPanel';
import ThinkingBlock from './ThinkingBlock';
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
  activeToolCalls?: string[];
  customEvents?: Map<string, CustomEventPayload>;
  thinkingTraces?: ThinkingStep[][];
}

export default function MessagesPanel({
  messages,
  isStreaming,
  error,
  onSendMessage,
  onClearError,
  disabled = false,
  sessionId = null,
  activeToolCalls = [],
  customEvents = new Map(),
  thinkingTraces = [],
}: MessagesPanelProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [documentsRefreshKey, setDocumentsRefreshKey] = useState(0);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isStreaming]);

  const copyToClipboard = (text: string, index: number) => {
    navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  return (
    <div className="flex-1 flex flex-col min-w-0" style={{ backgroundColor: 'var(--color-background-light)' }}>
      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        {messages.length === 0 && !disabled ? (
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
              <p className="text-lg font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                Start a conversation
              </p>
              <p className="text-sm leading-relaxed">
                Ask anything — I can help with research, analysis, coding, and more.
              </p>
            </div>
          </div>
        ) : (
          <div className="w-full space-y-3 mx-8">

          {messages.map((message, index) => (
            <div
              key={index}
              className={`flex gap-4 ${message.role === 'user' ? 'flex-row-reverse' : ''}`}
            >
              {/* Avatar */}
              {message.role !== 'system' && (
                <div
                  className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 mt-1"
                  style={{
                    backgroundColor: message.role === 'user' ? 'var(--color-primary)' : '#e5e7eb',
                    color: message.role === 'user' ? 'white' : '#6b7280',
                    fontSize: '0.75rem',
                    fontWeight: 600,
                  }}
                >
                  {message.role === 'user' ? (
                    <User className="w-4 h-4" />
                  ) : (
                    'AI'
                  )}
                </div>
              )}

              {/* Message Content */}
              <div className={`flex-1 ${message.role === 'user' ? 'flex justify-end' : ''}`}>
                <div className={`${message.role === 'system' ? 'text-center w-full' : 'max-w-6xl'}`}>
                  {message.role === 'system' ? (
                    <div
                      className="text-sm px-4 py-2 rounded-lg inline-block"
                      style={{
                        color: 'var(--color-text-muted)',
                        backgroundColor: '#e5e7eb',
                      }}
                    >
                      {message.content}
                    </div>
                  ) : (
                    <>
                      {/* Message Bubble */}
                      <div
                        className={`rounded-2xl px-4 py-2.5 ${
                          message.role === 'user' ? 'rounded-tr-sm' : 'rounded-tl-sm'
                        }`}
                        style={{
                          backgroundColor: message.role === 'user' ? 'var(--color-primary)' : 'white',
                          color: message.role === 'user' ? 'white' : 'var(--color-text-primary)',
                          boxShadow: message.role === 'assistant' ? '0 1px 2px rgba(0, 0, 0, 0.05)' : 'none',
                          lineHeight: '1.5',
                        }}
                      >
                        <div
                          className="prose prose-xs max-w-none"
                          style={{
                            color: message.role === 'user' ? 'white' : 'inherit',
                            lineHeight: '1.65',
                            fontSize: '0.81rem',
                          }}
                        >
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            components={{
                              code({ node, inline, className, children, ...props }: any) {
                                const match = /language-(\w+)/.exec(className || '');
                                return !inline && match ? (
                                  <div className="relative group my-3">
                                    <SyntaxHighlighter
                                      style={vscDarkPlus}
                                      language={match[1]}
                                      PreTag="div"
                                      customStyle={{
                                        margin: 0,
                                        borderRadius: '0.5rem',
                                        fontSize: '0.875rem',
                                      }}
                                      {...props}
                                    >
                                      {String(children).replace(/\n$/, '')}
                                    </SyntaxHighlighter>
                                  </div>
                                ) : (
                                  <code
                                    className={`${className} px-1.5 py-0.5 rounded text-sm`}
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
                                return <p style={{ marginBottom: '0.75rem', marginTop: '0.75rem' }}>{children}</p>;
                              },
                              ul({ children }) {
                                return <ul style={{ marginLeft: '1.25rem', marginBottom: '0.75rem' }}>{children}</ul>;
                              },
                              ol({ children }) {
                                return <ol style={{ marginLeft: '1.25rem', marginBottom: '0.75rem' }}>{children}</ol>;
                              },
                              h1({ children }) {
                                return <h1 style={{ fontSize: '1.5rem', fontWeight: '600', marginTop: '1rem', marginBottom: '0.5rem' }}>{children}</h1>;
                              },
                              h2({ children }) {
                                return <h2 style={{ fontSize: '1.25rem', fontWeight: '600', marginTop: '0.875rem', marginBottom: '0.5rem' }}>{children}</h2>;
                              },
                              h3({ children }) {
                                return <h3 style={{ fontSize: '1.125rem', fontWeight: '600', marginTop: '0.75rem', marginBottom: '0.5rem' }}>{children}</h3>;
                              },
                              // Table components for GFM tables
                              table({ children }) {
                                return (
                                  <div className="overflow-x-auto my-3">
                                    <table
                                      style={{
                                        width: '100%',
                                        borderCollapse: 'collapse',
                                        fontSize: '0.875rem',
                                        border: '1px solid #e5e7eb',
                                        borderRadius: '0.5rem',
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
                                      padding: '0.75rem 1rem',
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
                                      padding: '0.75rem 1rem',
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
                        // Count assistant messages up to this index
                        const aiIdx = messages.slice(0, index + 1).filter(m => m.role === 'assistant').length - 1;
                        const trace = thinkingTraces[aiIdx];
                        if (trace && trace.length > 0) {
                          return <ThinkingBlock steps={trace} />;
                        }
                        return null;
                      })()}

                      {/* Message Footer */}
                      <div className={`flex items-center gap-2 mt-2 px-2 ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        <span
                          className="text-xs"
                          style={{ color: 'var(--color-text-muted)' }}
                        >
                          {new Date(message.timestamp).toLocaleTimeString()}
                        </span>

                        {message.role === 'assistant' && (
                          <button
                            onClick={() => copyToClipboard(message.content, index)}
                            className="p-1.5 rounded-lg hover:bg-gray-200 transition-colors"
                            title="Copy message"
                            style={{ color: 'var(--color-text-muted)' }}
                          >
                            {copiedIndex === index ? (
                              <CheckCircle className="w-3.5 h-3.5" style={{ color: '#10b981' }} />
                            ) : (
                              <Copy className="w-3.5 h-3.5" />
                            )}
                          </button>
                        )}
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>
          ))}

          {/* Streaming Indicator - only show before first token */}
          {isStreaming && messages.length > 0 && messages[messages.length - 1].role === 'user' && (
            <div className="flex gap-4">
              <div
                className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 mt-1"
                style={{ backgroundColor: '#e5e7eb', color: '#6b7280', fontSize: '0.75rem', fontWeight: 600 }}
              >
                AI
              </div>
              <div className="flex-1">
                <div
                  className="rounded-2xl rounded-tl-sm px-5 py-3 inline-block"
                  style={{
                    backgroundColor: 'white',
                    boxShadow: '0 1px 2px rgba(0, 0, 0, 0.05)',
                  }}
                >
                  <div className="flex items-center gap-2" style={{ color: 'var(--color-text-muted)' }}>
                    <Activity className="w-4 h-4 animate-pulse" />
                    <span className="text-sm">Thinking...</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Active Tool Calls Indicator */}
          {activeToolCalls.length > 0 && (
            <div className="flex gap-4">
              <div
                className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0"
                style={{ backgroundColor: 'var(--color-primary)', color: 'white' }}
              >
                <Activity className="w-4 h-4 animate-pulse" />
              </div>
              <div className="flex-1">
                <div
                  className="rounded-2xl rounded-tl-sm px-5 py-3 inline-block"
                  style={{
                    backgroundColor: 'white',
                    boxShadow: '0 1px 2px rgba(0, 0, 0, 0.05)',
                    borderLeft: '3px solid var(--color-primary)'
                  }}
                >
                  <div style={{ color: 'var(--color-text-primary)' }}>
                    <div className="text-sm font-medium mb-1">Running tools:</div>
                    <div className="flex flex-wrap gap-2">
                      {activeToolCalls.map((tool, idx) => (
                        <span
                          key={idx}
                          className="text-xs px-2 py-1 rounded"
                          style={{
                            backgroundColor: 'var(--color-primary)',
                            color: 'white'
                          }}
                        >
                          {tool}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Custom Events (LangGraph-style progress, status, file operations) */}
          {customEvents.size > 0 && (
            <div className="flex gap-4">
              <div
                className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0"
                style={{ backgroundColor: 'var(--color-primary)', color: 'white' }}
              >
                <Activity className="w-4 h-4" />
              </div>
              <div className="flex-1">
                <div
                  className="rounded-2xl rounded-tl-sm px-5 py-3 space-y-2"
                  style={{
                    backgroundColor: 'white',
                    boxShadow: '0 1px 2px rgba(0, 0, 0, 0.05)',
                    borderLeft: '3px solid var(--color-primary)'
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

      {/* Input Area */}
      <div
        className="p-4 border-t"
        style={{ borderColor: 'var(--color-border-dark)' }}
      >
        <MessageInput
          onSendMessage={onSendMessage}
          disabled={disabled}
          isStreaming={isStreaming}
          placeholder={disabled ? "Select an agent first..." : "Type your message..."}
          sessionId={sessionId}
          onFileUploaded={(file) => {
            console.log('File uploaded:', file);
            setDocumentsRefreshKey(k => k + 1);
            // Auto-trigger data analysis after CSV upload
            if (file.filename.toLowerCase().endsWith('.csv') && onSendMessage) {
              setTimeout(() => {
                onSendMessage(
                  `I just uploaded ${file.filename}. Please run the auto-analysis workflow: ` +
                  `1) read the CSV to understand columns and data, ` +
                  `2) generate 10 key metrics overview, ` +
                  `3) identify top 3 findings, ` +
                  `4) provide detailed analysis with charts, ` +
                  `5) save results.`
                );
              }, 500);
            }
          }}
        />
      </div>
    </div>
  );
}
