/**
 * Minimal SSE (Server-Sent Events) parser.
 *
 * LangGraph's `runs/stream` endpoint emits event/data line pairs, e.g.:
 *
 *   event: messages/partial
 *   data: [{"content": "Hel", "type": "ai", "id": "run-1", ...}]
 *
 * Each parsed event is delivered to `onEvent` as soon as it arrives.
 */

export interface StreamEvent {
  event: string
  data: unknown
}

function parseLine(line: string, currentEvent: string | null): StreamEvent | null {
  if (line.startsWith('data: ')) {
    const payload = line.slice(6).trim()
    if (!payload || payload === '[DONE]') return null
    try {
      return { event: currentEvent ?? '', data: JSON.parse(payload) }
    } catch {
      // Malformed JSON payloads are skipped — the stream stays intact.
      return null
    }
  }
  return null
}

export async function streamSSE(
  res: Response,
  onEvent: (ev: StreamEvent) => void,
): Promise<void> {
  if (!res.body) return

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let currentEvent: string | null = null

  const flush = (line: string) => {
    if (line.startsWith('event: ')) {
      currentEvent = line.slice(7).trim()
      return
    }
    const parsed = parseLine(line, currentEvent)
    if (parsed) {
      onEvent(parsed)
      currentEvent = null
    }
  }

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) flush(line)
  }

  // Drain any final line that arrived without a trailing newline
  if (buffer.trim()) flush(buffer)
}
