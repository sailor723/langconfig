/**
 * MetricEditorChat — the metric editor's chat, in the Ontology browser's Metrics tab.
 *
 * Same shape as the Knowledge / Analysis chats (streamed tokens, a tool trace, one continuing
 * session, a stop button), with one difference that matters: the agent behind it is the ontology
 * editor, so a conversation can END IN A CHANGE. Everything it proposes arrives as a staged
 * publish, and the panel shows that proposal with the files it would touch, the gates it ran and
 * the apply button — "set result" is that button, and the metric cards behind this panel refresh
 * with the new numbers the moment it lands.
 *
 * Two deliberate limits:
 *  - the panel never talks to the database and never types SQL. It streams a turn and renders the
 *    proposal the publish channel produced;
 *  - applying is a two-step confirmation (a publish changes what a number MEANS for everyone), and
 *    the backend refuses it without the ontology_editor role — the error is shown, not swallowed.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowUpRight, CheckCheck, Loader2, Send, Square, Wrench, X,
} from 'lucide-react';
import apiClient from '../../lib/api-client';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { streamChatEvents } from '../chat/utils/streamChatEvents';
import { mono, Quiet, SUCCESS, WARN } from './ui';

interface ToolStep { name: string; done: boolean; detail?: string }
interface Turn {
  role: 'user' | 'assistant';
  content: string;
  tools?: ToolStep[];
}
interface Proposal {
  id: string;
  actor: string | null;
  note: string | null;
  created_at: string | null;
  files: string[];
  new_refusals: string[];
  carried_refusals: string[];
  gates_ok: boolean | null;
  gates_fails: string[];
  gates_not_run: string[];
  compile: { metrics?: number; compiled?: number; refused?: unknown[] };
}

interface Props {
  /** The ontology this panel edits (settings profile key). */
  ontologyKey: string;
  /** Called after a publish is applied, so the metric cards can re-read their numbers. */
  onApplied?: () => void;
  onClose?: () => void;
}

