/**
 * ActivityBar — the 48px vertical icon strip on the left edge.
 *
 * Inspired by Obsidian's "Ribbon" / VS Code's "Activity Bar".
 * Each icon represents a top-level activity mode that changes
 * what the sidebar and workspace show.
 */
import { useLayoutState, ACTIVITIES, type ActivityId } from './useLayout';
import { useLayoutTokens } from './tokens';
import {
  GitBranch, Brain, BookOpen, BarChart3, Settings, type LucideIcon,
} from 'lucide-react';

// Map activity id → lucide icon component
const ICON_MAP: Record<ActivityId, LucideIcon> = {
  workflows: GitBranch,
  agents:    Brain,
  library:   BookOpen,
  analysis:  BarChart3,
  settings:  Settings,
};

export default function ActivityBar() {
  const { activeActivity, setActiveActivity, sidebarOpen, toggleSidebar } = useLayoutState();
  const t = useLayoutTokens();

  return (
    <div
      style={{
        width: 48,
        minWidth: 48,
        background: t.bgBase,
        borderRight: `1px solid ${t.border}`,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        paddingTop: 8,
        gap: 2,
        userSelect: 'none',
      }}
    >
      {ACTIVITIES.map(act => {
        const Icon = ICON_MAP[act.id];
        const isActive = act.id === activeActivity;
        return (
          <button
            key={act.id}
            title={act.label}
            onClick={() => setActiveActivity(act.id)}
            style={{
              width: 36,
              height: 36,
              borderRadius: 8,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: isActive ? t.bgSelected : 'transparent',
              color: isActive ? t.accent : t.textMuted,
              border: 'none',
              cursor: 'pointer',
              position: 'relative',
            }}
            onMouseEnter={e => {
              if (!isActive) e.currentTarget.style.background = t.bgHover;
            }}
            onMouseLeave={e => {
              if (!isActive) e.currentTarget.style.background = 'transparent';
            }}
          >
            <Icon size={20} strokeWidth={isActive ? 2.5 : 1.75} />
            {/* Active indicator dot */}
            {isActive && (
              <div
                style={{
                  position: 'absolute',
                  left: -6,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  width: 3,
                  height: 18,
                  borderRadius: 2,
                  background: t.accent,
                }}
              />
            )}
          </button>
        );
      })}

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Toggle sidebar (same icon as active activity's icon) */}
      <button
        title="Toggle sidebar"
        onClick={toggleSidebar}
        style={{
          width: 36,
          height: 36,
          borderRadius: 8,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'transparent',
          color: t.textMuted,
          border: 'none',
          cursor: 'pointer',
          marginBottom: 8,
        }}
      >
        {sidebarOpen ? (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <line x1="9" y1="3" x2="9" y2="21" />
          </svg>
        ) : (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <rect x="3" y="3" width="18" height="18" rx="2" />
          </svg>
        )}
      </button>
    </div>
  );
}
