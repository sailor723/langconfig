/**
 * Right panel top: JSON input editor + run execution.
 * The default input is seeded from the assistant's input schema
 * (e.g. a MessagesState graph gets a messages template).
 *
 * Chat graphs (input schema with `messages`) hide this editor entirely —
 * they are driven by the chat input under the Messages tab instead.
 */
import { useEffect, useState } from 'react'
import { Play, AlertTriangle, Loader2, RefreshCw } from 'lucide-react'
import { useStudioStore } from '@/store/studioStore'
import { hasMessagesInput } from '@/api/client'
import type { AssistantSchemas } from '@/api/client'

// Build a sensible starter input from the graph's input schema.
function defaultInput(schemas: AssistantSchemas | null): string {
  const props = schemas?.input_schema?.properties as
    | Record<string, unknown>
    | undefined
  if (props && 'messages' in props) {
    return JSON.stringify(
      { messages: [{ role: 'user', content: 'hi' }] },
      null,
      2,
    )
  }
  return '{\n  \n}'
}

export default function RunConsole() {
  const schemas = useStudioStore((s) => s.schemas)
  const activeAssistant = useStudioStore((s) => s.activeAssistant)
  const activeThreadId = useStudioStore((s) => s.activeThreadId)
  const running = useStudioStore((s) => s.running)
  const error = useStudioStore((s) => s.error)
  const run = useStudioStore((s) => s.run)
  const refreshState = useStudioStore((s) => s.refreshState)

  const [inputText, setInputText] = useState('{\n  \n}')
  const [parseError, setParseError] = useState<string | null>(null)

  // Re-seed the default input when the assistant changes
  useEffect(() => {
    setInputText(defaultInput(schemas))
    setParseError(null)
  }, [schemas])

  const handleRun = async () => {
    setParseError(null)
    let parsed: unknown
    try {
      parsed = JSON.parse(inputText)
    } catch {
      setParseError('Invalid JSON — check the braces and commas.')
      return
    }
    await run(parsed)
  }

  // Chat graphs are driven by the chat input, not this JSON editor
  if (hasMessagesInput(schemas)) {
    return (
      <div className="p-3">
        <span className="section-title">Run</span>
        <p className="mt-1 font-mono text-[11px] leading-relaxed text-ink-300">
          This graph takes chat messages — use the input box under the Messages tab.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2 p-3">
      <div className="flex items-center justify-between">
        <span className="section-title">Run</span>
        {activeAssistant && (
          <span className="font-mono text-[10px] text-ink-300">{activeAssistant.name}</span>
        )}
      </div>

      <textarea
        value={inputText}
        onChange={(e) => setInputText(e.target.value)}
        spellCheck={false}
        rows={6}
        className="field-input resize-y !leading-relaxed"
        placeholder="Enter graph input as JSON"
      />

      {parseError && (
        <p className="flex items-center gap-1.5 font-mono text-[11px] text-red-400">
          <AlertTriangle size={12} />
          {parseError}
        </p>
      )}

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handleRun}
          disabled={running || !activeThreadId}
          className="btn-primary flex-1 justify-center"
          title={activeThreadId ? 'Run the graph' : 'Create a thread first'}
        >
          {running ? (
            <>
              <Loader2 size={13} className="animate-spin" />
              Running…
            </>
          ) : (
            <>
              <Play size={13} />
              Run graph
            </>
          )}
        </button>
        <button
          type="button"
          onClick={() => refreshState()}
          disabled={!activeThreadId}
          title="Refresh state"
          className="btn-ghost"
        >
          <RefreshCw size={13} />
        </button>
      </div>

      {!activeThreadId && (
        <p className="font-mono text-[10px] text-ink-300">
          Create a thread to enable running.
        </p>
      )}

      {error && (
        <p className="max-h-28 overflow-y-auto rounded-md border border-red-400/30 bg-red-400/5 p-2 font-mono text-[11px] leading-relaxed text-red-400">
          {error}
        </p>
      )}
    </div>
  )
}
