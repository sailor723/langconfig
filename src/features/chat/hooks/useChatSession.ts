/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import type { ChatMessage } from '../types/chat';
import apiClient from '../../../lib/api-client';

interface UseChatSessionResult {
  sessionId: string | null;
  messages: ChatMessage[];
  isLoading: boolean;
  error: string | null;
  loadHistory: (sessionId: string) => Promise<void>;
  addMessage: (message: ChatMessage) => void;
  updateLastMessage: (content: string) => void;
  clearHistory: () => void;
  setError: (error: string | null) => void;
}

export function useChatSession(currentSessionId: string | null): UseChatSessionResult {
  const [sessionId, setSessionId] = useState<string | null>(currentSessionId);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Tracks the session the user last asked for, so a stale in-flight
  // history response can't overwrite a newer one (session-switch race)
  const requestedSessionRef = useRef<string | null>(null);

  // Update sessionId when currentSessionId changes
  useEffect(() => {
    setSessionId(currentSessionId);
  }, [currentSessionId]);

  // Load history when sessionId changes
  useEffect(() => {
    requestedSessionRef.current = sessionId;
    if (sessionId) {
      loadHistory(sessionId);
    } else {
      setMessages([]);
    }
  }, [sessionId]);

  const loadHistory = useCallback(async (sid: string) => {
    requestedSessionRef.current = sid;
    setIsLoading(true);
    setError(null);

    try {
      const response = await apiClient.getChatHistory(sid);
      // Ignore the response if the user already switched sessions
      if (requestedSessionRef.current !== sid) return;

      const data = response.data;
      if (data.messages && Array.isArray(data.messages)) {
        setMessages(data.messages);
      } else {
        setMessages([]);
      }
    } catch (err: any) {
      if (requestedSessionRef.current !== sid) return;
      console.error('Failed to load chat history:', err);
      setError('Failed to load chat history');
      setMessages([]);
    } finally {
      if (requestedSessionRef.current === sid) {
        setIsLoading(false);
      }
    }
  }, []);

  const addMessage = useCallback((message: ChatMessage) => {
    setMessages(prev => [...prev, message]);
  }, []);

  const updateLastMessage = useCallback((content: string) => {
    setMessages(prev => {
      if (prev.length === 0) return prev;

      // Replace the last message immutably — mutating it in place would
      // violate React state immutability and skip re-renders
      const newMessages = [...prev];
      newMessages[newMessages.length - 1] = {
        ...newMessages[newMessages.length - 1],
        content,
      };
      return newMessages;
    });
  }, []);

  const clearHistory = useCallback(() => {
    setMessages([]);
    setError(null);
  }, []);

  return {
    sessionId,
    messages,
    isLoading,
    error,
    loadHistory,
    addMessage,
    updateLastMessage,
    clearHistory,
    setError,
  };
}
