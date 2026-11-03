/**
 * Graph Studio store — a tiny dependency-free global store.
 *
 * Uses React's `useSyncExternalStore` (no zustand dependency) to keep the
 * sidebar, canvas, run console, and inspector in sync. State flows:
 *
 *   loadAssistants → selectAssistant (loads graph + schemas + threads)
 *   run()          → SSE stream (messages/partial, values, updates)
 *   refreshState() → thread state from the graph's checkpointer
 */
import { useSyncExternalStore } from 'react';
import { api, semanticsApi } from './api';
import { streamSSE } from './stream';
import i18n from '../../i18n';
import type {
  Assistant,
  AssistantSchemas,
  DatabaseSummary,
  GraphSpec,
  LiveMessage,
  RunInfo,
  Thread,
  ThreadState,
} from './api';

export type Direction = 'lr' | 'tb';

/** Currently active visualization: flow chart of the assistant's runtime,
 *  or schema network of the underlying database. Defaults to 'flow'. */
// Three representations of the same run:
//   flow     — the graph's nodes/edges (what the code does)
//   schema   — the database it queries (what the code sees)
//   semantic — the rules injected into the SQL prompts (what the code means)
// The third one is edited in place; `load_semantics` re-reads the file every run.
export type ViewMode = 'flow' | 'schema' | 'semantic';

export interface SemanticsState {
  database: string;
  path: string;
  exists: boolean;
  bytes: number;
  /** Sections the loader will actually inject ('schema' | 'semantic' | 'examples'). */
  blocks: string[];
  checker: string;
  text: string;
  loading: boolean;
  saving: boolean;
  dirty: boolean;
  message: string | null;
  /** Verdict from the database's own gate, when it has one. */
  check: { status: string; lines: string[]; checker?: string | null } | null;
}

export interface StudioState {
  apiOnline: boolean;
  assistants: Assistant[];
  activeAssistantId: string;
  graph: GraphSpec | null;
  schemas: AssistantSchemas | null;
  direction: Direction;
  /** Which visualization the canvas renders. */
  viewMode: ViewMode;
  semantics: SemanticsState | null;
  /** DBs split by type so the dropdown swaps source based on the active assistant. */
  sqlDatabases: string[];
  neo4jDatabases: string[];
  /** Currently-selected DB per type. Used by the type-aware dropdown. */
  activeSqlDatabase: string;
  activeNeo4jDatabase: string;
  /** Live summary of the active database (canvas header). */
  dbSummary: DatabaseSummary | null;
  threads: Thread[];
  currentThreadId: string;
  threadState: ThreadState | null;
  runHistory: RunInfo[];
  running: boolean;
  runError: string | null;
  liveMap: Record<string, LiveMessage>;
  runPath: string[];
  inspectorTab: 'messages' | 'state' | 'raw';
  /** Canvas node currently selected for the detail popup (id or null). */
  activeNodeId: string | null;
}

const initialState: StudioState = {
  apiOnline: false,
  assistants: [],
  activeAssistantId: '',
  graph: null,
  schemas: null,
  direction: 'lr',
  viewMode: 'flow',
  semantics: null,
  sqlDatabases: [],
  neo4jDatabases: [],
  activeSqlDatabase: '',
  activeNeo4jDatabase: '',
  dbSummary: null,
  threads: [],
  currentThreadId: '',
  threadState: null,
  runHistory: [],
  running: false,
  runError: null,
  liveMap: {},
  runPath: [],
  inspectorTab: 'messages',
  activeNodeId: null,
};

let state: StudioState = initialState;
const listeners = new Set<() => void>();

function setState(patch: Partial<StudioState>) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): StudioState {
  return state;
}

