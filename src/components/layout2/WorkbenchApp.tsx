/**
 * WorkbenchApp — the ontology workbench, opened from the ActivityBar as an application.
 *
 * The workbench is not a page of this app: it is a separate server (`retail_graph/
 * serve_ui.py`) that loads ONE profile — the ontology, its overlay and its profile file —
 * and compiles every number from that profile. So this view is a host, not a reimplementation:
 * it frames the running workbench, keeps the URL in the address of a small chrome bar, and
 * tells you plainly when the server is not answering instead of showing a blank frame that
 * looks like a broken page.
 *
 * Why an iframe and not a proxy: the workbench serves its own JSON endpoints and its own
 * CSP-free HTML for a specific origin; proxying it would mean re-implementing its routes
 * here and drifting from them. The one thing a frame cannot do is tell us it failed, so the
 * liveness check is a separate `fetch` against `/api/metrics/import` (the read-only state
 * endpoint) — that is the honest signal.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ExternalLink, RefreshCw, ServerCrash, Server, ChevronDown } from 'lucide-react';
import { useLayoutTokens } from './tokens';

/** Presets come from the profiles that exist on disk; the list is data, not logic. */
const DEFAULT_WORKBENCH = 'http://127.0.0.1:8096';

const PRESETS: Array<{ label: string; url: string; profile: string }> = [
  { label: 'Clinic', url: 'http://127.0.0.1:8096', profile: 'ontologies/clinic/clinic_settings.json' },
  { label: 'Retail', url: 'http://127.0.0.1:8092', profile: 'retail_graph/settings.json' },
  { label: 'TPC-H', url: 'http://127.0.0.1:8093', profile: 'retail_graph/tpch_settings.json' },
  { label: 'ABC', url: 'http://127.0.0.1:8094', profile: 'retail_graph/abc_settings.json' },
];

const STORAGE_KEY = 'langconfig.workbench.url';

type State = 'checking' | 'up' | 'down';

export default function WorkbenchApp() {
  const t = useLayoutTokens();
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [url, setUrl] = useState<string>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) || DEFAULT_WORKBENCH;
    } catch {
      return DEFAULT_WORKBENCH;
    }
  });
  const [draft, setDraft] = useState(url);
  const [state, setState] = useState<State>('checking');
  const [detail, setDetail] = useState<string>('');
  const [metrics, setMetrics] = useState<number | null>(null);
  const [nonce, setNonce] = useState(0);

  const origin = useMemo(() => {
    try {
      return new URL(url).origin;
    } catch {
      return '';
    }
  }, [url]);

  const probe = useCallback(async () => {
    setState('checking');
    setDetail('');
    setMetrics(null);
    if (!origin) {
      setState('down');
      setDetail('not a URL');
      return;
    }
    try {
      const res = await fetch(`${origin}/api/metrics/import`, { signal: AbortSignal.timeout(4000) });
      const body = await res.json();
      if (!res.ok || !body?.ok) {
        setState('down');
        setDetail(body?.error || `HTTP ${res.status}`);
        return;
      }
      setState('up');
      setMetrics(Array.isArray(body.metrics) ? body.metrics.length : 0);
      setDetail(body.profile || '');
    } catch (err: any) {
      // A workbench that is not running is the common case (it is a separate server), so
      // say how to start it rather than leaving the user with a blank frame.
      setState('down');
      setDetail(err?.name === 'TimeoutError' ? 'no answer in 4s' : String(err?.message || err));
    }
  }, [origin]);

  useEffect(() => {
    probe();
  }, [probe, nonce]);

  const applyUrl = (next: string) => {
    const clean = next.trim().replace(/\/+$/, '');
    setUrl(clean);
    setDraft(clean);
    try {
      localStorage.setItem(STORAGE_KEY, clean);
    } catch {
      /* private mode: the URL simply does not persist */
    }
    setNonce(n => n + 1);
  };

  const bar: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '8px 12px',
    borderBottom: `1px solid ${t.border}`,
    background: t.bgTabBar,
    font: '12px -apple-system, "Segoe UI", Roboto, sans-serif',
    color: t.textPrimary,
    flex: 'none',
  };

  const chip = (active: boolean): React.CSSProperties => ({
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: '4px 9px',
    borderRadius: 999,
    border: `1px solid ${active ? (t.accent) : (t.border)}`,
    background: active ? `${t.accent}14` : 'transparent',
    color: active ? (t.accent) : (t.textMuted),
    cursor: 'pointer',
    fontSize: 11,
    whiteSpace: 'nowrap',
  });

  const badge = state === 'up'
    ? { color: '#12805c', bg: '#e9f7f0', text: metrics !== null ? `running · ${metrics} metrics` : 'running' }
    : state === 'down'
      ? { color: '#b3261e', bg: '#fdecea', text: 'not answering' }
      : { color: '#8a6d3b', bg: '#fdf6e3', text: 'checking…' };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, background: t.bgContent }}>
      <div style={bar}>
        <Server size={14} />
        <span style={{ fontWeight: 600, letterSpacing: 0.2 }}>Workbench</span>

        <span
          title={detail || undefined}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 5, padding: '2px 8px',
            borderRadius: 999, background: badge.bg, color: badge.color, fontSize: 11,
          }}
        >
          {state === 'down' && <ServerCrash size={11} />}
          {badge.text}
        </span>

        {PRESETS.map(p => (
          <button
            key={p.url}
            style={chip(url === p.url)}
            title={p.profile}
            onClick={() => applyUrl(p.url)}
          >
            {p.label}
          </button>
        ))}

        <form
          onSubmit={e => { e.preventDefault(); applyUrl(draft); }}
          style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 'auto' }}
        >
          <input
            value={draft}
            onChange={e => setDraft(e.target.value)}
            spellCheck={false}
            style={{
              width: 260, font: '11px ui-monospace, Menlo, monospace',
              padding: '4px 8px', borderRadius: 6,
              border: `1px solid ${t.border}`,
              background: t.bgInput, color: t.textPrimary,
            }}
            placeholder="http://127.0.0.1:8096"
          />
          <button type="submit" style={chip(false)} title="load this workbench">
            <ChevronDown size={11} style={{ transform: 'rotate(-90deg)' }} /> load
          </button>
        </form>

        <button style={chip(false)} onClick={() => setNonce(n => n + 1)} title="re-check and reload">
          <RefreshCw size={11} /> reload
        </button>
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          style={{ ...chip(false), textDecoration: 'none' }}
          title="open in a new tab (the workbench keeps its own URLs)"
        >
          <ExternalLink size={11} /> open
        </a>
      </div>

      {state === 'down' && (
        <div style={{ margin: '10px 12px 0', padding: '10px 12px', borderRadius: 8, background: '#fdecea', color: '#8c1d18', fontSize: 12, lineHeight: 1.55 }}>
          <b>No workbench at {origin || url}</b>{detail ? ` — ${detail}` : ''}.<br />
          Start one with a profile, then press reload:
          <div style={{ font: '11px ui-monospace, Menlo, monospace', marginTop: 6, whiteSpace: 'pre-wrap' }}>
            {`cd ontology && python3 retail_graph/serve_ui.py \\\n    --settings ontologies/clinic/clinic_settings.json --port 8096`}
          </div>
        </div>
      )}

      <iframe
        key={`${url}#${nonce}`}
        ref={iframeRef}
        src={url}
        title="Ontology workbench"
        style={{ flex: 1, width: '100%', border: 'none', minHeight: 0, background: '#fff' }}
        // The workbench needs its own storage for its language/profile prefs; it is a
        // trusted local server, not third-party content.
        sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-downloads"
      />
    </div>
  );
}
