/**
 * Human-in-the-loop approval bar for the Graph activity.
 *
 * Shown when the active thread is paused on an `interrupt()` — e.g. the HITL
 * SQL/Neo4j agents stop before running a model-generated query. The reviewer can
 *
 *   Approve      → { type: 'accept' }
 *   Edit & run   → { type: 'edit', args: { args: { query: <edited> } } }
 *   Reject       → { type: 'response', args: <feedback> }
 *
 * which the store forwards as LangGraph's `Command(resume=...)`.
 *
 * Interrupt payload shape (one entry per pending interrupt):
 *   { value: [{ action, args: { query|cypher, ... }, description }] }
 */
import { useEffect, useMemo, useState } from 'react';
import { ShieldAlert, Check, PencilLine, MessageSquareWarning } from 'lucide-react';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { studio, useStudioState } from './studioStore';

type ReviewRequest = {
  action?: string;
  description?: string;
  args?: Record<string, unknown>;
};

/** Normalise the interrupt payloads into a flat list of review requests. */
function extractRequests(interrupts: unknown[]): ReviewRequest[] {
  const out: ReviewRequest[] = [];
  for (const raw of interrupts) {
    const value = (raw as { value?: unknown })?.value ?? raw;
    const items = Array.isArray(value) ? value : [value];
    for (const item of items) {
      if (item && typeof item === 'object') out.push(item as ReviewRequest);
    }
  }
  return out;
}

/** The query text a reviewer would want to edit (.query for SQL, .cypher for Neo4j). */
function queryOf(req: ReviewRequest | undefined): string {
  const args = req?.args ?? {};
  const value = args.query ?? args.cypher;
  return typeof value === 'string' ? value : '';
}

/** Which arg key to write back when the reviewer edits the statement. */
function queryKey(req: ReviewRequest | undefined): string {
  return req?.args && 'cypher' in req.args ? 'cypher' : 'query';
}

export default function InterruptBar() {
  const t = useLayoutTokens();
  const { threadState, running } = useStudioState();
  const interrupts = (threadState?.interrupts ?? []) as unknown[];
  const requests = useMemo(() => extractRequests(interrupts), [interrupts]);

  const primary = requests[0];
  const key = queryKey(primary);
  const [edited, setEdited] = useState(() => queryOf(primary));
  const [feedback, setFeedback] = useState('');
  const [mode, setMode] = useState<'idle' | 'edit' | 'reject'>('idle');

  // A new interrupt (different query) resets the editor to its proposal.
  useEffect(() => {
    setEdited(queryOf(primary));
    setMode('idle');
    setFeedback('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryOf(primary)]);

  if (!interrupts.length || !primary) return null;

  const busy = running;
  const btn = (bg: string, fg: string): React.CSSProperties => ({
    display: 'inline-flex',
    alignItems: 'center',
    gap: 5,
    border: 'none',
    borderRadius: 6,
    padding: '5px 10px',
    fontSize: 11.5,
    fontWeight: 600,
    cursor: busy ? 'not-allowed' : 'pointer',
    background: busy ? t.bgInput : bg,
    color: busy ? t.textDim : fg,
  });

  return (
    <div
      style={{
        border: '1px solid #e5484d',
        borderRadius: 8,
        background: t.bgBase,
        padding: 10,
        margin: '8px 0',
        fontFamily: 'inherit',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <ShieldAlert size={13} color="#e5484d" />
        <span style={{ fontSize: 11.5, fontWeight: 700, color: t.textPrimary }}>
          Human review required
        </span>
        <span style={{ fontSize: 11, color: t.textMuted }}>
          {primary.action ? `· ${primary.action}` : ''}
          {requests.length > 1 ? ` · ${requests.length} pending` : ''}
        </span>
      </div>

      <div
        style={{
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
          fontSize: 11,
          lineHeight: 1.5,
          color: t.textPrimary,
          background: t.bgInput,
          border: `1px solid ${t.border}`,
          borderRadius: 6,
          padding: 8,
          maxHeight: 180,
          overflow: 'auto',
          whiteSpace: 'pre-wrap',
        }}
      >
        {mode === 'edit' ? (
          <textarea
            value={edited}
            onChange={(e) => setEdited(e.target.value)}
            spellCheck={false}
            rows={Math.min(12, Math.max(3, edited.split('\n').length))}
            style={{
              width: '100%',
              border: 'none',
              outline: 'none',
              resize: 'vertical',
              background: 'transparent',
              color: t.textPrimary,
              font: 'inherit',
            }}
          />
        ) : (
          queryOf(primary) || primary.description || JSON.stringify(primary)
        )}
      </div>

      {mode === 'reject' && (
        <input
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          placeholder="Why should it not run? (sent back to the model)"
          style={{
            width: '100%',
            marginTop: 6,
            padding: '5px 8px',
            fontSize: 11.5,
            borderRadius: 6,
            border: `1px solid ${t.border}`,
            background: t.bgInput,
            color: t.textPrimary,
            outline: 'none',
          }}
        />
      )}

      <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
        <button
          style={btn('#2ea043', '#ffffff')}
          disabled={busy}
          onClick={() => void studio.resume({ type: 'accept' })}
        >
          <Check size={12} /> Approve &amp; run
        </button>

        {mode === 'edit' ? (
          <button
            style={btn(t.accent, '#ffffff')}
            disabled={busy || !edited.trim()}
            onClick={() =>
              void studio.resume({
                type: 'edit',
                args: { args: { [key]: edited.trim() } },
              })
            }
          >
            <Check size={12} /> Run edited
          </button>
        ) : (
          <button style={btn(t.bgSelected, t.textPrimary)} disabled={busy} onClick={() => setMode('edit')}>
            <PencilLine size={12} /> Edit
          </button>
        )}

        {mode === 'reject' ? (
          <button
            style={btn('#c98a3d', '#ffffff')}
            disabled={busy || !feedback.trim()}
            onClick={() =>
              void studio.resume({ type: 'response', args: feedback.trim() })
            }
          >
            <MessageSquareWarning size={12} /> Send feedback
          </button>
        ) : (
          <button
            style={btn(t.bgSelected, t.textPrimary)}
            disabled={busy}
            onClick={() => setMode('reject')}
          >
            <MessageSquareWarning size={12} /> Reject
          </button>
        )}

        {mode !== 'idle' && (
          <button style={btn('transparent', t.textMuted)} disabled={busy} onClick={() => setMode('idle')}>
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}
