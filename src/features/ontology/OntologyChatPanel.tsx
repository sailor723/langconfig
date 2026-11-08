/**
 * OntologyChatPanel — the ontology, in the right rail, next to whatever you are working on.
 *
 * Three things, and they are deliberately in one panel because they are one question
 * ("what does this number mean, and is it right?"):
 *
 *  1. **Ask** — a question goes to the ontology's own NL lane (`/api/ontology/{key}/wb/nl`), which answers from the
 *     declarations (rules first) or refuses BY NAME. The refusal is rendered as the answer,
 *     not as an error: "no metric declares that count" is the useful output.
 *  2. **Declarations** — every metric with the declaration it compiles from, the compiled SQL,
 *     the number under the guardrails, and the guard's own report. One call fills it
 *     (`/api/ontology/{key}/metrics/cards`, the same one the browser's card grid uses), so a number can never
 *     disagree with the declaration it belongs to.
 *  3. **Pending publishes** — what an agent staged for this ontology, so a proposal is visible
 *     where the declarations are discussed instead of only in Settings. Applying stays there:
 *     it is a role check + a deliberate confirmation, not a button in a chat rail.
 *
 * It does NOT invent tools of its own: no SQL is typed here, no number is computed here, and
 * the panel never talks to the database. Everything is the ontology's answer or nothing.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, Loader2, Search, Sigma, Sparkles } from 'lucide-react';
import apiClient from '../../lib/api-client';
import { useLayoutTokens } from '../../components/layout2/tokens';
import {
  fetchMetricCards, ontology, useOntology, type MetricCard,
} from './ontologyStore';
import { Btn, DANGER, INFO, mono, Quiet, SUCCESS, WARN } from './ui';

interface PublishRow {
  id: string;
  key: string;
  actor: string | null;
  status: string;
  note: string | null;
  report: any;
  created_at: string | null;
}

interface DiffFile {
  path: string;
  status: 'added' | 'changed' | 'unchanged' | 'binary';
  added?: number;
  removed?: number;
  diff: string;
}
interface DiffResult {
  ok: boolean;
  staged_id: string;
  key: string;
  files: DiffFile[];
  changed: string[];
  not_in_staging?: string[];
  error?: string;
}

interface ValueChange {
  metric: string;
  before: unknown;
  after: unknown;
  before_state?: string | null;
  after_state?: string | null;
}
interface ValueDelta {
  ok: boolean;
  metrics?: number;
  changed?: ValueChange[];
  unchanged?: number;
  error?: string;
}


const declBits = (c: MetricCard): string =>
  [
    c.aggregate && `:aggregate ${c.aggregate}`,
    c.formula && `:formula "${c.formula}"`,
    c.grain && `:grain :${c.grain}`,
    c.universe && c.universe !== c.grain && `:universe :${c.universe}`,
    c.where && `:where :${c.where}`,
    c.groupBy?.length ? `:groupBy ${c.groupBy.join(', ')}` : '',
    c.numerator && `:numerator :${c.numerator}`,
    c.denominator && `:denominator :${c.denominator}`,
    c.scale && `:scale ${c.scale}`,
  ].filter(Boolean).join(' · ');

export default function OntologyChatPanel() {
  const t = useLayoutTokens();
  const s = useOntology();
  const [cards, setCards] = useState<MetricCard[] | null>(null);
  const [cardsError, setCardsError] = useState<string | null>(null);
  const [needle, setNeedle] = useState('');
  const [open, setOpen] = useState<string | null>(null);
  const [publishes, setPublishes] = useState<PublishRow[]>([]);
  // The editor agent's conversation. One session per ontology, kept in localStorage so a reload
  // continues the same thread instead of starting a fresh one every time.
  const [editorText, setEditorText] = useState('');
  const [working, setWorking] = useState(false);
  const [turn, setTurn] = useState<{ answer: string; toolCalls: number; error?: string } | null>(null);
  const [diffOpen, setDiffOpen] = useState<string | null>(null);
  const [diffs, setDiffs] = useState<Record<string, DiffResult | null>>({});
  const [valuesOpen, setValuesOpen] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, ValueDelta | null>>({});

  // Make sure an ontology is selected before asking it anything (a bookmark or a reload
  // arrives with no selection, and asking '' is a 404 against the frontend's own origin).
  useEffect(() => {
    void (async () => {
      await ontology.ensureReady();
      if (!ontology.get().ontology && ontology.get().status !== 'loading') {
        const url = ontology.get().url;
        if (url) await ontology.select(url, ontology.get().preset ?? undefined);
      }
    })();
  }, []);

  const url = s.url;
  // the key is the identity (all urls are '' for same-origin ontologies)
  const key = s.preset || '';

  // the cards come from the app now (one origin, keyed by the ontology) — the URL is only how the
  // profile was chosen, never where its numbers are fetched from
  useEffect(() => {
    if (!key) return;
    let cancelled = false;
    setCards(null);
    setCardsError(null);
    fetchMetricCards(key)
      .then(list => { if (!cancelled) setCards(list); })
      .catch(err => { if (!cancelled) setCardsError(String(err?.message || err)); });
    return () => { cancelled = true; };
  }, [key]);

  const loadPublishes = useCallback(async () => {
    // NOT filtered by the open key. Measured: this rail asked for `key=new_coldchain`, but that
    // ontology had no installed profile, so the panel that lists what you can open never offered
    // it — and its staged publish was invisible everywhere except one settings section. Every
    // staged publish is listed, with its key, so "an agent staged something for an ontology you
    // have not opened yet" cannot hide.
    try {
      const res: any = await apiClient.get('/api/ontology/publish/history',
        { params: { status: 'staged', limit: 20 } });
      setPublishes((res?.data?.publishes || []) as PublishRow[]);
    } catch {
      setPublishes([]);
    }
  }, []);
  useEffect(() => { void loadPublishes(); }, [loadPublishes]);

  /** Fetch the diff for one staged publish, once, and keep it — a diff is a fact, not a poll. */
  const openDiff = async (id: string) => {
    setDiffOpen(prev => (prev === id ? null : id));
    if (diffs[id] !== undefined) return;
    try {
      const res: any = await apiClient.get(`/api/ontology/publish/${id}/diff`);
      setDiffs(prev => ({ ...prev, [id]: (res?.data || null) as DiffResult }));
    } catch (err: any) {
      setDiffs(prev => ({ ...prev, [id]: null }));
      setCardsError(`diff unavailable: ${err?.response?.data?.detail || err?.message || err}`);
    }
  };

  const sessionKey = `langconfig.ontology.editor.${key}`;
  const editorSessionId = (() => {
    try { return localStorage.getItem(sessionKey) || ''; } catch { return ''; }
  })();

  /** One editor turn. The backend binds the ontology key, runs the agent, and returns both the
   *  answer and the proposals it staged — so the panel never has to guess what changed. */
  const runEditor = async () => {
    const text = editorText.trim();
    if (!text || !key) return;
    setWorking(true);
    setTurn(null);
    try {
      const res: any = await apiClient.post(`/api/ontology/${encodeURIComponent(key)}/ask-editor`, {
        message: text,
        session_id: editorSessionId || undefined,
        project_id: 1,
      }, { timeout: 600000 });
      const d = res?.data || {};
      if (d.session_id) {
        try { localStorage.setItem(sessionKey, d.session_id); } catch { /* private mode */ }
      }
      setTurn({
        answer: String(d.answer || ''),
        toolCalls: (d.tool_calls || []).length,
      });
      setEditorText('');
      await loadPublishes();
    } catch (err: any) {
      setTurn({ answer: '', toolCalls: 0, error: err?.response?.data?.detail || String(err?.message || err) });
    } finally {
      setWorking(false);
    }
  };

  /** Run both ontologies and show which NUMBERS move. The reviewer's actual question. */
  const openValues = async (id: string) => {
    setValuesOpen(prev => (prev === id ? null : id));
    if (values[id] !== undefined) return;
    try {
      const res: any = await apiClient.get(`/api/ontology/publish/${id}/values`, { timeout: 300000 });
      setValues(prev => ({ ...prev, [id]: (res?.data || null) as ValueDelta }));
    } catch (err: any) {
      setValues(prev => ({ ...prev, [id]: {
        ok: false, error: err?.response?.data?.detail || String(err?.message || err) } }));
    }
  };

  const needleLc = needle.trim().toLowerCase();
  const rows = useMemo(() => {
    const list = cards || [];
    if (!needleLc) return list;
    return list.filter(c =>
      c.name.toLowerCase().includes(needleLc) || (c.label || '').toLowerCase().includes(needleLc));
  }, [cards, needleLc]);

  const refused = rows.filter(c => c.error);
  const answered = rows.filter(c => !c.error);

  const sectionLabel: React.CSSProperties = {
    fontSize: 10.5, fontWeight: 600, letterSpacing: 0.6, textTransform: 'uppercase',
    color: t.textDim, margin: '0 0 6px',
  };

  return (
    <div style={{
      flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column',
      background: t.bgSidebar, color: t.textPrimary,
    }}>
      {/* header */}
      <div style={{ padding: '10px 12px 8px', borderBottom: `1px solid ${t.border}`, flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Sigma size={13} color={t.accent} />
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>
            {s.ontology?.title || (key ? key : 'Ontology')}
          </span>
          <span style={{ ...mono, fontSize: 10.5, color: t.textDim }}>
            {s.ontology?.counts
              ? `${s.ontology.counts.metrics} metrics · ${s.ontology.counts.compiled} compiled · ${s.ontology.counts.refused} refused`
              : ''}
          </span>
        </div>
        {s.profiles.length > 1 && (
          <select
            value={key}
            onChange={e => {
              const p = s.profiles.find(x => x.key === e.target.value);
              if (p) void ontology.select(p.url, p.key);
            }}
            style={{
              marginTop: 6, width: '100%', height: 26, borderRadius: 7, fontSize: 11.5,
              border: `1px solid ${t.border}`, background: t.bgInput || t.bgSidebar,
              color: t.textPrimary, outline: 'none',
            }}
          >
            {s.profiles.map(p => (
              <option key={p.key} value={p.key}>{p.label || p.key}</option>
            ))}
          </select>
        )}
      </div>

      {/* ask MOVED: business questions are answered beside the business numbers.
          Two chat boxes answering the same question in two places is how a panel starts disagreeing
          with the dashboard — so this rail keeps the DECLARATIONS and the pending publishes, and
          points at the one place a question is asked. */}
      <div style={{ padding: '10px 12px', borderBottom: `1px solid ${t.border}`, flexShrink: 0 }}>
        <div style={sectionLabel}>Ask this ontology</div>
        <Link
          to="/ontology/dashboard"
          style={{
            display: 'flex', alignItems: 'center', gap: 6, padding: '7px 9px', borderRadius: 8,
            border: `1px solid ${t.border}`, color: t.textPrimary, textDecoration: 'none',
            fontSize: 11.5, lineHeight: 1.5,
          }}
        >
          <Sparkles size={12} color={t.accent} />
          <span>业务问答已移到看板</span>
          <ArrowUpRight size={12} style={{ marginLeft: 'auto', color: t.textDim }} />
        </Link>
        <div style={{ marginTop: 5, fontSize: 10.5, color: t.textDim, lineHeight: 1.5 }}>
          看板把问题、数字和编译出的 SQL 放在一起；这一栏保留声明与待发布提案。
        </div>
      </div>

      {/* the editor agent */}
      <div style={{ padding: '10px 12px', borderBottom: `1px solid ${t.border}`, flexShrink: 0 }}>
        <div style={sectionLabel}>Ask the Editor agent</div>
        <textarea
          value={editorText}
          onChange={e => setEditorText(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void runEditor(); }
          }}
          placeholder="把 onTimeStops 的说明符补清楚 · 教程第 7 步解释一下每条拒绝 · 加一条必须被拒的样本"
          rows={2}
          style={{
            width: '100%', boxSizing: 'border-box', padding: '6px 8px', borderRadius: 7, fontSize: 11.5,
            border: `1px solid ${t.border}`, background: t.bgInput || 'transparent', color: t.textPrimary,
            outline: 'none', resize: 'vertical', fontFamily: 'inherit', lineHeight: 1.5,
          }}
        />
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6 }}>
          <Btn variant="primary" onClick={() => void runEditor()} disabled={working || !editorText.trim() || !key}>
            {working ? <Loader2 size={12} /> : 'Send to editor'}
          </Btn>
          <span style={{ fontSize: 10.5, color: t.textDim }}>
            {working ? 'the agent is working — it opens a copy, edits, verifies, stages'
                     : '⌘/Ctrl+Enter · it can only stage; applying is yours'}
          </span>
        </div>
        {turn?.error && (
          <div style={{ marginTop: 6, fontSize: 11.5, color: DANGER, whiteSpace: 'pre-wrap' }}>{turn.error}</div>
        )}
        {turn && !turn.error && (
          <div style={{
            marginTop: 8, padding: '8px 9px', borderRadius: 8, fontSize: 11.5, lineHeight: 1.65,
            border: `1px solid ${t.border}`, background: t.bgInput || 'rgba(127,127,127,0.06)',
            maxHeight: 260, overflowY: 'auto', whiteSpace: 'pre-wrap',
          }}>
            {turn.answer || '(the agent returned no text)'}
            <div style={{ marginTop: 4, fontSize: 10.5, color: t.textDim }}>
              {turn.toolCalls} tool call(s) · read the proposals below before believing any of it
            </div>
          </div>
        )}
      </div>

      {/* pending publishes */}
      {publishes.length > 0 && (
        <div style={{ padding: '10px 12px', borderBottom: `1px solid ${t.border}`, flexShrink: 0 }}>
          <div style={sectionLabel}>Pending publishes ({publishes.length})</div>
          {publishes.slice(0, 3).map(p => {
            const d = diffs[p.id];
            const isOpen = diffOpen === p.id;
            return (
              <div key={p.id} style={{ fontSize: 11.5, lineHeight: 1.6, color: t.textPrimary }}>
                <div
                  onClick={() => void openDiff(p.id)}
                  style={{ cursor: 'pointer', display: 'flex', alignItems: 'baseline', gap: 5 }}
                >
                  <span style={{ ...mono, fontSize: 10.5, color: t.textDim }}>{p.id}</span>
                  <span style={{ fontSize: 10.5, color: t.textPrimary }}>{p.key}</span>
                  <span style={{ fontSize: 10.5, color: t.textDim }}>{p.actor || 'agent'}</span>
                  <span style={{ marginLeft: 'auto', fontSize: 10.5, color: t.textDim }}>
                    {isOpen ? '▾' : '▸'} diff
                  </span>
                </div>
                {p.note ? <div style={{ color: t.textDim }}>{p.note}</div> : null}
                {isOpen && (
                  <div style={{ marginTop: 4 }}>
                    {d === undefined && <Quiet>reading the diff…</Quiet>}
                    {d === null && <Quiet>this publish has no staging tree left to diff.</Quiet>}
                    {d && d.ok && (
                      <>
                        {(d.changed || []).length === 0 && (
                          <Quiet>no file differs from the installed ontology — there is nothing to install.</Quiet>
                        )}
                        {(d.files || []).filter(f => f.status === 'added' || f.status === 'changed').map(f => (
                          <div key={f.path} style={{ marginTop: 4 }}>
                            <div style={{ ...mono, fontSize: 10.5, color: t.textPrimary }}>
                              {f.path}{' '}
                              <span style={{ color: SUCCESS }}>+{f.added || 0}</span>{' '}
                              <span style={{ color: DANGER }}>−{f.removed || 0}</span>
                              <span style={{ color: t.textDim }}> {f.status}</span>
                            </div>
                            <pre style={{
                              margin: '2px 0 0', padding: '5px 6px', borderRadius: 5, fontSize: 9.5,
                              fontFamily: 'ui-monospace, Menlo, monospace', lineHeight: 1.5,
                              background: t.bgInput || 'rgba(127,127,127,0.08)', color: t.textPrimary,
                              maxHeight: 180, overflow: 'auto', whiteSpace: 'pre',
                            }}>{f.diff.trim()}</pre>
                          </div>
                        ))}
                      </>
                    )}
                    <span
                      onClick={e => { e.stopPropagation(); void openValues(p.id); }}
                      style={{ display: 'inline-block', marginTop: 6, fontSize: 10.5, color: t.textDim, cursor: 'pointer' }}
                    >
                      {valuesOpen === p.id ? '▾' : '▸'} which numbers move
                    </span>
                    {valuesOpen === p.id && (() => {
                      const v = values[p.id];
                      if (v === undefined) return <Quiet>running both ontologies…</Quiet>;
                      if (!v || !v.ok) return <Quiet>{v?.error || 'no comparison'}</Quiet>;
                      const changed = v.changed || [];
                      if (!changed.length) {
                        return <Quiet>no number moves ({v.unchanged || 0} metric(s) checked) — this publish changes declarations or text only.</Quiet>;
                      }
                      return (
                        <div style={{ marginTop: 4 }}>
                          {changed.map(c => (
                            <div key={c.metric} style={{ ...mono, fontSize: 10.5, lineHeight: 1.7 }}>
                              <span style={{ color: WARN }}>{c.metric}</span>{' '}
                              <span style={{ color: t.textDim }}>{String(c.before ?? c.before_state ?? '—')}</span>
                              {' → '}
                              <span style={{ color: t.textPrimary }}>{String(c.after ?? c.after_state ?? '—')}</span>
                            </div>
                          ))}
                          <div style={{ fontSize: 10, color: t.textDim, marginTop: 2 }}>
                            {changed.length} of {v.metrics} metric(s) move · the rest agree
                          </div>
                        </div>
                      );
                    })()}
                  </div>
                )}
              </div>
            );
          })}
          <Link
            to="/settings?section=apply"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 3, marginTop: 4, fontSize: 11.5, color: INFO }}
          >
            review and apply in Settings → Ontology <ArrowUpRight size={11} />
          </Link>
        </div>
      )}

      {/* declarations */}
      <div style={{ padding: '10px 12px 4px', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Search size={12} color={t.textDim} />
          <input
            value={needle}
            onChange={e => setNeedle(e.target.value)}
            placeholder="filter metrics"
            style={{
              flex: 1, minWidth: 0, height: 24, padding: '0 6px', borderRadius: 6, fontSize: 11.5,
              border: `1px solid ${t.border}`, background: 'transparent', color: t.textPrimary, outline: 'none',
            }}
          />
          <span style={{ ...mono, fontSize: 10.5, color: t.textDim }}>
            {cards ? `${answered.length}/${rows.length}` : '…'}
          </span>
        </div>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '4px 12px 20px' }}>
        {cardsError && (
          <Quiet>
            values unavailable — {cardsError}. The app must compile{' '}
            <code style={mono}>/api/metrics/cards</code> (restart it and reload).
          </Quiet>
        )}
        {!cards && !cardsError && <Quiet>reading the declarations…</Quiet>}

        {answered.map(c => {
          const isOpen = open === c.name;
          return (
            <div key={c.name} style={{ borderBottom: `1px solid ${t.border}55`, padding: '6px 0' }}>
              <div
                onClick={() => setOpen(isOpen ? null : c.name)}
                style={{ display: 'flex', alignItems: 'baseline', gap: 6, cursor: 'pointer' }}
              >
                <span style={{ ...mono, fontSize: 11.5, color: t.accent }}>{c.name}</span>
                {c.label && <span style={{ fontSize: 11.5, color: t.textPrimary }}>{c.label}</span>}
                <span style={{ marginLeft: 'auto', ...mono, fontSize: 11.5, color: t.textPrimary }}>
                  {c.value === null || c.value === undefined ? '—' : String(c.value)}
                </span>
              </div>
              {isOpen && (
                <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 5 }}>
                  {declBits(c) && (
                    <div style={{ ...mono, fontSize: 10.5, lineHeight: 1.7, color: t.textDim }}>
                      {declBits(c)}
                    </div>
                  )}
                  {c.sql && (
                    <pre style={{
                      margin: 0, padding: '6px 7px', borderRadius: 6, fontSize: 10,
                      fontFamily: 'ui-monospace, Menlo, monospace', lineHeight: 1.55,
                      background: t.bgInput || 'rgba(127,127,127,0.08)', color: t.textPrimary,
                      whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                    }}>{c.sql}</pre>
                  )}
                  <div style={{ fontSize: 10.5, color: t.textDim, lineHeight: 1.6 }}>
                    {c.plan_rows !== undefined && `plan ≈ ${Number(c.plan_rows).toLocaleString()} rows · `}
                    {c.ms !== undefined && `${c.ms} ms`}
                    {c.guard_notes?.length ? (
                      <div style={{ marginTop: 2 }}>{c.guard_notes.join(' · ')}</div>
                    ) : null}
                  </div>
                </div>
              )}
            </div>
          );
        })}

        {refused.length > 0 && (
          <div style={{ marginTop: 10 }}>
            <div style={sectionLabel}>Refused by name ({refused.length})</div>
            {refused.map(c => (
              <div key={c.name} style={{ padding: '5px 0', borderBottom: `1px solid ${t.border}55` }}>
                <span style={{ ...mono, fontSize: 11.5, color: WARN }}>{c.name}</span>
                {c.label && <span style={{ fontSize: 11.5, color: t.textDim }}> {c.label}</span>}
                <div style={{ fontSize: 10.5, lineHeight: 1.6, color: t.textDim, marginTop: 2 }}>
                  {c.error}
                </div>
              </div>
            ))}
            <div style={{ fontSize: 10.5, color: t.textDim, lineHeight: 1.6, marginTop: 6 }}>
              These are the declarations the business has not made yet. They are the backlog,
              not a bug — and the panel refuses rather than guessing a number.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
