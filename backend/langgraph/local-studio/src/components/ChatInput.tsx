/**
 * Chat input box (classic Studio style) for chat graphs.
 * Renders at the bottom of the Messages tab; Enter sends, Shift+Enter newline.
 * Wraps the typed text as a human message before invoking the graph run.
 */
import { useEffect, useRef, useState } from 'react'
import { Send, Loader2 } from 'lucide-react'
import { useStudioStore } from '@/store/studioStore'

export default function ChatInput() {
  const activeThreadId = useStudioStore((s) => s.activeThreadId)
  const running = useStudioStore((s) => s.running)
  const run = useStudioStore((s) => s.run)

  const [text, setText] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const canSend = activeThreadId !== null && !running && text.trim().length > 0

  // Auto-grow the textarea up to a few lines as the user types
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`
  }, [text])

  const handleSend = async () => {
    const content = text.trim()
    if (!content || !canSend) return
    setText('')
    // Classic Studio wraps chat text as a user message
    await run({ messages: [{ role: 'user', content }] })
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends the message; Shift+Enter inserts a newline
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      void handleSend()
    }
  }

  return (
    <div className="shrink-0 border-t border-ink-600/60 p-3">
      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          spellCheck={false}
          disabled={!activeThreadId || running}
          placeholder={
            !activeThreadId
              ? 'Create a thread to start chatting…'
              : running
                ? 'Graph is running…'
                : 'Type a message and press Enter'
          }
          className="field-input min-h-[38px] flex-1 resize-none !leading-relaxed"
        />
        <button
          type="button"
          onClick={() => void handleSend()}
          disabled={!canSend}
          className="btn-primary flex h-[38px] w-[38px] shrink-0 items-center justify-center"
          title="Send (Enter)"
        >
          {running ? (
            <Loader2 size={15} className="animate-spin" />
          ) : (
            <Send size={15} />
          )}
        </button>
      </div>
    </div>
  )
}
