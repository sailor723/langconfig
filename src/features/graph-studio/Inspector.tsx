/**
 * Inspector panel — messages / state / raw JSON views for the active thread,
 * plus the chat input for message-based graphs.
 */
import type { CSSProperties } from 'react';
import { useState } from 'react';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { studio, useStudioState } from './studioStore';
import ChatInput from './ChatInput';
import InterruptBar from './InterruptBar';
import type { LiveMessage } from './api';

type ContentBlock = { type?: string; text?: string; name?: string; input?: unknown };

function renderContent(content: unknown): string {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content
      .map((block) => {
        const b = block as ContentBlock;
        if (b.type === 'text' || typeof b.text === 'string') return b.text ?? '';
        if (b.type === 'tool_use' && b.name) return `tool_use: ${b.name}`;
        return JSON.stringify(block);
      })
      .filter(Boolean)
      .join('\n');
  }
  if (content == null) return '';
  return JSON.stringify(content);
}

/** Collapsible block showing a reasoning model's chain-of-thought. */
function ThinkingBlock({ text }: { text: string }) {
  const t = useLayoutTokens();
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginTop: 4 }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          fontSize: 10.5,
          fontWeight: 600,
          padding: '2px 8px',
          borderRadius: 999,
          border: 'none',
          cursor: 'pointer',
          color: '#c4b5fd',
          background: 'rgba(168,85,247,0.12)',
        }}
      >
        {open ? '▾' : '▸'} 🧠 Thinking
      </button>
      {open && (
        <pre
          style={{
            margin: '4px 0 0',
            fontSize: 11,
            lineHeight: 1.5,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            fontFamily: 'monospace',
            color: t.textMuted,
            background: t.bgInput,
            borderRadius: 6,
            padding: '6px 8px',
            maxHeight: 260,
            overflowY: 'auto',
          }}
        >
          {text}
        </pre>
      )}
    </div>
  );
}

function MessageRow({ message }: { message: LiveMessage }) {
  const t = useLayoutTokens();
  const type = message.type ?? 'ai';
  const isHuman = type === 'human';
  const isTool = type === 'tool';
  const label = isHuman ? 'You' : isTool ? 'Tool' : 'Assistant';
  const body = renderContent(message.content);
  const toolCalls = message.tool_calls ?? [];
  const reasoning = message.reasoning_content;

  const rowStyle: CSSProperties = {
    border: `1px solid ${t.border}`,
    borderRadius: 6,
    padding: '6px 8px',
    background: isHuman ? t.bgInput : t.bgBase,
    fontSize: 12,
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span
        style={{
          fontSize: 10,
          fontWeight: 600,
          textTransform: 'uppercase',
          letterSpacing: 0.5,
          color: isHuman ? t.accent : isTool ? '#c98a3d' : t.textDim,
        }}
      >
        {label}
      </span>
      <div style={rowStyle}>
        {body ? <div style={{ whiteSpace: 'pre-wrap', color: t.textPrimary }}>{body}</div> : null}
        {reasoning ? <ThinkingBlock text={reasoning} /> : null}
        {toolCalls.length > 0 && (
          <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 3 }}>
            {toolCalls.map((tc, i) => (
              <div
                key={`${tc.id ?? i}`}
                style={{
                  fontSize: 11,
                  fontFamily: 'monospace',
                  color: t.textMuted,
                  background: t.bgInput,
                  borderRadius: 4,
                  padding: '4px 6px',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                ⚙ {tc.name}({JSON.stringify(tc.args ?? {})})
              </div>
            ))}
          </div>
        )}
        {!body && toolCalls.length === 0 && !reasoning && (
          <span style={{ color: t.textDim, fontStyle: 'italic' }}>…</span>
        )}
      </div>
    </div>
  );
}

