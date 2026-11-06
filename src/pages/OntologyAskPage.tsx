/**
 * OntologyAskPage — the workbench itself, framed.
 *
 * The workbench (ontology/retail_graph/serve_ui.py) is a separate server: it loads one
 * profile and answers questions from it. That is where asking happens — the natural-language
 * console, the metric menu, the guardrail reports. Re-implementing any of it here would
 * duplicate the compiler and drift from it, so this page hosts it and keeps the two things a
 * frame cannot do: say whether the server is alive, and switch profile without opening a
 * terminal.
 */
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ExternalLink, RefreshCw, ServerCrash, Server, ListTree, ChevronDown } from 'lucide-react';
import { useLayoutTokens } from '../components/layout2/tokens';
import { ontology, useOntology } from '../features/ontology/ontologyStore';

export default function OntologyAskPage() {
  const t = useLayoutTokens();
  const navigate = useNavigate();
  const s = useOntology();
  const [draft, setDraft] = useState(s.url);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    void ontology.ensureReady();
  }, []);
  useEffect(() => {
    setDraft(s.url);
  }, [s.url]);

  const origin = useMemo(() => {
    try {
      return new URL(s.url).origin;
    } catch {
      return '';
    }
  }, [s.url]);

  const bar: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
    borderBottom: `1px solid ${t.border}`, background: t.bgTabBar,
    font: '12px -apple-system, "Segoe UI", Roboto, sans-serif', color: t.textPrimary, flex: 'none',
  };
  const chip = (active = false): React.CSSProperties => ({
    display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 9px',
    borderRadius: 999, border: `1px solid ${active ? t.accent : t.border}`,
    background: active ? `${t.accent}14` : 'transparent',
    color: active ? t.accent : t.textMuted, cursor: 'pointer', fontSize: 11, whiteSpace: 'nowrap',
  });

  const badge = s.status === 'up'
    ? { color: '#12805c', bg: '#e9f7f0', text: s.ontology?.counts ? `running · ${s.ontology.counts.metrics} metrics` : 'running' }
    : s.status === 'down'
      ? { color: '#b3261e', bg: '#fdecea', text: 'not answering' }
      : { color: '#8a6d3b', bg: '#fdf6e3', text: 'checking…' };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, background: t.bgContent }}>
      <div style={bar}>
        <Server size={14} />
        <span style={{ fontWeight: 600, letterSpacing: 0.2 }}>Ask</span>

        <span
          title={s.error || s.ontology?.profile || undefined}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 5, padding: '2px 8px',
            borderRadius: 999, background: badge.bg, color: badge.color, fontSize: 11,
          }}
        >
          {s.status === 'down' && <ServerCrash size={11} />}
          {badge.text}
        </span>

        {s.profiles.map(p => (
          <button key={p.key} style={chip(s.url === p.url)} title={p.profile || p.url}
                  onClick={() => void ontology.select(p.url, p.key)}>
            {p.label}
          </button>
        ))}

        <form
          onSubmit={e => { e.preventDefault(); void ontology.select(draft); setNonce(n => n + 1); }}
          style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 'auto' }}
        >
          <input
            value={draft}
            onChange={e => setDraft(e.target.value)}
            spellCheck={false}
            placeholder="http://127.0.0.1:8096"
            style={{
              width: 240, font: '11px ui-monospace, Menlo, monospace', padding: '4px 8px',
              borderRadius: 6, border: `1px solid ${t.border}`, background: t.bgInput, color: t.textPrimary,
            }}
          />
          <button type="submit" style={chip()} title="load this ontology">
            <ChevronDown size={11} style={{ transform: 'rotate(-90deg)' }} /> load
          </button>
        </form>

        <button style={chip()} onClick={() => { void ontology.select(s.url, s.preset ?? undefined); setNonce(n => n + 1); }} title="reload">
          <RefreshCw size={11} /> reload
        </button>
        <button style={chip()} onClick={() => navigate('/ontology/browse')} title="browse the declarations">
          <ListTree size={11} /> browse
        </button>
        <a href={s.url} target="_blank" rel="noreferrer" style={{ ...chip(), textDecoration: 'none' }} title="open in a new tab">
          <ExternalLink size={11} /> open
        </a>
      </div>

      {s.status === 'down' && (
        <div style={{ margin: '10px 12px 0', padding: '10px 12px', borderRadius: 8, background: '#fdecea', color: '#8c1d18', fontSize: 12, lineHeight: 1.55 }}>
          <b>No workbench at {origin || s.url}</b>{s.error ? ` — ${s.error}` : ''}.<br />
          Start one with a profile, then press reload:
          <div style={{ font: '11px ui-monospace, Menlo, monospace', marginTop: 6, whiteSpace: 'pre-wrap' }}>
            {`cd ontology && python3 retail_graph/serve_ui.py \\\n    --settings ontologies/clinic/clinic_settings.json --port 8096`}
          </div>
        </div>
      )}

      <iframe
        key={`${s.url}#${nonce}`}
        src={s.url}
        title="Ontology workbench"
        style={{ flex: 1, width: '100%', border: 'none', minHeight: 0, background: '#fff' }}
        sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-downloads"
      />
    </div>
  );
}
