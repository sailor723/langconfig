/**
 * OntologyBrowserPage — read what the loaded profile declares.
 *
 * The workbench answers questions; this page answers "what is in there": objects and their
 * physical tables, the definitions (axioms) that decide membership, the declared links, and
 * every metric with its compiled SQL *or* its refusal. Nothing is fetched per row — the
 * document is one `/api/ontology` call, so the lists cannot disagree with each other.
 */
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ListTree, Table2, Link2, Sigma, AlertTriangle, Play, RefreshCw, Copy, Check, Boxes, Search,
} from 'lucide-react';
import { useLayoutTokens } from '../components/layout2/tokens';
import { Card, Chip, Btn, mono, SUCCESS, DANGER, WARN } from '../features/ontology/ui';
import { ontology, useOntology } from '../features/ontology/ontologyStore';

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

  useEffect(() => {
    void (async () => {
      await ontology.ensureReady();
      if (!ontology.get().ontology && ontology.get().status !== 'loading') {
        const url = ontology.get().url;
        if (url) await ontology.select(url, ontology.get().preset ?? undefined);
      }
    })();
  }, []);

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
          <button style={btn(true)} onClick={() => navigate('/ontology/app')}>
            <Play size={11} /> open app
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

      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        {/* list */}
        <div style={{ width: 280, borderRight: `1px solid ${t.border}`, overflowY: 'auto', flex: 'none' }}>
          {rows.length === 0 && (
            <div style={{ padding: 12, fontSize: 12.5, color: t.textDim }}>nothing matches</div>
          )}
          {rows.map((r: any) => {
            const active = current?.name === r.name;
            const refused = tab === 'metrics' && !!r.refused;
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
                  {tab === 'metrics' && r.grain ? ` · ${String(r.grain).replace(/^.*#/, '')}` : ''}
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

          {current && tab === 'metrics' && (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: t.textPrimary }}>
                  {current.label || current.name}{' '}
                  <span style={{ ...mono, fontSize: 12, color: t.textDim, fontWeight: 400 }}>:{current.name}</span>
                </h2>
                {current.sql && (
                  <button
                    style={{ ...btn(), marginLeft: 'auto' }}
                    onClick={async () => {
                      await navigator.clipboard.writeText(current.sql || '');
                      setCopied(true);
                      setTimeout(() => setCopied(false), 1200);
                    }}
                  >
                    {copied ? <Check size={11} /> : <Copy size={11} />} {copied ? 'copied' : 'SQL'}
                  </button>
                )}
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
                {current.aggregate && <span style={{ ...chip, ...mono }}>{current.aggregate}</span>}
                {current.grain && <span style={{ ...chip, ...mono }}>grain :{String(current.grain).replace(/^.*#/, '')}</span>}
                {current.where && <span style={{ ...chip, ...mono }}>where :{String(current.where).replace(/^.*#/, '')}</span>}
                {(current.groupBy || []).length > 0 && (
                  <span style={{ ...chip, ...mono }}>groupBy {(current.groupBy || []).join(', ')}</span>
                )}
                {current.numerator && (
                  <span style={{ ...chip, ...mono }}>
                    ratio :{current.numerator}/:{current.denominator}
                    {current.scale ? ` ×${current.scale}` : ''}
                  </span>
                )}
                {current.unit && <span style={{ ...chip, ...mono }}>{current.unit}</span>}
              </div>
              {current.description && (
                <p style={{ fontSize: 13, color: t.textMuted, lineHeight: 1.7, marginTop: 0 }}>
                  {current.description}
                </p>
              )}
              {current.refused ? (
                <Card style={{ borderColor: `${DANGER}55`, background: `${DANGER}10`, padding: '12px 14px', fontSize: 12.5, lineHeight: 1.7, color: t.textPrimary }}>
                  <b>Refused by the compiler:</b> {current.refused}
                  <div style={{ marginTop: 6, color: t.textMuted }}>
                    A refusal is a result: the definition is incomplete, and the reason names what is missing.
                  </div>
                </Card>
              ) : (
                <pre style={{
                  ...mono, fontSize: 12, lineHeight: 1.6, padding: '12px 14px', borderRadius: 9,
                  background: '#0f172a', color: '#dbe7f3', overflowX: 'auto', margin: 0,
                  whiteSpace: 'pre-wrap',
                }}>
                  {current.sql}
                </pre>
              )}
              {(current.notes || []).length > 0 && (
                <div style={{ marginTop: 8, fontSize: 12, color: t.textDim, lineHeight: 1.7 }}>
                  {(current.notes || []).map((n: string, i: number) => <div key={i}>· {n}</div>)}
                </div>
              )}
              {(current.missing || []).length > 0 && (
                <div style={{ marginTop: 8, fontSize: 12, color: WARN }}>
                  missing in the overlay: {(current.missing || []).join(', ')}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