function StatusChip({ label, tone }: { label: string; tone: string }) {
  const t = useLayoutTokens();
  return (
    <span
      style={{
        fontSize: 10,
        padding: '2px 7px',
        borderRadius: 999,
        border: `1px solid ${tone}`,
        color: tone,
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </span>
  );
}

export default function Inspector() {
  const t = useLayoutTokens();
  const { inspectorTab, threadState, liveMap, runPath, running, runError } = useStudioState();

  const messages = Object.values(liveMap).reverse();
  const interrupts = threadState?.interrupts ?? [];
  const next = threadState?.next ?? [];

  const tabStyle = (active: boolean): CSSProperties => ({
    border: 'none',
    background: active ? t.bgSelected : 'transparent',
    color: active ? t.textPrimary : t.textMuted,
    fontSize: 11.5,
    padding: '4px 10px',
    borderRadius: 5,
    cursor: 'pointer',
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      {/* Header + tabs */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '6px 10px',
          borderBottom: `1px solid ${t.border}`,
        }}
      >
        <span style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, color: t.textDim }}>
          Inspector
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 2 }}>
          {(['messages', 'state', 'raw'] as const).map((tab) => (
            <button key={tab} style={tabStyle(inspectorTab === tab)} onClick={() => studio.setInspectorTab(tab)}>
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* Status chips */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, padding: '6px 10px', borderBottom: `1px solid ${t.border}` }}>
        {running ? (
          <StatusChip label="● running" tone={t.accent} />
        ) : next.length > 0 ? (
          <StatusChip label="⏸ paused" tone="#c98a3d" />
        ) : (
          <StatusChip label="idle" tone={t.textDim} />
        )}
        {interrupts.length > 0 && (
          <StatusChip label={`${interrupts.length} interrupt(s)`} tone="#e5484d" />
        )}
        <StatusChip label={`${messages.length} message(s)`} tone={t.textMuted} />
        {threadState?.checkpoint_id && (
          <StatusChip label={`cp ${String(threadState.checkpoint_id).slice(0, 8)}`} tone={t.textMuted} />
        )}
      </div>

      {/* Body */}
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {inspectorTab === 'messages' && (
          <>
            {messages.length === 0 && !runError && (
              <span style={{ color: t.textDim, fontSize: 12 }}>No messages yet. Run a test below to get started.</span>
            )}
            {runError && (
              <div style={{ fontSize: 12, color: '#e5484d', border: `1px solid #e5484d55`, borderRadius: 6, padding: 6 }}>
                {runError}
              </div>
            )}
            {messages.map((m, i) => (
              <MessageRow key={m.id ?? i} message={m} />
            ))}
          </>
        )}

        {inspectorTab === 'state' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12 }}>
            <Field label="next" value={next} />
            <Field label="run path" value={runPath} />
            <Field label="interrupts" value={interrupts} />
            <Field
              label="metadata"
              value={threadState?.metadata ? { thread_id: threadState.metadata.thread_id } : {}}
            />
            <Field label="checkpoint_id" value={threadState?.checkpoint_id ?? '—'} />
          </div>
        )}

        {inspectorTab === 'raw' && (
          <pre
            style={{
              fontSize: 11,
              lineHeight: 1.5,
              color: t.textMuted,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              fontFamily: 'monospace',
              margin: 0,
            }}
          >
            {JSON.stringify(threadState ?? {}, null, 2)}
          </pre>
        )}
      </div>

      {/* Pauses on an interrupt() and answers it (accept / edit / reject). */}
      <InterruptBar />

      <ChatInput />
    </div>
  );
}

function Field({ label, value }: { label: string; value: unknown }) {
  const t = useLayoutTokens();
  const text = Array.isArray(value)
    ? value.length
      ? value.map((v) => (typeof v === 'object' ? JSON.stringify(v) : String(v))).join(', ')
      : '—'
    : value === null || value === undefined
      ? '—'
      : JSON.stringify(value);
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
      <span style={{ color: t.textDim, fontWeight: 600, minWidth: 80, flexShrink: 0 }}>{label}</span>
      <span style={{ color: t.textPrimary, fontFamily: 'monospace', wordBreak: 'break-word' }}>{text}</span>
    </div>
  );
}
