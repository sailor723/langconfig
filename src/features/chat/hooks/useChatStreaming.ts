/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useState, useCallback, useRef } from 'react';
import type { ChatMessage, ChatStreamEvent } from '../types/chat';
import apiClient from '../../../lib/api-client';

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
  ) => Promise<void>;
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
        // Call streaming endpoint
        const response = await fetch(`${apiClient.baseURL}/api/chat/message/stream`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: sessionId,
            message: message,
            enable_hitl: hitlEnabled,
          }),
          signal: abortControllerRef.current.signal,
        });

        if (!response.ok) {
          throw new Error(`Failed to send message: ${response.statusText}`);
        }

        // Read stream
        const reader = response.body?.getReader();
        const decoder = new TextDecoder();

        if (!reader) {
          throw new Error('No reader available for response stream');
        }

        let accumulatedContent = '';
        let assistantMessageAdded = false;

        while (true) {
          const { done, value } = await reader.read();

          if (done) break;

          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split('\n');

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data: ChatStreamEvent = JSON.parse(line.substring(6));

                if (data.type === 'chunk') {
                  if (!toolPhaseSeenRef.current) {
                    // Before any tool call → this is thinking content only
                    thinkingBufferRef.current += data.content;
                    accumulatedContent += data.content;  // keep for fallback
                    if (onThinkingUpdate) {
                      onThinkingUpdate(thinkingBufferRef.current);
                    }
                  } else {
                    // After tool phase → this is answer content (accumulatedContent was reset)
                    accumulatedContent += data.content;
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
                  }
                } else if (data.type === 'complete') {
                  // If never created assistant msg (no-tool path), create it now
                  if (!assistantMessageAdded) {
                    const finalContent = data.content || thinkingBufferRef.current || accumulatedContent;
                    const assistantMessage: ChatMessage = {
                      role: 'assistant',
                      content: finalContent,
                      timestamp: new Date().toISOString(),
                    };
                    onMessageAdd(assistantMessage);
                  }
                } else if (data.type === 'error') {
                  setError(data.message || 'An error occurred during streaming');
                } else if (data.type === 'tool_start') {
                  // First tool call marks the end of thinking phase
                  if (!toolPhaseSeenRef.current) {
                    toolPhaseSeenRef.current = true;
                    accumulatedContent = '';  // Reset for answer content
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
              } catch (parseError) {
                // Skip invalid JSON lines
                console.warn('Failed to parse SSE data:', line);
              }
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

  // Cleanup on unmount
  const cancel = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsStreaming(false);
  }, []);

  return {
    sendMessage,
    isStreaming,
    error,
    clearError,
  };
}
