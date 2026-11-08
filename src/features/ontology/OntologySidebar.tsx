/**
 * OntologySidebar — the ontology list in the left rail, like every other activity's browser
 * (Analysis lists dashboards, Knowledge lists sources, this lists ontologies).
 *
 * One row per ONTOLOGY (a profile), not per file: a profile is the unit a number is
 * compiled from, so it is the unit a reader picks. The dot is whether the app compiles it — a
 * profile that is not running is shown as off with its counts hidden, not hidden altogether,
 * because "why is nothing here" is the question a missing row creates.
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Boxes, RefreshCw, Loader2, ListTree, Settings2, Compass, PlayCircle, Gavel, FileCode2, GraduationCap,
  BarChart3,
} from 'lucide-react';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { ontology, profileIsActive, useOntology } from './ontologyStore';

const SECTION_ICON: Record<string, any> = {
  home: Compass,
  query: PlayCircle,
  dashboard: BarChart3,
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
  // Re-compiling every ontology takes a moment and used to give no sign it had run at all, so the
  // button read as broken. It now says what it did: `recompiled 3/7 · 14:32:07`.
  const [refreshed, setRefreshed] = useState<{ at: string; up: number; total: number } | null>(null);
  const refreshAll = async () => {
    setRefreshed(null);
    await ontology.probeAll();
    const st = ontology.get();
    setRefreshed({
      at: new Date().toLocaleTimeString(),
      up: st.profiles.filter(p => st.probes[p.key]?.status === 'up').length,
      total: st.profiles.length,
    });
  };

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

  // by KEY: every same-origin ontology has url '', so a probe keyed by url reported one ontology's
  // liveness on all seven rows.
  const upCount = s.profiles.filter(p => s.probes[p.key]?.status === 'up').length;

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
          onClick={() => void refreshAll()}
          disabled={s.starting}
          title="re-compile every ontology (reads each one's document again)"
          style={{ ...rowTitle, marginLeft: 'auto', color: t.textDim, opacity: s.starting ? 0.5 : 1 }}
        >
          <RefreshCw size={12} className={s.starting ? 'animate-spin' : undefined} />
        </button>
        <button
          // The gear goes to Settings → ONTOLOGY, where the publish panel is the FIRST thing on the
          // page: profiles you can open, and the publishes an agent staged that a person has to apply.
          // It used to open Settings on General, so that panel — the whole reason to leave this page —
          // was one unmarked click further away. (There was briefly a separate Apply section; it only
          // repeated the top of Ontology, so it is gone.)
          onClick={() => navigate('/settings?section=ontology')}
          title="Settings → Ontology: the pending publishes an agent staged, waiting for you to apply them (top of the page)"
          style={{ ...rowTitle, color: t.textDim }}
        >
          <Settings2 size={12} />
        </button>
      </div>

      {(s.starting || refreshed) && (
        <div style={{ flexShrink: 0, padding: '0 10px 6px', fontSize: 10.5, color: t.textDim }}>
          {s.starting ? 'recompiling…' : `recompiled ${refreshed!.up}/${refreshed!.total} · ${refreshed!.at}`}
        </div>
      )}

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
        {s.profiles.map(p => {
          const probe = s.probes[p.key];
          // the KEY decides the open row (see profileIsActive): comparing urls highlighted every row
          // that shared one, which after same-origin serving was most of them.
          const active = profileIsActive(p, s);
          // HOVER IS NOT "OPEN", and it is now the smallest thing that can still be read: the NAME
          // underlines and takes the accent colour, nothing else moves.
          //
          // Reported from the deployment: hovering looked like a second selection, because a hovered
          // row got the same tint, the same expansion and the same word ("sections") as the open one.
          // The open row keeps the whole signal — accent bar, selected background, bold accent name, a
          // filled marker and the section list; a hovered row changes ONE property of ONE element.
          const preview = !active && peek === p.key;
          const up = probe?.status === 'up';
          return (
            <div
              key={p.key}
              // data-* so the difference can be asserted from a test without guessing at DOM shape:
              // data-open is "this is the ontology that is open", data-peek flips while hovered.
              data-ontology-row={p.key}
              data-open={active ? '1' : '0'}
              data-peek={preview ? '1' : '0'}
              style={{
                padding: '6px 10px',
                // no hover tint: only the open row is filled, so "filled" means exactly one thing
                background: active ? t.bgSelected : 'transparent',
                borderLeft: `2px solid ${active ? t.accent : 'transparent'}`,
                cursor: 'pointer',
              }}
              onMouseEnter={() => setPeek(p.key)}
              onMouseLeave={() => setPeek(null)}
              onFocus={() => setPeek(p.key)}
              onBlur={() => setPeek(null)}
              onClick={async () => {
                await ontology.select(p.url, p.key);
                // Land where this ontology is most useful: the board when it DECLARES one, the
                // metrics it does declare when it does not. `sections` already carries the answer
                // (`dashboard` is enabled only when dashboard.json exists), so the decision is read
                // from the declaration rather than guessed from a profile field.
                const secs = ontology.get().sections || [];
                const hasBoard = secs.some(x => x.key === 'dashboard' && x.enabled);
                navigate(hasBoard ? '/ontology/dashboard' : '/ontology/browse');
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span
                  title={up ? 'compiled by the app' : (probe?.error || 'not compiled yet')}
                  style={{
                    width: 6, height: 6, borderRadius: 999, flex: 'none',
                    background: up ? '#12805c' : probe?.status === 'down' ? '#c2410c' : t.textDim,
                  }}
                />
                <span style={{
                  fontSize: 12.5,
                  fontWeight: active ? 700 : 500,
                  // the accent colour is legible on both the dark and the light theme's selected tint
                  // (white text is not: the light themes select onto a pale background)
                  color: (active || preview) ? t.accent : t.textPrimary,
                  // hover = under the pointer: the name underlines. The open row is bold and filled, so
                  // the two never read as the same state.
                  textDecoration: preview ? 'underline' : 'none',
                  textUnderlineOffset: 2,
                }}>
                  {p.label}
                </span>
                {probe?.status === 'unknown' && <Loader2 size={10} className="animate-spin" />}
                <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 5 }}>
                  {active && <span title="this is the open ontology"
                                  style={{ width: 5, height: 5, borderRadius: 999, background: t.accent }} />}
                  <span style={{ fontSize: 11, color: t.textDim }}>
                    {up && probe?.counts ? `${probe.counts.metrics} m · ${probe.counts.objects} o` : ''}
                  </span>
                </span>
              </div>
              <div style={{ fontSize: 11, color: t.textDim, marginTop: 2, lineHeight: 1.45 }}>
                {p.profile || p.key}
              </div>
              {/* The sections of the OPEN ontology. The framed page carries no rail of its own; this
                  list is the navigation, and it lives under the ontology it belongs to. A hovered row
                  does NOT expand it: expanding was what made hovering read as a selection. */}
              {active && up && (
                <div style={{
                  display: 'flex', flexDirection: 'column', gap: 1, marginTop: 5, paddingLeft: 12,
                  borderLeft: `1px solid ${t.border}`,
                }}>
                  <span style={{ fontSize: 9.5, letterSpacing: 0.5, textTransform: 'uppercase',
                                 color: t.textDim, marginTop: 2 }}>
                    sections
                  </span>
                  <button
                    onClick={async e => {
                      e.stopPropagation();
                      // select THIS row's ontology first: the page then reads `s.preset`, so the schema
                      // and the metrics belong to the row that was clicked, not to the previous one.
                      await ontology.select(p.url, p.key);
                      navigate('/ontology/browse');
                    }}
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
                        onClick={async e => {
                          e.stopPropagation();
                          // the section belongs to THIS row: select it before navigating, otherwise
                          // `/ontology/app` frames whatever `s.preset` still holds (measured: an
                          // ontology's sections opened another ontology's page).
                          await ontology.select(p.url, p.key);
                          // an APP page (the dashboard) is a route in this app; a section page is served
                          // by this app too (`/api/ontology/{key}/page/…`) and framed here.
                          if (sec.kind === 'app') { navigate(sec.path); return; }
                          navigate(sec.key === 'home' ? '/ontology/app' : `/ontology/app?view=${sec.key}`);
                        }}
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
