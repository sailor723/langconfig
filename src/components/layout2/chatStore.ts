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
import { streamChatEvents } from '../../features/chat/utils/streamChatEvents';

/** Per-tool-call record captured during streaming */
export interface ChatToolCall {
  /** Tool name as emitted by the backend (e.g. "math_sqrt", "Web Search") */
  name: string;
  /** Tool-call id from the backend (e.g. LangChain tool_call_id) */
  id?: string;
  /** Arguments passed to the tool (parsed if backend sent them as JSON) */
  args?: Record<string, any>;
  /** Result text returned by the tool (empty while still running) */
  result?: string;
  /** Lifecycle state */
  status: 'running' | 'completed' | 'error';
  /** When the tool call started streaming in (epoch ms) */
  startedAt: number;
  /** When the tool call finished (epoch ms) */
  endedAt?: number;
  /** Error message when status === 'error' */
  error?: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  text: string;
  /** Optional metadata (tokens, tool calls, etc.) */
  meta?: { tokens?: number; toolCalls?: number; latencyMs?: number };
  /** Reasoning trace extracted from  think... think blocks (assistant only) */
  thinking?: string;
  /** Subagent / tool activity log */
  activity?: Array<{ type: string; name?: string; detail?: string }>;
  /** Tool calls invoked while producing this message, in order */
  toolCalls?: ChatToolCall[];
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
   * The SSE transport (fetch + `data:` parsing) is shared with
   * `useChatStreaming` via `streamChatEvents` — only the event
   * handling below differs.
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
        const res = await fetch(`${apiClient.baseURL}/api/chat/start`, {
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
      let assistantAdded = false;

      // Shared SSE transport — fetch + `data:` parsing live in
      // streamChatEvents (same transport as useChatStreaming).
      const events = streamChatEvents(
        '/api/chat/message/stream',
        { session_id: sessionId, message: prompt },
        this.abortController.signal,
      );
      for await (const payload of events) {
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

          case 'custom_event': {
            // LangGraph-style progress/status events are not rendered in
            // the compact sidebar chat — intentionally ignored here (the
            // full ChatPage renders them via useChatStreaming instead).
            break;
          }

          case 'tool_start': {
            // First tool_start marks end of thinking phase
            if (!this.toolPhaseSeen) {
              this.toolPhaseSeen = true;
            }
            this.toolPhaseCount += 1;
            this.toolPhaseActive = true;
            // Capture the tool call into the assistant message so the UI can render it
            const calls = this._getToolCalls(assistantId);
            calls.push({
              name: payload.tool_name || payload.name || 'unknown_tool',
              id: payload.tool_call_id || payload.id,
              args: payload.args || payload.arguments || payload.input,
              status: 'running',
              startedAt: Date.now(),
            });
            this._updateMessage(assistantId, { toolCalls: calls });
            break;
          }

          case 'tool_end': {
            this.toolPhaseCount -= 1;
            if (this.toolPhaseCount <= 0) {
              this.toolPhaseCount = 0;
              this.toolPhaseActive = false;
            }
            // Mark the matching tool call as completed/error
            const calls = this._getToolCalls(assistantId);
            const targetName = payload.tool_name || payload.name;
            const targetId = payload.tool_call_id || payload.id;
            // Find the last running call that matches (by id, then by name)
            const lastIdx: number = (() => {
              for (let i = calls.length - 1; i >= 0; i--) {
                const c = calls[i];
                if (c.status !== 'running') continue;
                if (targetId && c.id === targetId) return i;
                if (targetName && c.name === targetName) return i;
                if (!targetId && !targetName) return i;
              }
              return -1;
            })();
            if (lastIdx >= 0) {
              const tc = calls[lastIdx];
              const hasError = !!payload.error;
              calls[lastIdx] = {
                ...tc,
                status: hasError ? 'error' : 'completed',
                result: payload.output ?? payload.result ?? tc.result,
                error: payload.error,
                endedAt: Date.now(),
              };
              this._updateMessage(assistantId, { toolCalls: [...calls] });
            }
            break;
          }

          case 'tool_error': {
            // Optional explicit error event
            const calls = this._getToolCalls(assistantId);
            const targetName = payload.tool_name || payload.name;
            let idx = -1;
            for (let i = calls.length - 1; i >= 0; i--) {
              if (calls[i].status !== 'running') continue;
              if (!targetName || calls[i].name === targetName) { idx = i; break; }
            }
            if (idx >= 0) {
              calls[idx] = {
                ...calls[idx],
                status: 'error',
                error: payload.error || payload.message,
                endedAt: Date.now(),
              };
              this._updateMessage(assistantId, { toolCalls: [...calls] });
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

  /**
   * Get the current toolCalls array for a message id, or [] if none yet.
   * Returns a fresh copy so callers can mutate it safely.
   */
  private _getToolCalls(id: string): ChatToolCall[] {
    const m = this.messages.find(x => x.id === id);
    return m?.toolCalls ? [...m.toolCalls] : [];
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
