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
import { appendReasoning, finishToolCall, startToolCall } from '../utils/assistantBlocks';
import type { ChatSession, ChatStreamEvent, CustomEventPayload, InterruptData, ToolCall } from '../types/chat';
import type { ThinkingStep } from '../ui/ThinkingBlock';

type Panel = 'metrics' | 'context' | 'files' | 'calendar';

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

  // ── Side panel visibility (metrics / context / files / calendar) ────
  const [showMetrics, setShowMetrics] = useState(false);
  const [showContext, setShowContext] = useState(false);
  const [showFiles, setShowFiles] = useState(false);
  const [showCalendar, setShowCalendar] = useState(false);

  // Toggle the clicked panel; clicking a different panel switches to it
  const togglePanel = useCallback((panel: Panel) => {
    if (panel === 'metrics') {
      setShowMetrics(v => !v);
      if (!showMetrics) { setShowContext(false); setShowFiles(false); setShowCalendar(false); }
    } else if (panel === 'context') {
      setShowContext(v => !v);
      if (!showContext) { setShowMetrics(false); setShowFiles(false); setShowCalendar(false); }
    } else if (panel === 'calendar') {
      setShowCalendar(v => !v);
      if (!showCalendar) { setShowMetrics(false); setShowContext(false); setShowFiles(false); }
    } else {
      setShowFiles(v => !v);
      if (!showFiles) { setShowMetrics(false); setShowContext(false); setShowCalendar(false); }
    }
  }, [showMetrics, showContext, showFiles, showCalendar]);

  // ── Streaming / tool / thinking / HITL state ───────────────────────
  const [activeToolCalls, setActiveToolCalls] = useState<ToolCall[]>([]);
  const [customEvents, setCustomEvents] = useState<Map<string, CustomEventPayload>>(new Map());
  const [thinkingTraces, setThinkingTraces] = useState<ThinkingStep[][]>([]);
  const [thinkingBuffer, setThinkingBuffer] = useState('');
  const tracesRef = useRef<ThinkingStep[]>([]);
  const [pendingInterrupt, setPendingInterrupt] = useState<InterruptData | null>(null);
  const [isResuming, setIsResuming] = useState(false);

  // Per-turn state belongs to the session that produced it. Without this, an
  // open conversation kept showing the previous chat's tool/subagent list under
  // its last message — the transcript was reloaded, the stream state was not.
  useEffect(() => {
    setActiveToolCalls([]);
    setThinkingTraces([]);
    setThinkingBuffer('');
    tracesRef.current = [];
    setCustomEvents(new Map());
    setPendingInterrupt(null);
    setIsResuming(false);
  }, [currentSessionId]);

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
    updateLastMessageWith,
    loadHistory,
    clearHistory,
    setError: setSessionError,
  } = useChatSession(currentSessionId);

  const {
    sendMessage,
    isStreaming,
    error: streamingError,
    clearError: clearStreamingError,
    cancel: cancelStreaming,
  } = useChatStreaming(currentSessionId, hitlEnabled);

  /** Stop the run that is streaming: aborts the SSE reader and closes the
   *  request, which is what tells the backend to stop producing. */
  const handleStop = useCallback(() => {
    cancelStreaming();
  }, [cancelStreaming]);

  const {
    metrics,
    context,
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


  // ── dashboards: open one the moment it is generated ──────────────────────
  // The dashboard tool writes `generated/*dashboard*.html`; a page served over http cannot
  // navigate to file://, so the backend serves it inline and this opens that URL. Only files
  // newer than the last one opened are auto-opened, so finishing an unrelated turn does not
  // pop a tab every time.
  const [dashboardCount, setDashboardCount] = useState(0);
  const lastDashboardRef = useRef<string>("");
  const openNewestDashboard = useCallback(async (open: boolean = true) => {
    if (!currentSessionId) return;
    try {
      const res = await apiClient.get(`/api/chat/${currentSessionId}/dashboards`);
      const list = res.data?.dashboards || [];
      setDashboardCount(list.length);
      const first = list[0];
      if (!first) return;
      const isNew = first.modified_at !== lastDashboardRef.current;
      if (open) {
        // An explicit click always opens; the automatic path only opens what is new.
        lastDashboardRef.current = first.modified_at;
        window.open(`${apiClient.baseURL}${first.url}`, "_blank", "noopener");
      } else if (isNew) {
        lastDashboardRef.current = first.modified_at;
        window.open(`${apiClient.baseURL}${first.url}`, "_blank", "noopener");
      }
    } catch {
      /* a missing dashboard list must never fail a turn */
    }
  }, [currentSessionId]);

  /** The header's 仪表盘 button: open the newest dashboard, or explain why there is none. */
  const openDashboard = useCallback(async () => {
    if (!currentSessionId) return;
    await openNewestDashboard(true);
  }, [currentSessionId, openNewestDashboard]);

  // Refresh the badge whenever a turn ends, so the button appears as soon as a dashboard exists.
  useEffect(() => {
    if (!currentSessionId) { setDashboardCount(0); return; }
    void openNewestDashboard(false);
  }, [currentSessionId, openNewestDashboard]);

  const handleSendMessage = async (message: string) => {
    if (!currentSessionId) return;
    setPendingInterrupt(null);
    // Per-turn state starts empty. It used to be cleared only on `complete`, so a
    // turn that ended any other way (interrupt, error, stop) kept its tool calls
    // and custom events, and the next turn's pass appended to them — the
    // "thinking appended to all thinking" report.
    setActiveToolCalls([]);
    setCustomEvents(new Map());
    setThinkingBuffer('');
    tracesRef.current = [];
    await sendMessage(
      message,
      addMessage,
      updateLastMessage,
      async () => {
        // On complete: refresh metrics, save traces, clear active tools and custom events
        void openNewestDashboard();
        await refreshMetrics();
        setThinkingTraces(prev => [...prev, [...tracesRef.current]]);
        tracesRef.current = [];
        setActiveToolCalls([]);
        setCustomEvents(new Map());
      },
      (event: ChatStreamEvent) => {
        // A handoff moves the speaker, so the transcript records it: without a
        // marker the same bubble reads as one agent that both offers to
        // transfer and answers as the expert.
        if ((event as any).type === 'handoff') {
          // Same shape the history endpoint returns, so the live card and the
          // reloaded card are one component, not two look-alikes.
          const fromLabel = (event as any).from_label || (event as any).from_step;
          const toLabel = (event as any).to_label || (event as any).to || '另一个步骤';
          const reason = (event as any).reason as string | undefined;
          const where = fromLabel ? `${fromLabel} → ${toLabel}` : `转交给「${toLabel}」`;
          addMessage({
            role: 'handoff',
            content: reason ? `${where} · ${reason}` : where,
            from_step: (event as any).from_step ?? null,
            from_label: (event as any).from_label ?? null,
            to: (event as any).to ?? null,
            to_label: (event as any).to_label ?? null,
            reason: reason ?? null,
            timestamp: new Date().toISOString(),
          } as any);
          return;
        }
        // Tool events
        if (event.type === 'tool_start' && event.tool_name) {
          const skill_name = event.skill_name || null;
          const callId = (event as any).tool_call_id || event.tool_name;
          const args = event.data?.input || event.data?.args || {};
          // The turn's own record: a block, on the message that made the call.
          updateLastMessageWith(m => ({
            ...m,
            blocks: startToolCall(m.blocks || [], { name: event.tool_name!, args, callId }),
          }));
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
          const callId = (event as any).tool_call_id || event.tool_name;
          updateLastMessageWith(m => ({
            ...m,
            blocks: finishToolCall(m.blocks || [], {
              name: event.tool_name!,
              callId,
              output: typeof result === 'string' ? result : JSON.stringify(result),
              status: event.data?.status === 'failed' || event.data?.error ? 'failed' : 'completed',
            }),
          }));
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
      undefined, // onHandoff — handled inline in the tool-event callback above
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
      (delta: string) => {
        // A reasoning delta belongs to this turn's message, as its own block —
        // not to a session-wide buffer that outlives the turn.
        setThinkingBuffer(prev => (prev + delta).slice(-4000));
        updateLastMessageWith(m => ({ ...m, blocks: appendReasoning(m.blocks || [], delta) }));
      }
    );
  };

  const handleResume = async (
    action: 'approve' | 'reject' | 'edit' | 'respond',
    value?: string,
    editedAction?: { name: string; args: Record<string, unknown> },
  ) => {
    if (!currentSessionId) return;
    setIsResuming(true);
    try {
      // Use raw fetch since apiClient doesn't have a resume method.
      // `edit` must carry the action to run instead (LangChain's decision
      // shape: {"type": "edit", "edited_action": {name, args}}); without it
      // the backend rejects the resume instead of silently continuing.
      const response = await fetch(`${apiClient.baseURL}/api/chat/${currentSessionId}/resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, value, edited_action: editedAction }),
      });
      if (!response.ok) {
        // Carry the server's reason: a 400 here means the graph was not parked the
        // way the resume expects (stale/orphan tool call), and the only symptom the
        // user sees otherwise is a review card that will not go away.
        let detail = '';
        try {
          detail = (await response.text()).slice(0, 300);
        } catch {
          /* body is a bonus */
        }
        throw new Error(`HTTP ${response.status} ${detail || response.statusText}`);
      }
      setPendingInterrupt(null);
      // Reload messages to show the resumed response. The decision note and the tool calls the
      // resumed run executed are persisted by the endpoint, so they arrive with this reload —
      // the client used to add its own note, which vanished on reload and would now duplicate.
      await loadHistory(currentSessionId);
      await refreshMetrics();
    } catch (err: any) {
      // Never fail silently: a failed resume leaves the review card on screen, and
      // "the box is still there" with no explanation is what that looks like.
      console.error('Failed to resume:', err);
      setSessionError(`审批没有生效：${err?.message || '请重试'}（卡片保持打开，可直接再试一次）`);
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
    handleStop,
    error,
    clearError,
    // metrics
    metrics,
    // context occupancy for the composer meter
    context,
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
    showCalendar,
    togglePanel,
    openDashboard,
    dashboardCount,
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
