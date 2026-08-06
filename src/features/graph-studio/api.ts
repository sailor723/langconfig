/**
 * API client + types for the Graph Engineering Studio.
 *
 * The studio talks to the natively-hosted graph_studio router on the
 * LangConfig backend (same FastAPI process, no separate langgraph server).
 * All endpoints live under `${API_BASE_URL}/api/graph-studio`; in dev the
 * Vite proxy forwards `/api` to the backend, so SSE works out of the box.
 */
import { API_BASE_URL } from '../../config/api';

const BASE = `${API_BASE_URL}/api/graph-studio`;

// ---------------------------------------------------------------------------
// Types (mirror the backend response shapes)
// ---------------------------------------------------------------------------
export interface Assistant {
  assistant_id: string;
  graph_id: string;
  name: string;
  description?: string;
}

/** Node metadata + source info returned by the graph endpoint (canvas popup). */
export interface GraphNodeData {
  name: string;
  kind?: 'start' | 'end' | 'function' | 'tool' | 'subgraph' | 'unknown';
  module?: string | null;
  file?: string | null;
  start_line?: number | null;
  end_line?: number | null;
  code?: string | null;
  metadata?: Record<string, unknown> | null;
  tools?: {
    name?: string | null;
    description?: string | null;
    module?: string | null;
    file?: string | null;
    start_line?: number | null;
    end_line?: number | null;
    code?: string | null;
  }[];
}

export interface GraphSpec {
  nodes: { id: string; data: GraphNodeData }[];
  edges: { source: string; target: string; conditional?: boolean }[];
}

export interface AssistantSchemas {
  graph_id: string;
  input_schema?: { properties?: Record<string, unknown>; required?: string[] };
  state_schema?: unknown;
  output_schema?: unknown;
}

/** Databases the SQL tools can target (list + current selection). */
export interface DatabaseInfo {
  databases: string[];
  active: string;
}

export interface Thread {
  thread_id: string;
  assistant_id: string;
  created_at: string;
  status: 'idle' | 'running' | 'completed' | 'error';
  metadata?: { graph_id?: string };
}

export interface ThreadState {
  values: Record<string, unknown>;
  next: string[];
  tasks: { name?: string; interrupts?: unknown[] }[];
  interrupts: unknown[];
  metadata?: Record<string, unknown>;
  checkpoint_id?: string | null;
  created_at?: string;
}

export interface RunInfo {
  run_id: string;
  thread_id: string;
  assistant_id: string;
  status: 'running' | 'completed' | 'error';
  created_at: string;
  updated_at: string;
  kwargs?: { input?: Record<string, unknown> };
}

export interface LiveMessage {
  id?: string;
  type?: string;
  name?: string;
  content?: string | unknown[];
  tool_calls?: { name: string; args: Record<string, unknown>; id: string }[];
  response_metadata?: Record<string, unknown>;
}

/** A chat graph takes `{messages: [{role, content}]}`; a form graph takes raw fields. */
export function hasMessagesInput(schemas?: AssistantSchemas | null): boolean {
  return Boolean(schemas?.input_schema?.properties?.messages);
}

// ---------------------------------------------------------------------------
// Low-level request helper
// ---------------------------------------------------------------------------
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${res.status}: ${text.slice(0, 200) || res.statusText}`);
  }
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------
export const api = {
  async loadAssistants(metadata: Record<string, unknown> = {}): Promise<Assistant[]> {
    return request('/assistants/search', { method: 'POST', body: JSON.stringify({ metadata }) });
  },

  async loadGraph(assistantId: string): Promise<GraphSpec> {
    return request(`/assistants/${assistantId}/graph`);
  },

  async loadSchemas(assistantId: string): Promise<AssistantSchemas> {
    return request(`/assistants/${assistantId}/schemas`);
  },

  async loadDatabases(): Promise<DatabaseInfo> {
    return request('/databases');
  },

  async selectDatabase(name: string): Promise<DatabaseInfo> {
    return request('/databases/select', {
      method: 'POST',
      body: JSON.stringify({ database: name }),
    });
  },

  async loadThreads(metadata: Record<string, unknown> = {}): Promise<Thread[]> {
    return request('/threads/search', { method: 'POST', body: JSON.stringify({ metadata }) });
  },

  async createThread(assistantId: string, graphId?: string): Promise<Thread> {
    return request('/threads', {
      method: 'POST',
      body: JSON.stringify({ assistant_id: assistantId, metadata: { graph_id: graphId } }),
    });
  },

  async loadThreadState(threadId: string): Promise<ThreadState> {
    return request(`/threads/${threadId}/state`);
  },

  async loadRuns(threadId: string, limit = 20): Promise<RunInfo[]> {
    return request(`/threads/${threadId}/runs?limit=${limit}`);
  },

  /** Open the SSE stream for a run (returns the raw Response for streamSSE). */
  streamRun(
    threadId: string,
    assistantId: string,
    input: Record<string, unknown>,
  ): Promise<Response> {
    return fetch(`${BASE}/threads/${threadId}/runs/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        assistant_id: assistantId,
        input,
        stream_mode: ['messages', 'values', 'updates'],
      }),
    });
  },

  /** Interrupt the in-flight run on a thread (stops at the next event boundary). */
  async cancelRun(threadId: string): Promise<{ thread_id: string; cancelled: boolean }> {
    return request(`/threads/${threadId}/runs/cancel`, { method: 'POST' });
  },
};
