/**
 * Workspace — the central editor area with tab bar + content.
 *
 * Acts like Obsidian's tabbed document area. Each tab represents
 * an open "document" (workflow, playground, analysis, etc.).
 * The active tab's view type determines which page component to render.
 */
import { useLayoutState, type Tab } from './useLayout';
import { useLayoutTokens } from './tokens';
import { X, Workflow, User, BookOpen, BarChart3 } from 'lucide-react';

// ── View icon map ───────────────────────────────────────
const VIEW_ICONS: Record<string, React.ReactNode> = {
  workflow:  <Workflow size={14} />,
  agent:     <User size={14} />,
  library:   <BookOpen size={14} />,
  analysis:  <BarChart3 size={14} />,
};

// ── View router ──────────────────────────────────────────
// Maps viewType string → React component for the tab content area.
// We add entries as we migrate pages into the tab system.

interface ViewComponentProps {
  tab: Tab;
  onClose?: () => void;
}

const VIEWS: Record<string, React.FC<ViewComponentProps>> = {
  workflow:  WorkflowView,
  agent:     AgentView,
  library:   LibraryView,
  analysis:  AnalysisView,
};

interface WorkspaceProps {
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
                  {/* View type icon */}
                  {VIEW_ICONS[tab.viewType] && (
                    <span style={{ opacity: 0.6, display: 'flex' }}>
                      {VIEW_ICONS[tab.viewType]}
                    </span>
                  )}
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

// ── View Components ──────────────────────────────────────

function TabContentView({ tab }: { tab: Tab }) {
  const View = VIEWS[tab.viewType];
  if (View) return <View tab={tab} />;

  // Fallback for unregistered view types
  return (
    <div style={{ padding: 24, color: 'inherit' }}>
      <p style={{ opacity: 0.5 }}>{tab.viewType}</p>
      <p>{tab.label}</p>
    </div>
  );
}

/** Placeholder workflow view — will be replaced with WorkflowCanvas */
function WorkflowView({ tab }: ViewComponentProps) {
  const t = useLayoutTokens();
  return (
    <div style={{ padding: 32, color: t.textPrimary }}>
      <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>{tab.label}</h2>
      <p style={{ color: t.textMuted, fontSize: 14 }}>
        Workflow canvas will render here.
      </p>
    </div>
  );
}

/** Placeholder agent view */
function AgentView({ tab }: ViewComponentProps) {
  const t = useLayoutTokens();
  return (
    <div style={{ padding: 32, color: t.textPrimary }}>
      <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>{tab.label}</h2>
      <p style={{ color: t.textMuted, fontSize: 14 }}>
        Agent detail will render here.
      </p>
    </div>
  );
}

/** Placeholder library (skill/tool/prompt) view */
function LibraryView({ tab }: ViewComponentProps) {
  const t = useLayoutTokens();
  return (
    <div style={{ padding: 32, color: t.textPrimary }}>
      <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>{tab.label}</h2>
      <p style={{ color: t.textMuted, fontSize: 14 }}>
        Library item detail will render here.
      </p>
    </div>
  );
}

/** Placeholder analysis view */
function AnalysisView({ tab }: ViewComponentProps) {
  const t = useLayoutTokens();
  return (
    <div style={{ padding: 32, color: t.textPrimary }}>
      <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>{tab.label}</h2>
      <p style={{ color: t.textMuted, fontSize: 14 }}>
        Dashboard will render here.
      </p>
    </div>
  );
}
