/**
 * ActivityBar — VS Code-style 48px left icon strip.
 *
 * VS Code pattern:
 *   - 48px wide, #181818 background (darker than sidebar)
 *   - Icons grouped at top, settings at bottom
 *   - Active icon: left 2px white accent bar
 *   - Hover: subtle bg change
 */
import { useLayoutState, ACTIVITIES, type ActivityId } from './useLayout';
import { useLayoutTokens } from './tokens';
import {
  GitBranch, Brain, BookOpen, BarChart3, Settings, type LucideIcon,
} from 'lucide-react';

const ICON_MAP: Record<ActivityId, LucideIcon> = {
  workflows: GitBranch,
  agents:    Brain,
  library:   BookOpen,
  analysis:  BarChart3,
  settings:  Settings,
};

const MAIN_ACTIVITIES = ACTIVITIES.filter(a => a.id !== 'settings');
const SETTINGS_ACTIVITY = ACTIVITIES.find(a => a.id === 'settings')!;

export default function ActivityBar() {
  const { activeActivity, setActiveActivity, sidebarOpen, toggleSidebar } = useLayoutState();
  const t = useLayoutTokens();

  return (
    <div
      style={{
        width: 48,
        minWidth: 48,
        background: t.bgActivityBar,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        userSelect: 'none',
      }}
    >
      {/* Main activity icons */}
      {MAIN_ACTIVITIES.map(act => {
        const Icon = ICON_MAP[act.id];
        const isActive = act.id === activeActivity;
        return (
          <button
            key={act.id}
            title={act.label}
            onClick={() => setActiveActivity(act.id)}
            style={{
              width: 48,
              height: 48,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: 'transparent',
              color: isActive ? t.textWhite : '#6b6b6b',
              border: 'none',
              cursor: 'pointer',
              position: 'relative',
            }}
            onMouseEnter={e => {
              if (!isActive) e.currentTarget.style.background = 'rgba(255,255,255,0.06)';
            }}
            onMouseLeave={e => {
              if (!isActive) e.currentTarget.style.background = 'transparent';
            }}
          >
            {/* Left-edge white accent indicator (VS Code pattern) */}
            {isActive && (
              <span
                style={{
                  position: 'absolute',
                  left: 0,
                  top: 8,
                  bottom: 8,
                  width: 2,
                  background: t.textWhite,
                }}
              />
            )}
            <Icon size={20} strokeWidth={isActive ? 2 : 1.5} />
          </button>
        );
      })}

      <div style={{ flex: 1 }} />

      {/* Settings — pinned to bottom */}
      <button
        title={SETTINGS_ACTIVITY.label}
        onClick={() => setActiveActivity(SETTINGS_ACTIVITY.id)}
        style={{
          width: 48,
          height: 48,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'transparent',
          color: activeActivity === 'settings' ? t.textWhite : '#6b6b6b',
          border: 'none',
          cursor: 'pointer',
          position: 'relative',
        }}
        onMouseEnter={e => {
          if (activeActivity !== 'settings') e.currentTarget.style.background = 'rgba(255,255,255,0.06)';
        }}
        onMouseLeave={e => {
          if (activeActivity !== 'settings') e.currentTarget.style.background = 'transparent';
        }}
      >
        {activeActivity === 'settings' && (
          <span
            style={{
              position: 'absolute',
              left: 0,
              top: 8,
              bottom: 8,
              width: 2,
              background: t.textWhite,
            }}
          />
        )}
        <Settings size={20} strokeWidth={activeActivity === 'settings' ? 2 : 1.5} />
      </button>

      {/* Toggle sidebar */}
      <button
        title="Toggle sidebar"
        onClick={toggleSidebar}
        style={{
          width: 48,
          height: 48,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'transparent',
          color: '#6b6b6b',
          border: 'none',
          cursor: 'pointer',
          borderTop: '1px solid rgba(255,255,255,0.06)',
        }}
        onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.06)'; }}
        onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
      >
        {sidebarOpen ? (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <line x1="9" y1="3" x2="9" y2="21" />
          </svg>
        ) : (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <rect x="3" y="3" width="18" height="18" rx="2" />
          </svg>
        )}
      </button>
    </div>
  );
}
