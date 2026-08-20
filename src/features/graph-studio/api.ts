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

/** Databases the tools can target, split by type (SQL / Neo4j) plus the
 *  active target for each. Backwards-compat fields (databases / active) are
 *  preserved so old code keeps reading the SQL list without surprises. */
export interface DatabaseInfo {
  /** Postgres databases available to SQL agents. */
  sql: string[];
  /** Neo4j databases available to Neo4j agents. */
  neo4j: string[];
  /** Currently-active Postgres DB (for SQL agents). */
  active_sql: string;
  /** Currently-active Neo4j DB (for Neo4j agents). */
  active_neo4j: string;
  /** Backwards-compat: flat list (= sql[]) and current SQL selection. */
  databases: string[];
  active: string;
}

/** One table of the active database, with its exact row count (null = unknown). */
export interface TableSummary {
  name: string;
  rows: number | null;
}

/** Summary of the active target database, rendered in the canvas header.
 *  Shared shape for SQL (tables/rows) and Neo4j (labels/edges); the renderer
 *  picks the fields that exist on whichever type was returned. */
export interface DatabaseSummary {
  database: string;
  /** SQL: number of tables. Neo4j: number of node labels. */
  table_count?: number;
  /** SQL: total row count. Neo4j: total node count. */
  row_count?: number;
  /** SQL: per-table stats. */
  tables?: TableSummary[];
  /** Neo4j: per-label stats. */
  labels?: Array<{ name: string; nodes: number }>;
  /** Neo4j: per-rel-type stats. */
  rels?: Array<{ name: string; edges: number }>;
  /** Neo4j: total edge count (mirrors SQL row_count for symmetry). */
  edge_count?: number;
  /** Neo4j: total node count. */
  node_count?: number;
  /** LLM-written business description (<=3 lines) in the requested language; null on failure. */
  summary: string | null;
  /** Backend tag: 'sql' or 'neo4j'. Used by the renderer to pick the right field set. */
  type?: 'sql' | 'neo4j';
  /** SQL: which Postgres schema was introspected (defaults to first non-empty). */
  schema?: string;
  /** SQL: full ER diagram (columns + FKs). Null if introspection failed or DB unreachable. */
  er_diagram?: ErDiagram | null;
  /** Neo4j: label supernodes + rel-type edges. Null if introspection failed or DB unreachable. */
  network_diagram?: Neo4jNetworkDiagram | null;
}

// ---------------------------------------------------------------------------
// Schema-diagram payloads (returned by the same /databases/summary and
// /databases/neo4j-summary endpoints — null on introspection failure).
// Generic shapes: no hardcoded table or label names; whatever the active
// Postgres / Neo4j database exposes.
// ---------------------------------------------------------------------------

/** One column of a Postgres table, with PK / nullable flags. */
export interface TableColumn {
  name: string;
  type: string;
  nullable: boolean;
  pk: boolean;
}

/** One base table of the active Postgres schema. */
export interface TableNode {
  name: string;
  /** Live row count; null when COUNT(*) failed for this table (e.g. permissions). */
  row_count: number | null;
  columns: TableColumn[];
}

/** One foreign key between two tables in the active schema. */
export interface ForeignKey {
  from_table: string;
  from_column: string;
  to_table: string;
  to_column: string;
  constraint_name: string;
  on_update: string;
  on_delete: string;
}

/** ER-diagram payload: tables + the FK edges between them. */
export interface ErDiagram {
  schema: string;
  tables: TableNode[];
  foreign_keys: ForeignKey[];
}

/** One node label of the active Neo4j graph. */
export interface LabelNode {
  name: string;
  /** Number of nodes with this label. */
  count: number;
  /** Property keys observed on nodes with this label. */
  properties: string[];
}

/** One (label_a)-[:REL_TYPE]->(label_b) edge group. */
export interface RelEdge {
  type: string;
  from_label: string;
  to_label: string;
  count: number;
}

/** Network-diagram payload: label supernodes + rel-type edges between labels. */
export interface Neo4jNetworkDiagram {
  label_nodes: LabelNode[];
  rel_edges: RelEdge[];
}

// ---------------------------------------------------------------------------
// Full Neo4j graph (node-per-instance) — mirrors `db.schema.visualization()`
// ---------------------------------------------------------------------------
// Re-exported here so the typed API client can use them; the canvas
// currently uses the supernode view above and the full-graph endpoint
// stays available for future use.
export interface FullGraphNode {
  id: string;
  labels: string[];
  primary_label: string | null;
  display_name: string;
  degree: number;
  properties: Record<string, string>;
}

export interface FullGraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
}

export interface Neo4jFullGraph {
  database: string;
  node_cap: number;
  edge_cap: number;
  nodes: FullGraphNode[];
  edges: FullGraphEdge[];
  truncated: boolean;
  total_nodes_in_db?: number;
  error?: string;
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
  /** Chain-of-thought from reasoning models (ChatDeepSeek / ChatOllama). */
  reasoning_content?: string;
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

  /** Full Python source of the assistant's graph module (plain text). */
  async loadAssistantCode(assistantId: string): Promise<string> {
    const res = await fetch(`${BASE}/assistants/${assistantId}/code`);
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`${res.status}: ${text.slice(0, 200) || res.statusText}`);
    }
    return res.text();
  },

  async loadSchemas(assistantId: string): Promise<AssistantSchemas> {
    return request(`/assistants/${assistantId}/schemas`);
  },

  async loadDatabases(): Promise<DatabaseInfo> {
    return request('/databases');
  },

  async selectDatabase(name: string, type: 'sql' | 'neo4j' = 'sql'): Promise<DatabaseInfo> {
    return request('/databases/select', {
      method: 'POST',
      body: JSON.stringify({ database: name, type }),
    });
  },

  async loadDatabaseSummary(lang?: 'en' | 'zh'): Promise<DatabaseSummary> {
    const qs = lang ? `?lang=${lang}` : '';
    return request(`/databases/summary${qs}`);
  },

  async loadNeo4jSummary(lang?: 'en' | 'zh'): Promise<DatabaseSummary> {
    const qs = lang ? `?lang=${lang}` : '';
    return request(`/databases/neo4j-summary${qs}`);
  },

  /**
   * Full Neo4j graph (node-per-instance, edge-per-relationship),
   * like `CALL db.schema.visualization()`. Capped to keep the canvas
   * usable on large graphs. Used by the "Network" view mode of the
   * Neo4j schema tab.
   */
  async loadNeo4jFullGraph(
    nodeCap = 200,
    edgeCap = 600,
  ): Promise<Neo4jFullGraph> {
    return request(
      `/databases/neo4j-full-graph?node_cap=${nodeCap}&edge_cap=${edgeCap}`
    );
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
