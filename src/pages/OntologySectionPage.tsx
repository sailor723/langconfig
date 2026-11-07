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
import { ontology, useOntology, SECTIONS, sectionPageUrl } from '../features/ontology/ontologyStore';
import { Chip, Btn, SUCCESS, DANGER, WARN } from '../features/ontology/ui';

export default function OntologySectionPage() {
  const t = useLayoutTokens();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const { theme } = useTheme();
  const { i18n } = useTranslation('chat');
  const s = useOntology();
  const [nonce, setNonce] = useState(0);

  const view = params.get('view') || 'home';
  // The server says which sections this profile serves: offering a section that is switched
  // off in the profile would frame a 404.
  const sections = s.sections?.length ? s.sections.filter(x => x.enabled) : SECTIONS.map(x => ({ ...x, enabled: true }));
  const framed = sections.filter(x => x.kind !== 'app');
  const section = framed.find(x => x.key === view) ?? framed[0] ?? SECTIONS[0];
  const lang = (i18n?.language || '').startsWith('zh') ? 'zh' : 'en';
  const themeName = theme?.name === 'dark' ? 'dark' : 'light';
  const sectionKey = s.preset || s.profiles.find(p => p.url === s.url)?.key || '';

  useEffect(() => {
    const app_section = sections.find(x => x.key === view && x.kind === 'app');
    if (app_section) navigate(app_section.path, { replace: true });
  }, [view, sections, navigate]);

  useEffect(() => { void ontology.ensureReady(); }, []);


  // The page comes from THIS app now (`/api/ontology/{key}/page/…`), not from a workbench port: the frame
  // stays, the second server does not. `theme`/`lang` still travel so an embedded page matches the shell.
  const src = useMemo(() => {
    if (!sectionKey) return '';
    const base = sectionPageUrl(sectionKey, section.key);
    const sep = base.includes('?') ? '&' : '?';
    return `${base}${sep}${new URLSearchParams({ theme: themeName, lang }).toString()}`;
  }, [sectionKey, section.key, themeName, lang]);

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
        <Chip title="the ontology's own app, framed here">{s.ontology?.profile?.replace('_settings.json', '') || 'workbench'}</Chip>
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
            onClick={() => {
              // the dashboard is a page of THIS app, not a workbench path: switching ?view would frame a
              // 404. The two kinds share one list, and this is where they part company.
              if (sec.kind === 'app') { navigate(sec.path); return; }
              setParams(sec.key === 'home' ? {} : { view: sec.key }, { replace: true });
            }}
          >
            {sec.label}
          </Chip>
        ))}


        <Btn onClick={() => { void ontology.select(s.url, s.preset ?? undefined); setNonce(n => n + 1); }} title="reload the section">
          <RefreshCw size={13} /> reload
        </Btn>
        <Btn onClick={() => navigate('/ontology/browse')} title="objects, definitions, links and every metric with its compiled SQL">
          <ListTree size={13} /> schema &amp; metrics
        </Btn>
        <Btn title="open this section in a new browser tab (without the frame)" onClick={() => window.open(src, '_blank', 'noreferrer')}>
          <ExternalLink size={13} /> new tab
        </Btn>
      </div>

      {s.status === 'down' && (
        <div style={{ margin: '12px 14px 0', padding: '12px 14px', borderRadius: 10, border: `1px solid ${DANGER}55`, background: `${DANGER}10`, color: t.textPrimary, fontSize: 12.5, lineHeight: 1.7 }}>
          <b>This ontology did not compile</b>{sectionKey ? ` (${sectionKey})` : ''}{s.error ? ` — ${s.error}` : ''}.<br />
          Every section of this page is compiled in the app, from the ontology's own declarations — there is
          no second server to start. The refusal above is the compiler's answer; fix the declaration it
          names, then press reload.
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
