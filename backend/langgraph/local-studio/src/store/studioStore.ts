/**
 * Global state for the studio, backed by zustand.
 * Owns: assistants, active graph, threads, thread state, run status.
 */
import { create } from 'zustand'
import { api } from '@/api/client'
import { streamSSE } from '@/api/stream'
import type {
  Assistant,
  AssistantSchemas,
  GraphSpec,
  RunInfo,
  Thread,
  ThreadState,
} from '@/api/client'

/**
 * A single message assembled from `messages/partial` chunks.
 * Content is cumulative across chunks, so later chunks replace earlier ones.
 */
export interface LiveMessage {
  id: string
  type: string
  name?: string | null
  content: string
  tool_calls?: unknown[]
  response_metadata?: unknown
}

interface StudioState {
  // assistants / graph
  assistants: Assistant[]
  activeAssistant: Assistant | null
  graph: GraphSpec | null
  schemas: AssistantSchemas | null

  // threads / state
  threads: Thread[]
  activeThreadId: string | null
  state: ThreadState | null
  runs: RunInfo[]

  // live streaming
  liveMessages: LiveMessage[] | null
  /** Node ids that actually executed in the current run, in order (from `updates` events). */
  runPath: string[]

  // graph canvas
  /** Graph layout direction: left-to-right (lr) or top-to-bottom (tb). */
  direction: 'lr' | 'tb'

  // ui flags
  loading: boolean
  running: boolean
  apiOnline: boolean
  error: string | null

  loadAssistants: () => Promise<void>
  selectAssistant: (assistantId: string) => Promise<void>
  loadThreads: () => Promise<void>
  createThread: () => Promise<void>
  selectThread: (threadId: string) => Promise<void>
  refreshState: () => Promise<void>
  run: (input: unknown) => Promise<void>
  toggleDirection: () => void
}

/** Merge a chunked message into the live map (content is cumulative). */
function mergeLiveMessage(
  map: Map<string, LiveMessage>,
  chunk: LiveMessage,
): void {
  const prev = map.get(chunk.id)
  map.set(chunk.id, {
    id: chunk.id,
    type: chunk.type ?? prev?.type ?? 'ai',
    name: chunk.name ?? prev?.name ?? null,
    content: typeof chunk.content === 'string' ? chunk.content : JSON.stringify(chunk.content ?? ''),
    tool_calls: chunk.tool_calls ?? prev?.tool_calls,
    response_metadata: chunk.response_metadata ?? prev?.response_metadata,
  })
}

