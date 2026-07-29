/**
 * CodexMessageInput — Codex-style multi-line composer with action row.
 *
 * Layout (inside the rounded composer card):
 *   ┌──────────────────────────────────────────┐
 *   │  Multi-line textarea                     │
 *   │                                          │
 *   ├──────────────────────────────────────────┤
 *   │ [+] [Mode ▾]            [Send button ↑] │
 *   ├──────────────────────────────────────────┤
 *   │ [project] · Work locally                 │
 *   └──────────────────────────────────────────┘
 */
import { useState, useRef, KeyboardEvent, useEffect } from 'react';
import { Send } from 'lucide-react';
import FileUploadButton from './FileUploadButton';
import type { SessionDocument } from '../types/chat';

interface CodexMessageInputProps {
  onSendMessage: (message: string) => void;
  disabled?: boolean;
  isStreaming?: boolean;
  placeholder?: string;
  sessionId?: string | null;
  projectId?: number | null;
  onFileUploaded?: (file: SessionDocument) => void;
  /** Optional current project/agent label shown inside composer footer */
  agentName?: string;
}

export default function CodexMessageInput({
  onSendMessage,
  disabled = false,
  isStreaming = false,
  placeholder = 'Do anything',
  sessionId = null,
  projectId = null,
  onFileUploaded = () => {},
  agentName,
}: CodexMessageInputProps) {
  const [inputValue, setInputValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea (44px min, 240px max)
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    const newHeight = Math.min(ta.scrollHeight, 240);
    ta.style.height = `${newHeight}px`;
  }, [inputValue]);

  const handleSend = () => {
    const message = inputValue.trim();
    if (!message || disabled || isStreaming) return;
    onSendMessage(message);
    setInputValue('');
    setTimeout(() => textareaRef.current?.focus(), 50);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const canSend = inputValue.trim().length > 0 && !disabled && !isStreaming;

  return (
    <div
      className="rounded-2xl overflow-hidden transition-colors"
      style={{
        backgroundColor: 'var(--color-input-background, #ffffff)',
      }}
    >
      {/* Textarea */}
      <textarea
        ref={textareaRef}
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={disabled || isStreaming}
        rows={1}
        className="w-full resize-none px-4 pt-3 pb-2 text-sm focus:outline-none disabled:opacity-50"
        style={{
          backgroundColor: 'transparent',
          color: 'var(--color-text-primary)',
          minHeight: '44px',
          maxHeight: '240px',
          lineHeight: '1.5',
        }}
      />

      {/* Action row */}
      <div className="flex items-center justify-between px-2 py-1.5">
        <div className="flex items-center gap-0.5">
          <FileUploadButton
            sessionId={sessionId}
            projectId={projectId}
            onFileUploaded={onFileUploaded}
            disabled={disabled || isStreaming}
          />
        </div>

        {/* Round send button */}
        <button
          onClick={handleSend}
          disabled={!canSend}
          className="w-8 h-8 rounded-full flex items-center justify-center transition-all
                     disabled:opacity-40 disabled:cursor-not-allowed
                     hover:opacity-90 active:scale-95"
          style={{
            backgroundColor: 'var(--color-primary)',
            color: 'white',
          }}
          title={isStreaming ? 'Streaming...' : 'Send message'}
        >
          {isStreaming ? (
            <span className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
          ) : (
            <Send className="w-3.5 h-3.5" />
          )}
        </button>
      </div>

      {/* Footer row (project badge, environment) */}
      {agentName && (
        <div
          className="flex items-center gap-3 px-3 py-1.5 text-[11px]"
          style={{
            color: 'var(--color-text-muted)',
          }}
        >
          <span className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
            {agentName}
          </span>
          <span>·</span>
          <span>Work locally</span>
        </div>
      )}
    </div>
  );
}
