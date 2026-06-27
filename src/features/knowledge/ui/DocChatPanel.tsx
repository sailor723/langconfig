/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useEffect, useState } from 'react';
import { Loader, MessageCircle, Sparkles } from 'lucide-react';
import apiClient from '../../../lib/api-client';
import { useChat } from '../../chat/state/ChatContext';
import { useChatSession } from '../../chat/hooks/useChatSession';
import { useChatStreaming } from '../../chat/hooks/useChatStreaming';
import MessagesPanel from '../../chat/ui/MessagesPanel';
import { useToast } from '../../../hooks/useToast';
import type { ChatStreamEvent } from '../../chat/types/chat';

interface DocChatPanelProps {
  projectId: number | null;
  /** Called when the chat picks a doc (e.g. the LLM called
      graphindex_multi_doc_load with primary=...). The parent uses
      this to scroll/highlight/select the doc in the left column. */
  onDocSelected?: (docName: string) => void;
}

/**
 * Right-column chat panel for the Knowledge panel.
 *
 * Always uses the `graphindex_chat` deepagent (the Phase 9 template) — the
 * same agent that was previously offered via the "Use in agent builder"
 * button. The 4 graphindex_* tools (list / search / load / multi_doc_load)
 * let the LLM route the query to the right project document(s) and answer
 * from their content.
 *
 * Lifecycle:
 *   1. On mount + project_id change → look up the `graphindex_chat` agent
 *      id by name in the user's deepagent library. If missing, show a
 *      friendly placeholder asking the user to import it once.
 *   2. Auto-start a new chat session with that agent id.
 *   3. Drive messages via `useChatSession` + `useChatStreaming` from the
 *      existing chat module — no duplication of streaming logic.
 *
 * The panel does NOT add the chat to the global chat modal's history
 * automatically (we don't `openChat()` it). Each project gets its own
 * fresh session per panel-mount.
 */
