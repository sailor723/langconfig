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
import { Chip, Btn, SUCCESS, DANGER, WARN } from '../features/ontology/ui';

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

  // A toolbar, not a hero: the same 12–13px scale and 8px radii the rest of the app's
  // panel headers use, so a framed workbench does not look bolted on.
  const bar: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 8, padding: '9px 14px',
    borderBottom: `1px solid ${t.border}`, background: t.bgTabBar, flex: 'none',
    color: t.textPrimary,
  };
  const badge = s.status === 'up'
    ? { colour: SUCCESS, text: s.ontology?.counts ? `running · ${s.ontology.counts.metrics} metrics` : 'running' }
    : s.status === 'down'
      ? { colour: DANGER, text: 'not answering' }
      : { colour: WARN, text: 'checking…' };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, background: t.bgContent }}>
      <div style={bar}>
        <Btn onClick={() => navigate('/ontology')} title="back to the ontology list">
          <ArrowLeft size={13} /> ontologies
        </Btn>
        <Server size={15} color={t.textMuted} />
        <span style={{ fontSize: 14, fontWeight: 600 }}>{section.label}</span>
        <Chip
          colour={badge.colour}
          title={s.error || s.ontology?.profile || undefined}
        >
          {s.status === 'down' && <ServerCrash size={11} />}
          {badge.text}
        </Chip>

        {/* the sections live here too, so switching does not need the sidebar */}
        {sections.map(sec => (
          <Chip
            key={sec.key}
            title={sec.hint}
            active={sec.key === section.key}
            onClick={() => setParams(sec.key === 'home' ? {} : { view: sec.key }, { replace: true })}
          >
            {sec.label}
          </Chip>
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
            style={{ width: 230, font: '12px ui-monospace, Menlo, monospace', padding: '6px 9px', borderRadius: 8, border: `1px solid ${t.border}`, background: t.bgInput, color: t.textPrimary }}
          />
          <Btn title="load this ontology" onClick={() => { void ontology.select(draft); setNonce(n => n + 1); }}>
            <ChevronDown size={13} style={{ transform: 'rotate(-90deg)' }} /> load
          </Btn>
        </form>

        <Btn onClick={() => { void ontology.select(s.url, s.preset ?? undefined); setNonce(n => n + 1); }} title="reload the section">
          <RefreshCw size={13} /> reload
        </Btn>
        <Btn onClick={() => navigate('/ontology/browse')} title="declarations (objects, definitions, links, metrics)">
          <ListTree size={13} /> declarations
        </Btn>
        <Btn title="open this section without the frame" onClick={() => window.open(src, '_blank', 'noreferrer')}>
          <ExternalLink size={13} /> open
        </Btn>
      </div>

      {s.status === 'down' && (
        <div style={{ margin: '12px 14px 0', padding: '12px 14px', borderRadius: 10, border: `1px solid ${DANGER}55`, background: `${DANGER}10`, color: t.textPrimary, fontSize: 12.5, lineHeight: 1.7 }}>
          <b>No workbench at {s.url || '(no profile selected)'}</b>{s.error ? ` — ${s.error}` : ''}.<br />
          Start one with a profile, then press reload:
          <div style={{ font: '12px ui-monospace, Menlo, monospace', marginTop: 6, whiteSpace: 'pre-wrap' }}>
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