export const useStudioStore = create<StudioState>((set, get) => ({
  assistants: [],
  activeAssistant: null,
  graph: null,
  schemas: null,

  threads: [],
  activeThreadId: null,
  state: null,
  runs: [],

  liveMessages: null,
  runPath: [],

  direction: 'lr',

  loading: false,
  running: false,
  apiOnline: false,
  error: null,

  loadAssistants: async () => {
    set({ loading: true, error: null })
    try {
      const assistants = await api.listAssistants()
      // Prefer the plain sql_agent graph for the chat UI: the hitl variant
      // pauses at a human-approval interrupt the studio does not surface yet.
      assistants.sort((a, b) => a.graph_id.localeCompare(b.graph_id))
      set({ assistants, apiOnline: true })
      // Auto-select the first assistant if none is active
      if (!get().activeAssistant && assistants.length > 0) {
        await get().selectAssistant(assistants[0].assistant_id)
      }
    } catch (err) {
      set({ apiOnline: false, error: (err as Error).message })
    } finally {
      set({ loading: false })
    }
  },

  selectAssistant: async (assistantId: string) => {
    const assistant =
      get().assistants.find((a) => a.assistant_id === assistantId) ?? null
    set({
      activeAssistant: assistant,
      graph: null,
      schemas: null,
      activeThreadId: null,
      state: null,
      runs: [],
      runPath: [],
      error: null,
    })
    if (!assistant) return
    try {
      const [graph, schemas] = await Promise.all([
        api.getGraph(assistantId),
        api.getSchemas(assistantId),
      ])
      set({ graph, schemas })
    } catch (err) {
      set({ error: (err as Error).message })
    }
    await get().loadThreads()
  },

  loadThreads: async () => {
    try {
      const threads = await api.listThreads()
      set({ threads })
      // Keep the active thread if it still exists; otherwise clear selection
      const { activeThreadId } = get()
      if (activeThreadId && !threads.some((t) => t.thread_id === activeThreadId)) {
        set({ activeThreadId: null, state: null, runs: [] })
      }
    } catch (err) {
      set({ error: (err as Error).message })
    }
  },

  createThread: async () => {
    const { activeAssistant } = get()
    if (!activeAssistant) return
    set({ error: null })
    try {
      const thread = await api.createThread({
        assistant_id: activeAssistant.assistant_id,
        graph_id: activeAssistant.graph_id,
      })
      await get().loadThreads()
      await get().selectThread(thread.thread_id)
    } catch (err) {
      set({ error: (err as Error).message })
    }
  },

  selectThread: async (threadId: string) => {
    set({ activeThreadId: threadId, error: null })
    try {
      const [state, runs] = await Promise.all([
        api.getThreadState(threadId),
        api.listRuns(threadId),
      ])
      set({ state, runs })
    } catch (err) {
      set({ error: (err as Error).message })
    }
  },

  refreshState: async () => {
    const { activeThreadId } = get()
    if (!activeThreadId) return
    try {
      const [state, runs] = await Promise.all([
        api.getThreadState(activeThreadId),
        api.listRuns(activeThreadId),
      ])
      set({ state, runs })
    } catch (err) {
      set({ error: (err as Error).message })
    }
  },

  run: async (input: unknown) => {
    const { activeAssistant, activeThreadId } = get()
    if (!activeAssistant || !activeThreadId) {
      set({ error: 'Create a thread before running.' })
      return
    }

    set({ running: true, error: null, liveMessages: null, runPath: [] })
    // Assemble streaming messages per id; insertion order mirrors arrival order.
    const liveMap = new Map<string, LiveMessage>()
    // Track which nodes actually executed, in order (drives canvas highlighting)
    const executed: string[] = []

    try {
      const res = await api.streamRun(
        activeThreadId,
        activeAssistant.assistant_id,
        input,
        ['messages', 'values', 'updates'],
      )
      if (!res.ok) {
        let detail = `${res.status} ${res.statusText}`
        try {
          const body = (await res.json()) as { detail?: unknown; error?: unknown }
          const message = body?.detail ?? body?.error
          detail = typeof message === 'string' ? message : JSON.stringify(message ?? detail)
        } catch {
          // keep the status text
        }
        throw new Error(detail)
      }

      await streamSSE(res, (ev) => {
        if (ev.event === 'messages/partial') {
          // data: [messageChunk] — content is cumulative, replace per id
          const chunks = ev.data as LiveMessage[]
          for (const chunk of chunks) {
            if (chunk?.id) mergeLiveMessage(liveMap, chunk)
          }
          set({ liveMessages: Array.from(liveMap.values()) })
        } else if (ev.event === 'values') {
          // Full state snapshots carry tool/human messages too; sync them in
          const values = ev.data as Record<string, unknown>
          const messages = values.messages as LiveMessage[] | undefined
          if (Array.isArray(messages)) {
            for (const m of messages) {
              if (m?.id) mergeLiveMessage(liveMap, m)
            }
            set({ liveMessages: Array.from(liveMap.values()) })
          }
        } else if (ev.event === 'updates') {
          // { node_name: { ...updated state } } — the node just finished running
          const update = ev.data as Record<string, unknown>
          for (const nodeId of Object.keys(update)) {
            if (nodeId !== '__end__' && !executed.includes(nodeId)) {
              executed.push(nodeId)
            }
          }
          set({ runPath: [...executed] })
        }
      })
    } catch (err) {
      set({ error: (err as Error).message })
    } finally {
      set({ running: false, liveMessages: null })
      // Re-fetch persisted state so the inspector shows the final result
      await get().refreshState()
    }
  },

  toggleDirection: () => {
    set((s) => ({ direction: s.direction === 'lr' ? 'tb' : 'lr' }))
  },
}))
