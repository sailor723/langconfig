/**
 * ActivityBar — the left icon rail, with the hover-expand the workbench grew first.
 *
 * Two behaviours, one rail:
 *
 *  - **Collapsed (48px)** in the layout, always. The workspace never shifts when the
 *    pointer crosses the rail — the rail expands as an OVERLAY above the sidebar instead
 *    (`z-index: 60`), the way the ontology workbench's own `#sbnav` does (56px → 184px
 *    on hover).
 *  - **Expanded on hover (208px)**: every row grows to `icon + label`, section dividers
 *    stretch to the full width, and the account row shows the whole name instead of an
 *    ellipsised 44px stub. A rail that is a guessing game of glyphs is what the labels
 *    fix; the tooltip stays as a fallback.
 *
 * The groups are unchanged (vault · deepagents/agents/graph · prompt/tools/skills ·
 * ontology/knowledge/analysis/learning) and the vault / account / settings / chat entries
 * keep their popovers, the settings modal event and the dedicated chat window.
 */
import { useState, useRef, useEffect, Fragment } from 'react';
import { useTranslation } from 'react-i18next';
import { useLayoutState, ACTIVITIES, type ActivityId } from './useLayout';
import { useLayoutTokens } from './tokens';
import {
  GitBranch, Brain, Users, BarChart3, Network, Settings, Wrench, Database, Award,
  MessageSquare, Archive, FileText, BookOpen, Workflow, UserRound, Boxes,
  PanelLeftClose, PanelLeftOpen, type LucideIcon,
} from 'lucide-react';
import apiClient from '../../lib/api-client';
import VaultPopover from './VaultPopover';
import UserPopover from './UserPopover';

const ICON_MAP: Partial<Record<ActivityId, LucideIcon>> = {
  vault:      Archive,
  deepagents: Brain,
  agents:     Users,
  workflows:  GitBranch,
  graph:      Workflow,
  prompt:     FileText,
  tools:      Wrench,
  skills:     Award,
  ontology:   Boxes,
  knowledge:  Database,
  analysis:   BarChart3,
  studio:     Network,
  learning:   BookOpen,
  settings:   Settings,
};

// Ordered activity groups with visual dividers between them
const SECTION_GROUPS: ActivityId[][] = [
  ['vault', 'deepagents', 'agents', 'graph'],
  ['prompt', 'tools', 'skills'],
  ['ontology', 'knowledge', 'analysis', 'learning'],
];

const RAIL_COLLAPSED = 48;
const RAIL_EXPANDED = 208;

/** One row of the rail: icon + label. The label is what the hover expansion reveals. */
function RailItem({
  icon: Icon,
  label,
  title,
  active,
  onClick,
  style,
  children,
  btnRef,
}: {
  icon?: LucideIcon;
  label: string;
  title?: string;
  active?: boolean;
  onClick?: () => void;
  style?: React.CSSProperties;
  children?: React.ReactNode;
  /** The row element itself, for popovers that anchor to it. */
  btnRef?: React.Ref<HTMLButtonElement>;
}) {
  const t = useLayoutTokens();
  return (
    <button
      ref={btnRef}
      title={title || label}
      onClick={onClick}
      style={{
        position: 'relative',
        width: '100%',
        height: 48,
        flex: 'none',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '0 12px 0 14px',
        background: 'transparent',
        border: 'none',
        cursor: 'pointer',
        color: active ? t.activityBarActive : t.activityBarInactive,
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        fontFamily: 'inherit',
        textAlign: 'left',
        ...style,
      }}
      onMouseEnter={e => { if (!active) e.currentTarget.style.background = t.activityBarHover; }}
      onMouseLeave={e => { if (!active) e.currentTarget.style.background = 'transparent'; }}
    >
      {active && (
        <span
          style={{
            position: 'absolute', left: 0, top: 8, bottom: 8, width: 2,
            background: t.activityBarActive,
          }}
        />
      )}
      {Icon && <Icon size={20} strokeWidth={active ? 2 : 1.5} style={{ flex: 'none' }} />}
      {children}
      <span
        className="lc-rail-label"
        style={{ fontSize: 13, lineHeight: '18px', overflow: 'hidden', textOverflow: 'ellipsis' }}
      >
        {label}
      </span>
    </button>
  );
}

interface ActivityBarProps {
  /** Called after an activity icon is clicked, with the clicked activity id */
  onClickActivity?: (activity: ActivityId) => void;
}

