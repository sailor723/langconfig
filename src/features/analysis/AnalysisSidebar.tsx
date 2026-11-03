/**
 * Analysis sidebar — the dashboard browser, in the left rail like every other
 * activity's browser.
 *
 * One row per DATABASE, not per page. 38 pages is a file tree; a user cannot tell
 * "sunhing_dashboard_liability.html" from "sunhing_gantt.html" without opening
 * both. The row shows the database name and how many pages it owns; clicking it
 * opens that database's home page. Pages inside it are reachable from the home
 * page's own nav (Hub / Revenue / Catalog / …), which is where a reader looks.
 */
import { useEffect } from 'react';
import { Monitor, Search, RefreshCw, Loader2, X } from 'lucide-react';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { analysis, useAnalysisState } from './analysisStore';

export default function AnalysisSidebar() {
  const t = useLayoutTokens();
  const s = useAnalysisState();

  useEffect(() => {
    void analysis.loadDashboards();
  }, []);

  const q = s.query.trim().toLowerCase();
  const rows = s.databases.filter(
    d => !q || d.name.toLowerCase().includes(q) || d.key.toLowerCase().includes(q),
  );

  const sectionTitle: React.CSSProperties = {
    fontSize: 10.5,
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
    color: t.textDim,
    padding: '8px 10px 4px',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 10px 6px', flexShrink: 0 }}>
        {/* Clicking the section title IS the way home: no extra Home row, and it
            clears any database selection so the board (one card per database) is
            what you see. */}
        <button
          onClick={() => analysis.openHome()}
          title="回到 Home"
          style={{
            display: 'flex', alignItems: 'center', gap: 6, padding: 0,
            border: 'none', background: 'transparent', cursor: 'pointer',
            color: s.activeDb === null ? t.textPrimary : t.textMuted,
          }}
          onMouseEnter={e => { e.currentTarget.style.color = t.textPrimary; }}
          onMouseLeave={e => { e.currentTarget.style.color = s.activeDb === null ? t.textPrimary : t.textMuted; }}
        >
          <Monitor size={13} color={t.accent} />
          <span style={{ fontSize: 11.5, fontWeight: 700 }}>Dashboards</span>
          <span style={{ fontSize: 10, color: t.textDim }}>{s.databases.length} db</span>
        </button>
        <button
          onClick={() => void analysis.loadDashboards()}
          title="Refresh"
          style={{
            marginLeft: 'auto', border: 'none', background: 'transparent',
            color: t.textDim, cursor: 'pointer', display: 'flex', alignItems: 'center',
          }}
        >
          {s.loading
            ? <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} />
            : <RefreshCw size={12} />}
        </button>
      </div>

      <div style={{ padding: '0 8px 6px', flexShrink: 0 }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 5,
          background: t.bgContent, border: `1px solid ${t.border}`,
          borderRadius: 4, padding: '0 6px', height: 24,
        }}>
          <Search size={11} color={t.textDim} />
          <input
            value={s.query}
            onChange={e => analysis.setQuery(e.target.value)}
            placeholder="筛选数据库…"
            style={{
              flex: 1, minWidth: 0, border: 'none', outline: 'none',
              background: 'transparent', color: t.textPrimary, fontSize: 11,
            }}
          />
          {s.query && (
            <button onClick={() => analysis.setQuery('')}
              style={{ border: 'none', background: 'transparent', color: t.textDim, cursor: 'pointer', display: 'flex' }}>
              <X size={11} />
            </button>
          )}
        </div>
      </div>

      <div style={{ ...sectionTitle, paddingTop: 2 }}>数据库 · {rows.length}</div>

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '0 6px 10px' }}>
        {s.error && <div style={{ fontSize: 11, color: '#e5484d', padding: '6px 8px' }}>{s.error}</div>}
        {!s.error && rows.length === 0 && (
          <div style={{ fontSize: 11, color: t.textDim, padding: '10px 8px', lineHeight: '16px' }}>
            {s.databases.length === 0 ? '还没有 dashboard。' : '没有匹配的数据库'}
          </div>
        )}
        {rows.map(d => {
          const active = s.activeDb === d.key;
          return (
            <button
              key={d.key}
              onClick={() => analysis.openDatabase(d.key)}
              title={d.intro}
              style={{
                display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 2,
                width: '100%', padding: '6px 8px 6px 10px', margin: '1px 0',
                border: 'none',
                borderLeft: active ? `2px solid ${t.accent}` : '2px solid transparent',
                borderRadius: 6,
                background: active ? t.bgSelected : 'transparent',
                cursor: 'pointer', textAlign: 'left',
              }}
              onMouseEnter={e => { if (!active) e.currentTarget.style.background = t.bgHover; }}
              onMouseLeave={e => { if (!active) e.currentTarget.style.background = 'transparent'; }}
            >
              <span style={{
                fontSize: 12, fontWeight: active ? 600 : 500,
                color: active ? t.textWhite : t.textPrimary,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '100%',
              }}>
                {d.name}
              </span>
              <span style={{ display: 'flex', gap: 6, fontSize: 10, color: t.textDim, alignItems: 'center' }}>
                <span style={{ fontFamily: 'monospace' }}>{d.key}</span>
                <span>{d.pages} 页</span>
                {!d.home && <span style={{ color: '#e5484d' }}>no home</span>}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
