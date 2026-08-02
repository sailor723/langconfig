/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import type { ChatMessage, ChatStreamEvent } from '../types/chat';
import { streamChatEvents } from '../utils/streamChatEvents';

interface UseChatStreamingResult {
  sendMessage: (
    message: string,
    onMessageAdd: (message: ChatMessage) => void,
    onMessageUpdate: (content: string) => void,
    onComplete: () => void,
    onToolEvent?: (event: ChatStreamEvent) => void,
    onCustomEvent?: (event: ChatStreamEvent) => void,
    onInterrupt?: (event: ChatStreamEvent) => void,
    /** Called with thinking content (pre-tool-call text) during streaming */
    onThinkingUpdate?: (content: string) => void,
    /** Optional doc scope — when provided (and non-empty), the backend
        chat agent will only consider / read these docs (by name). */
    scope?: string[] | null,
    /** Optional active project id — when provided, the Phase 9 chat
        agent queries this project's Neo4j catalog instead of
        falling back to the hardcoded project 1 (which is usually
        empty and causes "no documents in project X"). */
    projectId?: number | null,
  ) => Promise<void>;
  /** Abort the current in-flight stream (also called automatically on unmount) */
  cancel: () => void;
  isStreaming: boolean;
  error: string | null;
  clearError: () => void;
}

