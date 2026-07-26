/**
 * Workspace — the central editor area with tab bar + content.
 *
 * Acts like Obsidian's tabbed document area. Each tab represents
 * an open "document" (workflow, playground, analysis, etc.).
 * The active tab's view type determines which page component to render.
 */
import { useLayoutState, type Tab } from './useLayout';
import { useLayoutTokens } from './tokens';
import { X } from 'lucide-react';

// ── View router ──────────────────────────────────────────
// Maps viewType string → React component for the tab content area.
// We add entries as we migrate pages into the tab system.
const VIEWS: Record<string, React.FC<{ tab: Tab }>> = {};

interface WorkspaceProps {
  /** Fallback content when no tab is open — shows a "home" view for the active activity */
  fallback: React.ReactNode;
}

export default function Workspace({ fallback }: WorkspaceProps) {
  const { tabs, activeTabId, setActiveTab, closeTab } = useLayoutState();
  const t = useLayoutTokens();

  const activeTab = tabs.find(t => t.id === activeTabId) ?? null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0, background: t.bgBase }}>
      {/* ── Tab bar ─────────────────────────────────────── */}
      {tabs.length > 0 && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            height: 36,
            minHeight: 36,
            background: t.bgBase,
            borderBottom: `1px solid ${t.border}`,
            overflowX: 'auto',
            overflowY: 'hidden',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', height: '100%', gap: 0 }}>
            {tabs.map(tab => {
              const isActive = tab.id === activeTabId;
              return (
                <div
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    height: '100%',
                    padding: '0 10px',
                    fontSize: 13,
                    color: isActive ? t.textPrimary : t.textMuted,
                    background: isActive ? t.bgContent : 'transparent',
                    borderRight: `1px solid ${t.border}`,
                    cursor: 'pointer',
                    whiteSpace: 'nowrap',
                    userSelect: 'none',
                    position: 'relative',
                    minWidth: 0,
                  }}
                >
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {tab.label}
                  </span>
                  {tab.dirty && (
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: t.accent, minWidth: 8 }} />
                  )}
                  <button
                    onClick={e => { e.stopPropagation(); closeTab(tab.id); }}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      width: 18,
                      height: 18,
                      borderRadius: 4,
                      border: 'none',
                      background: 'transparent',
                      color: t.textMuted,
                      cursor: 'pointer',
                      padding: 0,
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                  >
                    <X size={14} />
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Content area ────────────────────────────────── */}
      <div style={{ flex: 1, minHeight: 0, background: t.bgContent, overflow: 'auto' }}>
        {activeTab ? (
          <TabContentView tab={activeTab} />
        ) : (
          fallback
        )}
      </div>
    </div>
  );
}

/** Renders the appropriate view component for a given tab type. */
function TabContentView({ tab }: { tab: Tab }) {
  const View = VIEWS[tab.viewType];
  if (View) return <View tab={tab} />;

  // Fallback: show a simple placeholder with the tab info
  return (
    <div style={{ padding: 24, color: 'inherit' }}>
      <p style={{ opacity: 0.5 }}>View: {tab.viewType}</p>
      <p>{tab.label}</p>
    </div>
  );
}