export default function DocChatPanel({ projectId, onDocSelected }: DocChatPanelProps) {
  const { startSession, currentSessionId } = useChat();
  const { showToast } = useToast();

  // Lookup state — graphindex_chat agent id from the user's library
  const [agentId, setAgentId] = useState<number | null>(null);
  const [agentName, setAgentName] = useState<string>('graphindex_chat');
  const [agentDescription, setAgentDescription] = useState<string>('');
  const [lookupError, setLookupError] = useState<string | null>(null);

  // Session hooks (only active when we have a session_id)
  const {
    messages,
    isLoading: isLoadingSession,
    error: sessionError,
    addMessage,
    updateLastMessage,
    loadHistory,
    clearHistory,
  } = useChatSession(currentSessionId);

  const {
    sendMessage,
    isStreaming,
    error: streamingError,
    clearError: clearStreamingError,
  } = useChatStreaming(currentSessionId, false);

  // Resolve the graphindex_chat agent id (and start a session) when
  // projectId becomes available. We look it up by name in the user's
  // deepagent library.
  useEffect(() => {
    let cancelled = false;
    if (!projectId) {
      setAgentId(null);
      setLookupError(null);
      return;
    }
    setLookupError(null);
    apiClient
      .listDeepAgents({ public_only: false })
      .then((res: any) => {
        if (cancelled) return;
        const agents: any[] = res.data || [];
        const match = agents.find(
          (a: any) =>
            a.name === 'graphindex_chat' ||
            a.name === 'GraphIndex Chat' ||
            (a.tools || []).includes('graphindex_multi_doc_load')
        );
        if (match) {
          setAgentId(match.id);
          setAgentName(match.name);
          setAgentDescription(match.description || '');
        } else {
          setLookupError(
            'graphindex_chat agent not found in your library. Open the Knowledge panel once with the old banner to import it.'
          );
        }
      })
      .catch((err: any) => {
        if (cancelled) return;
        setLookupError(
          err?.response?.data?.detail || err?.message || 'Failed to load agents'
        );
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Once we know the agent id, start a fresh session for this project.
  // We avoid auto-restarting if a session is already active for this agent.
  useEffect(() => {
    if (!projectId || !agentId) return;
    if (currentSessionId) return; // already have one
    startSession(agentId).catch((err: any) => {
      showToast(
        err?.response?.data?.detail || 'Failed to start chat session',
        'error',
        4000
      );
    });
  }, [projectId, agentId, currentSessionId, startSession, showToast]);

  // Tool-event handler: detect when the LLM picks a doc and notify
  // the parent. The two tool calls that reveal a doc are:
  //   - graphindex_multi_doc_load → output_preview starts with
  //     "=== Document 1 (PRIMARY): <doc_name> ==="
  //   - graphindex_search → output_preview is a JSON with "results"
  //     and each result has "name"
  const handleToolEvent = (ev: ChatStreamEvent) => {
    if (!onDocSelected) return;
    if (ev.type !== 'tool_end') return;
    const toolName = (ev as any).tool_name;
    const preview: string = (ev as any).data?.output_preview || '';
    // 1) graphindex_multi_doc_load: parse === Document N (PRIMARY): name ===
    if (toolName === 'graphindex_multi_doc_load') {
      const m = preview.match(/=== Document \d+ \(PRIMARY\): (.+?) ===/);
      if (m && m[1]) {
        onDocSelected(m[1].trim());
      }
    }
    // 2) graphindex_search: parse JSON "results": [{ "name": ... }]
    if (toolName === 'graphindex_search') {
      try {
        // The preview may be the raw text or a JSON string. Try both.
        const txt = preview.trim();
        const obj = JSON.parse(txt);
        const first = obj?.results?.[0]?.name || obj?.primary?.name;
        if (first) onDocSelected(String(first));
      } catch {
        // ignore — preview may not be JSON
      }
    }
  };

  // ----- Render -----

  return (
    <div className="h-full flex flex-col bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg overflow-hidden">
      {/* Header — agent name + description */}
      <div
        className="flex items-center gap-2 px-3 py-2 border-b border-gray-200 dark:border-border-dark flex-shrink-0"
        style={{
          backgroundImage: 'linear-gradient(135deg, rgba(168, 85, 247, 0.06), rgba(99, 102, 241, 0.06))',
        }}
      >
        <div
          className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
          style={{ backgroundColor: 'rgba(168, 85, 247, 0.15)' }}
        >
          <Sparkles className="w-3.5 h-3.5" style={{ color: '#a855f7' }} />
        </div>
        <div className="flex-1 min-w-0">
          <p
            className="text-[11px] font-semibold truncate"
            style={{ color: 'var(--color-text-primary)' }}
            title={agentDescription || agentName}
          >
            {agentName}
          </p>
          <p
            className="text-[9px] truncate"
            style={{ color: 'var(--color-text-muted)' }}
          >
            {agentDescription || 'Phase 9 / 4 GraphIndex tools'}
          </p>
        </div>
      </div>

      {/* Body — depends on state */}
      {!projectId ? (
        <EmptyHint icon={<MessageCircle className="w-6 h-6" />} text="Select a project to start chatting with your documents." />
      ) : lookupError ? (
        <EmptyHint icon={<MessageCircle className="w-6 h-6" />} text={lookupError} />
      ) : !currentSessionId ? (
        <div className="flex-1 flex items-center justify-center text-xs gap-2" style={{ color: 'var(--color-text-muted)' }}>
          <Loader className="w-3.5 h-3.5 animate-spin" />
          Starting chat session…
        </div>
      ) : (
        <>
          <div
            className="flex-1 overflow-y-auto overflow-x-auto kb-chat-scroll"
            // The kb-chat-scroll class gives the chat a custom scrollbar
            // (see globals.css) so the user has both vertical and
            // horizontal scroll for long content like code blocks or
            // wide tables.
            tabIndex={0}
            onKeyDown={(e) => {
              // Keyboard nav: PgUp/PgDn scroll the chat by one page.
              // ArrowUp/ArrowDown scroll by 60px (one line). This
              // gives the user fine control without leaving the chat.
              const el = e.currentTarget;
              if (e.key === 'PageUp') { el.scrollBy({ top: -el.clientHeight, behavior: 'smooth' }); e.preventDefault(); }
              else if (e.key === 'PageDown') { el.scrollBy({ top: el.clientHeight, behavior: 'smooth' }); e.preventDefault(); }
              else if (e.key === 'ArrowUp' && (e.metaKey || e.ctrlKey)) { el.scrollBy({ top: -60, behavior: 'smooth' }); e.preventDefault(); }
              else if (e.key === 'ArrowDown' && (e.metaKey || e.ctrlKey)) { el.scrollBy({ top: 60, behavior: 'smooth' }); e.preventDefault(); }
              else if (e.key === 'Home' && (e.metaKey || e.ctrlKey)) { el.scrollTo({ top: 0, behavior: 'smooth' }); e.preventDefault(); }
              else if (e.key === 'End' && (e.metaKey || e.ctrlKey)) { el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }); e.preventDefault(); }
            }}
          >
            <MessagesPanel
              messages={messages}
              isStreaming={isStreaming}
              error={streamingError || sessionError}
              onSendMessage={(text) =>
                sendMessage(
                  text,
                  addMessage,
                  updateLastMessage,
                  () => {
                    // onComplete — streaming finished
                  },
                  handleToolEvent,  // <- detects when LLM picks a doc
                ).catch(() => {})
              }
              onClearError={() => {
                clearStreamingError();
              }}
              disabled={isStreaming || isLoadingSession}
              sessionId={currentSessionId}
              projectId={projectId}
            />
          </div>
        </>
      )}
    </div>
  );
}

function EmptyHint({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="flex-1 flex items-center justify-center p-4">
      <div className="text-center max-w-xs">
        <div className="mx-auto mb-2 opacity-40" style={{ color: 'var(--color-text-muted)' }}>
          {icon}
        </div>
        <p className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>
          {text}
        </p>
      </div>
    </div>
  );
}