/**
 * OntologyBrowserPage — read what the loaded profile declares.
 *
 * The workbench answers questions; this page answers "what is in there": objects and their
 * physical tables, the definitions (axioms) that decide membership, the declared links, and
 * every metric with its compiled SQL *or* its refusal. Nothing is fetched per row — the
 * document is one `/api/ontology` call, so the lists cannot disagree with each other.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ListTree, Table2, Link2, Sigma, AlertTriangle, Play, RefreshCw, Copy, Check, Boxes, Search,
  Sparkles,
} from 'lucide-react';
import { useLayoutTokens } from '../components/layout2/tokens';
import { Card, Chip, Btn, mono, SUCCESS, DANGER, WARN } from '../features/ontology/ui';
import { ontology, useOntology, fetchMetricCards, type MetricCard } from '../features/ontology/ontologyStore';
import MetricEditorChat from '../features/ontology/MetricEditorChat';
import MetricEditorPanel from '../features/ontology/MetricEditorPanel';
import BuildOntologyDialog from '../features/ontology/BuildOntologyDialog';

type Tab = 'objects' | 'definitions' | 'links' | 'metrics';

const TAB_META: Array<{ id: Tab; label: string; icon: typeof Table2 }> = [
  { id: 'objects', label: 'Objects', icon: Table2 },
  { id: 'definitions', label: 'Definitions', icon: ListTree },
  { id: 'links', label: 'Links', icon: Link2 },
  { id: 'metrics', label: 'Metrics', icon: Sigma },
];

export default function OntologyBrowserPage() {
  const t = useLayoutTokens();
  const navigate = useNavigate();
  const s = useOntology();
  const [tab, setTab] = useState<Tab>('metrics');
  const [selected, setSelected] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const [copied, setCopied] = useState(false);
  // Metrics are shown as CARDS (the workbench's own layout): declaration, compiled SQL, the
  // number the database returns and the guard's report, all on one card. One request fills
  // the whole grid, because a card without its number is half a card.
  const [cards, setCards] = useState<MetricCard[] | null>(null);
  const [cardsError, setCardsError] = useState<string | null>(null);
  // The metric editor's chat is docked on the right of the Metrics tab. Applying a proposal
  // changes what the numbers ARE, so the grid behind it has to re-read them.
  const [editorOpen, setEditorOpen] = useState(true);
  // Generation is step one and it runs as a job — the entry point lives here because this is the
  // page where a person reads what an ontology declares and decides it is missing something.
  const [buildOpen, setBuildOpen] = useState(false);
  // Which metric the editor panel is showing. Clicking a card selects it; the panel is the
  // standardized surface for that one metric (business fields + declaration + value).
  const [metricName, setMetricName] = useState<string | null>(null);
  const refreshCards = useCallback(() => {
    setCards(null);
    setCardsError(null);
  }, []);

  useEffect(() => {
    void (async () => {
      await ontology.ensureReady();
      if (!ontology.get().ontology && ontology.get().status !== 'loading') {
        const url = ontology.get().url;
        if (url) await ontology.select(url, ontology.get().preset ?? undefined);
      }
    })();
  }, []);

  useEffect(() => {
    if (tab !== 'metrics' || cards || !s.url) return;
    let cancelled = false;
    setCardsError(null);
    fetchMetricCards(s.url)
      .then(list => { if (!cancelled) setCards(list); })
      .catch(err => { if (!cancelled) setCardsError(String(err?.message || err)); });
    return () => { cancelled = true; };
  }, [tab, cards, s.url]);

  const doc = s.ontology;
  const needle = q.trim().toLowerCase();

  const rows = useMemo(() => {
    if (!doc) return [];
    const keep = (name?: string | null, extra?: string | null) =>
      !needle || (name || '').toLowerCase().includes(needle) || (extra || '').toLowerCase().includes(needle);
    if (tab === 'objects') return (doc.objects || []).filter(o => keep(o.name, o.label));
    if (tab === 'definitions') return (doc.definitions || []).filter(o => keep(o.name, o.label));
    if (tab === 'links') return (doc.links || []).filter(l => keep(l.name, l.label));
    return (doc.metrics || []).filter(m => keep(m.name, m.label));
  }, [doc, tab, needle]);

  // The tab decides which shape `current` has; the row types are not structurally
  // compatible, so the page narrows through one cast rather than three copies of the list.
  const current = useMemo<any>(() => {
    if (!rows.length) return null;
    return rows.find((r: any) => r.name === selected) ?? rows[0];
  }, [rows, selected]);

  // Labels and headings follow the same scale as the other activity pages (13–15px),
  // not the 10px caps this page started with.
  const chip: React.CSSProperties = {
    display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11.5,
    padding: '2px 9px', borderRadius: 999, border: `1px solid ${t.border}`, color: t.textMuted,
  };
  const btn = (primary = false): React.CSSProperties => ({
    display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: primary ? 600 : 500,
    padding: '6px 12px', borderRadius: 8, cursor: 'pointer',
    border: primary ? 'none' : `1px solid ${t.border}`, background: primary ? t.accent : 'transparent',
    color: primary ? '#fff' : t.textPrimary,
  });

  if (s.status === 'loading' && !doc) {
    return <div style={{ padding: 26, color: t.textMuted, fontSize: 12.5 }}>loading {s.url} …</div>;
  }
  if (!doc) {
    return (
      <div style={{ padding: 26, maxWidth: 720 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary, marginBottom: 6 }}>
          No ontology loaded from {s.url}
        </div>
        <div style={{ fontSize: 12, color: '#b3261e', marginBottom: 10 }}>{s.error}</div>
        <div style={{ fontSize: 11.5, color: t.textMuted, lineHeight: 1.7 }}>
          Start a workbench with a profile, then press reload:
          <div style={{ ...mono, fontSize: 11, marginTop: 6 }}>
            cd ontology && python3 retail_graph/serve_ui.py \<br />
            &nbsp;&nbsp;--settings ontologies/clinic/clinic_settings.json --port 8096
          </div>
        </div>
        <button style={{ ...btn(), marginTop: 12 }} onClick={() => navigate('/ontology')}>
          back to the ontology list
        </button>
      </div>
    );
  }

  const guard = (doc.guard || {}) as Record<string, any>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      {/* header: which profile, and what it is pointed at */}
      <div style={{ padding: '12px 18px 8px', borderBottom: `1px solid ${t.border}`, display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <Boxes size={15} color={t.accent} />
        <span style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, letterSpacing: '-0.2px' }}>
          {doc.profile || 'ontology'}
        </span>
        <span style={{ ...chip, ...mono }}>{doc.ns}</span>
        {doc.dsn && (
          <span style={{ ...chip, ...mono }}>
            {String(doc.dsn.dbname)} @ {String(doc.dsn.host)}:{String(doc.dsn.port)}
          </span>
        )}
        <span style={{ ...chip }}>
          guard · rows ≤ {String(guard.max_rows ?? '?')} · plan ≤{' '}
          {Number(guard.max_plan_rows ?? 0).toLocaleString()} · timeout{' '}
          {String(guard.statement_timeout_ms ?? '?')}ms · window{' '}
          {String(guard.default_window_days ?? '?')}d
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button style={btn()} onClick={() => void ontology.select(s.url, s.preset ?? undefined)}>
            <RefreshCw size={11} /> reload
          </button>
          <button style={btn(true)} onClick={() => navigate('/ontology/app')}
                  title="the ontology's own app — graph page, query console, actions, tutorial">
            <Play size={11} /> workbench
          </button>
        </div>
      </div>

      {/* tabs + filter */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 18px', borderBottom: `1px solid ${t.border}` }}>
        {TAB_META.map(({ id, label, icon: Icon }) => {
          const active = tab === id;
          const count = (doc.counts as any)?.[id] ?? (doc as any)[id]?.length ?? 0;
          return (
            <button
              key={id}
              onClick={() => { setTab(id); setSelected(null); }}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12.5,
                padding: '6px 12px', borderRadius: 8, cursor: 'pointer',
                border: `1px solid ${active ? t.accent : t.border}`,
                background: active ? `${t.accent}12` : 'transparent',
                color: active ? t.accent : t.textMuted, fontWeight: active ? 600 : 400,
              }}
            >
              <Icon size={12} /> {label}
              <span style={{ fontSize: 11, color: active ? t.accent : t.textDim }}>{count}</span>
            </button>
          );
        })}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
          <button
            onClick={() => setBuildOpen(true)}
            title="generate or rebuild this ontology with an agent (runs as a background job)"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12,
              padding: '5px 10px', borderRadius: 8, cursor: 'pointer',
              border: `1px solid ${t.border}`, background: 'transparent', color: t.textMuted,
            }}
          >
            <Sparkles size={12} /> Build…
          </button>
          <Search size={12} color={t.textDim} />
          <input
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder="filter…"
            style={{
              width: 180, fontSize: 11.5, padding: '3px 8px', borderRadius: 6,
              border: `1px solid ${t.border}`, background: t.bgInput, color: t.textPrimary,
            }}
          />
        </div>
      </div>

      {buildOpen && (
        <BuildOntologyDialog
          ontologyKey={s.preset || s.profiles.find(p => p.url === s.url)?.key || ''}
          onClose={() => setBuildOpen(false)}
          onLanded={refreshCards}
        />
      )}

      {tab === 'metrics' ? (
        <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
          <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
            <MetricsGrid
              cards={cards} error={cardsError} needle={needle} doc={doc}
              selected={metricName} onSelect={setMetricName}
            />
          </div>
          {editorOpen ? (
            <MetricEditorPanel
              ontologyKey={s.preset || s.profiles.find(p => p.url === s.url)?.key || ''}
              cards={cards}
              metricName={metricName}
              onSelectMetric={setMetricName}
              onApplied={refreshCards}
              onClose={() => setEditorOpen(false)}
            />
          ) : (
            <button
              onClick={() => setEditorOpen(true)}
              title="open the metric editor chat"
              style={{
                width: 34, flex: 'none', borderLeft: `1px solid ${t.border}`, background: 'transparent',
                color: t.textMuted, cursor: 'pointer', fontSize: 11, writingMode: 'vertical-rl',
                padding: '10px 0', border: 'none', borderLeftWidth: 1, borderLeftStyle: 'solid',
                borderLeftColor: t.border,
              }}
            >
              metric editor chat
            </button>
          )}
        </div>
      ) : (
      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        {/* list */}
        <div style={{ width: 280, borderRight: `1px solid ${t.border}`, overflowY: 'auto', flex: 'none' }}>
          {rows.length === 0 && (
            <div style={{ padding: 12, fontSize: 12.5, color: t.textDim }}>nothing matches</div>
          )}
          {rows.map((r: any) => {
            const active = current?.name === r.name;
            const refused = !!r.refused;
            return (
              <div
                key={r.name}
                onClick={() => setSelected(r.name)}
                style={{
                  padding: '6px 12px', cursor: 'pointer',
                  background: active ? t.bgSelected : 'transparent',
                  borderLeft: `2px solid ${active ? t.accent : 'transparent'}`,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ ...mono, fontSize: 12.5, color: t.textPrimary }}>{r.name}</span>
                  {refused && <span title="refused at compile time"><AlertTriangle size={10} color="#c2410c" /></span>}
                </div>
                <div style={{ fontSize: 11.5, color: t.textDim }}>
                  {r.label || ''}
                  {r.table ? ` · ${r.table}` : ''}
                  {r.grain ? ` · ${String(r.grain).replace(/^.*#/, '')}` : ''}
                </div>
              </div>
            );
          })}
        </div>

        {/* detail */}
        <div style={{ flex: 1, minWidth: 0, overflowY: 'auto', padding: '14px 18px 40px' }}>
          {!current && <div style={{ fontSize: 13, color: t.textDim }}>pick a row on the left</div>}

          {current && tab === 'objects' && (
            <div>
              <h2 style={{ margin: '0 0 6px', fontSize: 16, fontWeight: 700, color: t.textPrimary }}>
                {current.label || current.name}{' '}
                <span style={{ ...mono, fontSize: 12, color: t.textDim, fontWeight: 400 }}>:{current.name}</span>
              </h2>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
                <span style={{ ...chip, ...mono }}>table {current.table}</span>
                <span style={{ ...chip, ...mono }}>pk {(current.primaryKey || []).join(', ') || '—'}</span>
                <span style={{ ...chip }}>{(current.columns || []).length} columns</span>
              </div>
              {current.description && (
                <p style={{ fontSize: 13, color: t.textMuted, lineHeight: 1.7, marginTop: 0 }}>{current.description}</p>
              )}
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
                <thead>
                  <tr style={{ color: t.textDim, textAlign: 'left' }}>
                    <th style={{ padding: '4px 8px', fontWeight: 500 }}>property</th>
                    <th style={{ padding: '4px 8px', fontWeight: 500 }}>column</th>
                    <th style={{ padding: '4px 8px', fontWeight: 500 }}>label</th>
                  </tr>
                </thead>
                <tbody>
                  {(current.columns || []).map((c: any) => (
                    <tr key={c.name} style={{ borderTop: `1px solid ${t.border}` }}>
                      <td style={{ ...mono, padding: '4px 8px', color: t.textPrimary }}>:{c.name}</td>
                      <td style={{ ...mono, padding: '4px 8px', color: c.column ? t.textMuted : DANGER }}>
                        {c.column || '— not annotated'}
                      </td>
                      <td style={{ padding: '4px 8px', color: t.textMuted }}>{c.label || ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {current && tab === 'definitions' && (
            <div>
              <h2 style={{ margin: '0 0 6px', fontSize: 16, fontWeight: 700, color: t.textPrimary }}>
                {current.label || current.name}{' '}
                <span style={{ ...mono, fontSize: 12, color: t.textDim, fontWeight: 400 }}>:{current.name}</span>
              </h2>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
                <span style={{ ...chip, ...mono }}>{(current.kinds || [current.kind]).join(' + ')}</span>
                {current.base && <span style={{ ...chip, ...mono }}>base :{current.base}</span>}
                {(current.members || []).length > 0 && (
                  <span style={{ ...chip, ...mono }}>members {(current.members || []).join(', ')}</span>
                )}
                {current.predicate && (
                  <span style={{ ...chip, ...mono }}>predicate {current.predicate}</span>
                )}
              </div>
              {current.description && (
                <p style={{ fontSize: 13, color: t.textMuted, lineHeight: 1.7, marginTop: 0 }}>
                  {current.description}
                </p>
              )}
              <div style={{ fontSize: 11, color: t.textDim, lineHeight: 1.6 }}>
                A definition is what a metric's <code style={mono}>:where</code> points at. Change it and
                every number that uses it moves — which is why it lives in the ontology, not in SQL.
              </div>
            </div>
          )}

          {current && tab === 'links' && (
            <div>
              <h2 style={{ margin: '0 0 6px', fontSize: 16, fontWeight: 700, color: t.textPrimary }}>
                {current.label || current.name}{' '}
                <span style={{ ...mono, fontSize: 12, color: t.textDim, fontWeight: 400 }}>:{current.name}</span>
              </h2>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
                <span style={{ ...chip, ...mono }}>{(current.from || []).join(', ') || '—'}</span>
                <span style={{ ...chip, ...mono }}>→ {current.to || '—'}</span>
                <span style={{ ...chip, ...mono }}>via {current.column || '—'}</span>
              </div>
              <div style={{ fontSize: 11, color: t.textDim, lineHeight: 1.6 }}>
                A link is <code style={mono}>:physicalColumn</code> + <code style={mono}>:references</code>.
                Drop the reference and the join is refused by name — it is never inferred.
              </div>
            </div>
          )}


        </div>
      </div>
      )}
    </div>
  );
}

/**
 * MetricsGrid — the workbench's metric cards: name, label, the declaration it compiles from,
 * that compiled SQL, the guard's report and the number. The number is read from the card
 * response (one call for the whole grid); a metric that refuses shows the compiler's sentence
 * instead of a value, because that refusal is the declaration still missing.
 */
function MetricsGrid({ cards, error, needle, doc, selected, onSelect }: {
  cards: MetricCard[] | null; error: string | null; needle: string; doc: any;
  selected?: string | null; onSelect?: (name: string) => void;
}) {
  const t = useLayoutTokens();
  if (error) {
    // A workbench can be up and still not serve the cards endpoint (an older build, for
    // instance). Showing "nothing" there is the worst answer; show what /api/ontology
    // already knows — every declaration and its SQL — and say the numbers are missing.
    const fallback: any[] = (doc?.metrics || []).filter(
      (m: any) => !needle || m.name.toLowerCase().includes(needle) || (m.label || '').toLowerCase().includes(needle),
    );
    return (
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '14px 16px 40px' }}>
        <div style={{
          marginBottom: 12, padding: '10px 12px', borderRadius: 9, fontSize: 12.5, lineHeight: 1.7,
          border: `1px solid ${WARN}55`, background: `${WARN}12`, color: t.textPrimary,
        }}>
          <b>values unavailable</b> — {error}. The declarations and their compiled SQL are below;
          the numbers need a workbench that serves <code style={mono}>/api/metrics/cards</code>{' '}
          (restart it and reload).
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(330px, 1fr))', gap: 12 }}>
          {fallback.map((m: any) => (
            <Card
              key={m.name}
              style={{
                display: 'flex', flexDirection: 'column', gap: 6, padding: '12px 14px',
                cursor: 'pointer',
                outline: selected === m.name ? `2px solid ${t.accent}` : 'none',
              }}
              {...(onSelect ? { onClick: () => onSelect(m.name) } : {})}
            >
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <span style={{ ...mono, fontSize: 13.5, fontWeight: 600, color: t.accent }}>{m.name}</span>
                {m.label && <span style={{ fontSize: 12, color: t.textPrimary }}>{m.label}</span>}
              </div>
              <div style={{ ...mono, fontSize: 10.5, lineHeight: 1.6, color: WARN, background: `${WARN}14`, borderRadius: 5, padding: '5px 7px' }}>
                {[m.aggregate && `:aggregate ${m.aggregate}`, m.formula && `:formula "${m.formula}"`,
                  m.grain && `:grain :${m.grain}`, m.where && `:where :${m.where}`].filter(Boolean).join(' · ')}
              </div>
              {m.refused ? (
                <div style={{ fontSize: 12, color: DANGER, lineHeight: 1.65 }}><b>refused:</b> {m.refused}</div>
              ) : (
                <pre style={{ ...mono, fontSize: 10, lineHeight: 1.5, background: '#0f172a', color: '#dbe7f3', borderRadius: 7, padding: '8px 10px', margin: 0, whiteSpace: 'pre-wrap', maxHeight: 110, overflow: 'auto' }}>
                  {m.sql}
                </pre>
              )}
            </Card>
          ))}
          {fallback.length === 0 && (
            <div style={{ fontSize: 12.5, color: t.textDim }}>and no declarations came back either — the profile itself did not load.</div>
          )}
        </div>
      </div>
    );
  }
  if (!cards) {
    return <div style={{ padding: 18, fontSize: 12.5, color: t.textMuted }}>running every metric once…</div>;
  }
  const shown = cards.filter(c =>
    !needle || c.name.toLowerCase().includes(needle) || (c.label || '').toLowerCase().includes(needle));
  const def = (c: MetricCard) => {
    if (c.numerator && c.denominator) {
      return [`:numerator :${c.numerator}`, `:denominator :${c.denominator}`,
        c.grain && `:grain :${c.grain}`, c.scale && `:scale ${c.scale}`].filter(Boolean).join(' · ');
    }
    return [
      c.aggregate && `:aggregate ${c.aggregate}`,
      c.formula && `:formula "${c.formula}"`,
      c.grain && `:grain :${c.grain}`,
      c.where && `:where :${c.where}`,
      (c.groupBy || []).length > 0 && `:groupBy :${(c.groupBy || []).join(' :')}`,
    ].filter(Boolean).join(' · ');
  };
  const value = (c: MetricCard) => {
    if (c.value === null || c.value === undefined) return '—';
    if (typeof c.value === 'number') return c.value.toLocaleString(undefined, { maximumFractionDigits: 4 });
    return String(c.value);
  };

  return (
    <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '14px 16px 40px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(330px, 1fr))', gap: 12 }}>
        {shown.map(c => (
          <Card
            key={c.name}
            style={{
              display: 'flex', flexDirection: 'column', gap: 6, padding: '12px 14px',
              cursor: onSelect ? 'pointer' : 'default',
              outline: selected === c.name ? `2px solid ${t.accent}` : 'none',
            }}
            {...(onSelect ? { onClick: () => onSelect(c.name) } : {})}
          >
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span style={{ ...mono, fontSize: 13.5, fontWeight: 600, color: t.accent }}>{c.name}</span>
              {c.label && <span style={{ fontSize: 12, color: t.textPrimary }}>{c.label}</span>}
              {c.unit && <span style={{ marginLeft: 'auto', fontSize: 10.5, color: t.textDim }}>{c.unit}</span>}
            </div>
            {c.error ? (
              <div style={{ fontSize: 12, color: DANGER, lineHeight: 1.65 }}>
                <b>refused:</b> {c.error}
              </div>
            ) : (
              <>
                <div style={{
                  ...mono, fontSize: 10.5, lineHeight: 1.6, color: WARN,
                  background: `${WARN}14`, borderRadius: 5, padding: '5px 7px', wordBreak: 'break-word',
                }}>
                  {def(c)}
                </div>
                <pre style={{
                  ...mono, fontSize: 10, lineHeight: 1.5, background: '#0f172a', color: '#dbe7f3',
                  borderRadius: 7, padding: '8px 10px', margin: 0, whiteSpace: 'pre-wrap',
                  maxHeight: 110, overflow: 'auto',
                }}>
                  {c.sql}
                </pre>
                {(c.notes || []).length > 0 && (
                  <div style={{ fontSize: 10.5, color: t.textDim, lineHeight: 1.55 }}>
                    {(c.notes || []).map((n, i) => <div key={i}>· {n}</div>)}
                  </div>
                )}
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 'auto' }}>
                  <span style={{ ...mono, fontSize: 17, fontWeight: 700, color: SUCCESS }}>{value(c)}</span>
                  {c.plan_rows !== undefined && (
                    <span style={{ fontSize: 10.5, color: t.textDim }}>
                      plan {c.plan_rows?.toLocaleString?.() ?? c.plan_rows} rows
                      {c.ms !== undefined ? ` · ${c.ms} ms` : ''}
                    </span>
                  )}
                </div>
                {c.run_error && (
                  <div style={{ fontSize: 11, color: DANGER, lineHeight: 1.55 }}>run failed: {c.run_error}</div>
                )}
              </>
            )}
          </Card>
        ))}
        {shown.length === 0 && (
          <div style={{ fontSize: 12.5, color: t.textDim }}>no metric matches “{needle}”</div>
        )}
      </div>
    </div>
  );
}
