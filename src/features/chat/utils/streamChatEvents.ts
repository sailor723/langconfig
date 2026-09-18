/**
 * streamChatEvents — shared SSE transport for the chat streaming endpoint.
 *
 * Both `useChatStreaming` (full ChatPage / GlobalChatModal) and `chatStore`
 * (right-sidebar chat) stream from POST /api/chat/message/stream. They used
 * to each implement the fetch → reader → `data:` line-splitting → JSON parse
 * loop; this helper is that transport, yielding one parsed event at a time.
 *
 * Event *handling* stays with each consumer (they differ: hooks dispatch to
 * callbacks, the store updates message objects) — only the I/O is shared.
 */
import apiClient from '../../../lib/api-client';

/** Parsed SSE event — loosely typed so consumers can read optional fields
 * (e.g. tool_call_id, args, output, error) that chatStore relies on. */
export type SseChatEvent = Record<string, any>;

/**
 * POST `path` with `body` and yield each parsed `data:` event.
 * Throws on HTTP errors or aborts (AbortError) — callers catch as usual.
 */
export async function* streamChatEvents(
  path: string,
  body: Record<string, unknown>,
  signal?: AbortSignal | null,
): AsyncGenerator<SseChatEvent, void, unknown> {
  const response = await fetch(`${apiClient.baseURL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    throw new Error(`Stream request failed: ${response.status} ${response.statusText}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('No reader available for response stream');
  }

  const decoder = new TextDecoder();
  let buffer = ''; // carry a partial final line across chunks

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || !trimmed.startsWith('data: ')) continue;
      try {
        yield JSON.parse(trimmed.slice(6));
      } catch {
        // Skip malformed SSE lines (stray newline, partial JSON, etc.)
      }
    }
  }
}
