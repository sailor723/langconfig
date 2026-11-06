/**
 * OntologySectionPage — one workbench section per ontology, framed.
 *
 * The workbench is a separate server with its own rail (Overview / Query / Actions / Design /
 * Tutorial). Rather than show that rail inside the frame — two browsers for one thing — the
 * frame is loaded with `embed=1`, which drops the workbench's own navigation, and this app
 * lists those sections under each ontology in its own sidebar (OntologySidebar).
 *
 * The frame also inherits **global settings**: the theme (dark/light) and the interface
 * language are passed through, so an embedded workbench matches the app around it instead of
 * flashing a white, English page inside a dark shell.
 */
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ExternalLink, RefreshCw, ServerCrash, Server, ListTree, ChevronDown, ArrowLeft } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../lib/themes';
import { useLayoutTokens } from '../components/layout2/tokens';
import { ontology, useOntology, SECTIONS, framedUrl } from '../features/ontology/ontologyStore';

export default function OntologySectionPage() {
  const t = useLayoutTokens();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const { theme } = useTheme();
  const { i18n } = useTranslation('chat');
  const s = useOntology();
  const [nonce, setNonce] = useState(0);
  const [draft, setDraft] = useState(s.url);

  const view = params.get('view') || 'home';
  // The server says which sections this profile serves: offering a section that is switched
  // off in the profile would frame a 404.
  const sections = s.sections?.length ? s.sections.filter(x => x.enabled) : SECTIONS.map(x => ({ ...x, enabled: true }));
  const section = sections.find(x => x.key === view) ?? sections[0] ?? SECTIONS[0];
  const lang = (i18n?.language || '').startsWith('zh') ? 'zh' : 'en';
  const themeName = theme?.name === 'dark' ? 'dark' : 'light';

  useEffect(() => { void ontology.ensureReady(); }, []);
  useEffect(() => { setDraft(s.url); }, [s.url]);

  const src = useMemo(
    () => (s.url ? framedUrl(s.url, section.path, themeName, lang) : ''),
    [s.url, section.path, themeName, lang],
  );

  const bar: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
    borderBottom: `1px solid ${t.border}`, background: t.bgTabBar, flex: 'none',
    font: '12px -apple-system, "Segoe UI", Roboto, sans-serif', color: t.textPrimary,
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
        <button style={chip()} onClick={() => navigate('/ontology')} title="back to the ontology list">
          <ArrowLeft size={11} /> ontologies
        </button>
        <Server size={13} />
        <span style={{ fontWeight: 600 }}>{section.label}</span>
        <span
          title={s.error || s.ontology?.profile || undefined}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '2px 8px', borderRadius: 999, background: badge.bg, color: badge.color, fontSize: 11 }}
        >
          {s.status === 'down' && <ServerCrash size={11} />}
          {badge.text}
        </span>

        {/* the sections live here too, so switching does not need the sidebar */}
        {sections.map(sec => (
          <button
            key={sec.key}
            style={chip(sec.key === section.key)}
            title={sec.hint}
            onClick={() => setParams(sec.key === 'home' ? {} : { view: sec.key }, { replace: true })}
          >
            {sec.label}
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
            style={{ width: 220, font: '11px ui-monospace, Menlo, monospace', padding: '4px 8px', borderRadius: 6, border: `1px solid ${t.border}`, background: t.bgInput, color: t.textPrimary }}
          />
          <button type="submit" style={chip()} title="load this ontology">
            <ChevronDown size={11} style={{ transform: 'rotate(-90deg)' }} /> load
          </button>
        </form>

        <button style={chip()} onClick={() => { void ontology.select(s.url, s.preset ?? undefined); setNonce(n => n + 1); }} title="reload the section">
          <RefreshCw size={11} /> reload
        </button>
        <button style={chip()} onClick={() => navigate('/ontology/browse')} title="declarations (objects, definitions, links, metrics)">
          <ListTree size={11} /> declarations
        </button>
        <a href={src} target="_blank" rel="noreferrer" style={{ ...chip(), textDecoration: 'none' }} title="open this section without the frame">
          <ExternalLink size={11} /> open
        </a>
      </div>

      {s.status === 'down' && (
        <div style={{ margin: '10px 12px 0', padding: '10px 12px', borderRadius: 8, background: '#fdecea', color: '#8c1d18', fontSize: 12, lineHeight: 1.55 }}>
          <b>No workbench at {s.url || '(no profile selected)'}</b>{s.error ? ` — ${s.error}` : ''}.<br />
          Start one with a profile, then press reload:
          <div style={{ font: '11px ui-monospace, Menlo, monospace', marginTop: 6, whiteSpace: 'pre-wrap' }}>
            {`cd ontology && python3 retail_graph/serve_ui.py \\\n    --settings ontologies/clinic/clinic_settings.json --port 8096`}
          </div>
        </div>
      )}

      <iframe
        key={`${src}#${nonce}`}
        src={src}
        title={`${section.label} — ${s.ontology?.profile || 'ontology'}`}
        style={{ flex: 1, width: '100%', border: 'none', minHeight: 0, background: themeName === 'dark' ? '#15181d' : '#fff' }}
        sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-downloads"
      />
    </div>
  );
}