export default function MetricEditorChat({ ontologyKey, onApplied, onClose }: Props) {
  const t = useLayoutTokens();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [armed, setArmed] = useState<string | null>(null);
  const [applying, setApplying] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const sessionKey = `langconfig.ontology.editor.${ontologyKey}`;
  const sessionId = (() => {
    try { return localStorage.getItem(sessionKey) || ''; } catch { return ''; }
  })();

  const loadProposals = useCallback(async () => {
    if (!ontologyKey) return;
    try {
      const res: any = await apiClient.get(
        `/api/ontology/${encodeURIComponent(ontologyKey)}/proposals`);
      setProposals((res?.data?.proposals || []) as Proposal[]);
    } catch {
      setProposals([]);
    }
  }, [ontologyKey]);

  // Continue the same conversation across a reload; the history is the server's, not local state.
  useEffect(() => {
    void loadProposals();
    const sid = (() => { try { return localStorage.getItem(sessionKey) || ''; } catch { return ''; } })();
    if (!sid) return;
    void (async () => {
      try {
        const res: any = await apiClient.get(`/api/chat/${sid}/history`);
        const msgs: any[] = res?.data?.messages || [];
        setTurns(msgs
          .filter(m => m.role === 'user' || m.role === 'assistant')
          .slice(-20)
          .map(m => ({
            role: m.role as 'user' | 'assistant',
            // the bound key is part of the stored message; show the sentence, not the preamble
            content: String(m.content || '').replace(/^\[ontology_key=[^\]]+\][^\n]*\n\n/, ''),
          })));
      } catch {
        /* a dead session is not an error: the next send opens a new one */
      }
    })();
  }, [loadProposals, sessionKey]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, proposals]);

  const stop = () => {
    const sid = (() => { try { return localStorage.getItem(sessionKey) || ''; } catch { return ''; } })();
    abortRef.current?.abort();
    if (sid) void apiClient.post(`/api/chat/${sid}/stop`, {}).catch(() => undefined);
    setBusy(false);
  };

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput('');
    setError(null);
    setNotice(null);
    setBusy(true);
    setTurns(prev => [...prev, { role: 'user', content: text },
                             { role: 'assistant', content: '', tools: [] }]);

    const patchLast = (fn: (turn: Turn) => Turn) =>
      setTurns(prev => {
        const next = [...prev];
        const idx = next.length - 1;
        if (idx >= 0) next[idx] = fn(next[idx]);
        return next;
      });

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const body: Record<string, unknown> = { message: text, project_id: 1 };
      const sid = (() => { try { return localStorage.getItem(sessionKey) || ''; } catch { return ''; } })();
      if (sid) body.session_id = sid;

      for await (const ev of streamChatEvents(
        `/api/ontology/${encodeURIComponent(ontologyKey)}/ask-editor/stream`, body, ctrl.signal)) {
        if (ev.type === 'session' && ev.session_id) {
          try { localStorage.setItem(sessionKey, String(ev.session_id)); } catch { /* private mode */ }
        } else if (ev.type === 'chunk') {
          patchLast(turn => ({ ...turn, content: turn.content + String(ev.content || '') }));
        } else if (ev.type === 'tool_start') {
          patchLast(turn => ({ ...turn, tools: [...(turn.tools || []),
            { name: String(ev.tool_name || 'tool'), done: false }] }));
        } else if (ev.type === 'tool_end') {
          patchLast(turn => {
            const tools = [...(turn.tools || [])];
            const i = tools.map(x => x.name).lastIndexOf(String(ev.tool_name || 'tool'));
            if (i >= 0) tools[i] = { ...tools[i], done: true };
            return { ...turn, tools };
          });
        } else if (ev.type === 'complete') {
          patchLast(turn => ({ ...turn, content: String(ev.content || turn.content) }));
        } else if (ev.type === 'stopped') {
          patchLast(turn => ({ ...turn, content: turn.content + '\n\n(stopped)' }));
        } else if (ev.type === 'error') {
          setError(String(ev.message || 'the turn failed'));
        }
      }
      await loadProposals();
    } catch (err: any) {
      if (err?.name === 'AbortError') {
        patchLast(turn => ({ ...turn, content: turn.content + '\n\n(stopped)' }));
      } else {
        setError(String(err?.message || err));
      }
    } finally {
      abortRef.current = null;
      setBusy(false);
    }
  };

  const apply = async (id: string) => {
    setApplying(id);
    setNotice(null);
    try {
      await apiClient.post(`/api/ontology/publish/${id}/apply`, { confirmed: true });
      setNotice({ ok: true, text: `applied ${id} — the cards behind this panel now show the new numbers` });
      setArmed(null);
      await loadProposals();
      onApplied?.();
    } catch (e: any) {
      const status = e?.response?.status;
      const detail = e?.response?.data?.detail || e?.message || 'apply failed';
      setNotice({
        ok: false,
        text: status === 403
          ? `你的帐号没有 ontology_editor 角色，不能 apply：${detail}`
          : `apply failed: ${detail}`,
      });
    } finally {
      setApplying(null);
    }
  };

  const discard = async (id: string) => {
    setNotice(null);
    try {
      await apiClient.post(`/api/ontology/publish/${id}/discard`, {});
      setNotice({ ok: true, text: `discarded ${id} — the installed ontology was never touched` });
      await loadProposals();
    } catch (e: any) {
      setNotice({ ok: false, text: `discard failed: ${e?.response?.data?.detail || e?.message}` });
    }
  };

  return (
    <div style={{
      width: 400, flex: 'none', display: 'flex', flexDirection: 'column', minHeight: 0,
      borderLeft: `1px solid ${t.border}`, background: t.bgSidebar,
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px',
        borderBottom: `1px solid ${t.border}`, flexShrink: 0,
      }}>
        <span style={{ fontSize: 12.5, fontWeight: 600, color: t.textPrimary }}>Metric editor chat</span>
        <span style={{ ...mono, fontSize: 10.5, color: t.textDim }}>{ontologyKey}</span>
        {onClose && (
          <button
            onClick={onClose}
            title="close the editor chat"
            style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: t.textDim }}
          >
            <X size={13} />
          </button>
        )}
      </div>

      {/* conversation */}
      <div ref={scrollRef} style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '10px 12px' }}>
        {turns.length === 0 && (
          <Quiet>
            Ask for a change in your own words — “把 onTimeStops 的说明补清楚”、“加一条必须被拒的样本”.
            The agent opens a copy, edits one declaration, verifies the number and stages a
            proposal; applying it here is what changes the metric.
          </Quiet>
        )}
        {turns.map((turn, i) => (
          <div key={i} style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 10.5, color: t.textDim, marginBottom: 2 }}>
              {turn.role === 'user' ? 'you' : 'editor'}
            </div>
            {turn.content && (
              <div style={{
                fontSize: 12, lineHeight: 1.65, whiteSpace: 'pre-wrap', color: t.textPrimary,
                padding: turn.role === 'user' ? '6px 8px' : '0',
                borderRadius: 7,
                background: turn.role === 'user' ? (t.bgInput || 'rgba(127,127,127,0.08)') : 'transparent',
              }}>
                {turn.content}
              </div>
            )}
            {(turn.tools || []).length > 0 && (
              <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 2 }}>
                {(turn.tools || []).map((tool, j) => (
                  <div key={j} style={{ ...mono, fontSize: 10, color: t.textDim }}>
                    <Wrench size={9} /> {tool.name} {tool.done ? '✓' : '…'}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div style={{ fontSize: 11, color: t.textDim, display: 'flex', alignItems: 'center', gap: 5 }}>
            <Loader2 size={11} /> the editor is working — it opens a copy, edits, verifies, stages
          </div>
        )}
        {error && <div style={{ fontSize: 11.5, color: '#b3261e', whiteSpace: 'pre-wrap' }}>{error}</div>}
      </div>

      {/* proposals: the "set result" half */}
      {proposals.length > 0 && (
        <div style={{
          borderTop: `1px solid ${t.border}`, maxHeight: 260, overflowY: 'auto',
          padding: '8px 12px', flexShrink: 0,
        }}>
          <div style={{ fontSize: 10.5, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, color: t.textDim, marginBottom: 5 }}>
            staged proposals ({proposals.length})
          </div>
          {proposals.map(p => {
            const changed = (p.files || []).length;
            return (
              <div key={p.id} style={{ border: `1px solid ${t.border}`, borderRadius: 8, padding: '7px 8px', marginBottom: 6 }}>
                <div style={{ ...mono, fontSize: 10.5, color: t.textDim }}>{p.id} · {p.actor || 'agent'}</div>
                {p.note && <div style={{ fontSize: 11.5, color: t.textPrimary, lineHeight: 1.5 }}>{p.note}</div>}
                <div style={{ fontSize: 10.5, color: t.textDim, marginTop: 2 }}>
                  {changed} file(s) · {p.compile?.compiled ?? '?'}/{p.compile?.metrics ?? '?'} metrics ·{' '}
                  <span style={{ color: p.gates_ok ? SUCCESS : WARN }}>gates {p.gates_ok ? 'pass' : 'fail'}</span>
                  {p.new_refusals?.length ? ` · NEW refusals: ${p.new_refusals.join(', ')}` : ''}
                </div>
                {p.gates_not_run?.length ? (
                  <div style={{ fontSize: 10, color: t.textDim }}>NOT RUN: {p.gates_not_run.join(' · ')}</div>
                ) : null}
                <div style={{ display: 'flex', gap: 6, marginTop: 5, alignItems: 'center' }}>
                  {armed === p.id ? (
                    <>
                      <button
                        onClick={() => void apply(p.id)}
                        disabled={applying === p.id}
                        style={{
                          fontSize: 11.5, padding: '4px 10px', borderRadius: 6, cursor: 'pointer',
                          border: 'none', background: t.accent, color: '#fff', fontWeight: 600,
                        }}
                      >
                        {applying === p.id ? 'applying…' : 'confirm apply'}
                      </button>
                      <button onClick={() => setArmed(null)} style={{ fontSize: 11, background: 'none', border: 'none', color: t.textDim, cursor: 'pointer' }}>
                        cancel
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => setArmed(p.id)}
                      disabled={!!(p.new_refusals?.length || p.gates_fails?.length)}
                      style={{
                        fontSize: 11.5, padding: '4px 10px', borderRadius: 6, cursor: 'pointer',
                        border: `1px solid ${t.border}`, background: 'transparent', color: t.textPrimary,
                      }}
                    >
                      <CheckCheck size={11} /> apply…
                    </button>
                  )}
                  <button onClick={() => void discard(p.id)} style={{ fontSize: 11, background: 'none', border: 'none', color: t.textDim, cursor: 'pointer' }}>
                    discard
                  </button>
                  <a
                    href="/settings?section=ontology"
                    style={{ fontSize: 10.5, color: t.textDim, marginLeft: 'auto', display: 'inline-flex', gap: 2, alignItems: 'center' }}
                  >
                    diff <ArrowUpRight size={10} />
                  </a>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {notice && (
        <div style={{
          padding: '6px 12px', fontSize: 11.5, lineHeight: 1.5, flexShrink: 0,
          color: notice.ok ? SUCCESS : '#b3261e',
        }}>{notice.text}</div>
      )}

      {/* composer */}
      <div style={{ padding: '8px 12px 10px', borderTop: `1px solid ${t.border}`, flexShrink: 0 }}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'flex-end' }}>
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(); }
            }}
            rows={2}
            placeholder="把 onTimeStops 的说明补清楚（Enter 发送，Shift+Enter 换行）"
            style={{
              flex: 1, minWidth: 0, resize: 'vertical', padding: '6px 8px', borderRadius: 7,
              fontSize: 12, lineHeight: 1.5, fontFamily: 'inherit',
              border: `1px solid ${t.border}`, background: t.bgInput || 'transparent',
              color: t.textPrimary, outline: 'none',
            }}
          />
          {busy ? (
            <button
              onClick={stop}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12,
                padding: '7px 10px', borderRadius: 7, cursor: 'pointer',
                border: `1px solid ${t.border}`, background: 'transparent', color: t.textPrimary,
              }}
            >
              <Square size={11} /> stop
            </button>
          ) : (
            <button
              onClick={() => void send()}
              disabled={!input.trim()}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12,
                padding: '7px 12px', borderRadius: 7, cursor: input.trim() ? 'pointer' : 'default',
                border: 'none', background: t.accent, color: '#fff', opacity: input.trim() ? 1 : 0.45,
              }}
            >
              <Send size={11} /> send
            </button>
          )}
        </div>
        <div style={{ fontSize: 10, color: t.textDim, marginTop: 4 }}>
          the agent can only stage; applying is yours and changes what the number means
        </div>
      </div>
    </div>
  );
}
