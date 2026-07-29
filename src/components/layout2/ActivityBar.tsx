/**
 * ActivityBar — VS Code-style 48px left icon strip.
 *
 * VS Code pattern:
 *   - 48px wide, #181818 background (darker than sidebar)
 *   - Icons grouped at top, settings at bottom
 *   - Active icon: left 2px white accent bar
 *   - Hover: subtle bg change
 *
 * Settings opens a popover (mirroring agent-workspace) instead of navigating.
 */
import { useState, useRef } from 'react';
import { useLayoutState, ACTIVITIES, type ActivityDef, type ActivityId } from './useLayout';
import { useLayoutTokens } from './tokens';
import {
  GitBranch, Brain, Users, BookOpen, BarChart3, Network, Settings, Sparkles, Globe, Wrench, Database, Award, MessageSquare, type LucideIcon,
} from 'lucide-react';
import SystemSettingsPopover from './SystemSettingsPopover';

const ICON_MAP: Record<ActivityId, LucideIcon> = {
  workflows:  GitBranch,
  deepagents: Brain,
  agents:     Users,
  tools:      Wrench,
  knowledge:  Database,
  models:     Sparkles,
  search:     Globe,
  library:    BookOpen,
  analysis:   BarChart3,
  skills:     Award,
  studio:     Network,
  settings:   Settings,
};

// Activity groups are declared on each ActivityDef.group; we split
// here so we can render them in two visual clusters inside the bar.
const MAIN_ACTIVITIES = ACTIVITIES.filter(a => a.group === 'main' && a.id !== 'settings');
const BOTTOM_ACTIVITIES = ACTIVITIES.filter(a => a.group === 'bottom' && a.id !== 'settings');

interface ActivityButtonProps {
  act: ActivityDef;
  active: boolean;
  onClick: () => void;
}

/** Single icon button in the ActivityBar — shared by main and bottom clusters
 *  so hover/active styling stays in sync and stays uniform (48×48, icon 20). */
function ActivityButton({ act, active, onClick }: ActivityButtonProps) {
  const t = useLayoutTokens();
  const Icon = ICON_MAP[act.id];
  return (
    <button
      title={act.label}
      onClick={onClick}
      style={{
        width: 48,
        height: 48,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'transparent',
        color: active ? t.textWhite : '#6b6b6b',
        border: 'none',
        cursor: 'pointer',
        position: 'relative',
      }}
      onMouseEnter={e => {
        if (!active) e.currentTarget.style.background = 'rgba(255,255,255,0.06)';
      }}
      onMouseLeave={e => {
        if (!active) e.currentTarget.style.background = 'transparent';
      }}
    >
      {active && (
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
      <Icon size={20} strokeWidth={active ? 2 : 1.5} />
    </button>
  );
}

interface ActivityBarProps {
  /** Called after an activity icon is clicked, with the clicked activity id */
  onClickActivity?: (activity: ActivityId) => void;
}

export default function ActivityBar({ onClickActivity }: ActivityBarProps) {
  const { activeActivity, setActiveActivity, sidebarOpen, toggleSidebar, rightPanelOpen, toggleRightPanel } = useLayoutState();
  const t = useLayoutTokens();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsBtnRef = useRef<HTMLButtonElement | null>(null);

  const handleActivityClick = (id: ActivityId) => {
    setActiveActivity(id);
    onClickActivity?.(id);
  };

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
      {MAIN_ACTIVITIES.map(act => (
        <ActivityButton
          key={act.id}
          act={act}
          active={act.id === activeActivity}
          onClick={() => handleActivityClick(act.id)}
        />
      ))}

      {/* Separator before settings-related activities */}
      <div style={{ width: 28, height: 1, background: 'rgba(255,255,255,0.08)', margin: '6px 0' }} />

      {/* Bottom activities — Models, Search (settings-like, not core activities) */}
      {BOTTOM_ACTIVITIES.map(act => (
        <ActivityButton
          key={act.id}
          act={act}
          active={act.id === activeActivity}
          onClick={() => handleActivityClick(act.id)}
        />
      ))}

      <div style={{ flex: 1 }} />

      {/* Settings gear — pinned to bottom, opens popover (no navigation) */}
      <button
        ref={settingsBtnRef}
        title="Settings"
        onClick={() => setSettingsOpen(v => !v)}
        style={{
          width: 48,
          height: 48,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'transparent',
          color: settingsOpen ? t.textWhite : '#6b6b6b',
          border: 'none',
          cursor: 'pointer',
          position: 'relative',
        }}
        onMouseEnter={e => { if (!settingsOpen) e.currentTarget.style.background = 'rgba(255,255,255,0.06)'; }}
        onMouseLeave={e => { if (!settingsOpen) e.currentTarget.style.background = 'transparent'; }}
      >
        {settingsOpen && (
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
        <Settings size={20} strokeWidth={settingsOpen ? 2 : 1.5} />
      </button>

      {settingsOpen && (
        <SystemSettingsPopover
          anchorRef={settingsBtnRef as React.RefObject<HTMLElement | null>}
          onClose={() => setSettingsOpen(false)}
        />
      )}

      {/* Toggle right panel (Chat) */}
      <button
        title={rightPanelOpen ? "Close chat panel" : "Open chat panel"}
        onClick={toggleRightPanel}
        style={{
          width: 48,
          height: 48,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'transparent',
          color: rightPanelOpen ? t.textWhite : '#6b6b6b',
          border: 'none',
          cursor: 'pointer',
        }}
        onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.06)'; }}
        onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
      >
        <MessageSquare size={20} strokeWidth={rightPanelOpen ? 2 : 1.5} />
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
