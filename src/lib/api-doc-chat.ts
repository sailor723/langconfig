/**
 * Doc Chat API client.
 *
 * Thin wrapper over the backend endpoints under `/api/doc-chat/*`.
 * The backend scans files in `folder_path`, builds a context window,
 * and streams the LLM response.
 *
 * Endpoints:
 *   GET   /api/doc-chat/folders                  — list available folder scopes
 *   POST  /api/doc-chat                          — stream a chat reply
 *   GET   /api/doc-chat/conversations            — list saved conversations
 *   GET   /api/doc-chat/history/{id}             — replay messages
 *   DELETE /api/doc-chat/history/{id}            — delete a conversation
 */
import apiClient from './api-client';

// ───────────────────────────────────────────────────────────
// Types
// ───────────────────────────────────────────────────────────

export interface DocChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  /** Client-side timestamp. */
  timestamp: Date;
  /** True while a streamed response is still being appended. */
  streaming?: boolean;
  /** Parsed from the backend's lead-in
   *  `**[Documents loaded: N files, M chars]**`. */
  contextChip?: { fileCount: number; charCount: number };
}

export interface DocChatRequest {
  messages: Array<{ role: 'user' | 'assistant'; content: string }>;
  /** Folder inside the knowledge base, e.g. "business_model/tesla". "" is the root. */
  folder_path: string;
  /** Knowledge base folder name — the same handle the upload endpoints take. */
  knowledge: string;
  conversation_id?: string | null;
  /** LLM settings (same resolution path as the rest of the app). */
  model?: string;
  temperature?: number;
  max_tokens?: number;
}

/**
 * LLM settings honored by the doc-chat backend (same resolution path as
 * the rest of the app). `model` empty/undefined = the app's default model.
 */
export interface DocChatLlmOptions {
  model?: string;
  temperature?: number;
  max_tokens?: number;
}

export interface DocChatConversation {
  conversation_id: string;
  message_count: number;
  last_updated: number | null;
}

// ───────────────────────────────────────────────────────────
// Endpoints
// ───────────────────────────────────────────────────────────

/**
 * List every folder inside a knowledge base that holds supported files.
 * Used by the scope selector in DocChatPanel.
 */
export async function listDocChatFolders(
  knowledge: string,
): Promise<string[]> {
  if (!knowledge) return [];
  try {
    const response = await apiClient.get('/api/doc-chat/folders', {
      params: { knowledge },
    });
    return response.data.folders || [];
  } catch {
    return [];
  }
}

/**
 * Stream a chat reply. Returns the raw fetch Response so the
 * caller can read the X-Conversation-ID header and consume the
 * body as a ReadableStream.
 */
export async function postChat(
  request: DocChatRequest,
): Promise<{ response: Response; conversationId: string }> {
  const response = await fetch('/api/doc-chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw new Error(`Doc chat request failed: HTTP ${response.status}`);
  }
  const headerId = response.headers.get('X-Conversation-ID');
  const conversationId = headerId || request.conversation_id || '';
  return { response, conversationId };
}

/**
 * Fetch the backend doc-chat module source. Powers the "View code"
 * action in the Doc Chat panel.
 */
export async function getDocChatCode(): Promise<{ file: string; code: string }> {
  const response = await apiClient.get('/api/doc-chat/code');
  return {
    file: response.data.file || 'doc_chat.py',
    code: response.data.code || '',
  };
}

export async function listConversations(): Promise<DocChatConversation[]> {
  const response = await apiClient.get('/api/doc-chat/conversations');
  return response.data.conversations || [];
}

export async function getHistory(
  conversationId: string,
): Promise<DocChatMessage[]> {
  const response = await apiClient.get(
    `/api/doc-chat/history/${encodeURIComponent(conversationId)}`,
  );
  const raw = response.data.messages || [];
  return raw.map(
    (m: { role: 'user' | 'assistant'; content: string; timestamp?: number }, i: number) => ({
      id: `${conversationId}-${i}`,
      role: m.role,
      content: m.content,
      timestamp: new Date(((m.timestamp ?? 0) * 1000) || Date.now()),
    }),
  );
}

export async function deleteConversation(conversationId: string): Promise<void> {
  await apiClient.delete(
    `/api/doc-chat/history/${encodeURIComponent(conversationId)}`,
  );
}

export const docChatApi = {
  postChat,
  listConversations,
  getHistory,
  deleteConversation,
  listDocChatFolders,
  getDocChatCode,
};

export default docChatApi;