export default function ActivityBar({ onClickActivity }: ActivityBarProps) {
  const { activeActivity, setActiveActivity, sidebarOpen, toggleSidebar } = useLayoutState();
  const t = useLayoutTokens();
  const { t: tr } = useTranslation('chat');
  const [vaultOpen, setVaultOpen] = useState(false);
  const vaultBtnRef = useRef<HTMLButtonElement | null>(null);
  const [userOpen, setUserOpen] = useState(false);
  // Which account this rail belongs to. Two people sharing a machine saw an identical
  // rail, so "am I signed in as me?" had no answer anywhere on screen.
  const [username, setUsername] = useState<string | null>(null);
  // What the rail shows: the nickname when the account has one, the login name otherwise.
  const [label, setLabel] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    apiClient.getMe()
      .then((r) => {
        if (cancelled) return;
        const me = r?.data;
        setUsername(me?.username ?? null);
        setLabel(me?.nickname || me?.username || null);
      })
      .catch(() => { /* not signed in / offline: keep the plain label */ });
    return () => { cancelled = true; };
  }, []);
  const userBtnRef = useRef<HTMLButtonElement | null>(null);

  const handleActivityClick = (id: ActivityId) => {
    setActiveActivity(id);
    onClickActivity?.(id);
  };

  const [expanded, setExpanded] = useState(false);

  return (
    <div
      style={{ width: RAIL_COLLAPSED, minWidth: RAIL_COLLAPSED, position: 'relative', zIndex: 60, userSelect: 'none' }}
      onMouseEnter={() => setExpanded(true)}
      onMouseLeave={() => setExpanded(false)}
      onFocus={() => setExpanded(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setExpanded(false);
      }}
    >
      {/* The rail overlays the sidebar while it is wide, so the layout column stays 48px. */}
      <style>{`
        #lc-rail {
          width: ${RAIL_COLLAPSED}px;
          transition: width .16s ease;
          overflow: hidden;
        }
        /* State-driven, not :hover-only: the pointer can leave mid-transition, and a
           focused row should reveal its label too. */
        #lc-rail.lc-open {
          width: ${RAIL_EXPANDED}px;
          box-shadow: 2px 0 16px rgba(0,0,0,.22);
        }
        #lc-rail .lc-rail-label {
          opacity: 0;
          transition: opacity .1s ease;
        }
        #lc-rail.lc-open .lc-rail-label { opacity: 1; }
        #lc-rail .lc-rail-divider {
          width: 20px;
          margin: 6px 0 6px 14px;
          transition: width .16s ease;
        }
        #lc-rail.lc-open .lc-rail-divider { width: calc(100% - 28px); }
      `}</style>

      <div
        id="lc-rail"
        className={expanded ? 'lc-open' : undefined}
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          bottom: 0,
          background: t.bgActivityBar,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'stretch',
        }}
      >
        {/* Vault (popover) — always first */}
        <RailItem
          icon={Archive}
          label={tr('ab_switch_vault')}
          active={vaultOpen}
          onClick={() => setVaultOpen(v => !v)}
          btnRef={vaultBtnRef}
        />

        {/* Sectioned activity groups with dividers */}
        {SECTION_GROUPS.map((group, gi) => (
          <Fragment key={gi}>
            {gi > 0 && (
              <div className="lc-rail-divider" style={{ height: 1, background: t.activityBarDivider }} />
            )}
            {group.map(id => {
              const act = ACTIVITIES.find(a => a.id === id);
              if (!act) return null;
              // Vault is rendered specially as a popover above; skip it here
              if (act.id === 'vault') return null;
              const Icon = ICON_MAP[act.id];
              if (!Icon) return null;
              return (
                <RailItem
                  key={act.id}
                  icon={Icon}
                  label={tr(act.label)}
                  active={act.id === activeActivity}
                  onClick={() => handleActivityClick(act.id)}
                />
              );
            })}
          </Fragment>
        ))}

        <div style={{ flex: 1 }} />

        {/* Account — who am I, and the two things an account can do. Bottom cluster
            because that is where "this session" lives, next to Settings. */}
        <RailItem
          label={label || 'Your account'}
          title={
            label
              ? username && label !== username
                ? `Your account — ${label} (${username})`
                : `Your account — ${label}`
              : 'Your account'
          }
          active={userOpen}
          onClick={() => setUserOpen(v => !v)}
          btnRef={userBtnRef}
          icon={UserRound}
        />

        {/* Settings — opens the DSH-style settings modal (centered panel).
            In the Ontology activity the settings anyone actually wants are the publish DECISIONS:
            what an agent staged and what a person has to apply. The rail's gear used to open
            General from anywhere, so the apply page had no door you could reach from the ontology
            screens — the gear you see while browsing ontologies is this one. */}
        <RailItem
          icon={Settings}
          label={tr('ab_settings')}
          onClick={() => window.dispatchEvent(new CustomEvent('settings:open', {
            detail: { section: activeActivity === 'ontology' ? 'apply' : undefined },
          }))}
        />

        {/* Toggle right panel (Chat) — a dedicated window at almost the full screen. */}
        <RailItem
          icon={MessageSquare}
          label={tr('ab_open_chat')}
          onClick={() => {
            const w = Math.round(window.screen.availWidth * 0.95);
            const h = Math.round(window.screen.availHeight * 0.95);
            window.open(
              window.location.origin + '/#/chat',
              'langconfig-chat',
              `width=${w},height=${h},`
                + `left=${Math.round((window.screen.availWidth - w) / 2)},`
                + `top=${Math.round((window.screen.availHeight - h) / 2)},`
                + 'menubar=no,toolbar=no,scrollbars=yes'
            );
          }}
        />

        {/* Toggle sidebar */}
        <RailItem
          icon={sidebarOpen ? PanelLeftClose : PanelLeftOpen}
          label={tr('ab_toggle_sidebar')}
          onClick={toggleSidebar}
          style={{ borderTop: `1px solid ${t.activityBarDivider}` }}
        />
      </div>

      {/* Popovers are siblings of the rail, not children: the rail animates its width with
          `overflow: hidden`, which would clip a popover anchored inside it. */}
      {vaultOpen && (
        <VaultPopover
          anchorRef={vaultBtnRef as React.RefObject<HTMLElement | null>}
          onClose={() => setVaultOpen(false)}
        />
      )}
      {userOpen && (
        <UserPopover
          anchorRef={userBtnRef as React.RefObject<HTMLElement | null>}
          onClose={() => setUserOpen(false)}
          onOpenAccount={() => window.dispatchEvent(new CustomEvent('account:open'))}
          onOpenUsers={() => window.dispatchEvent(new CustomEvent('users:open'))}
        />
      )}
    </div>
  );
}
