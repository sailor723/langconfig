/**
 * useDocChat — owns the chat session for one Doc Chat panel.
 *
 * Responsibilities:
 *   - Maintain the in-memory message thread (user + assistant turns).
 *   - Drive the SSE stream from POST /api/doc-chat, appending deltas.
 *   - Persist the `conversation_id` for server-side memory.
 *   - Load, list, and delete past conversations.
 *
 * Adapted from agent-workspace's useDocChat.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  postChat,
  listConversations,
  getHistory,
  deleteConversation as deleteConversationApi,
  DocChatMessage,
  DocChatConversation,
  DocChatLlmOptions,
} from '../../lib/api-doc-chat';

// ── Backend contract ─────────────────────────────────
// The assistant begins its reply with:
//   `**[Documents loaded: N files, M chars]**`
// followed by the answer with inline citations `[Source: filename.md]`.
// ─────────────────────────────────────────────────────

/** Match the lead-in chip at the start of every response. */
const LEAD_IN_RE =
  /^\*{0,2}\[?\s*Documents loaded:\s*(\d+)\s*files?,\s*([\d,]+)\s*chars?\s*\]?\s*\*{0,2}\s*\n?/i;

export function parseContextChip(text: string): {
  chip: { fileCount: number; charCount: number };
  rest: string;
} | null {
  const m = LEAD_IN_RE.exec(text);
  if (!m) return null;
  const fileCount = Number(m[1]);
  const charCount = Number(m[2].replace(/,/g, ''));
  return {
    chip: { fileCount, charCount },
    rest: text.slice(m[0].length),
  };
}

// ── Types ─────────────────────────────────────────────

export type DocChatStatus =
  | { kind: 'idle' }
  | { kind: 'reading'; folderPath: string }
  | { kind: 'streaming'; folderPath: string };

export interface UseDocChatResult {
  messages: DocChatMessage[];
  conversationId: string | null;
  isStreaming: boolean;
  status: DocChatStatus;
  error: string | null;
  conversations: DocChatConversation[];
  send: (text: string, folderPath: string, knowledge: string, llm?: DocChatLlmOptions) => Promise<void>;
  cancel: () => void;
  regenerate: (folderPath: string, knowledge: string, llm?: DocChatLlmOptions) => Promise<void>;
  editAndResend: (messageId: string, newText: string, folderPath: string, knowledge: string, llm?: DocChatLlmOptions) => Promise<void>;
  clearMessages: () => void;
  loadConversation: (conversationId: string, folderPath: string) => Promise<void>;
  deleteConversation: (conversationId: string) => Promise<void>;
  refreshConversations: () => Promise<void>;
}

// ── Hook ──────────────────────────────────────────────

