/**
 * Studio shell: top bar + three-pane layout.
 */
import { useEffect } from 'react'
import { Radio } from 'lucide-react'
import AssistantList from '@/components/AssistantList'
import ThreadPanel from '@/components/ThreadPanel'
import GraphCanvas from '@/components/GraphCanvas'
import RunConsole from '@/components/RunConsole'
import Inspector from '@/components/Inspector'
import { useStudioStore } from '@/store/studioStore'

export default function Home() {
  const loadAssistants = useStudioStore((s) => s.loadAssistants)
  const apiOnline = useStudioStore((s) => s.apiOnline)
  const activeAssistant = useStudioStore((s) => s.activeAssistant)

  useEffect(() => {
    void loadAssistants()
  }, [loadAssistants])

  return (
    <div className="flex h-screen flex-col bg-ink-950 text-ink-100">
      {/* top bar */}
      <header className="flex h-11 shrink-0 items-center justify-between border-b border-ink-600/60 bg-ink-900 px-4">
        <div className="flex items-center gap-2.5">
          <Radio size={16} className="text-signal" />
          <h1 className="font-mono text-sm font-semibold tracking-[0.22em] text-ink-50">
            LOCAL&nbsp;STUDIO
          </h1>
          <span className="hidden items-center gap-1.5 font-mono text-[10px] text-ink-300 sm:flex">
            <span className="text-ink-400">/</span>
            langgraph debugger
          </span>
        </div>
        <div className="flex items-center gap-3">
          {activeAssistant && (
            <span className="font-mono text-[11px] text-ink-200">
              graph: <span className="text-signal">{activeAssistant.name}</span>
            </span>
          )}
          <span
            className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider
              ${apiOnline
                ? 'border-pulse/40 text-pulse shadow-glow-teal'
                : 'border-red-400/40 text-red-400'}`}
            title={apiOnline ? 'langgraph dev reachable' : 'langgraph dev unreachable'}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${apiOnline ? 'bg-pulse animate-pulse' : 'bg-red-400'}`}
            />
            {apiOnline ? 'online' : 'offline'}
          </span>
        </div>
      </header>

      {/* three-pane body */}
      <div className="flex min-h-0 flex-1">
        {/* left sidebar */}
        <aside className="flex w-64 shrink-0 flex-col border-r border-ink-600/60 bg-ink-850">
          <div className="flex h-full flex-col">
            <div className="shrink-0 px-3 pb-1 pt-3">
              <span className="section-title">Assistants</span>
            </div>
            <div className="max-h-48 overflow-y-auto border-b border-ink-600/40">
              <AssistantList />
            </div>
            <ThreadPanel />
          </div>
        </aside>

        {/* center canvas */}
        <main className="min-w-0 flex-1">
          <GraphCanvas />
        </main>

        {/* right panel */}
        <aside className="flex w-80 shrink-0 flex-col border-l border-ink-600/60 bg-ink-850">
          <div className="shrink-0 border-b border-ink-600/40">
            <RunConsole />
          </div>
          <div className="min-h-0 flex-1">
            <Inspector />
          </div>
        </aside>
      </div>
    </div>
  )
}
