/**
 * OntologySidebar — the ontology list in the left rail, like every other activity's browser
 * (Analysis lists dashboards, Knowledge lists sources, this lists ontologies).
 *
 * One row per ONTOLOGY (a workbench profile), not per file: a profile is the unit a number is
 * compiled from, so it is the unit a reader picks. The dot is that workbench's liveness — a
 * profile that is not running is shown as off with its counts hidden, not hidden altogether,
 * because "why is nothing here" is the question a missing row creates.
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Boxes, RefreshCw, Loader2, ListTree, Settings2, Compass, PlayCircle, Gavel, FileCode2, GraduationCap,
} from 'lucide-react';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { ontology, useOntology } from './ontologyStore';

const SECTION_ICON: Record<string, any> = {
  home: Compass,
  query: PlayCircle,
  actions: Gavel,
  design: FileCode2,
  tutorial: GraduationCap,
};

export default function OntologySidebar() {
  const t = useLayoutTokens();
  const navigate = useNavigate();
  const s = useOntology();
  // Second layer: which ontology's activities are open. Hovering any row opens it (the
  // first layer expands on hover too — same idea, one level down); the selected row stays
  // open so you can still see where you are after the pointer leaves.
  const [peek, setPeek] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      await ontology.ensureReady();
      if (Object.keys(s.probes).length === 0) void ontology.probeAll();
    })();
  }, []);

  const rowTitle: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 6, padding: 0,
    border: 'none', background: 'transparent', cursor: 'pointer',
  };

  const upCount = s.profiles.filter(p => s.probes[p.url]?.status === 'up').length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 10px 6px', flexShrink: 0 }}>
        {/* The section title is the way home, as in the Analysis rail. */}
        <button
          onClick={() => navigate('/ontology')}
          title="Ontology home"
          style={{ ...rowTitle, color: s.ontology ? t.textMuted : t.textPrimary }}
        >
          <Boxes size={13} color={t.accent} />
          <span style={{ fontSize: 12.5, fontWeight: 700 }}>Ontologies</span>
          <span style={{ fontSize: 11, color: t.textDim }}>
            {upCount}/{s.profiles.length}
          </span>
        </button>
        <button
          onClick={() => void ontology.probeAll()}
          title="re-probe every workbench"
          style={{ ...rowTitle, marginLeft: 'auto', color: t.textDim }}
        >
          <RefreshCw size={12} />
        </button>
        <button
          onClick={() => navigate('/settings')}
          title="Settings → Ontology (which profiles exist)"
          style={{ ...rowTitle, color: t.textDim }}
        >
          <Settings2 size={12} />
        </button>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
        {s.profiles.map(p => {
          const probe = s.probes[p.url];
          const active = s.url === p.url;
          const up = probe?.status === 'up';
          return (
            <div
              key={p.key}
              // data-* so the hover expansion can be asserted from a test without guessing
              // at DOM shape: data-peek flips while the pointer is on the row.
              data-ontology-row={p.key}
              data-peek={peek === p.key ? '1' : '0'}
              style={{
                padding: '6px 10px',
                background: active ? t.bgSelected : 'transparent',
                borderLeft: `2px solid ${active ? t.accent : 'transparent'}`,
                cursor: 'pointer',
              }}
              onMouseEnter={e => {
                if (!active) e.currentTarget.style.background = t.bgHover;
                setPeek(p.key);
              }}
              onMouseLeave={e => {
                if (!active) e.currentTarget.style.background = 'transparent';
                setPeek(null);
              }}
              onFocus={() => setPeek(p.key)}
              onBlur={() => setPeek(null)}
              onClick={async () => {
                await ontology.select(p.url, p.key);
                navigate('/ontology/browse');
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span
                  title={up ? 'workbench answering' : (probe?.error || 'not probed')}
                  style={{
                    width: 6, height: 6, borderRadius: 999, flex: 'none',
                    background: up ? '#12805c' : probe?.status === 'down' ? '#c2410c' : t.textDim,
                  }}
                />
                <span style={{ fontSize: 12.5, fontWeight: active ? 600 : 500, color: t.textPrimary }}>
                  {p.label}
                </span>
                {probe?.status === 'unknown' && <Loader2 size={10} className="animate-spin" />}
                <span style={{ marginLeft: 'auto', fontSize: 11, color: t.textDim }}>
                  {up && probe?.counts ? `${probe.counts.metrics} m · ${probe.counts.objects} o` : ''}
                </span>
              </div>
              <div style={{ fontSize: 11, color: t.textDim, marginTop: 2, lineHeight: 1.45 }}>
                {p.profile || p.key}
              </div>
              {/* The sections of the selected ontology. The workbench's own rail is hidden
                  inside the frame (embed=1); this list is what replaces it, and it lives under
                  the ontology it belongs to. */}
              {(active || peek === p.key) && up && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 1, marginTop: 5, paddingLeft: 12 }}>
                  <span style={{ fontSize: 9.5, letterSpacing: 0.5, textTransform: 'uppercase',
                                 color: t.textDim, marginTop: 2 }}>workbench</span>
                  <button
                    onClick={e => { e.stopPropagation(); navigate('/ontology/browse'); }}
                    title="objects, definitions, links and every metric with its compiled SQL"
                    style={{ ...rowTitle, fontSize: 11.5, color: t.accent, padding: '2px 0' }}
                  >
                    <ListTree size={11} /> schema &amp; metrics
                  </button>
                  {(probe?.sections ?? s.sections).filter(sec => sec.enabled).map(sec => {
                    const Icon = SECTION_ICON[sec.key] ?? Compass;
                    return (
                      <button
                        key={sec.key}
                        title={sec.hint}
                        onClick={e => { e.stopPropagation(); navigate(sec.key === 'home' ? '/ontology/app' : `/ontology/app?view=${sec.key}`); }}
                        style={{ ...rowTitle, fontSize: 11.5, color: t.textMuted, padding: '2px 0' }}
                      >
                        <Icon size={11} /> {sec.label.toLowerCase()}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
        {s.profiles.length === 0 && (
          <div style={{ padding: 12, fontSize: 11, color: t.textDim, lineHeight: 1.6 }}>
            No ontology profiles configured.
            <br />
            Add one in Settings → Ontology.
          </div>
        )}
      </div>

      <div style={{ padding: '8px 12px', borderTop: `1px solid ${t.border}`, fontSize: 11, color: t.textDim, lineHeight: 1.55 }}>
        {s.profilesFrom === 'settings' ? (
          'profiles from Settings → Ontology'
        ) : (
          <span title={s.profilesError || undefined}>
            built-in profile list{s.profilesError ? ` — ${s.profilesError.slice(0, 60)}` : ''}
          </span>
        )}
      </div>
    </div>
  );
}
