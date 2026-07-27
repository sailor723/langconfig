/**
 * chatStore — shared state for the right-sidebar chat panel.
 *
 * DeepAgentEditor's Run button writes user/assistant messages here.
 * NodeSidebar's ChatSidebar reads from here and renders them.
 *
 * Simple module-level singleton (no React Context needed — re-render
 * is driven by a manual subscription list, since the consumers are
 * deep inside the tree and adding a Provider is overkill).
 *
 * Supports both blocking POST /api/chat/message and SSE streaming
 * via POST /api/chat/message/stream.
 */
import { useEffect, useState } from 'react';
import apiClient from '../../lib/api-client';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  text: string;
  /** Optional metadata (tokens, tool calls, etc.) */
  meta?: { tokens?: number; toolCalls?: number; latencyMs?: number };
  /** Reasoning trace extracted from <think>...</think> blocks (assistant only) */
  thinking?: string;
  /** Subagent / tool activity log */
  activity?: Array<{ type: string; name?: string; detail?: string }>;
  /** Streaming: true while this message is still being received */
  streaming?: boolean;
  ts: number;
}

class ChatStoreImpl {
  private messages: ChatMessage[] = [];
  /** Currently active chat session id (created by DeepAgent Run button) */
  private sessionId: string | null = null;
  /** Currently active deep agent id (for follow-up messages) */
  private agentId: number | null = null;
  private listeners = new Set<() => void>();

  /** AbortController for the current in-flight stream */
  private abortController: AbortController | null = null;
  /** Whether a stream is currently in progress */
  private _isStreaming = false;

  /** Tool phase tracking — mirrors useChatStreaming pattern */
  private toolPhaseSeen = false;
  private toolPhaseActive = false;
  private toolPhaseCount = 0;
  private thinkingBuffer = '';

  getMessages(): ChatMessage[] {
    return this.messages;
  }

  getSessionId(): string | null {
    return this.sessionId;
  }

  getAgentId(): number | null {
    return this.agentId;
  }

  isStreaming(): boolean {
    return this._isStreaming;
  }

  add(msg: Omit<ChatMessage, 'id' | 'ts'>): ChatMessage {
    const full: ChatMessage = {
      ...msg,
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      ts: Date.now(),
    };
    this.messages = [...this.messages, full];
    this.emit();
    return full;
  }

  setSession(sessionId: string, agentId: number): void {
    this.sessionId = sessionId;
    this.agentId = agentId;
    this.emit();
  }

  /** Cancel the current in-flight stream, if any */
  cancelStream(): void {
    if (this.abortController) {
      this.abortController.abort();
      this.abortController = null;
    }
    this._isStreaming = false;
    this.emit();
  }

  clear(): void {
    this.cancelStream();
    this.messages = [];
    this.sessionId = null;
    this.agentId = null;
    this.emit();
  }

