/**
 * ChatPage — standalone full-viewport chat window (opened from ActivityBar or agent Run).
 *
 * Same chat UI as GlobalChatModal but rendered as a full page without the modal
 * backdrop, designed to be opened in a separate browser window. All shared state
 * and handlers live in useChatController; this file keeps only the page-specific
 * concerns: URL ?agentId= auto-open, the independent theme CSS variables, the
 * close-window button, and the bottom toolbar.
 */

import { useEffect, useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { X, GripVertical, BarChart3, FolderOpen } from 'lucide-react';
import { useChat } from '../state/ChatContext';
import { useProject } from '../../../contexts/ProjectContext';
import { themes, type ThemeName } from '../../../lib/themes';
import { useChatController } from '../hooks/useChatController';
import HitlInterruptModal from './HitlInterruptModal';
import FilesPanel from './FilesPanel';
import MetricsPanel from './MetricsPanel';
import MessagesPanel from './MessagesPanel';
import ChatHistorySidebar from './ChatHistorySidebar';
import AgentSelector from './AgentSelector';
import ConversationTitle from './ConversationTitle';
import ChatMeta from './ChatMeta';
import type { ChatSession } from '../types/chat';
import ChatSettingsMenu from './ChatSettingsMenu';
import SidePanel from './SidePanel';

export default function ChatPage() {
  // The open conversation is labelled with its workspace (project), which sits
  // above the agent in the platform's hierarchy.
  const { activeProject } = useProject();
  const [searchParams] = useSearchParams();
  const agentIdFromUrl = searchParams.get('agentId');

  const { openChat } = useChat();
  // Shared chat controller (same logic as GlobalChatModal) — page shell only.
  // autoStart: true → auto-start a session once the URL-selected agent is set.
  const c = useChatController({ locale: 'en', autoStart: true });

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

  return (
    <div
      style={{
        display: 'flex',
        height: '100vh',
        width: '100vw',
        overflow: 'hidden',
        backgroundColor: 'var(--color-background-light)',
      }}
    >
      {/* Left Sidebar + Resize Handle */}
      <div className="flex flex-shrink-0" style={{ width: c.sidebarWidth }}>
        <ChatHistorySidebar
          onNewSession={c.handleNewSession}
          footer={
            // Settings + copyright, at the foot of the LEFT column and on ONE
            // line. DSH pins its `sidebar.settings` slot at the foot of the left
            // sidebar; this used to live in a window-wide bar under the composer,
            // which both crowded the box and read as a second toolbar.
            <div className="flex items-center gap-2 min-w-0">
              <ChatSettingsMenu
                sessionId={c.currentSessionId}
                messages={c.messages}
                metrics={c.metrics}
                toolCalls={c.toolCalls}
                subagentActivity={c.subagentActivity}
                agentName={c.agentName}
                themeName={chatTheme}
                onThemeChange={handleThemeChange}
                onClearHistory={c.clearHistory}
                onEndSession={c.handleEndSession}
              />
              <span className="text-[11px] truncate" style={{ color: 'var(--color-text-muted)' }}>
                Copyright © EBL 2026
              </span>
            </div>
          }
          footerCompact={
            // The 48px rail gets the control alone — the copyright line does not fit.
            <ChatSettingsMenu
              sessionId={c.currentSessionId}
              messages={c.messages}
              metrics={c.metrics}
              toolCalls={c.toolCalls}
              subagentActivity={c.subagentActivity}
              agentName={c.agentName}
              themeName={chatTheme}
              onThemeChange={handleThemeChange}
              onClearHistory={c.clearHistory}
              onEndSession={c.handleEndSession}
            />
          }
        />
        <div
          onMouseDown={c.handleResizeStart}
          className="w-2 cursor-col-resize flex items-center justify-center hover:bg-primary/10 active:bg-primary/20 transition-colors flex-shrink-0"
          style={{
            backgroundColor: c.isResizing ? 'var(--color-primary)' : 'transparent',
          }}
        >
          <GripVertical className="w-3 h-3 opacity-30 hover:opacity-60 transition-opacity" />
        </div>
      </div>

      {/* Main Content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Header — everything informational sits on the left (agent, then the
            conversation title with its date/time/length), actions on the right.
            The title truncates, so the metadata never gets pushed out. */}
        <div className="flex items-center px-5 py-2 gap-3">
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <AgentSelector
              selectedAgentId={c.selectedAgentId}
              onSelectAgent={c.handleStartSession}
              displayName={c.agentName}
            />
            {c.currentSessionId && (() => {
              // Title + pin belong to the OPEN conversation: pinning is a
              // decision made while reading, and the history rows stay clean.
              const session = c.sessions.find((s: ChatSession) => s.session_id === c.currentSessionId);
              const firstUserMessage = c.messages.find((m: any) => m.role === 'user')?.content;
              const fallback = firstUserMessage
                ? String(firstUserMessage).slice(0, 50)
                : 'New conversation';
              // Prefer the live count: it includes the turn being streamed,
              // while the stored one is only as fresh as the last list refresh.
              const liveCount = c.messages.length || session?.message_count || 0;
              return (
                // Nudged off the agent selector rather than sitting flush
                // against it — the single number below is the whole adjustment.
                <div className="flex items-center gap-2 min-w-0" style={{ marginLeft: 20 }}>
                  <ConversationTitle
                    title={session?.title ?? null}
                    fallback={fallback}
                    isFavorite={Boolean(session?.is_favorite)}
                    onRename={(title) => c.renameSession(c.currentSessionId!, title)}
                    onToggleFavorite={() => c.toggleFavorite(c.currentSessionId!)}
                  />
                  <ChatMeta
                    createdAt={session?.created_at}
                    updatedAt={session?.updated_at}
                    messageCount={liveCount}
                  />
                </div>
              );
            })()}
          </div>
          <div className="flex items-center gap-1 flex-shrink-0">
            {c.currentSessionId && (
              <>
                <button
                  onClick={() => c.togglePanel('metrics')}
                  className={`p-2 rounded-lg transition-colors ${c.showMetrics ? 'bg-gray-100 dark:bg-gray-800' : 'hover:bg-gray-100 dark:hover:bg-gray-800'}`}
                  title={c.showMetrics ? 'Hide metrics' : 'Show metrics'}
                >
                  <BarChart3 className="w-4 h-4" style={{ color: c.showMetrics ? 'var(--color-primary)' : 'var(--color-text-muted)' }} />
                </button>
                <button
                  onClick={() => c.togglePanel('files')}
                  className={`p-2 rounded-lg transition-colors ${c.showFiles ? 'bg-gray-100 dark:bg-gray-800' : 'hover:bg-gray-100 dark:hover:bg-gray-800'}`}
                  title={c.showFiles ? 'Hide files' : 'Show files'}
                >
                  <FolderOpen className="w-4 h-4" style={{ color: c.showFiles ? 'var(--color-primary)' : 'var(--color-text-muted)' }} />
                </button>
              </>
            )}
            {c.isAgentCreator && c.currentSessionId && (
              <>
                {!c.savedAgentId ? (
                  <button
                    onClick={c.handleSaveFromCreator}
                    disabled={c.saving}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
                    style={{
                      background: c.saving
                        ? 'rgba(0, 109, 221, 0.5)'
                        : 'linear-gradient(135deg, #006DDD 0%, #7FC8FF 100%)',
                      color: '#FFFFFF',
                      boxShadow: c.saving ? 'none' : '0 0 8px rgba(0, 109, 221, 0.3)',
                      opacity: c.saving ? 0.7 : 1,
                    }}
                    title={c.saveError || 'Save designed agent to library'}
                  >
                    {c.saving ? 'Saving...' : 'Save Agent'}
                  </button>
                ) : (
                  <>
                    <button
                      onClick={c.handleTestNewAgent}
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
                      onClick={() => c.handleStartSession(112)}
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
            messages={c.messages}
            isStreaming={c.isStreaming}
            error={c.error}
            onSendMessage={c.handleSendMessage}
            onClearError={c.clearError}
            disabled={!c.currentSessionId}
            sessionId={c.currentSessionId}
            projectId={c.activeProjectId}
            activeToolCalls={c.activeToolCalls}
            customEvents={c.customEvents}
            thinkingTraces={c.thinkingTraces}
            thinkingBuffer={c.thinkingBuffer}
            workspaceName={activeProject?.name || undefined}
            agentName={c.agentName}
            context={c.context}
            stats={c.currentSessionId ? {
              tokens: c.metrics?.total_tokens || 0,
              toolCalls: c.toolCalls?.length || 0,
              theme: chatTheme,
            } : null}
          />
          {c.currentSessionId && c.showMetrics && (
            <SidePanel
              width={c.panelWidth}
              isResizing={c.isPanelResizing}
              onResizeStart={c.handlePanelResizeStart}
            >
              <MetricsPanel
                metrics={c.metrics}
                toolCalls={c.toolCalls}
                activeToolCalls={c.activeToolCalls}
                subagentActivity={c.subagentActivity}
                isLoading={c.isLoadingMetrics}
                agentName={c.agentName}
                agentDescription={c.agentDescription}
                sessionId={c.currentSessionId}
              />
            </SidePanel>
          )}
          {c.currentSessionId && c.showFiles && (
            <SidePanel
              width={c.panelWidth}
              isResizing={c.isPanelResizing}
              onResizeStart={c.handlePanelResizeStart}
            >
              <FilesPanel
                sessionId={c.currentSessionId}
                onClose={() => c.togglePanel('files')}
              />
            </SidePanel>
          )}
        </div>

        {/* No bar under the chat area: settings and the copyright moved to the
            foot of the left sidebar, and the composer block is now the last thing
            in this column — the box sits at the bottom, as DSH ends its column.
            The old bar's "No session — pick an agent to start" hint is already
            the composer's own placeholder ("No agent selected"). */}

      </div>

      {c.pendingInterrupt && (
        <HitlInterruptModal
          pendingInterrupt={c.pendingInterrupt}
          isResuming={c.isResuming}
          onResume={c.handleResume}
        />
      )}
    </div>
  );
}
