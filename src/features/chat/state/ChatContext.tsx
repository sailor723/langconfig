/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { createContext, useContext, useState, useEffect, ReactNode, useCallback } from 'react';
import type { ChatContextValue, ChatSession } from '../types/chat';
import apiClient from '../../../lib/api-client';

const ChatContext = createContext<ChatContextValue | undefined>(undefined);

interface ChatProviderProps {
  children: ReactNode;
}

export function ChatProvider({ children }: ChatProviderProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(() => {
    const stored = sessionStorage.getItem('chat_currentSessionId');
    return stored || null;
  });
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<number | null>(() => {
    const stored = sessionStorage.getItem('chat_selectedAgentId');
    return stored ? parseInt(stored, 10) : null;
  });
  const [hitlEnabled, setHitlEnabled] = useState<boolean>(() => {
    const stored = sessionStorage.getItem('chat_hitlEnabled');
    return stored === 'true';
  });

  // Persist currentSessionId to sessionStorage
  useEffect(() => {
    if (currentSessionId) {
      sessionStorage.setItem('chat_currentSessionId', currentSessionId);
    } else {
      sessionStorage.removeItem('chat_currentSessionId');
    }
  }, [currentSessionId]);

  // Persist selectedAgentId to sessionStorage
  useEffect(() => {
    if (selectedAgentId !== null) {
      sessionStorage.setItem('chat_selectedAgentId', selectedAgentId.toString());
    } else {
      sessionStorage.removeItem('chat_selectedAgentId');
    }
  }, [selectedAgentId]);

  // Persist hitlEnabled to sessionStorage
  useEffect(() => {
    sessionStorage.setItem('chat_hitlEnabled', hitlEnabled.toString());
  }, [hitlEnabled]);

  // Keyboard shortcut listener (Ctrl/Cmd + K)
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key === 'k') {
        event.preventDefault();
        setIsOpen(true);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const refreshSessions = useCallback(async () => {
    try {
      const response = await apiClient.getChatSessions();
      console.log('[ChatContext] Fetched sessions:', response.data);
      const fetchedSessions = response.data || [];
      setSessions(fetchedSessions);

      // If we have a persisted currentSessionId, update selectedAgentId from the session
      const persistedSessionId = sessionStorage.getItem('chat_currentSessionId');
      if (persistedSessionId && fetchedSessions.length > 0) {
        const persistedSession = fetchedSessions.find((s: ChatSession) => s.session_id === persistedSessionId);
        if (persistedSession) {
          setSelectedAgentId(persistedSession.agent_id);
          console.log('[ChatContext] Restored session:', persistedSession.session_id, 'agent:', persistedSession.agent_name);
        }
      }
    } catch (error) {
      console.error('Failed to fetch sessions:', error);
      setSessions([]);
    }
  }, []);

  // Fetch all sessions on mount
  useEffect(() => {
    refreshSessions();
  }, [refreshSessions]);

  const openChat = useCallback((agentId?: number) => {
    if (agentId !== undefined) {
      setSelectedAgentId(agentId);
    }
    setIsOpen(true);

    // Dispatch custom event to notify other components
    window.dispatchEvent(new CustomEvent('chat:opened'));
  }, []);

  const closeChat = useCallback(() => {
    setIsOpen(false);
  }, []);

  const startSession = useCallback(async (agentId: number): Promise<string> => {
    try {
      // Bind the active vault (project) so the agent workspace is vault-scoped
      const projectId = localStorage.getItem('activeProjectId');
      const response = await apiClient.startChatSession(
        agentId,
        projectId ? Number(projectId) : null,
      );
      const sessionId = response.data.session_id;

      // Set the selected agent so agent-scoped panels (Context, Files, Metrics)
      // can resolve the agent instead of showing "No agent selected"
      setSelectedAgentId(agentId);

      // Refresh sessions list to include new session
      await refreshSessions();

      // Set as current session
      setCurrentSessionId(sessionId);

      return sessionId;
    } catch (error) {
      console.error('Failed to start session:', error);
      throw error;
    }
  }, [refreshSessions]);

  const switchSession = useCallback((sessionId: string) => {
    setCurrentSessionId(sessionId);
    // Restore selected agent from session data
    const session = sessions.find(s => s.session_id === sessionId);
    if (session?.agent_id) {
      setSelectedAgentId(session.agent_id);
    }
  }, [sessions]);

  const endSession = useCallback(async (sessionId: string) => {
    try {
      await apiClient.endChatSession(sessionId);
      setSessions(prev => prev.filter(s => s.session_id !== sessionId));
      setCurrentSessionId(prev => prev === sessionId ? null : prev);
    } catch (error) {
      console.error('Failed to end session:', error);
      throw error;
    }
  }, []);

  const toggleHitl = useCallback(() => {
    setHitlEnabled(prev => !prev);
  }, []);

  /**
   * Pin/unpin a conversation. Optimistic: the star flips immediately and the
   * previously pinned conversations keep their order (the list sorts on
   * `favorited_at`, not on activity), so pinned chats don't jump around when
   * they receive new messages.
   */
  const toggleFavorite = useCallback(async (sessionId: string) => {
    const target = sessions.find(s => s.session_id === sessionId);
    if (!target) return;
    const next = !target.is_favorite;

    setSessions(prev => prev.map(s => (s.session_id === sessionId
      ? { ...s, is_favorite: next, favorited_at: next ? new Date().toISOString() : null }
      : s)));

    try {
      const res = await apiClient.setChatFavorite(sessionId, next);
      const confirmed = res?.data?.is_favorite ?? next;
      const confirmedAt = res?.data?.favorited_at ?? (next ? new Date().toISOString() : null);
      setSessions(prev => prev.map(s => (s.session_id === sessionId
        ? { ...s, is_favorite: confirmed, favorited_at: confirmedAt }
        : s)));
    } catch (error) {
      console.error('Failed to update favourite:', error);
      // Revert so the UI never claims a pin the server did not store.
      setSessions(prev => prev.map(s => (s.session_id === sessionId
        ? { ...s, is_favorite: target.is_favorite, favorited_at: target.favorited_at ?? null }
        : s)));
    }
  }, [sessions]);

  /**
   * Rename a conversation. Optimistic like the pin, and blank means "clear":
   * the row then falls back to the first user message, which keeps every
   * conversation readable without forcing a naming step.
   */
  const renameSession = useCallback(async (sessionId: string, title: string) => {
    const target = sessions.find(s => s.session_id === sessionId);
    if (!target) return;
    const cleaned = title.trim();
    const optimistic = cleaned || null;

    setSessions(prev => prev.map(s => (s.session_id === sessionId
      ? { ...s, title: optimistic, title_source: optimistic ? 'manual' : null }
      : s)));

    try {
      const res = await apiClient.setChatTitle(sessionId, cleaned);
      const confirmed = res?.data?.title ?? optimistic;
      setSessions(prev => prev.map(s => (s.session_id === sessionId
        ? { ...s, title: confirmed, title_source: res?.data?.title_source ?? (confirmed ? 'manual' : null) }
        : s)));
    } catch (error) {
      console.error('Failed to rename conversation:', error);
      setSessions(prev => prev.map(s => (s.session_id === sessionId
        ? { ...s, title: target.title ?? null, title_source: target.title_source ?? null }
        : s)));
      throw error;
    }
  }, [sessions]);

  const value: ChatContextValue = {
    isOpen,
    currentSessionId,
    sessions,
    selectedAgentId,
    hitlEnabled,
    openChat,
    closeChat,
    startSession,
    switchSession,
    endSession,
    toggleFavorite,
    renameSession,
    setSelectedAgent: setSelectedAgentId,
    toggleHitl,
    refreshSessions,
  };

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChat() {
  const context = useContext(ChatContext);
  if (context === undefined) {
    throw new Error('useChat must be used within a ChatProvider');
  }
  return context;
}
