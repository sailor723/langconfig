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
import { api } from './api';
import { streamSSE } from './stream';
import type {
  Assistant,
  AssistantSchemas,
  GraphSpec,
  LiveMessage,
  RunInfo,
  Thread,
  ThreadState,
} from './api';

export type Direction = 'lr' | 'tb';

export interface StudioState {
  apiOnline: boolean;
  assistants: Assistant[];
  activeAssistantId: string;
  graph: GraphSpec | null;
  schemas: AssistantSchemas | null;
  direction: Direction;
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
  /** Load the code-defined assistants; select the first one by default. */
  async loadAssistants() {
    try {
      const assistants = await api.loadAssistants();
      setState({ assistants, apiOnline: true });
      const active = assistants.find((a) => a.assistant_id === state.activeAssistantId);
      await studio.selectAssistant(active ?? assistants[0] ?? null);
    } catch (err) {
      setState({ apiOnline: false });
      console.error('[graph-studio] loadAssistants failed', err);
    }
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

  async run(input: Record<string, unknown>) {
    if (state.running) return;
    if (!state.currentThreadId) {
      await studio.createThread();
    }
    const threadId = state.currentThreadId;
    const assistantId = state.activeAssistantId;
    if (!threadId || !assistantId) return;

    setState({ running: true, runError: null, runPath: [], inspectorTab: 'messages' });

    try {
      const res = await api.streamRun(threadId, assistantId, input);
      if (!res.ok) {
        throw new Error(`${res.status}: ${(await res.text()).slice(0, 200)}`);
      }
      await streamSSE(res, (ev) => {
        if (ev.event === 'messages/partial') {
          const messages = ev.data as LiveMessage[];
          const liveMap = { ...state.liveMap };
          for (const m of messages) {
            if (m?.id) liveMap[m.id] = m; // content is cumulative per id
          }
          setState({ liveMap });
        } else if (ev.event === 'values') {
          const values = ev.data as { messages?: LiveMessage[] };
          const messages = values.messages ?? [];
          const liveMap = { ...state.liveMap };
          for (const m of messages) {
            if (m?.id) liveMap[m.id] = m;
          }
          setState({ liveMap });
        } else if (ev.event === 'updates') {
          const update = ev.data as Record<string, unknown>;
          const keys = Object.keys(update);
          setState({ runPath: [...state.runPath, ...keys] });
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

  toggleDirection() {
    setState({ direction: state.direction === 'lr' ? 'tb' : 'lr' });
  },

  setInspectorTab(tab: StudioState['inspectorTab']) {
    setState({ inspectorTab: tab });
  },

  /** Open (or close, with null) the canvas node detail popup. */
  selectNode(nodeId: string | null) {
    setState({ activeNodeId: nodeId });
  },
};
