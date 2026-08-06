/**
 * Left sidebar section: lists the available graph assistants.
 */
import { Workflow } from 'lucide-react'
import { useStudioStore } from '@/store/studioStore'

export default function AssistantList() {
  const assistants = useStudioStore((s) => s.assistants)
  const activeAssistant = useStudioStore((s) => s.activeAssistant)
  const loading = useStudioStore((s) => s.loading)
  const selectAssistant = useStudioStore((s) => s.selectAssistant)

  if (loading && assistants.length === 0) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 font-mono text-xs text-ink-300">
        <span className="h-3 w-3 animate-pulse rounded-full bg-signal" />
        Loading assistants…
      </div>
    )
  }

  return (
    <ul className="flex flex-col gap-1 p-2">
      {assistants.map((a) => {
        const active = activeAssistant?.assistant_id === a.assistant_id
        return (
          <li key={a.assistant_id}>
            <button
              type="button"
              onClick={() => selectAssistant(a.assistant_id)}
              className={`w-full rounded-md border px-2.5 py-2 text-left transition-colors cursor-pointer
                ${active
                  ? 'border-signal/60 bg-ink-700 shadow-glow'
                  : 'border-transparent hover:border-ink-600 hover:bg-ink-700'}`}
            >
              <span className="flex items-center gap-1.5 font-mono text-xs text-ink-50">
                <Workflow size={12} className={active ? 'text-signal' : 'text-ink-300'} />
                {a.name}
              </span>
              <span className="mt-0.5 block pl-[18px] font-mono text-[10px] text-ink-300">
                {a.graph_id}
              </span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
