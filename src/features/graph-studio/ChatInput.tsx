/**
 * Chat input for the Graph Engineering studio.
 *
 * Sends the typed message as a `messages`-shaped input (chat graphs) or a raw
 * `input` field (form graphs). Enter submits; Shift+Enter inserts a newline.
 */
import { useState } from 'react';
import { ArrowUp } from 'lucide-react';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { studio, useStudioState } from './studioStore';
import { hasMessagesInput } from './api';

export default function ChatInput() {
  const t = useLayoutTokens();
  const { running, threadState, schemas } = useStudioState();
  const [value, setValue] = useState('');

  const interrupted = (threadState?.interrupts?.length ?? 0) > 0;

  const submit = async () => {
    const text = value.trim();
    if (!text || running || interrupted) return;
    setValue('');
    const isChat = hasMessagesInput(schemas);
    const input = isChat
      ? { messages: [{ role: 'user', content: text }] }
      : { input: text };
    await studio.run(input);
  };

  const placeholder = interrupted
    ? 'Agent is waiting for approval…'
    : running
      ? 'Agent is running…'
      : 'Ask anything…';

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-end',
        gap: 6,
        padding: '8px 10px',
        borderTop: `1px solid ${t.border}`,
        background: t.bgSidebar,
      }}
    >
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            void submit();
          }
        }}
        rows={1}
        disabled={running || interrupted}
        placeholder={placeholder}
        style={{
          flex: 1,
          resize: 'none',
          background: t.bgInput,
          color: t.textPrimary,
          border: `1px solid ${t.border}`,
          borderRadius: 6,
          padding: '7px 10px',
          fontSize: 12.5,
          fontFamily: 'inherit',
          outline: 'none',
        }}
      />
      <button
        onClick={() => void submit()}
        disabled={!value.trim() || running || interrupted}
        title="Send (Enter)"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 28,
          height: 28,
          borderRadius: 6,
          border: 'none',
          background: value.trim() && !running && !interrupted ? t.accent : t.bgInput,
          color: value.trim() && !running && !interrupted ? '#ffffff' : t.textDim,
          cursor: value.trim() && !running && !interrupted ? 'pointer' : 'not-allowed',
        }}
      >
        <ArrowUp size={15} />
      </button>
    </div>
  );
}