/** React hook: re-renders the caller whenever any slice of studio state changes. */
export function useStudioState(): StudioState {
  return useSyncExternalStore(subscribe, getSnapshot);
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------
export const studio = {
  /** Load the code-defined assistants without selecting one (graph home page). */
  async loadAssistantsOnly() {
    try {
      const assistants = await api.loadAssistants();
      setState({ assistants, apiOnline: true });
    } catch (err) {
      setState({ apiOnline: false });
      console.error('[graph-studio] loadAssistants failed', err);
    }
    // Load the DB selector (best-effort; the SQL tools may be unavailable).
    await studio.loadDatabases();
  },

  /** Load the code-defined assistants; select the first one by default. */
  async loadAssistants() {
    await studio.loadAssistantsOnly();
    const assistants = state.assistants;
    const active = assistants.find((a) => a.assistant_id === state.activeAssistantId);
    await studio.selectAssistant(active ?? assistants[0] ?? null);
  },

  /** Load the databases the tools can target (split by SQL / Neo4j). */
  async loadDatabases() {
    try {
      const info = await api.loadDatabases();
      // Backwards-compat: the old API returned a flat {databases, active}.
      // The new API returns {sql, neo4j, active_sql, active_neo4j}.
      setState({
        sqlDatabases: info.sql ?? info.databases ?? [],
        neo4jDatabases: info.neo4j ?? [],
        activeSqlDatabase: info.active_sql ?? info.active ?? '',
        activeNeo4jDatabase: info.active_neo4j ?? '',
      });
    } catch (err) {
      console.error('[graph-studio] loadDatabases failed', err);
    }
    await studio.loadDatabaseSummary();
  },

  /** Refresh the canvas-header summary of the active database.
   *  The business-summary text follows the current UI language (en | zh).
   *  Picks the right endpoint based on the active assistant's db type. */
  async loadDatabaseSummary() {
    const lang = i18n.language?.toLowerCase().startsWith('zh') ? 'zh' : 'en';
    const dbType: 'sql' | 'neo4j' = state.activeAssistantId.startsWith('neo4j_')
      ? 'neo4j'
      : 'sql';
    try {
      const dbSummary = dbType === 'neo4j'
        ? await api.loadNeo4jSummary(lang)
        : await api.loadDatabaseSummary(lang);
      setState({ dbSummary });
    } catch (err) {
      console.error('[graph-studio] loadDatabaseSummary failed', err);
    }
  },

  /** Switch which database the tools query (runtime, no .env edit).
   *  `type` selects the target set; the dropdown's active assistant decides
   *  the right type but callers can override (e.g. manual switching). */
  async selectDatabase(name: string, type: 'sql' | 'neo4j' = 'sql') {
    if (!name) return;
    const currentActive = type === 'sql' ? state.activeSqlDatabase : state.activeNeo4jDatabase;
    if (name === currentActive) return;
    try {
      const info = await api.selectDatabase(name, type);
      setState({
        sqlDatabases: info.sql ?? state.sqlDatabases,
        neo4jDatabases: info.neo4j ?? state.neo4jDatabases,
        activeSqlDatabase: info.active_sql ?? state.activeSqlDatabase,
        activeNeo4jDatabase: info.active_neo4j ?? state.activeNeo4jDatabase,
      });
    } catch (err: any) {
      // Surface friendly messages when the user picks a DB that doesn't
      // exist on the server (404). Without this, the dropdown silently
      // stays on the old value and the user thinks "nothing happened".
      const detail = err?.response?.data?.detail || err?.message || 'Unknown error';
      const status = err?.response?.status;
      const message = status === 404
        ? `Database "${name}" not found on the ${type === 'neo4j' ? 'Neo4j' : 'Postgres'} server.`
        : `Failed to switch database: ${detail}`;
      // studioStore isn't a React component, so we can't call useToast
      // directly. Dispatch a DOM CustomEvent that the ToastContainer
      // (mounted by the app shell) listens for.
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('graph-studio:toast', {
          detail: { message, type: 'error' },
        }));
      } else {
        console.error('[graph-studio] selectDatabase failed', err);
      }
    }
    await studio.loadDatabaseSummary();
  },

  async selectAssistant(assistant: Assistant | null) {
    if (!assistant) {
      setState({
        activeAssistantId: '',
        graph: null,
        schemas: null,
        threads: [],
        currentThreadId: '',
        threadState: null,
        runHistory: [],
        runPath: [],
        liveMap: {},
        runError: null,
        activeNodeId: null,
      });
      return;
    }

    setState({ activeAssistantId: assistant.assistant_id, runError: null, activeNodeId: null });

    // Load graph structure + schemas in parallel.
    const [graph, schemas] = await Promise.all([
      api.loadGraph(assistant.assistant_id).catch(() => null),
      api.loadSchemas(assistant.assistant_id).catch(() => null),
    ]);
    setState({ graph, schemas, direction: 'lr', runPath: [], liveMap: {} });

    await studio.loadThreads(assistant.graph_id);
    // Refresh the canvas-header summary for the new assistant type
    // (SQL summary vs Neo4j summary are different endpoints).
    await studio.loadDatabaseSummary();
  },

  async loadThreads(graphId?: string) {
    try {
      const assistant = state.assistants.find((a) => a.assistant_id === state.activeAssistantId);
      const threads = await api.loadThreads({
        graph_id: graphId ?? assistant?.graph_id ?? undefined,
      });
      setState({ threads });
      if (threads.length === 0) {
        setState({ currentThreadId: '', threadState: null, runHistory: [], runPath: [], liveMap: {} });
      }
    } catch (err) {
      console.error('[graph-studio] loadThreads failed', err);
    }
  },

  async createThread() {
    const assistant = state.assistants.find((a) => a.assistant_id === state.activeAssistantId);
    if (!assistant) return;
    const thread = await api.createThread(assistant.assistant_id, assistant.graph_id);
    await studio.loadThreads(assistant.graph_id);
    await studio.selectThread(thread.thread_id);
  },

  /** Empty the chat log for the active graph.
   *
   *  Needed when the target database changes: the thread list would otherwise keep
   *  conversations about the OLD database, and `sql_agent` bakes the database name
   *  into its schema sentinel — stale history is wrong context, not just noise.
   *  Clears both stores: the Studio thread registry and each graph's checkpointer.
   */
  async clearThreads() {
    const assistant = state.assistants.find((a) => a.assistant_id === state.activeAssistantId);
    if (!assistant) return { cleared: 0, checkpoints_deleted: 0, remaining: 0 };
    try {
      const res = await api.clearThreads(assistant.graph_id);
      setState({
        threads: state.threads.filter((th) => th.metadata?.graph_id !== assistant.graph_id),
        currentThreadId: undefined,
        threadState: null,
        runPath: [],
        liveMap: {},
        runError: null,
      });
      await studio.createThread();
      return res;
    } catch (err) {
      console.error('[graph-studio] clearThreads failed', err);
      throw err;
    }
  },

  async selectThread(threadId: string) {
    setState({ currentThreadId: threadId });
    await studio.refreshState();
  },

  async refreshState() {
    if (!state.currentThreadId) return;
    try {
      const threadState = await api.loadThreadState(state.currentThreadId);
      setState({ threadState, runError: null });
      // Surface pending interrupts in the messages tab.
      if (threadState.interrupts?.length && state.inspectorTab !== 'state') {
        setState({ inspectorTab: 'messages' });
      }
      // Seed the live message map from checkpointed state.
      const values = threadState.values ?? {};
      const messages = (values.messages as LiveMessage[]) ?? [];
      const liveMap: Record<string, LiveMessage> = {};
      for (const m of messages) {
        if (m?.id) liveMap[m.id] = m;
      }
      setState({ liveMap });
    } catch (err) {
      console.error('[graph-studio] refreshState failed', err);
    }
  },

  async run(input: Record<string, unknown>, resume?: unknown) {
    if (state.running) return;
    if (!state.currentThreadId) {
      await studio.createThread();
    }
    let threadId = state.currentThreadId;
    const assistantId = state.activeAssistantId;
    if (!threadId || !assistantId) return;

    setState({ running: true, runError: null, runPath: [], inspectorTab: 'messages' });

    // Hoisted accumulators: `state` (the store snapshot) is captured at run
    // invocation and never refreshed inside the async streamSSE callback,
    // so reading `state.liveMap` / `state.runPath` per event would always
    // return the same stale base and the next setState would clobber all
    // previously streamed messages. Mutate these in the callback instead —
    // `let` bindings in the `run` closure persist across await ticks.
    const liveMap: Record<string, LiveMessage> = { ...state.liveMap };
    const runPath: string[] = [...state.runPath];

    try {
      let res = await api.streamRun(threadId, assistantId, input, resume);
      // Studio threads are in-memory (process-lifetime): after a backend
      // restart the browser can hold a stale thread id that no longer exists.
      // Auto-create a fresh thread and retry once instead of failing with 404.
      if (!res.ok && res.status === 404) {
        await studio.createThread();
        threadId = state.currentThreadId;
        res = await api.streamRun(threadId, assistantId, input, resume);
      }
      if (!res.ok) {
        throw new Error(`${res.status}: ${(await res.text()).slice(0, 200)}`);
      }
      await streamSSE(res, (ev) => {
        if (ev.event === 'messages/partial') {
          const messages = ev.data as LiveMessage[];
          for (const m of messages) {
            if (m?.id) liveMap[m.id] = m; // content is cumulative per id
          }
          setState({ liveMap });
        } else if (ev.event === 'values') {
          const values = ev.data as { messages?: LiveMessage[] };
          const messages = values.messages ?? [];
          for (const m of messages) {
            if (m?.id) liveMap[m.id] = m;
          }
          setState({ liveMap });
        } else if (ev.event === 'updates') {
          const update = ev.data as Record<string, unknown>;
          const keys = Object.keys(update);
          runPath.push(...keys);
          setState({ runPath });
        } else if (ev.event === 'error') {
          const msg = (ev.data as { message?: string })?.message ?? 'Run failed';
          setState({ runError: msg });
        }
      });
    } catch (err) {
      setState({ runError: err instanceof Error ? err.message : String(err) });
    } finally {
      setState({ running: false });
      await studio.refreshState();
      await studio.loadThreads();
    }
  },

  /**
   * Answer a pending human-in-the-loop interrupt.
   *
   * The HITL graphs expect one of:
   *   { type: 'accept' }                              → run the tool as proposed
   *   { type: 'edit', args: { args: { query } } }      → run the edited SQL/Cypher
   *   { type: 'response', args: 'feedback' }           → don't run; tell the model
   */
  async resume(resumeValue: unknown) {
    if (state.running) return;
    await studio.run({}, resumeValue);
  },

  toggleDirection() {
    setState({ direction: state.direction === 'lr' ? 'tb' : 'lr' });
  },

  /** Load the SEMANTICS.md of the ACTIVE database — the file the next run loads. */
  async loadSemantics() {
    const db = state.activeSqlDatabase || 'chinook';
    setState({
      semantics: {
        ...(state.semantics || {
          database: db, path: '', exists: false, bytes: 0, blocks: [],
          checker: '', text: '', loading: false, saving: false,
          dirty: false, message: null, check: null,
        }),
        database: db, loading: true, message: null,
      },
    });
    try {
      const doc = await semanticsApi.load(db);
      setState({
        semantics: {
          database: doc.database, path: doc.path, exists: doc.exists, bytes: doc.bytes,
          blocks: doc.blocks, checker: doc.checker, text: doc.text,
          loading: false, saving: false, dirty: false, message: null, check: null,
        },
      });
    } catch (err) {
      setState({
        semantics: {
          ...(state.semantics as SemanticsState),
          loading: false,
          message: err instanceof Error ? err.message : 'failed to load SEMANTICS.md',
        },
      });
    }
  },

  /** Local edit — does not touch the file. */
  setSemanticsText(text: string) {
    if (!state.semantics) return;
    setState({ semantics: { ...state.semantics, text, dirty: true, message: null } });
  },

  /** Save, then report the database's own gate verdict. */
  async saveSemantics() {
    if (!state.semantics || state.semantics.saving) return;
    const doc = state.semantics;
    setState({ semantics: { ...doc, saving: true, message: null } });
    try {
      const res = await semanticsApi.save(doc.database, doc.text);
      const gate = res.check?.status;
      setState({
        semantics: {
          ...doc, saving: false, dirty: false, bytes: res.bytes, blocks: res.blocks,
          check: res.check ?? null,
          message: gate === 'fail'
            ? '已保存，但校验未通过 —— 见下方输出'
            : gate === 'pass'
              ? '已保存，校验通过'
              : '已保存（该库没有校验脚本）',
        },
      });
      // The file changed: reload summaries so the model's view and the UI agree.
      void studio.loadDatabaseSummary?.();
    } catch (err) {
      setState({
        semantics: { ...doc, saving: false, message: err instanceof Error ? err.message : 'save failed' },
      });
    }
  },

  /** Run the gate without saving. */
  async checkSemantics() {
    if (!state.semantics) return;
    const doc = state.semantics;
    setState({ semantics: { ...doc, saving: true, message: null } });
    try {
      const res = await semanticsApi.check(doc.database);
      setState({
        semantics: {
          ...doc, saving: false, check: res.check ?? null,
          message: res.check?.status === 'pass' ? '校验通过'
            : res.check?.status === 'fail' ? '校验未通过'
            : '该库没有校验脚本',
        },
      });
    } catch (err) {
      setState({
        semantics: { ...doc, saving: false, message: err instanceof Error ? err.message : 'check failed' },
      });
    }
  },

  /** Switch between Graph Flow and Schema Network visualization.
   *  When switching to schema, the active assistant's DB-type drives the
   *  renderer (SQL → ErDiagram, Neo4j → Neo4jNetwork). The schema payload
   *  is already in dbSummary — no extra fetch needed. */
  setViewMode(mode: ViewMode) {
    if (state.viewMode === mode) return;
    setState({ viewMode: mode, activeNodeId: null });
    // Drop transient graph-flow state so the new view starts clean.
    setState({ runPath: [], liveMap: {} });
  },

  /** Switch which database the tools query (runtime, no .env edit). */
  async cancel() {
    if (!state.running || !state.currentThreadId) return;
    try {
      await api.cancelRun(state.currentThreadId);
    } catch (err) {
      console.error('[graph-studio] cancel failed', err);
    }
    // The SSE stream ends with a "Run cancelled" error event; stop the UI now.
    setState({ running: false, runError: 'Run cancelled by user' });
  },

  setInspectorTab(tab: StudioState['inspectorTab']) {
    setState({ inspectorTab: tab });
  },

  /** Open (or close, with null) the canvas node detail popup. */
  selectNode(nodeId: string | null) {
    setState({ activeNodeId: nodeId });
  },
};
