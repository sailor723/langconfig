/**
 * OntologyChatPanel — the ontology, in the right rail, next to whatever you are working on.
 *
 * Three things, and they are deliberately in one panel because they are one question
 * ("what does this number mean, and is it right?"):
 *
 *  1. **Ask** — a question goes to the workbench's own `/api/nl`, which answers from the
 *     declarations (rules first) or refuses BY NAME. The refusal is rendered as the answer,
 *     not as an error: "no metric declares that count" is the useful output.
 *  2. **Declarations** — every metric with the declaration it compiles from, the compiled SQL,
 *     the number under the guardrails, and the guard's own report. One call fills it
 *     (`/api/metrics/cards`, the same one the browser's card grid uses), so a number can never
 *     disagree with the declaration it belongs to.
 *  3. **Pending publishes** — what an agent staged for this ontology, so a proposal is visible
 *     where the declarations are discussed instead of only in Settings. Applying stays there:
 *     it is a role check + a deliberate confirmation, not a button in a chat rail.
 *
 * It does NOT invent tools of its own: no SQL is typed here, no number is computed here, and
 * the panel never talks to the database. Everything is the workbench's answer or nothing.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, Loader2, Search, Sigma, Sparkles } from 'lucide-react';
import apiClient from '../../lib/api-client';
import { useLayoutTokens } from '../../components/layout2/tokens';
import {
  fetchMetricCards, normalizeUrl, ontology, useOntology, type MetricCard,
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

interface AskResult {
  ok?: boolean;
  answer?: string;
  refused?: string;
  result?: { name?: string; value?: unknown; sql?: string; definition?: Record<string, unknown> };
  intent?: { kind?: string; name?: string };
  needs_confirmation?: boolean;
  understanding?: { text?: string } | null;
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
  const [question, setQuestion] = useState('');
  const [asking, setAsking] = useState(false);
  const [asked, setAsked] = useState<{ q: string; res: AskResult } | null>(null);
  const [askError, setAskError] = useState<string | null>(null);
  const [publishes, setPublishes] = useState<PublishRow[]>([]);
  // The editor agent's conversation. One session per ontology, kept in localStorage so a reload
  // continues the same thread instead of starting a fresh one every time.
  const [editorText, setEditorText] = useState('');
  const [working, setWorking] = useState(false);
  const [turn, setTurn] = useState<{ answer: string; toolCalls: number; error?: string } | null>(null);
  const [diffOpen, setDiffOpen] = useState<string | null>(null);
  const [diffs, setDiffs] = useState<Record<string, DiffResult | null>>({});

  // Make sure a workbench is selected before asking it anything (a bookmark or a reload
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
  const key = s.preset || s.profiles.find(p => p.url === url)?.key || '';

  useEffect(() => {
    if (!url) return;
    let cancelled = false;
    setCards(null);
    setCardsError(null);
    fetchMetricCards(url)
      .then(list => { if (!cancelled) setCards(list); })
      .catch(err => { if (!cancelled) setCardsError(String(err?.message || err)); });
    return () => { cancelled = true; };
  }, [url]);

  const loadPublishes = useCallback(async () => {
    if (!key) { setPublishes([]); return; }
    try {
      const res: any = await apiClient.get('/api/ontology/publish/history',
        { params: { key, status: 'staged', limit: 20 } });
      setPublishes((res?.data?.publishes || []) as PublishRow[]);
    } catch {
      setPublishes([]);
    }
  }, [key]);
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
      setAskError(`diff unavailable: ${err?.response?.data?.detail || err?.message || err}`);
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

  const ask = async () => {
    const q = question.trim();
    if (!q || !url) return;
    setAsking(true); setAskError(null); setAsked(null);
    try {
      const res = await fetch(`${normalizeUrl(url)}/api/nl`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q }),
        signal: AbortSignal.timeout(120000),
      });
      const body = (await res.json()) as AskResult;
      setAsked({ q, res: body });
    } catch (err: any) {
      setAskError(String(err?.message || err));
    } finally {
      setAsking(false);
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

      {/* ask */}
      <div style={{ padding: '10px 12px', borderBottom: `1px solid ${t.border}`, flexShrink: 0 }}>
        <div style={sectionLabel}>Ask this ontology</div>
        <div style={{ display: 'flex', gap: 6 }}>
          <input
            value={question}
            onChange={e => setQuestion(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') void ask(); }}
            placeholder="行程数 · 按门店区域看破损箱数 · 有多少条线路"
            style={{
              flex: 1, minWidth: 0, height: 28, padding: '0 8px', borderRadius: 7, fontSize: 12,
              border: `1px solid ${t.border}`, background: t.bgInput || 'transparent',
              color: t.textPrimary, outline: 'none',
            }}
          />
          <Btn variant="primary" onClick={() => void ask()} disabled={asking || !url}>
            {asking ? <Loader2 size={12} /> : 'Ask'}
          </Btn>
        </div>
        {askError && (
          <div style={{ marginTop: 6, fontSize: 11.5, color: DANGER }}>{askError}</div>
        )}
        {asked && (
          <div style={{
            marginTop: 8, padding: '8px 9px', borderRadius: 8, fontSize: 11.5, lineHeight: 1.65,
            border: `1px solid ${(asked.res.ok ? SUCCESS : WARN)}55`,
            background: `${asked.res.ok ? SUCCESS : WARN}10`,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
              <Sparkles size={11} color={asked.res.ok ? SUCCESS : WARN} />
              <span style={{ ...mono, fontSize: 10.5, color: t.textDim }}>
                {asked.q}
                {asked.res.intent?.name ? ` → ${asked.res.intent.kind} :${asked.res.intent.name}` : ''}
              </span>
            </div>
            <div style={{ whiteSpace: 'pre-wrap' }}>
              {asked.res.ok
                ? (asked.res.answer || asked.res.understanding?.text ||
                   (asked.res.needs_confirmation ? 'resolved — it needs a confirmation to run' : 'answered'))
                : (asked.res.refused || 'refused')}
            </div>
            {!asked.res.ok && (
              <div style={{ marginTop: 4, fontSize: 10.5, color: t.textDim }}>
                A refusal names what is missing. Declare it (Settings → Ontology, or ask the
                Ontology Editor agent) — do not type SQL for it.
              </div>
            )}
          </div>
        )}
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
                  </div>
                )}
              </div>
            );
          })}
          <Link
            to="/settings?section=ontology"
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
            values unavailable — {cardsError}. The workbench must serve{' '}
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
