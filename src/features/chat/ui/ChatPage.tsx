/**
 * ChatPage — standalone full-viewport chat window (opened from ActivityBar or agent Run).
 *
 * This is the same chat UI as GlobalChatModal but rendered as a full page
 * without the modal backdrop, designed to be opened in a separate browser window.
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { X, GripVertical, BarChart3, FileText } from 'lucide-react';
import { useChat } from '../state/ChatContext';
import { themes, type ThemeName } from '../../../lib/themes';
import HitlInterruptModal from './HitlInterruptModal';
import ContextPanel from './ContextPanel';
import { useChatSession } from '../hooks/useChatSession';
import { useChatStreaming } from '../hooks/useChatStreaming';
import { useChatMetrics } from '../hooks/useChatMetrics';
import MetricsPanel from './MetricsPanel';
import MessagesPanel from './MessagesPanel';
import ChatHistorySidebar from './ChatHistorySidebar';
import AgentSelector from './AgentSelector';
import ChatSettingsMenu from './ChatSettingsMenu';
import type { ChatSession, ChatStreamEvent, CustomEventPayload, InterruptData, ToolCall } from '../types/chat';
import type { ThinkingStep } from './ThinkingBlock';
import apiClient from '../../../lib/api-client';
import { useProject } from '../../../contexts/ProjectContext';

export default function ChatPage() {
  const [searchParams] = useSearchParams();
  const agentIdFromUrl = searchParams.get('agentId');

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
    sessions,
    openChat,
  } = useChat();

  // Auto-open chat with the agent from URL params
  useEffect(() => {
    if (agentIdFromUrl) {
      const id = parseInt(agentIdFromUrl, 10);
      if (!isNaN(id)) {
        openChat(id);
      }
    } else {
      // Open with no pre-selected agent (shows agent selector)
      openChat();
    }
    // Only run on mount — subsequent navigations are handled by the hash router
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-start session when agent is selected via URL params and no active session
  useEffect(() => {
    if (selectedAgentId && !currentSessionId) {
      handleStartSession(selectedAgentId);
    }
  }, [selectedAgentId, currentSessionId]);

  const modalRef = useRef<HTMLDivElement>(null);
  const [activeToolCalls, setActiveToolCalls] = useState<ToolCall[]>([]);
  const [customEvents, setCustomEvents] = useState<Map<string, CustomEventPayload>>(new Map());
  const [thinkingTraces, setThinkingTraces] = useState<ThinkingStep[][]>([]);
  const [thinkingBuffer, setThinkingBuffer] = useState('');
  const tracesRef = useRef<ThinkingStep[]>([]);
  const [pendingInterrupt, setPendingInterrupt] = useState<InterruptData | null>(null);
  const [isResuming, setIsResuming] = useState(false);
  const [showMetrics, setShowMetrics] = useState(false);
  const [showContext, setShowContext] = useState(false);

  // Independent chat window theme (separate from main app theme)
  const [chatTheme, setChatTheme] = useState<ThemeName>(() => {
    const saved = localStorage.getItem('langconfig-chat-theme');
    return (saved && ['langconfig', 'dark', 'warm'].includes(saved)) ? saved as ThemeName : 'langconfig';
  });

  // Apply chat theme CSS variables to the root element
  useEffect(() => {
    const t = themes[chatTheme];
    if (!t) return;
    const root = document.documentElement;
    const { colors } = t;
    root.style.setProperty('--color-primary', colors.primary);
    root.style.setProperty('--color-background-light', colors.backgroundLight);
    root.style.setProperty('--color-background-dark', colors.backgroundDark);
    root.style.setProperty('--color-panel-dark', colors.panelDark);
    root.style.setProperty('--color-border-dark', colors.borderDark);
    root.style.setProperty('--color-text-muted', colors.textMuted);
    root.style.setProperty('--color-text-primary', colors.textPrimary);
    root.style.setProperty('--color-input-background', colors.inputBackground);
    root.style.setProperty('--color-header-background', colors.headerBackground);
    root.style.setProperty('--color-header-text-color', colors.headerTextColor);
    localStorage.setItem('langconfig-chat-theme', chatTheme);
  }, [chatTheme]);

  const handleThemeChange = useCallback((name: ThemeName) => {
    setChatTheme(name);
  }, []);

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

  // Session management
  const {
    messages,
    isLoading: isLoadingSession,
    error: sessionError,
    addMessage,
    updateLastMessage,
    loadHistory,
    clearHistory,
    setError: setSessionError,
  } = useChatSession(currentSessionId);

  // Streaming
  const {
    sendMessage,
    isStreaming,
    error: streamingError,
    clearError: clearStreamingError,
  } = useChatStreaming(currentSessionId, hitlEnabled);

  // Metrics
  const {
    metrics,
    toolCalls,
    subagentActivity,
    isLoading: isLoadingMetrics,
    refresh: refreshMetrics,
  } = useChatMetrics(currentSessionId);

  const currentSession = sessions.find((s: ChatSession) => s.session_id === currentSessionId);
  const [fallbackAgentName, setFallbackAgentName] = useState('');
  const [agentDescription, setAgentDescription] = useState('');

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

  // Handle starting a new session
  const handleStartSession = async (agentId: number) => {
    if (agentId !== 112) setSavedAgentId(null);
    try {
      await startSession(agentId);
      try {
        const res = await apiClient.listDeepAgents({ public_only: false });
        const agents = (res as any).data ?? [];
        const agent = agents.find((a: any) => a.id === agentId);
        const name = agent?.name || `Agent #${agentId}`;
        const desc = agent?.description || '';
        const welcome = desc
          ? `👋 Hello! I'm **${name}**.\n\n${desc}\n\nHow can I help you?`
          : `👋 Hello! I'm **${name}**. How can I help you?`;
        addMessage({
          role: 'assistant',
          content: welcome,
          timestamp: new Date().toISOString(),
        });
      } catch {
        // Silently fail
      }
    } catch (error) {
      console.error('Failed to start session:', error);
      setSessionError('Failed to start chat session');
    }
  };

  const handleNewSession = async () => {
    if (selectedAgentId) {
      await handleStartSession(selectedAgentId);
    }
  };

  const handleSendMessage = async (message: string) => {
    if (!currentSessionId) return;
    setPendingInterrupt(null);
    await sendMessage(
      message,
      addMessage,
      updateLastMessage,
      async () => {
        await refreshMetrics();
        setThinkingTraces(prev => [...prev, [...tracesRef.current]]);
        tracesRef.current = [];
        setActiveToolCalls([]);
        setCustomEvents(new Map());
      },
      (event: ChatStreamEvent) => {
        if (event.type === 'tool_start' && event.tool_name) {
          const skill_name = event.skill_name || null;
          setActiveToolCalls(prev => [...prev, {
            tool_name: event.tool_name!,
            skill_name,
            arguments: event.data?.input || event.data?.args || {},
            result: '',
            timestamp: new Date().toISOString(),
            status: 'running',
          }]);
          tracesRef.current = [...tracesRef.current, { type: 'tool_start', tool_name: event.tool_name, data: event.data }];
        } else if (event.type === 'tool_end' && event.tool_name) {
          const result = event.data?.output || '';
          setActiveToolCalls(prev => prev.map(t =>
            t.tool_name === event.tool_name && t.status === 'running'
              ? { ...t, status: 'completed', result }
              : t
          ));
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
        if (event.type === 'interrupt' && event.data) {
          setPendingInterrupt(event.data as InterruptData);
        }
      },
      (content: string) => {
        setThinkingBuffer(content);
      }
    );
  };

  const handleResume = async (action: 'approve' | 'reject' | 'edit' | 'respond', value?: string) => {
    if (!currentSessionId) return;
    setIsResuming(true);
    try {
      const response = await fetch(`${apiClient.baseURL}/api/chat/${currentSessionId}/resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, value }),
      });
      if (!response.ok) throw new Error(`Resume failed: ${response.statusText}`);
      setPendingInterrupt(null);
      await loadHistory(currentSessionId);
      await refreshMetrics();
    } catch (err: any) {
      console.error('Failed to resume:', err);
    } finally {
      setIsResuming(false);
    }
  };

  const handleEndSession = async () => {
    if (!currentSessionId) return;
    try {
      await endSession(currentSessionId);
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

  // Agent Creator workflow
  const isAgentCreator = currentSession?.agent_id === 112;
  const [savedAgentId, setSavedAgentId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const handleSaveFromCreator = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      await handleSendMessage('Please save the current agent design using create_deepagent tool');
      setSaving(false);
    } catch (err: any) {
      setSaveError(err?.message || 'Failed to send save request');
      setSaving(false);
    }
  };

  const handleTestNewAgent = () => {
    if (savedAgentId) handleStartSession(savedAgentId);
  };

  return (
    <div
      ref={modalRef}
      style={{
        display: 'flex',
        height: '100vh',
        width: '100vw',
        overflow: 'hidden',
        backgroundColor: 'var(--color-background-light)',
      }}
    >
      {/* Left Sidebar + Resize Handle */}
      <div className="flex flex-shrink-0" style={{ width: sidebarWidth }}>
        <ChatHistorySidebar onNewSession={handleNewSession} />
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

      {/* Main Content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-2">
          <AgentSelector
            selectedAgentId={selectedAgentId}
            onSelectAgent={handleStartSession}
            displayName={agentName}
          />
          <div className="flex items-center gap-1">
            {currentSessionId && (
              <>
                <button
                  onClick={() => { setShowMetrics(v => !v); if (!showMetrics) setShowContext(false); }}
                  className={`p-2 rounded-lg transition-colors ${showMetrics ? 'bg-gray-100 dark:bg-gray-800' : 'hover:bg-gray-100 dark:hover:bg-gray-800'}`}
                  title={showMetrics ? 'Hide metrics' : 'Show metrics'}
                >
                  <BarChart3 className="w-4 h-4" style={{ color: showMetrics ? 'var(--color-primary)' : 'var(--color-text-muted)' }} />
                </button>
                <button
                  onClick={() => { setShowContext(v => !v); if (!showContext) setShowMetrics(false); }}
                  className={`p-2 rounded-lg transition-colors ${showContext ? 'bg-gray-100 dark:bg-gray-800' : 'hover:bg-gray-100 dark:hover:bg-gray-800'}`}
                  title={showContext ? 'Hide context' : 'Show context'}
                >
                  <FileText className="w-4 h-4" style={{ color: showContext ? 'var(--color-primary)' : 'var(--color-text-muted)' }} />
                </button>
              </>
            )}
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
                    >
                      Tune
                    </button>
                  </>
                )}
              </>
            )}
            <button
              onClick={() => window.close()}
              className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
              title="Close window"
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
            <div className="w-56 overflow-y-auto flex-shrink-0" style={{ backgroundColor: 'var(--color-panel-dark, #f9fafb)' }}>
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
          {currentSessionId && showContext && (
            <div className="w-56 overflow-y-auto flex-shrink-0" style={{ backgroundColor: 'var(--color-panel-dark, #f9fafb)' }}>
              <ContextPanel
                selectedAgentId={selectedAgentId}
                sessionId={currentSessionId}
              />
            </div>
          )}
        </div>

        {/* Bottom toolbar — agent info, status & settings gear */}
        <div
          className="flex items-center justify-between px-6 py-1.5"
          style={{
            backgroundColor: 'var(--color-panel-dark, #f9fafb)',
          }}
        >
          <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--color-text-muted)' }}>
            <span className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
              {currentSessionId ? agentName : 'Standalone Chat'}
            </span>
            <span className="w-1 h-1 rounded-full" style={{ backgroundColor: 'var(--color-text-muted)' }} />
            <span>{messages.length} message{messages.length !== 1 ? 's' : ''}</span>
            <span className="w-1 h-1 rounded-full" style={{ backgroundColor: 'var(--color-text-muted)' }} />
            <span className="capitalize">{chatTheme}</span>
          </div>
          <div className="flex items-center gap-1">
            <ChatSettingsMenu
              sessionId={currentSessionId}
              messages={messages}
              metrics={metrics}
              toolCalls={toolCalls}
              subagentActivity={subagentActivity}
              agentName={agentName}
              themeName={chatTheme}
              onThemeChange={handleThemeChange}
              onClearHistory={clearHistory}
              onEndSession={handleEndSession}
            />
          </div>
        </div>
      </div>

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
