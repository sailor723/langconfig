/**
 * useChatController — shared controller for the full chat UI.
 *
 * ChatPage and GlobalChatModal render the same chat experience (history
 * sidebar, agent selector, message panel, metrics/context/files panels,
 * HITL interrupt modal, Agent Creator workflow). Everything except the
 * outer shell (full page vs modal overlay) used to be copy-pasted between
 * the two files; this hook extracts that shared state + handlers.
 *
 * Shell-specific concerns stay in each component: opening/closing (openChat
 * / closeChat / isOpen / ESC / backdrop), the theme CSS variables (page), and
 * the bottom toolbar (page).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import apiClient from '../../../lib/api-client';
import { useProject } from '../../../contexts/ProjectContext';
import { useChat } from '../state/ChatContext';
import { useChatSession } from './useChatSession';
import { useChatStreaming } from './useChatStreaming';
import { useChatMetrics } from './useChatMetrics';
import type { ChatSession, ChatStreamEvent, CustomEventPayload, InterruptData, ToolCall } from '../types/chat';
import type { ThinkingStep } from '../ui/ThinkingBlock';

type Panel = 'metrics' | 'context' | 'files';

interface UseChatControllerOptions {
  /** Welcome-message language when a new session starts ('en' = page, 'zh' = modal) */
  locale?: 'en' | 'zh';
  /** Auto-start a session once an agent is selected (page: true, modal: only when open) */
  autoStart?: boolean;
}

