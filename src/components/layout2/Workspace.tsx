/**
 * Workspace — VS Code-style central editor with tab bar + content.
 *
 * VS Code pattern:
 *   - Tab bar: 35px height, #252526 bg, active tab has #1e1e1e bg + accent bottom border
 *   - Tabs: close-on-hover, drag reorder, middle-click close, dirty dot indicator
 *   - Content: fills remaining space with #1e1e1e bg
 */
import { useRef } from 'react';
import { useLayoutState, type Tab } from './useLayout';
import { useLayoutTokens } from './tokens';
import { X, File, User, BookOpen, BarChart3, Brain } from 'lucide-react';
import FileEditor from './FileEditor';
import DeepAgentEditor from './DeepAgentEditor';

const VIEW_ICONS: Record<string, React.ReactNode> = {
  workflow:  <File size={13} />,
  deepagent: <Brain size={13} />,
  agent:     <User size={13} />,
  library:   <BookOpen size={13} />,
  analysis:  <BarChart3 size={13} />,
};

interface ViewComponentProps {
  tab: Tab;
}

const VIEWS: Record<string, React.FC<ViewComponentProps>> = {
  workflow:  FileEditor,
  deepagent: DeepAgentEditor,
  agent:     FileEditor,
  library:   FileEditor,
  analysis:  FileEditor,
};

interface WorkspaceProps {
  fallback: React.ReactNode;
}

export default function Workspace({ fallback }: WorkspaceProps) {
  const { tabs, activeTabId, setActiveTab, closeTab, moveTab } = useLayoutState();
  const t = useLayoutTokens();
  const dragIndexRef = useRef<number | null>(null);

  const activeTab = tabs.find(t => t.id === activeTabId) ?? null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0, background: t.bgContent }}>
      <style>{`.tab-close-btn { display: none; } div:hover > .tab-close-btn { display: flex; }`}</style>

      {/* ── Tab bar (VS Code style) ────────────────────── */}
      {tabs.length > 0 && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            height: 35,
            minHeight: 35,
            background: t.bgTabBar,
            borderBottom: `1px solid ${t.bgContent}`,
            overflowX: 'auto',
            overflowY: 'hidden',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', height: '100%', gap: 0 }}>
            {tabs.map((tab, index) => {
              const isActive = tab.id === activeTabId;
              return (
                <div
                  key={tab.id}
                  title={tab.label}
                  draggable
                  onClick={() => setActiveTab(tab.id)}
                  onMouseDown={e => { if (e.button === 1) { e.preventDefault(); closeTab(tab.id); } }}
                  onDragStart={() => { dragIndexRef.current = index; }}
                  onDragOver={e => e.preventDefault()}
                  onDrop={() => {
                    const from = dragIndexRef.current;
                    if (from !== null && from !== index) { moveTab(from, index); }
                    dragIndexRef.current = null;
                  }}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                    height: '100%',
                    padding: '0 10px',
                    fontSize: 12,
                    color: isActive ? t.textPrimary : t.textMuted,
                    background: isActive ? t.bgContent : 'transparent',
                    borderBottom: isActive ? `2px solid ${t.accent}` : '2px solid transparent',
                    cursor: 'pointer',
                    whiteSpace: 'nowrap',
                    userSelect: 'none',
                    position: 'relative',
                  }}
                >
                  {VIEW_ICONS[tab.viewType] && (
                    <span style={{ opacity: 0.6, display: 'flex' }}>{VIEW_ICONS[tab.viewType]}</span>
                  )}
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 160 }}>{tab.label}</span>
                  {tab.dirty ? (
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: t.accent, minWidth: 8 }} />
                  ) : (
                    <button
                      onClick={e => { e.stopPropagation(); closeTab(tab.id); }}
                      style={{
                        display: 'none',
                        alignItems: 'center',
                        justifyContent: 'center',
                        width: 16,
                        height: 16,
                        border: 'none',
                        background: 'transparent',
                        color: t.textMuted,
                        cursor: 'pointer',
                        padding: 0,
                      }}
                      className="tab-close-btn"
                      onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
                      onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                    >
                      <X size={12} />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Content area ───────────────────────────────── */}
      <div style={{ flex: 1, minHeight: 0, background: t.bgContent, overflow: 'auto' }}>
        {activeTab ? <TabContentView tab={activeTab} /> : fallback}
      </div>
    </div>
  );
}

function TabContentView({ tab }: { tab: Tab }) {
  const View = VIEWS[tab.viewType];
  if (View) return <View tab={tab} />;
  return (
    <div style={{ padding: 24, color: 'inherit' }}>
      <p style={{ opacity: 0.5 }}>{tab.viewType}</p>
      <p>{tab.label}</p>
    </div>
  );
}
