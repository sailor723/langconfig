/**
 * Left sidebar section: thread management for the active assistant.
 */
import { Plus } from 'lucide-react'
import { useStudioStore } from '@/store/studioStore'

function statusStyles(status: string): string {
  const s = status.toLowerCase()
  if (s.includes('success') || s.includes('complete')) return 'text-pulse border-pulse/40'
  if (s.includes('interrupt')) return 'text-red-400 border-red-400/40'
  if (s.includes('running') || s.includes('pending')) return 'text-signal border-signal/40'
  return 'text-ink-300 border-ink-500/50'
}

export default function ThreadPanel() {
  const threads = useStudioStore((s) => s.threads)
  const activeAssistant = useStudioStore((s) => s.activeAssistant)
  const activeThreadId = useStudioStore((s) => s.activeThreadId)
  const createThread = useStudioStore((s) => s.createThread)
  const selectThread = useStudioStore((s) => s.selectThread)

  // Show only threads belonging to the currently selected assistant.
  // The dev server stores the graph_id in thread metadata, which is the
  // stable key to attribute threads to an assistant.
  const assistantThreads = activeAssistant
    ? threads.filter((t) => t.metadata?.graph_id === activeAssistant.graph_id)
    : []

  const shortId = (id: string) => id.slice(0, 8)

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center justify-between px-3 pb-1 pt-2">
        <span className="section-title">Threads</span>
        <button
          type="button"
          onClick={() => createThread()}
          disabled={!activeAssistant}
          title={activeAssistant ? 'Create a new thread' : 'Select an assistant first'}
          className="inline-flex h-5 w-5 items-center justify-center rounded border border-ink-500/70 text-ink-200 transition-colors hover:border-signal hover:text-signal disabled:opacity-40 cursor-pointer"
        >
          <Plus size={12} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2 pt-1">
        {assistantThreads.length === 0 ? (
          <p className="px-1 py-2 font-mono text-[11px] leading-relaxed text-ink-300">
            No threads yet.
            <br />
            Create one to start running.
          </p>
        ) : (
          <ul className="flex flex-col gap-1">
            {assistantThreads.map((t) => {
              const active = t.thread_id === activeThreadId
              return (
                <li key={t.thread_id}>
                  <button
                    type="button"
                    onClick={() => selectThread(t.thread_id)}
                    className={`w-full rounded-md border px-2.5 py-1.5 text-left transition-colors cursor-pointer
                      ${active
                        ? 'border-signal/60 bg-ink-700 shadow-glow'
                        : 'border-transparent hover:bg-ink-700'}`}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="font-mono text-xs text-ink-100">#{shortId(t.thread_id)}</span>
                      <span
                        className={`rounded-sm border px-1.5 py-px font-mono text-[9px] uppercase tracking-wider ${statusStyles(t.status)}`}
                      >
                        {t.status}
                      </span>
                    </span>
                    <span className="mt-0.5 block font-mono text-[10px] text-ink-300">
                      {new Date(t.created_at).toLocaleString()}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