export function useChatController(options: UseChatControllerOptions = {}) {
  const { locale = 'en', autoStart = false } = options;
  const { activeProjectId } = useProject();
  const {
    currentSessionId,
    selectedAgentId,
    hitlEnabled,
    startSession,
    endSession,
    sessions,
    toggleFavorite,
    renameSession,
  } = useChat();

  // ── Side panel visibility (metrics / context / files) ──────────────
  const [showMetrics, setShowMetrics] = useState(false);
  const [showContext, setShowContext] = useState(false);
  const [showFiles, setShowFiles] = useState(false);

  // Toggle the clicked panel; clicking a different panel switches to it
  const togglePanel = useCallback((panel: Panel) => {
    if (panel === 'metrics') {
      setShowMetrics(v => !v);
      if (!showMetrics) { setShowContext(false); setShowFiles(false); }
    } else if (panel === 'context') {
      setShowContext(v => !v);
      if (!showContext) { setShowMetrics(false); setShowFiles(false); }
    } else {
      setShowFiles(v => !v);
      if (!showFiles) { setShowMetrics(false); setShowContext(false); }
    }
  }, [showMetrics, showContext, showFiles]);

  // ── Streaming / tool / thinking / HITL state ───────────────────────
  const [activeToolCalls, setActiveToolCalls] = useState<ToolCall[]>([]);
  const [customEvents, setCustomEvents] = useState<Map<string, CustomEventPayload>>(new Map());
  const [thinkingTraces, setThinkingTraces] = useState<ThinkingStep[][]>([]);
  const [thinkingBuffer, setThinkingBuffer] = useState('');
  const tracesRef = useRef<ThinkingStep[]>([]);
  const [pendingInterrupt, setPendingInterrupt] = useState<InterruptData | null>(null);
  const [isResuming, setIsResuming] = useState(false);

  // ── History sidebar resize ─────────────────────────────────────────
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

  // ── Right side panel (metrics / files) resize — shared width ───────
  const [panelWidth, setPanelWidth] = useState(360);
  const [isPanelResizing, setIsPanelResizing] = useState(false);
  const panelResizeStartX = useRef(0);
  const panelResizeStartWidth = useRef(360);

  const handlePanelResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsPanelResizing(true);
    panelResizeStartX.current = e.clientX;
    panelResizeStartWidth.current = panelWidth;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, [panelWidth]);

  useEffect(() => {
    if (!isPanelResizing) return;
    const handleMouseMove = (e: MouseEvent) => {
      // Panel is anchored to the right window edge, so dragging the handle
      // right (toward the edge) SHRINKS it: invert the delta relative to
      // the left-anchored history sidebar.
      const delta = panelResizeStartX.current - e.clientX;
      const newWidth = Math.max(240, Math.min(640, panelResizeStartWidth.current + delta));
      setPanelWidth(newWidth);
    };
    const handleMouseUp = () => {
      setIsPanelResizing(false);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isPanelResizing]);

  // ── Session / streaming / metrics hooks ────────────────────────────
  const {
    messages,
    error: sessionError,
    addMessage,
    updateLastMessage,
    loadHistory,
    clearHistory,
    setError: setSessionError,
  } = useChatSession(currentSessionId);

  const {
    sendMessage,
    isStreaming,
    error: streamingError,
    clearError: clearStreamingError,
  } = useChatStreaming(currentSessionId, hitlEnabled);

  const {
    metrics,
    toolCalls,
    subagentActivity,
    isLoading: isLoadingMetrics,
    refresh: refreshMetrics,
  } = useChatMetrics(currentSessionId);

  // ── Agent display name / description ───────────────────────────────
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

  // ── Agent Creator workflow state (used by handleStartSession below) ─
  const [savedAgentId, setSavedAgentId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // ── Session lifecycle ──────────────────────────────────────────────
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
        const welcome = locale === 'zh'
          ? (desc
              ? `👋 你好！我是 **${name}**。\n\n${desc}\n\n有什么我可以帮助你的吗？`
              : `👋 你好！我是 **${name}**。有什么我可以帮助你的吗？`)
          : (desc
              ? `👋 Hello! I'm **${name}**.\n\n${desc}\n\nHow can I help you?`
              : `👋 Hello! I'm **${name}**. How can I help you?`);
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
        // On complete: refresh metrics, save traces, clear active tools and custom events
        await refreshMetrics();
        setThinkingTraces(prev => [...prev, [...tracesRef.current]]);
        tracesRef.current = [];
        setActiveToolCalls([]);
        setCustomEvents(new Map());
      },
      (event: ChatStreamEvent) => {
        // Tool events
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
        // Custom events (LangGraph-style progress, status, etc.)
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
        // HITL interrupt
        if (event.type === 'interrupt' && event.data) {
          setPendingInterrupt(event.data as InterruptData);
        }
      },
      (content: string) => {
        // Thinking content (pre-tool-call text, not the final answer)
        setThinkingBuffer(content);
      }
    );
  };

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

  // ── Agent Creator workflow: Save / Test / Tune ─────────────────────
  const isAgentCreator = currentSession?.agent_id === 112;

  const handleSaveFromCreator = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      // Tell the Agent Creator to save the current design using create_deepagent tool
      const saveMsg = locale === 'zh'
        ? '请保存当前设计的 agent，使用 create_deepagent 工具写入数据库'
        : 'Please save the current agent design using create_deepagent tool';
      await handleSendMessage(saveMsg);
      // The tool_end handler will detect the agent_id automatically
      setSaving(false);
    } catch (err: any) {
      setSaveError(err?.message || 'Failed to send save request');
      setSaving(false);
    }
  };

  const handleTestNewAgent = () => {
    if (savedAgentId) handleStartSession(savedAgentId);
  };

  // Auto-start a session once an agent is selected and no session exists
  useEffect(() => {
    if (autoStart && selectedAgentId && !currentSessionId) {
      handleStartSession(selectedAgentId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart, selectedAgentId, currentSessionId]);

  return {
    activeProjectId,
    currentSessionId,
    selectedAgentId,
    sessions,
    // conversation header (title + pin)
    toggleFavorite,
    renameSession,
    // agent display
    agentName,
    agentDescription,
    // session data
    messages,
    isStreaming,
    error,
    clearError,
    // metrics
    metrics,
    toolCalls,
    subagentActivity,
    isLoadingMetrics,
    // streaming display state
    activeToolCalls,
    customEvents,
    thinkingTraces,
    thinkingBuffer,
    pendingInterrupt,
    isResuming,
    // side panels
    showMetrics,
    showContext,
    showFiles,
    togglePanel,
    // sidebar resize
    sidebarWidth,
    isResizing,
    handleResizeStart,
    // right panel resize
    panelWidth,
    isPanelResizing,
    handlePanelResizeStart,
    // handlers
    handleStartSession,
    handleNewSession,
    handleSendMessage,
    handleResume,
    handleEndSession,
    clearHistory,
    // Agent Creator workflow
    isAgentCreator,
    savedAgentId,
    saving,
    saveError,
    handleSaveFromCreator,
    handleTestNewAgent,
  };
}
