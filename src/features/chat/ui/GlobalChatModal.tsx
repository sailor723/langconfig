/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { X, GripVertical, BarChart3 } from 'lucide-react';
import { useChat } from '../state/ChatContext';
import HitlInterruptModal from './HitlInterruptModal';
import { useChatSession } from '../hooks/useChatSession';
import { useChatStreaming } from '../hooks/useChatStreaming';
import { useChatMetrics } from '../hooks/useChatMetrics';
import MetricsPanel from './MetricsPanel';
import MessagesPanel from './MessagesPanel';
import ChatHistorySidebar from './ChatHistorySidebar';
import AgentSelector from './AgentSelector';
import type { ChatSession, ChatStreamEvent, CustomEventPayload, InterruptData, ToolCall } from '../types/chat';
import type { ThinkingStep } from './ThinkingBlock';
import apiClient from '../../../lib/api-client';
import { useProject } from '../../../contexts/ProjectContext';

export default function GlobalChatModal() {
  const { activeProjectId } = useProject();
  const {
    isOpen,
    closeChat,
    currentSessionId,
    selectedAgentId,
    hitlEnabled,
    startSession,
    switchSession,
    endSession,
    sessions
  } = useChat();

  const modalRef = useRef<HTMLDivElement>(null);
  const [activeToolCalls, setActiveToolCalls] = useState<ToolCall[]>([]);
  const [customEvents, setCustomEvents] = useState<Map<string, CustomEventPayload>>(new Map());
  const [thinkingTraces, setThinkingTraces] = useState<ThinkingStep[][]>([]);
  const [thinkingBuffer, setThinkingBuffer] = useState('');  // pre-tool-call thinking text
  const tracesRef = useRef<ThinkingStep[]>([]);  // collect events during streaming

  // HITL interrupt state
  const [pendingInterrupt, setPendingInterrupt] = useState<InterruptData | null>(null);
  const [isResuming, setIsResuming] = useState(false);
  // Metrics panel visibility
  const [showMetrics, setShowMetrics] = useState(false);

  // Sidebar resize state
  const [sidebarWidth, setSidebarWidth] = useState(260);
  const [isResizing, setIsResizing] = useState(false);
  const resizeStartX = useRef(0);
  const resizeStartWidth = useRef(260);

  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
    resizeStartX.current = e.clientX;
    resizeStartWidth.current = sidebarWidth;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, [sidebarWidth]);

  useEffect(() => {
    if (!isResizing) return;
    const handleMouseMove = (e: MouseEvent) => {
      const delta = e.clientX - resizeStartX.current;
      const newWidth = Math.max(180, Math.min(420, resizeStartWidth.current + delta));
      setSidebarWidth(newWidth);
    };
    const handleMouseUp = () => {
      setIsResizing(false);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing]);

  // Session management hook
  const {
    messages,
    isLoading: isLoadingSession,
    error: sessionError,
    addMessage,
    updateLastMessage,
    loadHistory,
    clearHistory,
    setError: setSessionError
  } = useChatSession(currentSessionId);

  // Streaming hook
  const {
    sendMessage,
    isStreaming,
    error: streamingError,
    clearError: clearStreamingError
  } = useChatStreaming(currentSessionId, hitlEnabled);

  // Metrics hook
  const {
    metrics,
    toolCalls,
    subagentActivity,
    isLoading: isLoadingMetrics,
    refresh: refreshMetrics
  } = useChatMetrics(currentSessionId);

  // Get current session details
  const currentSession = sessions.find((s: ChatSession) => s.session_id === currentSessionId);

  // Use selected agent name as fallback when session hasn't caught up yet
  const [fallbackAgentName, setFallbackAgentName] = useState('');
  useEffect(() => {
    if (selectedAgentId) {
      apiClient.listDeepAgents({ public_only: false }).then(res => {
        const agents = res.data || [];
        const agent = agents.find((a: any) => a.id === selectedAgentId);
        if (agent) {
          setFallbackAgentName(agent.name);
          setAgentDescription(agent.description || '');
        }
      }).catch(() => {});
    }
  }, [selectedAgentId]);

  const sessionMatchesSelected = currentSession && selectedAgentId && currentSession.agent_id === selectedAgentId;
  const agentName = sessionMatchesSelected
    ? (currentSession?.agent_name || fallbackAgentName || 'Agent')
    : (fallbackAgentName || currentSession?.agent_name || 'Agent');
  const [agentDescription, setAgentDescription] = useState('');

  // Handle ESC key
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        closeChat();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, closeChat]);

  // Auto-start session when modal opens with pre-selected agent
  useEffect(() => {
    if (isOpen && selectedAgentId && !currentSessionId) {
      // Automatically start a session with the pre-selected agent
      handleStartSession(selectedAgentId);
    }
  }, [isOpen, selectedAgentId, currentSessionId]);

  // Prevent body scroll when modal is open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }

    return () => {
      document.body.style.overflow = '';
    };
  }, [isOpen]);

  // Handle click outside
  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      closeChat();
    }
  };

  // Handle starting a new session
  const handleStartSession = async (agentId: number) => {
    if (agentId !== 112) setSavedAgentId(null);
    try {
      await startSession(agentId);
      // Fetch agent details and add welcome message
      try {
        const res = await apiClient.listDeepAgents({ public_only: false });
        const agents = (res as any).data ?? [];
        const agent = agents.find((a: any) => a.id === agentId);
        const name = agent?.name || `Agent #${agentId}`;
        const desc = agent?.description || '';
        const welcome = desc
          ? `👋 你好！我是 **${name}**。\n\n${desc}\n\n有什么我可以帮助你的吗？`
          : `👋 你好！我是 **${name}**。有什么我可以帮助你的吗？`;
        addMessage({
          role: 'assistant',
          content: welcome,
          timestamp: new Date().toISOString(),
        });
      } catch {
        // Silently fail — welcome message is optional
      }
    } catch (error) {
      console.error('Failed to start session:', error);
      setSessionError('Failed to start chat session');
    }
  };

  // Handle starting a new session (from session selector)
  const handleNewSession = async () => {
    if (selectedAgentId) {
      await handleStartSession(selectedAgentId);
    }
  };

  // Handle sending a message
  const handleSendMessage = async (message: string) => {
    if (!currentSessionId) return;

    // Clear any previous interrupt
    setPendingInterrupt(null);

    await sendMessage(
      message,
      addMessage,
      updateLastMessage,
      async () => {
        // On complete: refresh metrics, save traces, clear active tools and custom events
        await refreshMetrics();
        setThinkingTraces(prev => [...prev, [...tracesRef.current]]);
        tracesRef.current = [];
        setActiveToolCalls([]);
        setCustomEvents(new Map());
        // Don't clear interrupt on complete (resume may also complete the stream)
      },
      (event: ChatStreamEvent) => {
        // Handle tool events
        if (event.type === 'tool_start' && event.tool_name) {
          const skill_name = event.skill_name || null;
          setActiveToolCalls(prev => [...prev, {
            tool_name: event.tool_name!,
            skill_name: skill_name,
            arguments: event.data?.input || event.data?.args || {},
            result: '',
            timestamp: new Date().toISOString(),
            status: 'running'
          }]);
          tracesRef.current = [...tracesRef.current, { type: 'tool_start', tool_name: event.tool_name, data: event.data }];
        } else if (event.type === 'tool_end' && event.tool_name) {
          const result = event.data?.output || '';
          setActiveToolCalls(prev => prev.map(t =>
            t.tool_name === event.tool_name && t.status === 'running'
              ? { ...t, status: 'completed', result }
              : t
          ));
          // Detect create_deepagent tool result → extract agent_id for Test/Tune buttons
          if (event.tool_name === 'create_deepagent') {
            const idMatch = result.match(/id=(\d+)/);
            if (idMatch) {
              setSavedAgentId(parseInt(idMatch[1], 10));
            }
          }
          tracesRef.current = [...tracesRef.current, { type: 'tool_end', tool_name: event.tool_name, data: event.data }];
        }
      },
      (event: ChatStreamEvent) => {
        // Handle custom events (LangGraph-style progress, status, etc.)
        if (event.type === 'custom_event' && event.data) {
          const payload = event.data as CustomEventPayload;
          const eventId = payload.event_id || `${payload.event_type}-${Date.now()}`;
          setCustomEvents(prev => {
            const next = new Map(prev);
            next.set(eventId, payload);
            return next;
          });
          tracesRef.current = [...tracesRef.current, { type: 'custom_event', tool_name: event.data?.tool_name, data: event.data }];
        }
      },
      (event: ChatStreamEvent) => {
        // Handle interrupt (HITL)
        if (event.type === 'interrupt' && event.data) {
          setPendingInterrupt(event.data as InterruptData);
        }
      },
      (content: string) => {
        // Handle thinking content (pre-tool-call text, not the final answer)
        setThinkingBuffer(content);
      }
    );
  };

  // Resume from interrupt — approve/reject the tool call
  const handleResume = async (action: 'approve' | 'reject' | 'edit' | 'respond', value?: string) => {
    if (!currentSessionId) return;

    setIsResuming(true);
    try {
      // Use raw fetch since apiClient doesn't have a resume method
      const response = await fetch(`${apiClient.baseURL}/api/chat/${currentSessionId}/resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, value }),
      });

      if (!response.ok) {
        throw new Error(`Resume failed: ${response.statusText}`);
      }

      // Clear interrupt state
      setPendingInterrupt(null);

      // Reload messages to show the resumed response
      await loadHistory(currentSessionId);
      await refreshMetrics();
    } catch (err: any) {
      console.error('Failed to resume:', err);
    } finally {
      setIsResuming(false);
    }
  };

  // Handle ending the session
  const handleEndSession = async () => {
    if (!currentSessionId) return;

    try {
      await endSession(currentSessionId);
      // Context will handle clearing currentSessionId
    } catch (error) {
      console.error('Failed to end session:', error);
      setSessionError('Failed to end session');
    }
  };

  const error = sessionError || streamingError;
  const clearError = () => {
    setSessionError(null);
    clearStreamingError();
  };

  // ── Agent Creator workflow: Save / Test / Tune ─────────────
  const isAgentCreator = currentSession?.agent_id === 112;
  const [savedAgentId, setSavedAgentId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const handleSaveFromCreator = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      // Tell the Agent Creator to save the current design using create_deepagent tool
      await handleSendMessage('请保存当前设计的 agent，使用 create_deepagent 工具写入数据库');
      // The tool_end handler will detect the agent_id automatically
      setSaving(false);
    } catch (err: any) {
      setSaveError(err?.message || 'Failed to send save request');
      setSaving(false);
    }
  };

  const handleTestNewAgent = () => {
    if (savedAgentId) {
      handleStartSession(savedAgentId);
    }
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
      onClick={handleBackdropClick}
    >
      <div
        ref={modalRef}
        className="rounded-xl shadow-2xl w-full max-w-[95vw] h-[90vh] flex overflow-hidden"
        style={{
          backgroundColor: 'var(--color-background-light)',
          border: '1px solid var(--color-border-dark)',
        }}
      >
        {/* Left Sidebar + Resize Handle */}
        <div className="flex flex-shrink-0" style={{ width: sidebarWidth }}>
          <ChatHistorySidebar onNewSession={handleNewSession} />
          {/* Resize Handle */}
          <div
            onMouseDown={handleResizeStart}
            className="w-2 cursor-col-resize flex items-center justify-center hover:bg-primary/10 active:bg-primary/20 transition-colors flex-shrink-0"
            style={{
              backgroundColor: isResizing ? 'var(--color-primary)' : 'transparent',
            }}
          >
            <GripVertical className="w-3 h-3 opacity-30 hover:opacity-60 transition-opacity" />
          </div>
        </div>

        {/* Center area: Chat */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Slim Header */}
          <div className="flex items-center justify-between px-5 py-2 border-b" style={{ borderColor: 'var(--color-border-dark)' }}>
            <AgentSelector
              selectedAgentId={selectedAgentId}
              onSelectAgent={handleStartSession}
              displayName={agentName}
            />
            <div className="flex items-center gap-1">
              {/* Metrics toggle */}
              {currentSessionId && (
                <button
                  onClick={() => setShowMetrics(v => !v)}
                  className={`p-2 rounded-lg transition-colors ${showMetrics ? 'bg-gray-100 dark:bg-gray-800' : 'hover:bg-gray-100 dark:hover:bg-gray-800'}`}
                  title={showMetrics ? 'Hide metrics' : 'Show metrics'}
                >
                  <BarChart3 className="w-4 h-4" style={{ color: showMetrics ? 'var(--color-primary)' : 'var(--color-text-muted)' }} />
                </button>
              )}
              {/* Agent Creator workflow buttons */}
              {isAgentCreator && currentSessionId && (
                <>
                  {!savedAgentId ? (
                    <button
                      onClick={handleSaveFromCreator}
                      disabled={saving}
                      className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
                      style={{
                        background: saving
                          ? 'rgba(0, 109, 221, 0.5)'
                          : 'linear-gradient(135deg, #006DDD 0%, #7FC8FF 100%)',
                        color: '#FFFFFF',
                        boxShadow: saving ? 'none' : '0 0 8px rgba(0, 109, 221, 0.3)',
                        opacity: saving ? 0.7 : 1,
                      }}
                      title={saveError || 'Save designed agent to library'}
                    >
                      {saving ? 'Saving...' : 'Save Agent'}
                    </button>
                  ) : (
                    <>
                      <button
                        onClick={handleTestNewAgent}
                        className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
                        style={{
                          background: 'linear-gradient(135deg, #006DDD 0%, #7FC8FF 100%)',
                          color: '#FFFFFF',
                          boxShadow: '0 0 8px rgba(0, 109, 221, 0.3)',
                        }}
                        title="Test with the newly created agent"
                      >
                        Test New Agent
                      </button>
                      <button
                        onClick={() => handleStartSession(112)}
                        className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
                        style={{
                          background: 'rgba(99, 102, 241, 0.12)',
                          border: '1px solid rgba(99, 102, 241, 0.3)',
                          color: '#818CF8',
                        }}
                        title="Go back to Agent Creator for tuning"
                      >
                        Tune
                      </button>
                    </>
                  )}
                </>
              )}
              <button
                onClick={closeChat}
                className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                title="Close (ESC)"
              >
                <X className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
              </button>
            </div>
          </div>

          {/* Main Content */}
          <div className="flex flex-1 overflow-hidden">
            <MessagesPanel
              messages={messages}
              isStreaming={isStreaming}
              error={error}
              onSendMessage={handleSendMessage}
              onClearError={clearError}
              disabled={!currentSessionId}
              sessionId={currentSessionId}
              projectId={activeProjectId}
              activeToolCalls={activeToolCalls}
              customEvents={customEvents}
              thinkingTraces={thinkingTraces}
              thinkingBuffer={thinkingBuffer}
              agentName={agentName}
            />
            {currentSessionId && showMetrics && (
              <div className="border-l w-56 overflow-y-auto flex-shrink-0" style={{ borderColor: 'var(--color-border-dark)' }}>
                <MetricsPanel
                  metrics={metrics}
                  toolCalls={toolCalls}
                  activeToolCalls={activeToolCalls}
                  subagentActivity={subagentActivity}
                  isLoading={isLoadingMetrics}
                  agentName={agentName}
                  agentDescription={agentDescription}
                  sessionId={currentSessionId}
                />
              </div>
            )}
          </div>
        </div>
      </div>      {/* HITL Interrupt Modal */}
      {pendingInterrupt && (
        <HitlInterruptModal
          pendingInterrupt={pendingInterrupt}
          isResuming={isResuming}
          onResume={handleResume}
        />
      )}
    </div>
  );
}
