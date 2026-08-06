/**
 * Run console — the quick "test run" entry point in the studio's right rail.
 *
 * Seeds a default input from the assistant's input schema (chat graphs start
 * with an empty user message), then kicks off an SSE run on the active thread.
 */
import { useState } from 'react';
import { Play } from 'lucide-react';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { studio, useStudioState } from './studioStore';
import { hasMessagesInput } from './api';

export default function RunConsole() {
  const t = useLayoutTokens();
  const { schemas, running, runError, runHistory } = useStudioState();
  const [prompt, setPrompt] = useState('');

  const isChat = hasMessagesInput(schemas);
  const canRun = !running && (prompt.trim().length > 0 || !isChat);

  const run = async () => {
    if (running) return;
    const input = isChat
      ? { messages: [{ role: 'user', content: prompt.trim() }] }
      : { input: prompt.trim() };
    await studio.run(input);
  };

  const lastRun = runHistory[0];

  return (
    <div
      style={{
        padding: '8px 10px',
        borderBottom: `1px solid ${t.border}`,
        background: t.bgSidebar,
        flexShrink: 0,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <span style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, color: t.textDim }}>
          Test Run
        </span>
        {lastRun && (
          <span style={{ fontSize: 10.5, color: t.textMuted, marginLeft: 'auto' }}>
            last: {lastRun.status}
          </span>
        )}
      </div>

      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            void run();
          }
        }}
        rows={2}
        placeholder={isChat ? 'e.g. how many employees are there?' : 'Enter input JSON…'}
        disabled={running}
        style={{
          width: '100%',
          resize: 'none',
          boxSizing: 'border-box',
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

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
        <button
          onClick={() => void run()}
          disabled={!canRun}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 5,
            border: 'none',
            borderRadius: 6,
            padding: '5px 12px',
            fontSize: 12,
            fontWeight: 600,
            background: canRun ? t.accent : t.bgInput,
            color: canRun ? '#ffffff' : t.textDim,
            cursor: canRun ? 'pointer' : 'not-allowed',
          }}
        >
          <Play size={12} />
          {running ? 'Running…' : 'Run'}
        </button>
        {runError && (
          <span style={{ fontSize: 11, color: '#e5484d', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {runError}
          </span>
        )}
      </div>
    </div>
  );
}
