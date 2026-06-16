/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useState, useEffect, useRef, memo } from 'react';
import {
  Send,
  X,
  Trash2,
  Download,
  Activity,
  CheckCircle,
  Circle,
  Zap,
  Users,
  Database,
  AlertCircle,
  Loader,
  Bookmark
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import apiClient from '@/lib/api-client';

interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  banked?: boolean;
}

interface ToolCall {
  tool_name: string;
  arguments: Record<string, any>;
  result: string;
  timestamp: string;
  status: 'running' | 'completed';
}

interface SubAgentActivity {
  subagent_name: string;
  action: string;
  timestamp: string;
}

interface SessionMetrics {
  total_tokens: number;
  tool_calls: number;
  subagent_spawns: number;
  context_operations: number;
}

interface AgentChatTesterProps {
  agentId: number;
  agentName: string;
  onClose: () => void;
}

export default function AgentChatTester({
  agentId,
  agentName,
  onClose
}: AgentChatTesterProps) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([]);
  const [subagentActivity, setSubagentActivity] = useState<SubAgentActivity[]>([]);
  const [metrics, setMetrics] = useState<SessionMetrics>({
    total_tokens: 0,
    tool_calls: 0,
    subagent_spawns: 0,
    context_operations: 0
  });
  const [todos, setTodos] = useState<Array<{ id: number; content: string; status: string }>>([]);
  const [error, setError] = useState<string | null>(null);

  // HITL interrupt state
  const [pendingInterrupt, setPendingInterrupt] = useState<any>(null);
  const [isResuming, setIsResuming] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Start chat session on mount
  useEffect(() => {
    startSession();
    return () => {
      if (sessionId) {
        endSession();
      }
    };
  }, []);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const startSession = async () => {
    try {
      const response = await apiClient.startChatSession(agentId);
      setSessionId(response.data.session_id);

      // Add system message
      setMessages([{
        role: 'system',
        content: `Chat session started with ${agentName}. Ask anything!`,
        timestamp: new Date().toISOString()
      }]);

    } catch (err) {
      setError('Failed to start chat session');
      console.error(err);
    }
  };

  const endSession = async () => {
    if (!sessionId) return;

    try {
      await apiClient.endChatSession(sessionId);
    } catch (err) {
      console.error('Failed to end session:', err);
    }
  };

  const sendMessage = async () => {
    if (!inputValue.trim() || !sessionId || isLoading) return;

    const userMessage = inputValue.trim();
    setInputValue('');
    setIsLoading(true);
    setError(null);

    // Add user message immediately
    const newUserMessage: ChatMessage = {
      role: 'user',
      content: userMessage,
      timestamp: new Date().toISOString()
    };
    setMessages(prev => [...prev, newUserMessage]);

    try {
      // Use streaming endpoint
      const response = await fetch(`${apiClient.baseURL}/api/chat/message/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          message: userMessage
        })
      });

      if (!response.ok) throw new Error('Failed to send message');

      setIsStreaming(true);

      // Create placeholder for assistant message
      const assistantMessage: ChatMessage = {
        role: 'assistant',
        content: '',
        timestamp: new Date().toISOString()
      };
      setMessages(prev => [...prev, assistantMessage]);

      // Read stream
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) throw new Error('No reader available');

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.substring(6));

              if (data.type === 'chunk') {
                // Append to last message (defensive: check lastMsg exists)
                setMessages(prev => {
                  const newMessages = [...prev];
                  const lastMsg = newMessages[newMessages.length - 1];
                  if (lastMsg && data.content != null) {
                    lastMsg.content += String(data.content);
                  }
                  return newMessages;
                });
              } else if (data.type === 'tool_start') {
                // Show tool call in sidebar in real-time
                const toolName = data.tool_name || 'unknown';
                const toolArgs = data.data?.input || data.data?.args || {};
                setToolCalls(prev => [...prev, {
                  tool_name: toolName,
                  arguments: toolArgs,
                  result: '',
                  timestamp: new Date().toISOString(),
                  status: 'running'
                }]);
              } else if (data.type === 'tool_end') {
                // Mark matching tool call as completed
                const toolName = data.tool_name || '';
                const output = data.data?.output || data.data?.result || '';
                const outputStr = typeof output === 'string' ? output : JSON.stringify(output);
                setToolCalls(prev => {
                  // Find the last running tool with matching name
                  const idx = [...prev].reverse().findIndex(
                    t => t.tool_name === toolName && t.status === 'running'
                  );
                  if (idx === -1) return prev;
                  const realIdx = prev.length - 1 - idx;
                  const updated = [...prev];
                  updated[realIdx] = { ...updated[realIdx], result: outputStr, status: 'completed' };
                  return updated;
                });
              } else if (data.type === 'complete') {
                // Final message received
                setMessages(prev => {
                  const newMessages = [...prev];
                  const lastMsg = newMessages[newMessages.length - 1];
                  if (lastMsg) {
                    lastMsg.content = data.content || '';
                  }
                  return newMessages;
                });
              } else if (data.type === 'error') {
                setError(data.message);
              } else if (data.type === 'interrupt') {
                // HITL interrupt: pause and show approval modal
                setPendingInterrupt(data.data || data);
              }
            } catch (e) {
              // Skip invalid JSON
            }
          }
        }
      }

      setIsStreaming(false);

      // Fetch updated metrics (if session still valid)
      if (sessionId) {
        try {
          await fetchMetrics();
        } catch (e) {
          console.error('Metrics fetch failed (non-fatal):', e);
        }
      }

    } catch (err) {
      setError('Failed to send message');
      console.error(err);
      setIsStreaming(false);
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  };

  const fetchMetrics = async () => {
    if (!sessionId) return;

    try {
      const response = await apiClient.getChatMetrics(sessionId);
      const data = response.data;
      // Merge with defaults to handle missing properties from backend
      setMetrics({
        total_tokens: 0,
        tool_calls: 0,
        subagent_spawns: 0,
        context_operations: 0,
        ...(data?.metrics || {})
      });
      setToolCalls(data?.tool_calls || []);
      setSubagentActivity(data?.subagent_spawns || []);
    } catch (err) {
      console.error('Failed to fetch metrics:', err);
    }
  };

  // Resume from interrupt
  const handleResume = async (action: string) => {
    if (!sessionId) return;
    setIsResuming(true);
    try {
      const response = await fetch(`${apiClient.baseURL}/api/chat/${sessionId}/resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      });
      if (!response.ok) throw new Error(`Resume failed: ${response.statusText}`);
      const result = await response.json();

      // Add assistant response from resume result
      if (result.content) {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: result.content,
          timestamp: new Date().toISOString(),
        }]);
      }

      setPendingInterrupt(null);
      await fetchMetrics();
    } catch (err: any) {
      console.error('Failed to resume:', err);
      setError('Failed to resume: ' + err.message);
    } finally {
      setIsResuming(false);
    }
  };

  const toggleBankMessage = async (messageIndex: number) => {
    if (!sessionId) return;

    const message = messages[messageIndex];
    if (message.role === 'system') return; // Don't allow banking system messages

    try {
      const isBanked = message.banked || false;

      if (isBanked) {
        // Unbank message
        await apiClient.apiFetch(`${apiClient.baseURL}/api/chat/${sessionId}/messages/${messageIndex}/bank`, {
          method: 'DELETE'
        });
      } else {
        // Bank message
        await apiClient.apiFetch(`${apiClient.baseURL}/api/chat/${sessionId}/messages/${messageIndex}/bank`, {
          method: 'POST'
        });
      }

      // Update local state
      setMessages(prev => {
        const newMessages = [...prev];
        newMessages[messageIndex] = {
          ...newMessages[messageIndex],
          banked: !isBanked
        };
        return newMessages;
      });
    } catch (err) {
      console.error('Failed to toggle bank message:', err);
      setError('Failed to update message banking status');
    }
  };

  const clearHistory = () => {
    setMessages([{
      role: 'system',
      content: 'Chat history cleared',
      timestamp: new Date().toISOString()
    }]);
    setToolCalls([]);
    setSubagentActivity([]);
    setTodos([]);
  };

  const downloadHistory = () => {
    const history = JSON.stringify({
      agent: agentName,
      session_id: sessionId,
      messages,
      tool_calls: toolCalls,
      subagent_activity: subagentActivity,
      metrics
    }, null, 2);

    const blob = new Blob([history], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `chat_history_${sessionId}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-[#0a0a0a] border border-gray-800 rounded-xl w-full max-w-7xl h-[90vh] flex flex-col shadow-2xl">

        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-800">
          <div>
            <h2 className="text-xl font-semibold text-white">Chat Tester - {agentName}</h2>
            <p className="text-sm text-gray-400 mt-1">
              Test your agent before exporting. Watch tools, subagents, and planning in action.
            </p>
          </div>

          <div className="flex gap-2">
            <button
              onClick={downloadHistory}
              className="p-2 text-gray-400 hover:text-white transition-colors"
              title="Download history"
            >
              <Download className="w-5 h-5" />
            </button>

            <button
              onClick={clearHistory}
              className="p-2 text-gray-400 hover:text-white transition-colors"
              title="Clear history"
            >
              <Trash2 className="w-5 h-5" />
            </button>

            <button
              onClick={onClose}
              className="p-2 text-gray-400 hover:text-white transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        <div className="flex flex-1 overflow-hidden">

          {/* Main Chat Area */}
          <div className="flex-1 flex flex-col">

            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {messages.map((message, index) => (
                <div
                  key={index}
                  className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'} group`}
                >
                  <div className="flex items-start gap-2 max-w-[80%]">
                    {/* Bank button - Left side for assistant messages */}
                    {message.role === 'assistant' && (
                      <button
                        onClick={() => toggleBankMessage(index)}
                        className={`mt-1 p-1.5 rounded transition-all opacity-0 group-hover:opacity-100 ${message.banked
                          ? 'text-yellow-400 hover:text-yellow-500'
                          : 'text-gray-500 hover:text-yellow-400'
                          }`}
                        title={message.banked ? 'Unbank message' : 'Bank for future context'}
                      >
                        <Bookmark className={`w-4 h-4 ${message.banked ? 'fill-current' : ''}`} />
                      </button>
                    )}

                    <div
                      className={`flex-1 rounded-lg p-3 ${message.role === 'user'
                        ? 'bg-blue-600 text-white'
                        : message.role === 'assistant'
                          ? 'bg-gray-800 text-gray-100'
                          : 'bg-gray-700 text-gray-300'
                        }`}
                    >
                      <ReactMarkdown>{message.content}</ReactMarkdown>
                      <div className="text-xs opacity-70 mt-1 flex items-center gap-2">
                        {new Date(message.timestamp).toLocaleTimeString()}
                        {message.banked && (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-yellow-500/20 text-yellow-400">
                            <Bookmark className="w-3 h-3 fill-current" />
                            <span className="text-[10px] font-medium">Banked</span>
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Bank button - Right side for user messages */}
                    {message.role === 'user' && (
                      <button
                        onClick={() => toggleBankMessage(index)}
                        className={`mt-1 p-1.5 rounded transition-all opacity-0 group-hover:opacity-100 ${message.banked
                          ? 'text-yellow-400 hover:text-yellow-500'
                          : 'text-gray-400 hover:text-yellow-400'
                          }`}
                        title={message.banked ? 'Unbank message' : 'Bank for future context'}
                      >
                        <Bookmark className={`w-4 h-4 ${message.banked ? 'fill-current' : ''}`} />
                      </button>
                    )}
                  </div>
                </div>
              ))}

              {isStreaming && (
                <div className="flex justify-start">
                  <div className="bg-gray-800 rounded-lg p-3">
                    <div className="flex items-center gap-2 text-gray-400">
                      <Activity className="w-4 h-4 animate-pulse" />
                      <span className="text-sm">Agent is thinking...</span>
                    </div>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* Error Display */}
            {error && (
              <div className="mx-4 mb-2 p-3 bg-red-600/20 border border-red-600/50 rounded-lg flex items-center gap-2 text-red-400">
                <AlertCircle className="w-4 h-4" />
                <span className="text-sm">{error}</span>
                <button
                  onClick={() => setError(null)}
                  className="ml-auto text-red-400 hover:text-red-300"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            )}

            {/* Input */}
            <div className="p-4 border-t border-gray-800">
              <div className="flex gap-2">
                <input
                  ref={inputRef}
                  type="text"
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyPress={handleKeyPress}
                  placeholder="Type your message..."
                  disabled={isLoading || !sessionId}
                  className="flex-1 px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-white placeholder-gray-500"
                />

                <button
                  onClick={sendMessage}
                  disabled={isLoading || !inputValue.trim() || !sessionId}
                  className="px-6 py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 disabled:cursor-not-allowed rounded-lg transition-colors"
                >
                  <Send className="w-5 h-5" />
                </button>
              </div>
            </div>
          </div>

          {/* Sidebar - Metrics & Activity */}
          <div className="w-80 border-l border-gray-800 overflow-y-auto bg-gray-900/30">

            {/* Metrics */}
            <div className="p-4 border-b border-gray-800">
              <h3 className="text-sm font-semibold text-gray-400 mb-3">SESSION METRICS</h3>

              <div className="space-y-2">
                <MetricItem
                  icon={<Activity className="w-4 h-4" />}
                  label="Total Tokens"
                  value={String(metrics.total_tokens ?? 0)}
                />
                <MetricItem
                  icon={<Zap className="w-4 h-4" />}
                  label="Tool Calls"
                  value={String(metrics.tool_calls ?? 0)}
                />
                <MetricItem
                  icon={<Users className="w-4 h-4" />}
                  label="Subagent Spawns"
                  value={String(metrics.subagent_spawns ?? 0)}
                />
                <MetricItem
                  icon={<Database className="w-4 h-4" />}
                  label="Context Ops"
                  value={String(metrics.context_operations ?? 0)}
                />
              </div>
            </div>

            {/* Todo List */}
            {todos.length > 0 && (
              <div className="p-4 border-b border-gray-800">
                <h3 className="text-sm font-semibold text-gray-400 mb-3">TODO LIST</h3>
                <div className="space-y-2">
                  {todos.map((todo) => (
                    <div key={todo.id} className="flex items-center gap-2 text-sm">
                      {todo.status === 'completed' ? (
                        <CheckCircle className="w-4 h-4 text-green-500" />
                      ) : todo.status === 'in_progress' ? (
                        <Activity className="w-4 h-4 text-blue-500 animate-pulse" />
                      ) : (
                        <Circle className="w-4 h-4 text-gray-500" />
                      )}
                      <span className={todo.status === 'completed' ? 'line-through text-gray-500' : 'text-gray-300'}>
                        {todo.content}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Tool Calls */}
            {toolCalls.length > 0 && (
              <div className="p-4 border-b border-gray-800">
                <h3 className="text-sm font-semibold text-gray-400 mb-3">TOOL CALLS</h3>
                <div className="space-y-2">
                  {toolCalls.slice(-5).reverse().map((call, index) => (
                    <div key={index} className={`p-2 rounded text-xs ${
                      call.status === 'running'
                        ? 'bg-blue-600/10 border border-blue-600/30'
                        : 'bg-gray-800/50'
                    }`}>
                      <div className="flex items-center gap-2">
                        {call.status === 'running' ? (
                          <Activity className="w-3 h-3 text-blue-400 animate-pulse" />
                        ) : (
                          <CheckCircle className="w-3 h-3 text-green-500" />
                        )}
                        <span className={`font-mono ${call.status === 'running' ? 'text-blue-400' : 'text-green-400'}`}>
                          {call.tool_name}
                        </span>
                      </div>
                      {call.arguments && Object.keys(call.arguments).length > 0 && (
                        <div className="text-gray-500 mt-1 truncate">
                          {JSON.stringify(call.arguments)}
                        </div>
                      )}
                      {call.result && (
                        <div className="text-gray-400 mt-0.5 truncate" title={call.result}>
                          → {call.result.slice(0, 60)}
                        </div>
                      )}
                      <div className="text-gray-600 mt-1 text-[10px]">
                        {new Date(call.timestamp).toLocaleTimeString()}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Subagent Activity */}
            {subagentActivity.length > 0 && (
              <div className="p-4">
                <h3 className="text-sm font-semibold text-gray-400 mb-3">SUBAGENT ACTIVITY</h3>
                <div className="space-y-2">
                  {subagentActivity.slice(-5).reverse().map((activity, index) => (
                    <div key={index} className="p-2 bg-purple-600/10 border border-purple-600/30 rounded text-xs">
                      <div className="font-medium text-purple-400">{activity.subagent_name}</div>
                      <div className="text-gray-400 mt-1">{activity.action}</div>
                      <div className="text-gray-500 text-xs mt-1">
                        {new Date(activity.timestamp).toLocaleTimeString()}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

          </div>
        </div>
      </div>

      {/* HITL Interrupt Modal */}
      {pendingInterrupt && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[100]">
          <div
            className="bg-white dark:bg-panel-dark rounded-xl w-full max-w-lg shadow-2xl border"
            style={{ borderColor: 'var(--color-border-dark)' }}
            onClick={e => e.stopPropagation()}
          >
            <div className="px-5 py-3 rounded-t-xl" style={{ backgroundColor: '#f59e0b' }}>
              <h3 className="text-base font-semibold text-white flex items-center gap-2">
                ⏸️ Human Approval Required
              </h3>
              <p className="text-xs text-white/80 mt-0.5">
                An agent action needs your approval before proceeding
              </p>
            </div>

            <div className="p-5 space-y-4">
              {pendingInterrupt.action_requests?.map((req: any, i: number) => (
                <div key={i} className="p-3 rounded-lg border" style={{
                  borderColor: 'var(--color-border-dark)',
                  backgroundColor: 'var(--color-background-light)'
                }}>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                      {req.name}
                    </span>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-800">
                      Tool Call
                    </span>
                  </div>
                  <div className="text-xs space-y-1" style={{ color: 'var(--color-text-secondary)' }}>
                    {req.description && <p className="italic">{req.description}</p>}
                    {req.args && Object.keys(req.args).length > 0 && (
                      <pre className="mt-1 p-2 rounded text-xs font-mono overflow-x-auto" style={{
                        backgroundColor: 'var(--color-background)',
                        maxHeight: '120px'
                      }}>
                        {JSON.stringify(req.args, null, 2)}
                      </pre>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <div className="px-5 py-3 border-t flex items-center justify-end gap-2"
                 style={{ borderColor: 'var(--color-border-dark)' }}>
              <button
                onClick={() => handleResume('reject')}
                disabled={isResuming}
                className="px-4 py-2 rounded-lg text-sm font-medium border"
                style={{
                  borderColor: 'var(--color-border-dark)',
                  color: 'var(--color-text-primary)',
                  backgroundColor: 'var(--color-background-light)'
                }}
              >
                Reject
              </button>
              <button
                onClick={() => handleResume('approve')}
                disabled={isResuming}
                className="px-4 py-2 rounded-lg text-sm font-medium text-white"
                style={{ backgroundColor: '#16a34a' }}
              >
                {isResuming ? 'Resuming...' : 'Approve'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function MetricItem({
  icon,
  label,
  value
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2 text-gray-400">
        {icon}
        <span className="text-sm">{label}</span>
      </div>
      <span className="text-sm font-semibold text-white">{value}</span>
    </div>
  );
}
