/**
 * Typed client for the Local Studio backend.
 *
 * The Express server proxies `/api/langgraph/*` to the local
 * `langgraph dev` server (127.0.0.1:2024), so the browser only ever
 * talks to same-origin endpoints.
 */

export interface Assistant {
  assistant_id: string
  graph_id: string
  name: string
  description: string | null
  created_at?: string
}

export interface GraphNodeSpec {
  id: string
  type?: string
  data?: { name?: string; [k: string]: unknown }
}

export interface GraphEdgeSpec {
  source: string
  target: string
  conditional?: boolean
}

export interface GraphSpec {
  nodes: GraphNodeSpec[]
  edges: GraphEdgeSpec[]
}

export interface Thread {
  thread_id: string
  /** Present on create response; not always on list response. */
  assistant_id?: string
  created_at: string
  status: string
  metadata?: {
    graph_id?: string
    assistant_id?: string
    [k: string]: unknown
  }
}

export interface ThreadState {
  values: Record<string, unknown>
  next: string[]
  tasks: unknown[]
  interrupts: unknown[]
  metadata: Record<string, unknown>
  checkpoint_id: string
  checkpoint?: unknown
  created_at?: string
}

export interface RunInfo {
  run_id: string
  thread_id: string
  assistant_id: string
  status: string
  created_at: string
  updated_at: string
  kwargs?: { input?: unknown }
}

export interface AssistantSchemas {
  graph_id: string
  input_schema: Record<string, unknown>
  state_schema?: Record<string, unknown>
  output_schema?: Record<string, unknown>
}

/** True when the graph's input schema has a `messages` field (chat-style graph). */
export function hasMessagesInput(schemas: AssistantSchemas | null): boolean {
  const props = schemas?.input_schema?.properties as Record<string, unknown> | undefined
  return Boolean(props && 'messages' in props)
}

const BASE = '/api/langgraph'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = (await res.json()) as { detail?: unknown; error?: unknown }
      const message = body?.detail ?? body?.error
      if (typeof message === 'string') detail = message
      else if (message) detail = JSON.stringify(message)
    } catch {
      // non-JSON error body; keep the status text
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

export const api = {
  listAssistants: () =>
    request<Assistant[]>('/assistants/search', {
      method: 'POST',
      body: JSON.stringify({ metadata: {} }),
    }),

  getGraph: (assistantId: string) =>
    request<GraphSpec>(`/assistants/${assistantId}/graph`),

  getSchemas: (assistantId: string) =>
    request<AssistantSchemas>(`/assistants/${assistantId}/schemas`),

  listThreads: () =>
    request<Thread[]>('/threads/search', {
      method: 'POST',
      body: JSON.stringify({ metadata: {} }),
    }),

  createThread: (assistant: { assistant_id: string; graph_id: string }) =>
    request<Thread>('/threads', {
      method: 'POST',
      body: JSON.stringify({
        assistant_id: assistant.assistant_id,
        // The dev server persists graph_id in thread metadata, which is
        // used to attribute threads to assistants in the UI.
        metadata: { graph_id: assistant.graph_id },
      }),
    }),

  getThreadState: (threadId: string) =>
    request<ThreadState>(`/threads/${threadId}/state`),

  listRuns: (threadId: string) =>
    request<RunInfo[]>(`/threads/${threadId}/runs?limit=20`),

  run: (threadId: string, assistantId: string, input: unknown) =>
    request<Record<string, unknown>>(`/threads/${threadId}/runs/wait`, {
      method: 'POST',
      body: JSON.stringify({ assistant_id: assistantId, input }),
    }),

  /**
   * Start a run and stream live events (SSE).
   * Returns the raw Response so the caller can parse events incrementally.
   */
  streamRun: (
    threadId: string,
    assistantId: string,
    input: unknown,
    streamMode: string[],
  ) =>
    fetch(`${BASE}/threads/${threadId}/runs/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        assistant_id: assistantId,
        input,
        stream_mode: streamMode,
      }),
    }),
}
