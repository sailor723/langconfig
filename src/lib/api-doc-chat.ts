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
  folder_path: string;
  project_id?: number;
  conversation_id?: string | null;
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
 * List all folder paths under a project that contain supported
 * files. Used by the scope selector in DocChatPanel.
 */
export async function listDocChatFolders(
  projectId: number = 1,
): Promise<string[]> {
  try {
    const response = await apiClient.get('/api/doc-chat/folders', {
      params: { project_id: projectId },
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
};

export default docChatApi;
