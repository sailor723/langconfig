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
 * Vault opens a popover (Obsidian-style vault switcher) instead of navigating.
 */
import { useState, useRef, Fragment } from 'react';
import { useLayoutState, ACTIVITIES, type ActivityDef, type ActivityId } from './useLayout';
import { useLayoutTokens } from './tokens';
import {
  GitBranch, Brain, Users, BarChart3, Network, Settings, Sparkles, Globe, Wrench, Database, Award, MessageSquare, Archive, FileText, BookOpen, Workflow, type LucideIcon,
} from 'lucide-react';
import SystemSettingsPopover from './SystemSettingsPopover';
import VaultPopover from './VaultPopover';

const ICON_MAP: Partial<Record<ActivityId, LucideIcon>> = {
  vault:      Archive,
  deepagents: Brain,
  agents:     Users,
  workflows:  GitBranch,
  graph:      Workflow,
  prompt:     FileText,
  tools:      Wrench,
  skills:     Award,
  knowledge:  Database,
  analysis:   BarChart3,
  models:     Sparkles,
  search:     Globe,
  studio:     Network,
  learning:   BookOpen,
  settings:   Settings,
};

// Ordered activity groups with visual dividers between them
const SECTION_GROUPS: ActivityId[][] = [
  ['vault', 'deepagents', 'agents', 'graph'],
  ['prompt', 'tools', 'skills'],
  ['knowledge', 'analysis', 'learning'],
  ['models', 'search'],
];

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
  if (!Icon) return null;
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
        color: active ? t.activityBarActive : t.activityBarInactive,
        border: 'none',
        cursor: 'pointer',
        position: 'relative',
      }}
      onMouseEnter={e => {
        if (!active) e.currentTarget.style.background = t.activityBarHover;
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
            background: t.activityBarActive,
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
  const [vaultOpen, setVaultOpen] = useState(false);
  const settingsBtnRef = useRef<HTMLButtonElement | null>(null);
  const vaultBtnRef = useRef<HTMLButtonElement | null>(null);

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
      {/* Vault (popover) — always first */}
      <button
        ref={vaultBtnRef}
        title="Switch vault"
        onClick={() => setVaultOpen(v => !v)}
        style={{
          width: 48,
          height: 48,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'transparent',
          color: vaultOpen ? t.activityBarActive : t.activityBarInactive,
          border: 'none',
          cursor: 'pointer',
          position: 'relative',
        }}
        onMouseEnter={e => { if (!vaultOpen) e.currentTarget.style.background = t.activityBarHover; }}
        onMouseLeave={e => { if (!vaultOpen) e.currentTarget.style.background = 'transparent'; }}
      >
        {vaultOpen && (
          <span
            style={{
              position: 'absolute',
              left: 0,
              top: 8,
              bottom: 8,
              width: 2,
              background: t.activityBarActive,
            }}
          />
        )}
        <Archive size={20} strokeWidth={vaultOpen ? 2 : 1.5} />
      </button>

      {vaultOpen && (
        <VaultPopover
          anchorRef={vaultBtnRef as React.RefObject<HTMLElement | null>}
          onClose={() => setVaultOpen(false)}
        />
      )}

      {/* Sectioned activity groups with dividers */}
      {SECTION_GROUPS.map((group, gi) => (
        <Fragment key={gi}>
          {gi > 0 && <div style={{ width: 28, height: 1, background: t.activityBarDivider, margin: '6px 0' }} />}
          {group.map(id => {
            const act = ACTIVITIES.find(a => a.id === id);
            if (!act) return null;
            // Vault is rendered specially as a popover above; skip it here
            if (act.id === 'vault') return null;
            return (
              <ActivityButton
                key={act.id}
                act={act}
                active={act.id === activeActivity}
                onClick={() => handleActivityClick(act.id)}
              />
            );
          })}
        </Fragment>
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
          color: settingsOpen ? t.activityBarActive : t.activityBarInactive,
          border: 'none',
          cursor: 'pointer',
          position: 'relative',
        }}
        onMouseEnter={e => { if (!settingsOpen) e.currentTarget.style.background = t.activityBarHover; }}
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
              background: t.activityBarActive,
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

      {/* Toggle right panel (Chat) — opens a dedicated window */}
      <button
        title="Open chat window"
        onClick={() => window.open(
          window.location.origin + '/#/chat',
          'langconfig-chat',
          'width=700,height=900,menubar=no,toolbar=no,scrollbars=yes'
        )}
        style={{
          width: 48,
          height: 48,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'transparent',
          color: t.activityBarInactive,
          border: 'none',
          cursor: 'pointer',
        }}
        onMouseEnter={e => { e.currentTarget.style.background = t.activityBarHover; }}
        onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
      >
        <MessageSquare size={20} strokeWidth={1.5} />
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
          color: t.activityBarInactive,
          border: 'none',
          cursor: 'pointer',
          borderTop: `1px solid ${t.activityBarDivider}`,
        }}
        onMouseEnter={e => { e.currentTarget.style.background = t.activityBarHover; }}
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