export function useDocChat(): UseDocChatResult {
  const { t: tr } = useTranslation('chat');
  const [messages, setMessages] = useState<DocChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [status, setStatus] = useState<DocChatStatus>({ kind: 'idle' });
  const [error, setError] = useState<string | null>(null);
  const [conversations, setConversations] = useState<DocChatConversation[]>([]);

  const readerRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);
  const cancelledRef = useRef(false);

  // Load history list on mount
  useEffect(() => {
    listConversations().then(setConversations).catch(() => {});
  }, []);

  const refreshConversations = useCallback(async () => {
    try {
      const list = await listConversations();
      setConversations(list);
    } catch {
      // Keep old list on error
    }
  }, []);

  // Shared streaming loop — drains the SSE reader, parses lead-in chip
  const streamResponse = useCallback(
    async (
      assistantId: string,
      folderPath: string,
      historyForRequest: DocChatMessage[],
      knowledge: string,
      llm?: DocChatLlmOptions,
    ): Promise<void> => {
      try {
        const { response } = await postChat({
          messages: historyForRequest.map((m) => ({
            role: m.role,
            content: m.content,
          })),
          folder_path: folderPath,
          knowledge,
          conversation_id: conversationId,
          ...llm,
        });

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error(tr('dc_err_no_stream'));
        }
        readerRef.current = reader;
        setStatus({ kind: 'streaming', folderPath });

        const decoder = new TextDecoder();
        let buffer = '';
        let assistantContent = '';
        while (true) {
          if (cancelledRef.current) break;
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          // Split on double newline (SSE event boundary)
          const parts = buffer.split('\n\n');
          // Keep the last (possibly incomplete) part in the buffer
          buffer = parts.pop() || '';

          for (const part of parts) {
            if (!part.trim()) continue;

            // Strip "data: " prefix
            const line = part.startsWith('data: ') ? part.slice(6) : part;

            // Parse JSON SSE event
            let parsed: any;
            try {
              parsed = JSON.parse(line);
            } catch {
              continue; // skip malformed lines
            }

            if (parsed.type === 'token' && parsed.content) {
              assistantContent += parsed.content;
            } else if (parsed.type === 'done') {
              // Stream finished
              break;
            } else if (parsed.type === 'error') {
              setError(parsed.message || tr('dc_err_chat_error'));
              break;
            } else if (parsed.type === 'start') {
              // Start event — extract conversation_id from metadata
              if (parsed.conversation_id && parsed.conversation_id !== conversationId) {
                setConversationId(parsed.conversation_id);
              }
            }
          }

          // Parse the context chip (lead-in) from the accumulated content
          let displayContent = assistantContent;
          let chip: DocChatMessage['contextChip'] | undefined;
          const parsedChip = parseContextChip(assistantContent);
          if (parsedChip) {
            displayContent = parsedChip.rest;
            chip = parsedChip.chip;
          }

          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, content: displayContent, contextChip: chip ?? m.contextChip }
                : m,
            ),
          );
        }
        // Mark message as no longer streaming
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? { ...m, streaming: false } : m,
          ),
        );
        refreshConversations();
      } catch (err) {
        const message = (err as Error).message || tr('dc_err_chat_failed');
        setError(message);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? {
                  ...m,
                  content: tr('dc_err_connection'),
                  streaming: false,
                }
              : m,
          ),
        );
      } finally {
        setIsStreaming(false);
        setStatus({ kind: 'idle' });
        readerRef.current = null;
      }
    },
    [conversationId, refreshConversations],
  );

  const send = useCallback(
    async (text: string, folderPath: string, knowledge: string, llm?: DocChatLlmOptions) => {
      const trimmed = text.trim();
      if (!trimmed || !knowledge) return;
      if (isStreaming) return;

      cancelledRef.current = false;
      setError(null);

      const userMsg: DocChatMessage = {
        id: `user-${Date.now()}`,
        role: 'user',
        content: trimmed,
        timestamp: new Date(),
      };
      const assistantId = `assistant-${Date.now() + 1}`;
      const assistantMsg: DocChatMessage = {
        id: assistantId,
        role: 'assistant',
        content: '',
        timestamp: new Date(),
        streaming: true,
      };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setIsStreaming(true);
      setStatus({ kind: 'reading', folderPath });

      await streamResponse(assistantId, folderPath, [
        ...messages,
        userMsg,
      ], knowledge, llm);
    },
    [messages, isStreaming, streamResponse],
  );

  const cancel = useCallback(() => {
    if (!readerRef.current) return;
    cancelledRef.current = true;
    readerRef.current.cancel().catch(() => {});
    setMessages((prev) =>
      prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)),
    );
    setIsStreaming(false);
    readerRef.current = null;
  }, []);

  const regenerate = useCallback(
    async (folderPath: string, knowledge: string, llm?: DocChatLlmOptions) => {
      if (isStreaming) return;
      const lastUserIdx = messages
        .map((m, i) => (m.role === 'user' ? i : -1))
        .reduce((max, i) => Math.max(max, i), -1);
      if (lastUserIdx < 0) return;
      const trimmed = messages.slice(0, lastUserIdx + 1);

      cancelledRef.current = false;
      setError(null);

      const assistantId = `assistant-${Date.now()}`;
      const assistantMsg: DocChatMessage = {
        id: assistantId,
        role: 'assistant',
        content: '',
        timestamp: new Date(),
        streaming: true,
      };

      setMessages([...trimmed, assistantMsg]);
      setIsStreaming(true);
      setStatus({ kind: 'reading', folderPath });

      await streamResponse(assistantId, folderPath, trimmed, knowledge, llm);
    },
    [messages, isStreaming, streamResponse],
  );

  const editAndResend = useCallback(
    async (messageId: string, newText: string, folderPath: string, knowledge: string, llm?: DocChatLlmOptions) => {
      const trimmed = newText.trim();
      if (!trimmed || !knowledge) return;
      if (isStreaming) return;
      const idx = messages.findIndex((m) => m.id === messageId);
      if (idx < 0) return;
      const prev = messages.slice(0, idx);
      const editedUserMsg: DocChatMessage = {
        id: `user-${Date.now()}`,
        role: 'user',
        content: trimmed,
        timestamp: new Date(),
      };
      const assistantId = `assistant-${Date.now() + 1}`;
      const assistantMsg: DocChatMessage = {
        id: assistantId,
        role: 'assistant',
        content: '',
        timestamp: new Date(),
        streaming: true,
      };

      cancelledRef.current = false;
      setError(null);

      setMessages([...prev, editedUserMsg, assistantMsg]);
      setIsStreaming(true);
      setStatus({ kind: 'reading', folderPath });

      await streamResponse(assistantId, folderPath, [
        ...prev,
        editedUserMsg,
      ], knowledge, llm);
    },
    [messages, isStreaming, streamResponse],
  );

  const clearMessages = useCallback(() => {
    setMessages([]);
    setConversationId(null);
    setError(null);
  }, []);

  const loadConversation = useCallback(
    async (id: string, _folderPath: string) => {
      try {
        const history = await getHistory(id);
        setMessages(history);
        setConversationId(id);
        setError(null);
      } catch (err) {
        setError((err as Error).message || tr('dc_err_load_conversation'));
      }
    },
    [],
  );

  const deleteConversation = useCallback(
    async (id: string) => {
      try {
        await deleteConversationApi(id);
        if (conversationId === id) {
          clearMessages();
        }
        await refreshConversations();
      } catch (err) {
        setError((err as Error).message || tr('dc_err_delete_conversation'));
      }
    },
    [conversationId, clearMessages, refreshConversations],
  );

  return {
    messages,
    conversationId,
    isStreaming,
    status,
    error,
    conversations,
    send,
    cancel,
    regenerate,
    editAndResend,
    clearMessages,
    loadConversation,
    deleteConversation,
    refreshConversations,
  };
}
