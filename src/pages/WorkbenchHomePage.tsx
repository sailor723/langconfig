/**
 * WorkbenchHomePage — one card per ontology, with what it actually declares.
 *
 * The card is the honest summary: counts from the profile that is RUNNING (or the reason it
 * is not), the namespace, the guard limits that decide what a question may do, and the two
 * actions that matter — browse the declarations, or open the workbench itself. Numbers are
 * read from the workbench, never typed into the card.
 */
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Boxes, ListTree, Play, RefreshCw, AlertTriangle, ShieldCheck, Loader2 } from 'lucide-react';
import { useLayoutTokens } from '../components/layout2/tokens';
import { PRESETS, workbench, useWorkbench } from '../features/workbench/workbenchStore';

export default function WorkbenchHomePage() {
  const t = useLayoutTokens();
  const navigate = useNavigate();
  const s = useWorkbench();

  useEffect(() => {
    void workbench.probeAll();
  }, []);

  const card: React.CSSProperties = {
    background: t.bgInput,
    border: `1px solid ${t.border}`,
    borderRadius: 10,
    padding: '14px 16px',
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    minHeight: 168,
  };

  const stat = (label: string, value: React.ReactNode, dim = false) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <span style={{ fontSize: 16, fontWeight: 600, color: dim ? t.textMuted : t.textPrimary }}>
        {value}
      </span>
      <span style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5, color: t.textDim }}>
        {label}
      </span>
    </div>
  );

  return (
    <div style={{ height: '100%', overflowY: 'auto', padding: '22px 26px 40px' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 10, marginBottom: 4 }}>
        <Boxes size={20} color={t.accent} />
        <h1 style={{ margin: 0, fontSize: 19, fontWeight: 650, color: t.textPrimary }}>Workbench</h1>
        <button
          onClick={() => void workbench.probeAll()}
          style={{
            marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6,
            fontSize: 11.5, padding: '5px 10px', borderRadius: 999, cursor: 'pointer',
            border: `1px solid ${t.border}`, background: 'transparent', color: t.textMuted,
          }}
        >
          <RefreshCw size={11} /> re-probe
        </button>
      </div>
      <p style={{ margin: '0 0 20px', fontSize: 12.5, color: t.textMuted, maxWidth: 780, lineHeight: 1.6 }}>
        An ontology is a set of declarations a number is compiled from. Each card is one
        profile a workbench server can load — the counts come from that server, not from a
        catalogue. A profile that is not running is listed with the reason it is off.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 14 }}>
        {PRESETS.map(p => {
          const probe = s.probes[p.url];
          const up = probe?.status === 'up';
          const c = probe?.counts;
          const loading = probe?.status === 'unknown';
          return (
            <div key={p.key} style={{ ...card, opacity: up ? 1 : 0.92 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 14, fontWeight: 650, color: t.textPrimary }}>{p.label}</span>
                <span
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 10,
                    padding: '1px 7px', borderRadius: 999,
                    background: up ? '#e9f7f0' : loading ? '#fdf6e3' : '#fdecea',
                    color: up ? '#12805c' : loading ? '#8a6d3b' : '#b3261e',
                  }}
                >
                  {loading && <Loader2 size={9} className="animate-spin" />}
                  {up ? 'running' : loading ? 'probing' : 'not running'}
                </span>
              </div>

              <div style={{ fontSize: 10.5, color: t.textDim, fontFamily: 'ui-monospace, Menlo, monospace' }}>
                {p.url} · {p.profile}
              </div>
              <div style={{ fontSize: 11.5, color: t.textMuted, lineHeight: 1.5 }}>{p.note}</div>

              {up && c ? (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 6, marginTop: 2 }}>
                  {stat('objects', c.objects)}
                  {stat('definitions', c.definitions)}
                  {stat('links', c.links)}
                  {stat('metrics', c.metrics)}
                  {stat('refused', c.refused, c.refused > 0)}
                </div>
              ) : (
                <div style={{ fontSize: 11, color: '#b3261e', display: 'flex', gap: 5, alignItems: 'flex-start' }}>
                  <AlertTriangle size={12} style={{ flex: 'none', marginTop: 2 }} />
                  <span>
                    {probe?.error || 'probing…'}
                    <br />
                    <code style={{ fontFamily: 'ui-monospace, Menlo, monospace', fontSize: 10 }}>
                      {`serve_ui.py --settings ${p.profile} --port ${new URL(p.url).port}`}
                    </code>
                  </span>
                </div>
              )}

              <div style={{ display: 'flex', gap: 8, marginTop: 'auto', paddingTop: 4 }}>
                <button
                  disabled={!up}
                  onClick={async () => { await workbench.select(p.url, p.key); navigate('/workbench/browse'); }}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11.5,
                    padding: '6px 11px', borderRadius: 7, cursor: up ? 'pointer' : 'default',
                    border: 'none', background: up ? t.accent : t.border,
                    color: up ? '#fff' : t.textDim, opacity: up ? 1 : 0.7,
                  }}
                >
                  <ListTree size={12} /> Browse
                </button>
                <button
                  disabled={!up}
                  onClick={async () => { await workbench.select(p.url, p.key); navigate('/workbench/app'); }}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11.5,
                    padding: '6px 11px', borderRadius: 7, cursor: up ? 'pointer' : 'default',
                    border: `1px solid ${t.border}`, background: 'transparent',
                    color: up ? t.textMuted : t.textDim,
                  }}
                >
                  <Play size={12} /> Open app
                </button>
              </div>
            </div>
          );
        })}
      </div>

      <div
        style={{
          marginTop: 22, padding: '12px 14px', borderRadius: 9,
          border: `1px solid ${t.border}`, background: t.bgTabBar,
          fontSize: 11.5, color: t.textMuted, lineHeight: 1.65, maxWidth: 820,
        }}
      >
        <ShieldCheck size={13} color={t.accent} style={{ verticalAlign: '-2px', marginRight: 6 }} />
        Every number a workbench serves comes from the profile's ontology and its SQL guardrails
        — page cap, time bound, plan budget, statement timeout. The browser shows the other
        half: what is <i>declared</i>, which metrics compile, and which refuse by name.
      </div>
    </div>
  );
}
