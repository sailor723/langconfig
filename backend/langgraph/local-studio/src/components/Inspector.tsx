/**
 * Right panel bottom: inspect the active thread.
 * Tabs — Messages: chat-style view of state.values.messages
 *         State:  pretty JSON of state.values
 *         Raw:    full thread state
 */
import { useState } from 'react'
import { MessageSquare, Braces, FileCode2 } from 'lucide-react'
import { useStudioStore } from '@/store/studioStore'
import { hasMessagesInput } from '@/api/client'
import ChatInput from '@/components/ChatInput'

type Tab = 'messages' | 'state' | 'raw'

interface ChatMessage {
  content?: string | Array<unknown>
  type?: string
  role?: string
  name?: string | null
  tool_call_id?: string
  [k: string]: unknown
}

// Normalize message content (string or block array) to display text
function contentText(content: string | Array<unknown> | undefined): string {
  if (content === undefined || content === null) return ''
  if (typeof content === 'string') return content
  return JSON.stringify(content)
}

function MessageRow({ message }: { message: ChatMessage }) {
  const type = message.type ?? message.role ?? 'chat'
  const text = contentText(message.content)
  const isTool = type === 'tool' || type === 'function'
  const isHuman = type === 'human'
  const isSystem = type === 'system'

  if (isTool) {
    return (
      <div className="rounded-md border border-ink-600/60 bg-ink-900 px-2 py-1.5">
        <p className="font-mono text-[9px] uppercase tracking-wider text-ink-300">
          tool{message.tool_call_id ? ` · ${message.tool_call_id.slice(0, 8)}` : ''}
        </p>
        <pre className="mt-0.5 whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-ink-200">
          {text}
        </pre>
      </div>
    )
  }

  if (isSystem) {
    return (
      <div className="text-center">
        <span className="inline-block max-w-full rounded-md border border-ink-600/50 px-2 py-1 font-mono text-[10px] text-ink-300">
          {text}
        </span>
      </div>
    )
  }

  return (
    <div className={`flex ${isHuman ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] rounded-md border px-2.5 py-1.5
          ${isHuman
            ? 'border-signal/40 bg-signal/10 text-ink-50'
            : 'border-ink-600/70 bg-ink-700 text-ink-100'}`}
      >
        <p className="mb-0.5 font-mono text-[9px] uppercase tracking-wider text-ink-300">
          {isHuman ? 'human' : message.name ?? 'assistant'}
        </p>
        <p className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed">{text}</p>
      </div>
    </div>
  )
}

export default function Inspector() {
  const state = useStudioStore((s) => s.state)
  const activeThreadId = useStudioStore((s) => s.activeThreadId)
  const liveMessages = useStudioStore((s) => s.liveMessages)
  const running = useStudioStore((s) => s.running)
  const schemas = useStudioStore((s) => s.schemas)
  const [tab, setTab] = useState<Tab>('messages')

  // Chat graphs get a classic-studio chat input under the messages
  const isChatGraph = hasMessagesInput(schemas)

  // During a run, prefer live-streamed messages for real-time rendering;
  // fall back to the persisted state otherwise.
  const messages = liveMessages
    ? (liveMessages as unknown as ChatMessage[])
    : Array.isArray(state?.values?.messages)
      ? (state.values.messages as ChatMessage[])
      : null

  const tabs: { id: Tab; label: string; icon: typeof MessageSquare; count?: number }[] = [
    { id: 'messages', label: 'Messages', icon: MessageSquare, count: messages?.length },
    { id: 'state', label: 'State', icon: Braces },
    { id: 'raw', label: 'Raw', icon: FileCode2 },
  ]

  if (!activeThreadId) {
    return (
      <div className="flex h-full items-center justify-center p-4">
        <p className="text-center font-mono text-xs text-ink-300">
          Select a thread to inspect
          <br />
          its state and messages.
        </p>
      </div>
    )
  }

  const renderTabContent = () => {
    if (!state) {
      return <p className="font-mono text-xs text-ink-300">No state yet.</p>
    }
    if (tab === 'messages') {
      if (!messages || messages.length === 0) {
        return <p className="font-mono text-xs text-ink-300">No messages in state.</p>
      }
      return (
        <div className="flex flex-col gap-2">
          {messages.map((m, i) => (
            <MessageRow key={String(m.id ?? i)} message={m} />
          ))}
        </div>
      )
    }
    if (tab === 'state') {
      return (
        <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-ink-200">
          {JSON.stringify(state.values, null, 2)}
        </pre>
      )
    }
    return (
      <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-ink-200">
        {JSON.stringify(state, null, 2)}
      </pre>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* status chips */}
      <div className="flex flex-wrap items-center gap-1.5 px-3 pb-2">
        {running && (
          <span className="animate-pulse rounded-sm border border-signal/50 px-1.5 py-px font-mono text-[9px] text-signal">
            streaming…
          </span>
        )}
        {(state?.next ?? []).length > 0 && (
          <span className="rounded-sm border border-signal/40 px-1.5 py-px font-mono text-[9px] text-signal">
            next: {(state?.next ?? []).join(', ')}
          </span>
        )}
        {(state?.interrupts?.length ?? 0) > 0 && (
          <span className="rounded-sm border border-red-400/40 px-1.5 py-px font-mono text-[9px] text-red-400">
            {state?.interrupts?.length} interrupt(s)
          </span>
        )}
        {state?.metadata?.graph_id && (
          <span className="rounded-sm border border-ink-500/50 px-1.5 py-px font-mono text-[9px] text-ink-300">
            {state.metadata.graph_id as string}
          </span>
        )}
      </div>

      {/* tab bar */}
      <div className="flex gap-1 border-b border-ink-600/60 px-3">
        {tabs.map((t) => {
          const Icon = t.icon
          const active = tab === t.id
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={`-mb-px flex items-center gap-1.5 border-b-2 px-2 py-1.5 font-mono text-[11px] transition-colors cursor-pointer
                ${active
                  ? 'border-signal text-signal'
                  : 'border-transparent text-ink-300 hover:text-ink-100'}`}
            >
              <Icon size={12} />
              {t.label}
              {typeof t.count === 'number' && (
                <span className="text-[9px] text-ink-300">{t.count}</span>
              )}
            </button>
          )
        })}
      </div>

      {/* content */}
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto p-3">{renderTabContent()}</div>
        {/* Classic-studio chat input pinned under the message list */}
        {tab === 'messages' && isChatGraph && <ChatInput />}
      </div>
    </div>
  )
}