export function useChatStreaming(
  sessionId: string | null,
  hitlEnabled: boolean = false
): UseChatStreamingResult {
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  // Track tool phase for separating thinking content from answer content
  const toolPhaseCountRef = useRef(0);
  const toolPhaseActiveRef = useRef(false);
  const toolPhaseSeenRef = useRef(false);
  const thinkingBufferRef = useRef('');

  const clearError = useCallback(() => {
    setError(null);
  }, []);

  const sendMessage = useCallback(
    async (
      message: string,
      onMessageAdd: (message: ChatMessage) => void,
      onMessageUpdate: (content: string) => void,
      onComplete: () => void,
      onToolEvent?: (event: ChatStreamEvent) => void,
      onCustomEvent?: (event: ChatStreamEvent) => void,
      onInterrupt?: (event: ChatStreamEvent) => void,
      onThinkingUpdate?: (content: string) => void,
      scope?: string[] | null,
      projectId?: number | null,
    ) => {
      if (!sessionId || isStreaming) return;

      setError(null);
      setIsStreaming(true);

      // Reset tool phase tracking
      toolPhaseCountRef.current = 0;
      toolPhaseActiveRef.current = false;
      toolPhaseSeenRef.current = false;
      thinkingBufferRef.current = '';

      // Create abort controller for cancellation
      abortControllerRef.current = new AbortController();

      // Add user message immediately
      const userMessage: ChatMessage = {
        role: 'user',
        content: message,
        timestamp: new Date().toISOString(),
      };
      onMessageAdd(userMessage);

      try {
        // Call streaming endpoint. Only include `scope` when the caller
        // passed a non-empty list — sending `scope: []` or `scope: null`
        // would be ambiguous (does empty mean "no filter" or "filter
        // to nothing"?). We treat both as "no filter" by omitting.
        const requestBody: Record<string, unknown> = {
          session_id: sessionId,
          message: message,
          enable_hitl: hitlEnabled,
        };
        if (scope && scope.length > 0) {
          requestBody.scope = scope;
        }
        // Forward the active project so the Phase 9 chat agent queries
        // the right Neo4j catalog. Without this, the backend falls
        // back to the agent template's project_id (currently always
        // None) and ultimately to project 1 — which is usually empty
        // and the most common cause of "no documents in project X".
        if (projectId != null) {
          requestBody.project_id = projectId;
        }

        let accumulatedContent = '';
        let assistantMessageAdded = false;

        // Shared SSE transport — fetch + `data:` parsing live in
        // streamChatEvents so this hook and chatStore don't each
        // reimplement the reader loop.
        const events = streamChatEvents('/api/chat/message/stream', requestBody, abortControllerRef.current.signal);
        for await (const raw of events) {
          const data = raw as ChatStreamEvent;

          if (data.type === 'chunk') {
            // The LLM's content chunks go directly into the
            // assistant message. The backend already strips
            // <think>...</think> blocks before streaming
            // (see routes.py:778), so the chunks are the
            // LLM's final answer, not its private thinking.
            //
            // We previously buffered pre-tool chunks into a
            // separate "thinkingBufferRef" and only added the
            // assistant message after tool_start, relying on
            // a `complete` event for the no-tool case. The
            // Phase 9 backend only sends `done` (not
            // `complete`), so for greetings / identity
            // questions / small talk the assistant message
            // was never created and the user saw the previous
            // turn's content. The fix: use the LLM's chunks
            // directly and add the message on the first chunk,
            // matching the pre-64b638c behavior.
            //
            // We also keep `thinkingBufferRef` populated so
            // the "Show thinking" toggle in the UI still has
            // content to display. For the no-tool case, the
            // thinking equals the answer (which is fine — the
            // toggle is just a no-op visual element).
            accumulatedContent += data.content;
            if (!toolPhaseSeenRef.current) {
              thinkingBufferRef.current += data.content;
              if (onThinkingUpdate) {
                onThinkingUpdate(thinkingBufferRef.current);
              }
            }
            if (!assistantMessageAdded) {
              const assistantMessage: ChatMessage = {
                role: 'assistant',
                content: accumulatedContent,
                timestamp: new Date().toISOString(),
              };
              onMessageAdd(assistantMessage);
              assistantMessageAdded = true;
            } else {
              onMessageUpdate(accumulatedContent);
            }
          } else if (data.type === 'complete') {
            // If the backend DOES send `complete` (legacy
            // path, or future Phase 9 path), use it as the
            // authoritative final content. The Phase 9 path
            // doesn't currently send `complete`, so this is
            // a no-op for that path — but it keeps the
            // handler robust if the backend adds it later.
            if (data.content && data.content !== accumulatedContent) {
              accumulatedContent = data.content;
              onMessageUpdate(accumulatedContent);
            }
          } else if (data.type === 'thinking') {
            // Backend emits this for <think>...</think> blocks
            // (e.g., Minimax M3's reasoning) — separate from
            // the final answer text.
            thinkingBufferRef.current += data.content;
            if (onThinkingUpdate) {
              onThinkingUpdate(thinkingBufferRef.current);
            }
          } else if (data.type === 'error') {
            setError(data.message || 'An error occurred during streaming');
          } else if (data.type === 'tool_start') {
            // First tool call marks the end of thinking phase.
            // We do NOT reset accumulatedContent here — the
            // message is now the LLM's full response (pre-
            // + post-tool), and resetting would wipe it. The
            // tool-using case will keep streaming more
            // chunks after this, which will append to the
            // existing message.
            if (!toolPhaseSeenRef.current) {
              toolPhaseSeenRef.current = true;
            }
            toolPhaseCountRef.current += 1;
            toolPhaseActiveRef.current = true;
            if (onToolEvent) {
              onToolEvent(data);
            }
          } else if (data.type === 'tool_end') {
            toolPhaseCountRef.current -= 1;
            if (toolPhaseCountRef.current <= 0) {
              toolPhaseCountRef.current = 0;
              toolPhaseActiveRef.current = false;
            }
            if (onToolEvent) {
              onToolEvent(data);
            }
          } else if (data.type === 'custom_event') {
            // Pass custom events to callback (LangGraph-style progress, status, etc.)
            if (onCustomEvent) {
              onCustomEvent(data);
            }
          } else if (data.type === 'interrupt') {
            // HITL interrupt: pause streaming and show approval UI
            // Don't mark streaming as done — user will resume
            if (onInterrupt) {
              onInterrupt(data);
            }
          }
        }

        // Streaming complete
        setIsStreaming(false);
        onComplete();
      } catch (err: any) {
        if (err.name === 'AbortError') {
          console.log('Stream aborted by user');
        } else {
          console.error('Failed to send message:', err);
          setError(err.message || 'Failed to send message');
        }
        setIsStreaming(false);
      }
    },
    [sessionId, hitlEnabled, isStreaming]
  );

  // Cleanup on unmount — abort any in-flight stream so the aborted request
  // can't keep writing into state after the component is gone
  const cancel = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsStreaming(false);
  }, []);

  useEffect(() => cancel, [cancel]);

  return {
    sendMessage,
    cancel,
    isStreaming,
    error,
    clearError,
  };
}
