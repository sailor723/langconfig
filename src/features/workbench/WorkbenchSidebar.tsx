/**
 * WorkbenchSidebar — the ontology browser in the left rail, like every other activity's
 * browser (Analysis lists dashboards, this lists ontologies).
 *
 * One row per ONTOLOGY (a profile the workbench can load), not per file: a profile is the
 * unit a number is compiled from, so it is the unit a reader picks. A row's dot is the
 * liveness of that workbench — a profile that is not running is shown as off, not hidden,
 * because "why is it empty" is the question a hidden row creates.
 */
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Boxes, RefreshCw, Loader2, Play, ListTree } from 'lucide-react';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { PRESETS, workbench, useWorkbench } from './workbenchStore';

export default function WorkbenchSidebar() {
  const t = useLayoutTokens();
  const navigate = useNavigate();
  const s = useWorkbench();

  useEffect(() => {
    if (Object.keys(s.probes).length === 0) void workbench.probeAll();
  }, []);

  const rowTitle: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 6, padding: 0,
    border: 'none', background: 'transparent', cursor: 'pointer',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 10px 6px', flexShrink: 0 }}>
        {/* The section title is the way home, as in the Analysis rail. */}
        <button
          onClick={() => navigate('/workbench')}
          title="Workbench home"
          style={{ ...rowTitle, color: s.ontology ? t.textMuted : t.textPrimary }}
        >
          <Boxes size={13} color={t.accent} />
          <span style={{ fontSize: 11.5, fontWeight: 700 }}>Ontologies</span>
          <span style={{ fontSize: 10, color: t.textDim }}>
            {PRESETS.filter(p => s.probes[p.url]?.status === 'up').length}/{PRESETS.length}
          </span>
        </button>
        <button
          onClick={() => void workbench.probeAll()}
          title="re-probe every workbench"
          style={{ ...rowTitle, marginLeft: 'auto', color: t.textDim }}
        >
          <RefreshCw size={12} />
        </button>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
        {PRESETS.map(p => {
          const probe = s.probes[p.url];
          const active = s.url === p.url;
          const up = probe?.status === 'up';
          return (
            <div
              key={p.key}
              style={{
                padding: '6px 10px',
                background: active ? t.bgSelected : 'transparent',
                borderLeft: `2px solid ${active ? t.accent : 'transparent'}`,
                cursor: 'pointer',
              }}
              onMouseEnter={e => { if (!active) e.currentTarget.style.background = t.bgHover; }}
              onMouseLeave={e => { if (!active) e.currentTarget.style.background = 'transparent'; }}
              onClick={async () => {
                await workbench.select(p.url, p.key);
                navigate('/workbench/browse');
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
                <span style={{ fontSize: 12, fontWeight: active ? 600 : 500, color: t.textPrimary }}>
                  {p.label}
                </span>
                {probe?.status === 'unknown' && <Loader2 size={10} className="animate-spin" />}
                <span style={{ marginLeft: 'auto', fontSize: 10, color: t.textDim }}>
                  {up && probe?.counts ? `${probe.counts.metrics} m · ${probe.counts.objects} o` : ''}
                </span>
              </div>
              <div style={{ fontSize: 10.5, color: t.textDim, marginTop: 2, lineHeight: 1.4 }}>
                {p.profile}
              </div>
              {active && up && (
                <div style={{ display: 'flex', gap: 10, marginTop: 5 }}>
                  <button
                    onClick={e => { e.stopPropagation(); navigate('/workbench/browse'); }}
                    style={{ ...rowTitle, fontSize: 10.5, color: t.accent }}
                  >
                    <ListTree size={11} /> browse
                  </button>
                  <button
                    onClick={e => { e.stopPropagation(); navigate('/workbench/app'); }}
                    style={{ ...rowTitle, fontSize: 10.5, color: t.textMuted }}
                  >
                    <Play size={11} /> open app
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div style={{ padding: '6px 10px', borderTop: `1px solid ${t.border}`, fontSize: 10, color: t.textDim, lineHeight: 1.5 }}>
        A workbench server loads one profile and compiles every number from it.
        <br />
        Start one: <code style={{ fontFamily: 'ui-monospace, Menlo, monospace' }}>
          serve_ui.py --settings &lt;profile&gt;
        </code>
      </div>
    </div>
  );
}
