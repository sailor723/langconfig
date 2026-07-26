/**
 * chatStore — shared state for the right-sidebar chat panel.
 *
 * DeepAgentEditor's Run button writes user/assistant messages here.
 * NodeSidebar's ChatSidebar reads from here and renders them.
 *
 * Simple module-level singleton (no React Context needed — re-render
 * is driven by a manual subscription list, since the consumers are
 * deep inside the tree and adding a Provider is overkill).
 */
import { useEffect, useState } from 'react';

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
  ts: number;
}

class ChatStoreImpl {
  private messages: ChatMessage[] = [];
  /** Currently active chat session id (created by DeepAgent Run button) */
  private sessionId: string | null = null;
  /** Currently active deep agent id (for follow-up messages) */
  private agentId: number | null = null;
  private listeners = new Set<() => void>();

  getMessages(): ChatMessage[] {
    return this.messages;
  }

  getSessionId(): string | null {
    return this.sessionId;
  }

  getAgentId(): number | null {
    return this.agentId;
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

  clear(): void {
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