  subscribe(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit(): void {
    for (const fn of this.listeners) fn();
  }

  /**
   * Send a message via SSE streaming and update the store incrementally.
   *
   * Matches the battle-tested pattern from `useChatStreaming`:
   *   - AbortController for cancellation
   *   - Thinking phase tracking: content before first tool_start is tracked
   *     as "thinking" (shown as reasoning trace)
   *   - tool_start/tool_end events tracked
   *
   * @returns The assistant message id once streaming completes (or fails).
   */
  async sendStreamMessage(
    agentId: number,
    prompt: string,
    agentName?: string,
  ): Promise<string | null> {
    if (this._isStreaming) return null;

    // Add user message
    this.messages = [...this.messages, {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      role: 'user',
      text: agentName ? `[${agentName}] ${prompt}` : prompt,
      ts: Date.now(),
    }];
    this.emit();

    // Start session if needed
    let sessionId = this.sessionId;
    if (!sessionId) {
      try {
        const res = await fetch('/api/chat/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ agent_id: agentId }),
        });
        if (!res.ok) throw new Error(`Start session failed: ${res.status}`);
        const data = await res.json();
        sessionId = data.session_id ?? data.id;
        if (sessionId) this.setSession(sessionId, agentId);
        else { this.add({ role: 'system', text: '// Failed to start session: no session_id returned' }); return null; }
      } catch (err: any) {
        this.add({ role: 'system', text: `// Failed to start session: ${err.message}` });
        return null;
      }
    }

    // Create a placeholder assistant message for streaming
    this._isStreaming = true;
    this.abortController = new AbortController();
    this.toolPhaseSeen = false;
    this.toolPhaseActive = false;
    this.toolPhaseCount = 0;
    this.thinkingBuffer = '';

    const assistantId = `stream-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      text: '',
      thinking: '',
      streaming: true,
      ts: Date.now(),
    };
    this.messages = [...this.messages, assistantMsg];
    this.emit();

    let fullText = '';
    let fullThinking = '';
    const startedAt = Date.now();

    try {
      const response = await fetch(`${apiClient.baseURL}/api/chat/message/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message: prompt }),
        signal: this.abortController.signal,
      });
      if (!response.ok) throw new Error(`Stream request failed: ${response.status}`);

      const reader = response.body?.getReader();
      if (!reader) throw new Error('No response body');

      const decoder = new TextDecoder();
      let buffer = '';
      let assistantAdded = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // Keep partial last line in buffer

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || !trimmed.startsWith('data: ')) continue;

          try {
            const payload = JSON.parse(trimmed.slice(6));

            switch (payload.type) {
              case 'chunk': {
                const token = payload.content || '';
                fullText += token;

                // Track pre-tool content as thinking (mirrors useChatStreaming)
                if (!this.toolPhaseSeen) {
                  this.thinkingBuffer += token;
                  fullThinking = this.thinkingBuffer;
                }

                if (!assistantAdded) {
                  // First chunk: add the assistant message
                  this._updateMessage(assistantId, {
                    text: fullText,
                    thinking: fullThinking || undefined,
                    streaming: true,
                  });
                  assistantAdded = true;
                } else {
                  this._updateMessage(assistantId, {
                    text: fullText,
                    streaming: true,
                  });
                }
                break;
              }

              case 'thinking': {
                // Backend emits this for <think>...</think> blocks
                fullThinking += payload.content || '';
                this._updateMessage(assistantId, {
                  thinking: fullThinking,
                  streaming: true,
                });
                break;
              }

              case 'tool_start': {
                // First tool_start marks end of thinking phase
                if (!this.toolPhaseSeen) {
                  this.toolPhaseSeen = true;
                }
                this.toolPhaseCount += 1;
                this.toolPhaseActive = true;
                break;
              }

              case 'tool_end': {
                this.toolPhaseCount -= 1;
                if (this.toolPhaseCount <= 0) {
                  this.toolPhaseCount = 0;
                  this.toolPhaseActive = false;
                }
                break;
              }

              case 'complete': {
                // Authoritative final content from backend
                if (payload.content && payload.content !== fullText) {
                  fullText = payload.content;
                }
                this._updateMessage(assistantId, {
                  text: fullText,
                  thinking: fullThinking || undefined,
                  streaming: false,
                  meta: { latencyMs: Date.now() - startedAt },
                });
                break;
              }

              case 'error': {
                this._updateMessage(assistantId, {
                  text: fullText || `// Error: ${payload.message || 'unknown'}`,
                  streaming: false,
                });
                this._isStreaming = false;
                this.abortController = null;
                return assistantId;
              }

              case 'interrupt': {
                this._updateMessage(assistantId, {
                  text: fullText || '(interrupted — awaiting approval)',
                  streaming: false,
                });
                this._isStreaming = false;
                this.abortController = null;
                return assistantId;
              }
            }
          } catch {
            // Skip malformed SSE lines
          }
        }
      }

      // Stream ended normally — finalize
      this._updateMessage(assistantId, {
        text: fullText,
        thinking: fullThinking || undefined,
        streaming: false,
        meta: { latencyMs: Date.now() - startedAt },
      });

      this._isStreaming = false;
      this.abortController = null;
      return assistantId;

    } catch (err: any) {
      if (err.name === 'AbortError') {
        // User cancelled — mark as cancelled, not error
        this._updateMessage(assistantId, {
          text: fullText || '(cancelled)',
          streaming: false,
        });
      } else {
        this._updateMessage(assistantId, {
          text: fullText || `// Stream failed: ${err.message}`,
          streaming: false,
        });
      }
      this._isStreaming = false;
      this.abortController = null;
      return assistantId;
    }
  }

  /** Update a message in-place by id and emit. */
  private _updateMessage(id: string, patch: Partial<ChatMessage>): void {
    this.messages = this.messages.map(m =>
      m.id === id ? { ...m, ...patch } : m,
    );
    this.emit();
  }
}

export const chatStore = new ChatStoreImpl();

/**
 * useChatMessages — subscribe a component to the chat store.
 * Returns the current messages array; re-renders when messages change.
 */
export function useChatMessages(): ChatMessage[] {
  const [msgs, setMsgs] = useState(chatStore.getMessages());
  useEffect(() => chatStore.subscribe(() => setMsgs(chatStore.getMessages())), []);
  return msgs;
}
