/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useEffect, useRef } from 'react';
import { X, GripVertical, BarChart3, FolderOpen } from 'lucide-react';
import { useChat } from '../state/ChatContext';
import { useChatController } from '../hooks/useChatController';
import HitlInterruptModal from './HitlInterruptModal';
import FilesPanel from './FilesPanel';
import MetricsPanel from './MetricsPanel';
import MessagesPanel from './MessagesPanel';
import ChatHistorySidebar from './ChatHistorySidebar';
import AgentSelector from './AgentSelector';
import SidePanel from './SidePanel';

export default function GlobalChatModal() {
  const { isOpen, closeChat } = useChat();
  // Shared chat controller (same logic as ChatPage) — modal shell only
  const c = useChatController({ locale: 'zh', autoStart: isOpen });

  const modalRef = useRef<HTMLDivElement>(null);

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
        <div className="flex flex-shrink-0" style={{ width: c.sidebarWidth }}>
          <ChatHistorySidebar
            onNewSession={c.handleNewSession}
            onOpenFiles={() => c.togglePanel('files')}
          />
          {/* Resize Handle */}
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

        {/* Center area: Chat */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Slim Header */}
          <div className="flex items-center justify-between px-5 py-2 border-b" style={{ borderColor: 'var(--color-border-dark)' }}>
            <AgentSelector
              selectedAgentId={c.selectedAgentId}
              onSelectAgent={c.handleStartSession}
              displayName={c.agentName}
            />
            <div className="flex items-center gap-1">
              {/* Side panel toggles */}
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
              {/* Agent Creator workflow buttons */}
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
                        title="Test with the newly created agent"
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
              agentName={c.agentName}
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
        </div>
      </div>
      {/* HITL Interrupt Modal */}
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
