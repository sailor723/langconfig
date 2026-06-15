/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { useChat } from '../state/ChatContext';
import { useChatSession } from '../hooks/useChatSession';
import { useChatStreaming } from '../hooks/useChatStreaming';
import { useChatMetrics } from '../hooks/useChatMetrics';
import MetricsPanel from './MetricsPanel';
import MessagesPanel from './MessagesPanel';
import ChatHistorySidebar from './ChatHistorySidebar';
import type { ChatSession, ChatStreamEvent, CustomEventPayload, InterruptData } from '../types/chat';
import apiClient from '../../../lib/api-client';

export default function GlobalChatModal() {
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
  const [activeToolCalls, setActiveToolCalls] = useState<string[]>([]);
  const [customEvents, setCustomEvents] = useState<Map<string, CustomEventPayload>>(new Map());

  // HITL interrupt state
  const [pendingInterrupt, setPendingInterrupt] = useState<InterruptData | null>(null);
  const [isResuming, setIsResuming] = useState(false);

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
  const agentName = currentSession?.agent_name || 'Agent';

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
    try {
      await startSession(agentId);
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
        // On complete: refresh metrics, clear active tools and custom events
        await refreshMetrics();
        setActiveToolCalls([]);
        setCustomEvents(new Map());
        // Don't clear interrupt on complete (resume may also complete the stream)
      },
      (event: ChatStreamEvent) => {
        // Handle tool events
        if (event.type === 'tool_start' && event.tool_name) {
          setActiveToolCalls(prev => [...prev, event.tool_name!]);
        } else if (event.type === 'tool_end' && event.tool_name) {
          setActiveToolCalls(prev => prev.filter(t => t !== event.tool_name));
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
        }
      },
      (event: ChatStreamEvent) => {
        // Handle interrupt (HITL)
        if (event.type === 'interrupt' && event.data) {
          setPendingInterrupt(event.data as InterruptData);
        }
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
          backgroundColor: 'white',
          border: '1px solid var(--color-border-dark)',
        }}
      >
        {/* Left Sidebar - Conversation History (ChatGPT-style) */}
        <ChatHistorySidebar onNewSession={handleNewSession} />

        {/* Center + Right: Chat + Metrics */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Simple Header */}
          <div
            className="flex items-center justify-between px-5 py-3 border-b"
            style={{ borderColor: 'var(--color-border-dark)' }}
          >
            <div className="flex items-center gap-3">
              <h2
                className="text-base font-semibold"
                style={{ color: 'var(--color-text-primary)' }}
              >
                {agentName}
              </h2>
              <span
                className="text-xs px-2 py-0.5 rounded-full"
                style={{
                  backgroundColor: 'rgba(99,102,241,0.1)',
                  color: 'var(--color-primary)',
                }}
              >
                {currentSessionId ? 'Active' : 'Select an agent'}
              </span>
            </div>
            <div className="flex items-center gap-2">
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
            {/* Messages Panel - Center */}
            <MessagesPanel
              messages={messages}
              isStreaming={isStreaming}
              error={error}
              onSendMessage={handleSendMessage}
              onClearError={clearError}
              disabled={!currentSessionId}
              sessionId={currentSessionId}
              activeToolCalls={activeToolCalls}
              customEvents={customEvents}
            />

            {/* Metrics Panel - Right Sidebar */}
            <MetricsPanel
              metrics={metrics}
              toolCalls={toolCalls}
              subagentActivity={subagentActivity}
              isLoading={isLoadingMetrics}
              agentName={agentName}
              sessionId={currentSessionId}
            />
          </div>
        </div>
      </div>

      {/* HITL Interrupt Modal */}
      {pendingInterrupt && (
        <div
          className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[100]"
          onClick={() => {}}  // Don't close on backdrop click
        >
          <div
            className="bg-white dark:bg-panel-dark rounded-xl w-full max-w-lg shadow-2xl border"
            style={{ borderColor: 'var(--color-border-dark)' }}
            onClick={e => e.stopPropagation()}
          >
            {/* Header */}
            <div className="px-5 py-3 rounded-t-xl" style={{ backgroundColor: '#f59e0b' }}>
              <h3 className="text-base font-semibold text-white flex items-center gap-2">
                ⏸️ Human Approval Required
              </h3>
              <p className="text-xs text-white/80 mt-0.5">
                An agent action needs your approval before proceeding
              </p>
            </div>

            {/* Body */}
            <div className="p-5 space-y-4">
              {pendingInterrupt.action_requests?.map((req, i) => (
                <div key={i} className="p-3 rounded-lg border" style={{
                  borderColor: 'var(--color-border-dark)',
                  backgroundColor: 'var(--color-background-light)'
                }}>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                      {req.name}
                    </span>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200">
                      Tool Call
                    </span>
                  </div>
                  <div className="text-xs space-y-1" style={{ color: 'var(--color-text-secondary)' }}>
                    {req.description && (
                      <p className="italic">{req.description}</p>
                    )}
                    {req.args && Object.keys(req.args).length > 0 && (
                      <pre className="mt-1 p-2 rounded text-xs font-mono overflow-x-auto" style={{
                        backgroundColor: 'var(--color-background)',
                        color: 'var(--color-text-primary)',
                        maxHeight: '120px'
                      }}>
                        {JSON.stringify(req.args, null, 2)}
                      </pre>
                    )}
                  </div>
                </div>
              ))}

              {(!pendingInterrupt.action_requests || pendingInterrupt.action_requests.length === 0) && (
                <div className="p-3 rounded-lg border" style={{
                  borderColor: 'var(--color-border-dark)',
                  backgroundColor: 'var(--color-background-light)'
                }}>
                  <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                    Agent paused before executing actions.
                  </p>
                  {pendingInterrupt.tool_calls && pendingInterrupt.tool_calls.length > 0 && (
                    <pre className="mt-2 p-2 rounded text-xs font-mono overflow-x-auto" style={{
                      backgroundColor: 'var(--color-background)',
                      color: 'var(--color-text-primary)',
                      maxHeight: '120px'
                    }}>
                      {JSON.stringify(pendingInterrupt.tool_calls, null, 2)}
                    </pre>
                  )}
                  {pendingInterrupt.next_nodes && (
                    <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                      Next nodes: {pendingInterrupt.next_nodes.join(', ')}
                    </p>
                  )}
                </div>
              )}
            </div>

            {/* Actions */}
            <div className="px-5 py-3 border-t flex items-center justify-end gap-2" style={{
              borderColor: 'var(--color-border-dark)'
            }}>
              <button
                onClick={() => handleResume('reject')}
                disabled={isResuming}
                className="px-4 py-2 rounded-lg text-sm font-medium border transition-colors"
                style={{
                  borderColor: 'var(--color-border-dark)',
                  color: 'var(--color-text-primary)',
                  backgroundColor: 'var(--color-background-light)'
                }}
              >
                Reject
              </button>
              {pendingInterrupt.review_configs?.[0]?.allowed_decisions?.includes('edit') && (
                <button
                  onClick={() => handleResume('edit')}
                  disabled={isResuming}
                  className="px-4 py-2 rounded-lg text-sm font-medium border transition-colors"
                  style={{
                    borderColor: 'var(--color-border-dark)',
                    color: 'var(--color-text-primary)',
                    backgroundColor: 'var(--color-background-light)'
                  }}
                >
                  Edit
                </button>
              )}
              <button
                onClick={() => handleResume('approve')}
                disabled={isResuming}
                className="px-4 py-2 rounded-lg text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
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
