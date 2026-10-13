/**
 * ChatHistorySidebar — Codex-style compact sidebar.
 *
 * Layout:
 *   ┌─────────────────────┐
 *   │ [🗨] [🔍] [📅] [🧩] │  Top nav
 *   ├─────────────────────┤
 *   │ ▸ Projects          │
 *   │   my-agent ▸        │  Current project badge
 *   ├─────────────────────┤
 *   │ Chats               │
 *   │ title...        2d  │  Minimal rows
 *   │ title...        3w  │
 *   │ title...       15m  │
 *   ├─────────────────────┤
 *   │ ⚙ Settings          │  Bottom
 *   └─────────────────────┘
 */
import { useState } from 'react';
import { Plus, MessageSquare, MessageSquarePlus, Search, ChevronDown, ChevronRight, Calendar, Folder, FolderOpen, Package, Users, X, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import type { ChatSession } from '../types/chat';
import { useChat } from '../state/ChatContext';
import { useProject } from '../../../contexts/ProjectContext';
import {
  formatCompactDateTime, formatFullDateTime, formatMessageCount,
} from '../utils/formatChatTime';

/**
 * Which list the panel shows, chosen by the three buttons in the top bar:
 *  - 'agents'    one folder per agent, holding that agent's chats
 *  - 'favorites' the pinned conversations, flat
 *  - 'dates'     one folder per day, holding that day's chats
 */
type ChatHistoryView = 'agents' | 'favorites' | 'dates';

interface ChatHistorySidebarProps {
  onNewSession: () => void;
  /**
   * Pinned to the foot of the column, in both the expanded view and the 48px
   * rail. This is where the chat settings control lives, because that is where
   * DSH keeps its `sidebar.settings` slot — bottom-pinned in the left sidebar,
   * not in a bar under the conversation. It used to sit against the right edge
   * of a window-wide bar below the composer, which both looked like a second
   * toolbar and held the composer 48px off the bottom of the chat area.
   */
  footer?: React.ReactNode;
  /**
   * The rail's footer: the 48px column is narrower than the copyright line, so
   * the collapsed state gets the settings control alone.
   */
  footerCompact?: React.ReactNode;
}

/**
 * One view toggle, styled the way DSH styles its sidebar controls: a 28px
 * circle with a neutral translucent hover, and a selected state that is a
 * stronger fill plus a primary-tinted icon rather than a saturated block.
 *
 * The fill is a translucent grey so one value works on the light and dark
 * panels alike — `hover:bg-black/5` is imperceptible over #252526.
 */
function viewToggle(opts: {
  active: boolean;
  title: string;
  onClick: () => void;
  children: React.ReactNode;
  className?: string;
  ariaExpanded?: boolean;
}) {
  const fill = opts.active ? 'rgba(128,128,128,0.28)' : 'transparent';
  const hover = 'rgba(128,128,128,0.18)';
  return (
    <button
      onClick={opts.onClick}
      // 28px x 0.8 = 22.4, rounded to 22; the glyphs go 14 x 0.9 = 12.6 -> 13.
      className={`w-[22px] h-[22px] rounded-full flex items-center justify-center flex-shrink-0 transition-colors ${
        opts.active ? 'chat-view-toggle-active' : ''
      } ${opts.className || ''}`}
      style={{
        backgroundColor: fill,
        // Only the inactive colour is inline; the active tint comes from the
        // class above, because an inline color-primary is rewritten by the
        // theme layer into a solid primary fill (see index.css).
        ...(opts.active ? {} : { color: 'var(--color-text-muted)' }),
      }}
      onMouseEnter={(e) => { if (!opts.active) e.currentTarget.style.backgroundColor = hover; }}
      onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = fill; }}
      title={opts.title}
      aria-pressed={opts.active}
      aria-expanded={opts.ariaExpanded}
    >
      {opts.children}
    </button>
  );
}

/**
 * The column's background, in BOTH states.
 *
 * These disagreed: the expanded sidebar used `--color-panel-dark` while the 48px
 * rail asked for `--color-panel` — a variable nothing defines (ChatPage sets
 * panel-dark, and no data-theme block in index.css declares panel; only the
 * legacy `.theme-codex-dark` class does). The rail therefore fell back to its
 * light #f9fafb default and rendered grey inside an otherwise dark window.
 * One constant now, so the two states cannot drift apart again.
 */
const SIDEBAR_BG = 'var(--color-panel-dark, var(--color-panel, #f9fafb))';

export default function ChatHistorySidebar({ onNewSession, footer, footerCompact }: ChatHistorySidebarProps) {
  const { sessions, currentSessionId, switchSession } = useChat();
  // The heading says "Projects", so the value has to be the project (vault).
  // It used to render the current session's agent name — an agent shown under a
  // project heading, which is simply the wrong thing.
  const { activeProject, projects } = useProject();

  const currentSession = sessions.find((s: ChatSession) => s.session_id === currentSessionId);
  const sessionProject = projects.find(p => p.id === currentSession?.project_id);
  const projectName = sessionProject?.name
    || activeProject?.name
    || (currentSession ? 'No project' : 'my-project');
  const [collapsed, setCollapsed] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [showProjects, setShowProjects] = useState(true);
  // Two views, chosen by the two buttons in the top bar: 'agents' (the default)
  // groups the history into one folder per agent, 'favorites' shows only the
  // pinned conversations. Persisted in localStorage, not sessionStorage — the
  // chat window is opened with window.open(), so it gets a fresh session store
  // every time.
  const [view, setView] = useState<ChatHistoryView>(() => {
    const stored = localStorage.getItem('chat_view');
    // Must list every view: an unrecognised value silently fell back to the
    // agent folders, so a stored 'dates' choice was forgotten on reload.
    if (stored === 'agents' || stored === 'favorites' || stored === 'dates') return stored;
    // Carry over the previous boolean flag on first load after this change.
    return localStorage.getItem('chat_favorites_only') === 'true' ? 'favorites' : 'agents';
  });

  const selectView = (next: ChatHistoryView) => {
    localStorage.setItem('chat_view', next);
    setView(next);
  };

  const activeSessions = sessions.filter(
    (s: ChatSession) => s.message_count > 0 || s.session_id === currentSessionId
  );

  // Favourites: ordered by when they were pinned (newest first) rather than by
  // activity, so a pinned conversation doesn't jump around when it receives a
  // message. The section itself lives under Projects and starts collapsed.
  const pinnedSessions = activeSessions
    .filter((s: ChatSession) => s.is_favorite)
    .sort((a: ChatSession, b: ChatSession) =>
      (b.favorited_at || b.updated_at).localeCompare(a.favorited_at || a.updated_at)
    );

  // Agent folders — one per agent, holding that agent's conversations. They are
  // SIBLINGS of Favourites (both sit under Projects), because the interesting
  // grouping for history is "which agent", while Favourites is a hand-picked
  // quick-select shortcut that cuts across agents.
  //
  // Folders are ordered by their most recent conversation; chats inside are
  // newest first. Every conversation is included, including pinned ones, so a
  // folder really is that agent's full history and Favourites is purely a
  // shortcut on top of it.
  const agentFolders = (() => {
    const byAgent = new Map<number, { agentId: number; agentName: string; sessions: ChatSession[]; latest: string }>();
    for (const session of activeSessions) {
      const stamp = session.updated_at || session.created_at;
      const group = byAgent.get(session.agent_id);
      if (group) {
        group.sessions.push(session);
        if (stamp > group.latest) group.latest = stamp;
      } else {
        byAgent.set(session.agent_id, {
          agentId: session.agent_id,
          agentName: session.agent_name || 'Unknown agent',
          sessions: [session],
          latest: stamp,
        });
      }
    }
    return [...byAgent.values()]
      .map(group => ({
        ...group,
        sessions: [...group.sessions].sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
      }))
      .sort((a, b) => b.latest.localeCompare(a.latest));
  })();

  // Date folders: one per day, using the same timestamp the rows show (last
  // activity), so a folder and its rows can never disagree about which day a
  // conversation belongs to. Newest day first, chats newest-first inside.
  const dateFolders = (() => {
    const buckets = new Map<string, { key: string; label: string; sessions: ChatSession[] }>();
    const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const today = startOfDay(new Date());
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);

    for (const session of activeSessions) {
      const date = new Date(session.updated_at || session.created_at);
      if (Number.isNaN(date.getTime())) continue;
      const day = startOfDay(date);
      const key = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`;
      const label = day.getTime() === today.getTime()
        ? 'Today'
        : day.getTime() === yesterday.getTime()
          ? 'Yesterday'
          : day.toLocaleDateString(undefined, {
              weekday: 'short',
              day: 'numeric',
              month: 'short',
              ...(day.getFullYear() === today.getFullYear() ? {} : { year: 'numeric' }),
            });
      const bucket = buckets.get(key);
      if (bucket) bucket.sessions.push(session);
      else buckets.set(key, { key, label, sessions: [session] });
    }

    return [...buckets.values()]
      .map(bucket => ({
        ...bucket,
        sessions: [...bucket.sessions].sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
      }))
      .sort((a, b) => b.key.localeCompare(a.key));   // ISO-ish key sorts oldest->newest
  })();

  // Per-agent folder EXPANSION, persisted so the state survives the chat window
  // being closed and reopened (sessionStorage would not). Stored as the
  // exception rather than the rule: an absent entry means collapsed, which is
  // the default — folders are a table of contents, so they start closed and you
  // open the one agent you care about.
  const [expandedAgentFolders, setExpandedAgentFolders] = useState<Record<number, boolean>>(() => {
    try {
      return JSON.parse(localStorage.getItem('chat_expanded_agent_folders') || '{}');
    } catch {
      return {};
    }
  });

  const toggleAgentFolder = (agentId: number) => {
    setExpandedAgentFolders(prev => {
      const next = { ...prev, [agentId]: !prev[agentId] };
      localStorage.setItem('chat_expanded_agent_folders', JSON.stringify(next));
      return next;
    });
  };

  // Date folders collapse independently too, stored by day key under their own
  // localStorage entry so switching views never mixes the two trees up.
  const [expandedDateFolders, setExpandedDateFolders] = useState<Record<string, boolean>>(() => {
    try {
      return JSON.parse(localStorage.getItem('chat_expanded_date_folders') || '{}');
    } catch {
      return {};
    }
  });

  const toggleDateFolder = (key: string) => {
    setExpandedDateFolders(prev => {
      const next = { ...prev, [key]: !prev[key] };
      localStorage.setItem('chat_expanded_date_folders', JSON.stringify(next));
      return next;
    });
  };

  // While searching, favourites appear in the flat result list instead of
  // twice, so a match is never hidden inside a collapsed section.
  // Direct text mapping on the title: a plain case-insensitive substring, no
  // fuzzy matching and no message content. The input's placeholder says so, so
  // it is clear that only named conversations are searchable.
  const matchesSearch = (s: ChatSession) =>
    (s.title || '').toLowerCase().includes(searchQuery.trim().toLowerCase());

  // Search spans whichever view is active: favourites only when the star is on,
  // otherwise every conversation (pinned ones included — the folders hold the
  // agent's full history).
  const query = searchQuery.trim();
  const scopedSessions = view === 'favorites' ? pinnedSessions : activeSessions;
  const filteredSessions = query ? scopedSessions.filter(matchesSearch) : scopedSessions;

  /** Row label: the user's title, else the last message preview. */
  const sessionLabel = (session: ChatSession) =>
    session.title || (session.last_message_preview
      ? session.last_message_preview.slice(0, 60)
      : 'New conversation');

  // The box lives in the open conversation's header, not on every row: pinning is
  // a decision you make while reading, and an icon per row turns the list into
  // a management surface.
  const sessionRow = (session: ChatSession, variant: 'chat' | 'favorite' | 'dated' = 'chat') => {
    const isActive = currentSessionId === session.session_id;
    const isFavoriteRow = variant === 'favorite';
    // A pinned chat with no name would otherwise be an anonymous date, so it
    // says so rather than borrowing the conversation's first message.
    const label = isFavoriteRow ? (session.title || 'Untitled chat') : sessionLabel(session);

    return (
      <button
        key={session.session_id}
        onClick={() => switchSession(session.session_id)}
        className="w-full text-left px-2 py-1.5 rounded-lg transition-all group"
        // Everything the row leaves out (agent, exact timestamp, length) lives
        // here, so trimming the visible line loses nothing.
        title={[
          session.title || sessionLabel(session),
          session.agent_name,
          formatFullDateTime(session.updated_at),
          formatMessageCount(session.message_count),
          session.is_favorite ? 'pinned' : null,
        ].filter(Boolean).join(' · ')}
        style={{
          backgroundColor: isActive ? 'var(--color-primary)' : 'transparent',
        }}
        onMouseEnter={(e) => {
          if (!isActive) e.currentTarget.style.backgroundColor = 'rgba(0,0,0,0.04)';
        }}
        onMouseLeave={(e) => {
          if (!isActive) e.currentTarget.style.backgroundColor = 'transparent';
        }}
      >
        {isFavoriteRow ? (
          /* Favourites: the FULL title, wrapped — no truncation, and no length,
             agent name or message preview competing for the width. Just the
             date underneath. Favourites are hand-picked, so the name is the only
             thing worth the space. */
          <div className="flex flex-col gap-0.5 min-w-0">
            <span
              className="text-xs whitespace-normal break-words leading-snug"
              style={{ color: isActive ? 'white' : 'var(--color-text-primary)' }}
            >
              {label}
            </span>
            <span
              className="text-[10px]"
              style={{ color: isActive ? 'rgba(255,255,255,0.65)' : 'var(--color-text-muted)' }}
            >
              {formatCompactDateTime(session.updated_at)}
            </span>
          </div>
        ) : (
          /* History row: single line — title + when it happened + how long it is.
             The title truncates, the metadata never wraps away. */
          <div className="flex items-center gap-1.5 min-w-0">
            <span
              className="text-xs truncate flex-1 min-w-0"
              style={{ color: isActive ? 'white' : 'var(--color-text-primary)' }}
            >
              {label}
            </span>
            <span
              className="text-[10px] flex-shrink-0"
              style={{ color: isActive ? 'rgba(255,255,255,0.65)' : 'var(--color-text-muted)' }}
            >
              {/* The date folder already names the day, so repeating it here is
                  noise; the length still distinguishes one chat from another. */}
              {variant === 'dated'
                ? formatMessageCount(session.message_count)
                : `${formatCompactDateTime(session.updated_at)} · ${formatMessageCount(session.message_count)}`}
            </span>
          </div>
        )}
      </button>
    );
  };

  /** One folder: header (chevron, icon, name, count) plus its chats, indented. */
  const folderBlock = (opts: {
    id: string;
    label: string;
    sessions: ChatSession[];
    expanded: boolean;
    onToggle: () => void;
    /** Row style for this folder's chats (date folders hide the timestamp). */
    rowVariant?: 'chat' | 'dated';
  }) => (
    <div key={opts.id} className="pb-0.5">
      <button
        onClick={opts.onToggle}
        className="group flex items-center gap-1.5 w-full text-left px-2 py-1 rounded-lg hover:bg-black/5 transition-colors"
        title={`${opts.label} — ${opts.sessions.length} conversation${opts.sessions.length === 1 ? '' : 's'}`}
        aria-expanded={opts.expanded}
      >
        {/* Folder by default, expand arrow on row hover — DSH's leading-slot swap
            (ui-workspace Rows.module.css: `:hover` hides .folder and reveals
            .chevron). Two things are deliberate:

            - the slot is fixed-width, like DSH's 16px one, so the swap cannot
              shift the label even if the two glyphs differ in width;
            - the arrow is this row's own stroke chevron rotated 90° when open,
              not DSH's filled triangle, so it matches the other chevrons here.

            Hover only, as in DSH: the folder glyph still carries open vs closed,
            so the arrow is an affordance hint rather than the state. */}
        <span className="w-3.5 h-3.5 flex-shrink-0 inline-flex items-center justify-center">
          {opts.expanded ? (
            <FolderOpen className="w-3.5 h-3.5 group-hover:hidden" style={{ color: 'var(--color-text-muted)' }} />
          ) : (
            <Folder className="w-3.5 h-3.5 group-hover:hidden" style={{ color: 'var(--color-text-muted)' }} />
          )}
          <ChevronRight
            className="hidden w-3.5 h-3.5 group-hover:block transition-transform duration-150"
            style={{
              color: 'var(--color-text-muted)',
              transform: opts.expanded ? 'rotate(90deg)' : undefined,
            }}
          />
        </span>
        <span className="text-[11px] font-medium truncate" style={{ color: 'var(--color-text-muted)' }}>
          {opts.label}
        </span>
        <span className="ml-auto text-[10px] flex-shrink-0" style={{ color: 'var(--color-text-muted)' }}>
          {opts.sessions.length}
        </span>
      </button>
      {opts.expanded && (
        <div className="pl-3 space-y-0.5">
          {opts.sessions.map((s: ChatSession) => sessionRow(s, opts.rowVariant ?? 'chat'))}
        </div>
      )}
    </div>
  );

  // ── Collapsed state ────────────────────────────────────────────

  if (collapsed) {
    // Pinned chats come first so the rail stays a quick select.
    const railSessions = [...pinnedSessions, ...activeSessions.filter((s: ChatSession) => !s.is_favorite)];
    return (
      <div
        className="flex flex-col items-center py-3 transition-all duration-200"
        style={{
          width: '48px',
          backgroundColor: SIDEBAR_BG,
        }}
      >
        <button
          onClick={() => setCollapsed(false)}
          className="p-2 rounded-lg hover:bg-[rgba(128,128,128,0.18)] transition-colors mb-4"
          title="Expand sidebar"
        >
          <PanelLeftOpen className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
        </button>
        {/* New session in the rail: 36px, no border — DSH's collapsed form. */}
        <button
          onClick={onNewSession}
          className="w-9 h-9 rounded-xl flex items-center justify-center hover:bg-[rgba(128,128,128,0.18)] transition-colors mb-2"
          style={{ color: 'var(--color-text-primary)' }}
          title="New session"
        >
          <MessageSquarePlus className="w-4 h-4" />
        </button>
        {/* scrollbar-gutter: stable — see the note on the list below. */}
        <div className="flex-1 overflow-y-auto space-y-1 px-1" style={{ scrollbarGutter: 'stable' }}>
          {railSessions.slice(0, 8).map((session: ChatSession) => (
            <button
              key={session.session_id}
              onClick={() => switchSession(session.session_id)}
              className={`relative w-8 h-8 rounded-lg flex items-center justify-center text-xs font-medium transition-colors ${
                currentSessionId === session.session_id
                  ? 'bg-primary text-white'
                  : 'hover:bg-[rgba(128,128,128,0.18)]'
              }`}
              style={{
                color: currentSessionId === session.session_id ? 'white' : 'var(--color-text-muted)',
              }}
              title={[
                session.agent_name,
                sessionLabel(session),
                formatCompactDateTime(session.updated_at),
                formatMessageCount(session.message_count),
                session.is_favorite ? 'pinned' : null,
              ].filter(Boolean).join(' · ')}
            >
              {session.agent_name.charAt(0).toUpperCase()}
              {session.is_favorite && (
                // Sized up from the star's 10px: Package carries more detail than a
                // star at badge scale, and it is stroke-drawn, so the star's
                // fill="currentColor" would have rendered a blob rather than a box.
                <Package
                  className="w-3 h-3 absolute -top-0.5 -right-0.5"
                  style={{ color: 'var(--color-primary)' }}
                />
              )}
            </button>
          ))}
        </div>
        {(footerCompact || footer) && (
          <div className="pt-2 flex flex-col items-center">{footerCompact || footer}</div>
        )}
      </div>
    );
  }

  // ── Expanded state ─────────────────────────────────────────────

  return (
    <div
      className="flex flex-col transition-all duration-200"
      style={{
        width: '100%',
        backgroundColor: SIDEBAR_BG,
      }}
    >
      {/* ── Brand row ────────────────────────────────────────────────
          DSH's `logoRow`: the wordmark on the left, the panel toggle on the
          right, 60px tall, above everything else. The wordmark doubles as a New
          Session shortcut there, and this one does too.

          No image asset for the name exists in the repo (only LangConfig's), so
          the mark is drawn as text; swap the span for an <img src="…"> when there
          is one and nothing else here has to move.

          Bold, in DSH's font stack. This app sets Manrope app-wide (`--font-family-sans`)
          and Inter for display (`--font-family-display`); DSH sets neither — its
          `--dsw-font-family` is the plain system stack, so the wordmark asks for
          that explicitly rather than inheriting Manrope. The stack is copied
          verbatim so the CJK fallbacks match too. */}
      <div className="flex items-center gap-2 px-3 h-[60px]">
        <button
          onClick={onNewSession}
          className="text-[15px] truncate"
          style={{
            color: 'var(--color-text-primary)',
            fontWeight: 700,
            fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', "
              + "'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif",
          }}
          title="EBL Carrier Chat — new session"
        >
          &nbsp;EBL Carrier Chat
        </button>
        <div className="flex-1" />
        {/* Panel toggle, not a chevron: the affordance is "collapse this
            column", which is what DSH's panel icon says. */}
        <button
          onClick={() => setCollapsed(true)}
          className="p-1.5 rounded-lg hover:bg-black/5 transition-colors flex-shrink-0"
          title="Collapse sidebar"
          aria-label="Collapse sidebar"
        >
          <PanelLeftClose className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
        </button>
      </div>

      {/* ── New session ──────────────────────────────────────────────
          DSH's `sidebar.newSession`: a full-width box above the browsing
          controls (38px tall, 12px radius, icon + label), not a bare "+" hidden
          among the view toggles. The view row below is pushed down by it, which
          is the order DSH uses: new session, then the list of what exists.

          No border, by request: the elevated fill alone carries it. */}
      <div className="px-2 pt-2.5 pb-1">
        <button
          onClick={onNewSession}
          // The fill lives in index.css (.chat-new-session): an inline
          // `var(--color-input-background)` is rewritten to panelDark by the
          // runtime theme layer, which is exactly the sidebar's own colour — the
          // box came out flat with only a border, where DSH's is elevated.
          // text-sm (14px) x 0.8 = 11.2 -> 11px. The 38px box height is unchanged,
          // so the label sits a little smaller inside it.
          className="chat-new-session w-full flex items-center justify-center gap-1.5 text-[11px] font-medium transition-colors"
          style={{
            height: 38,
            borderRadius: 12,
            color: 'var(--color-text-primary)',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.opacity = '0.85'; }}
          onMouseLeave={(e) => { e.currentTarget.style.opacity = '1'; }}
          title="New session"
        >
          <MessageSquarePlus className="w-3.5 h-3.5" />
          New session
        </button>
      </div>

      {/* ── View controls: Search · Date view · Agents · Favourites ──
          DSH's `.iconButton` conventions, applied to our toggles:

            * 28px circle (border-radius: 50%), not a rounded square;
            * a neutral translucent hover, because `bg-black/5` on this dark
              panel is invisible — black over #252526 barely changes it;
            * SELECTED is a fill one step stronger with the icon tinted in the
              primary colour. It used to be a solid primary block under a white
              icon, which read far heavier than the icons beside it — DSH keeps
              its saturated fill for the send button, not for a view toggle;
            * `strokeWidth={1.5}` on the glyphs. DSH draws its icons as filled
              outline paths that are optically much finer than lucide's default
              stroke of 2 — the weight, not the size, is what looked clunky. */}
      <div className="flex items-center gap-1 pl-3 pr-2 py-1.5">
        {/* Name of the list on the left, controls on the right — DSH's row
            pattern (wordmark then panel toggle in its logo row). The label names
            whichever view is showing, so the row reads as "Agents … [toggles]"
            rather than four anonymous icons. */}
        <span
          className="text-[11px] font-medium truncate"
          style={{ color: 'var(--color-text-primary)' }}
        >
          {view === 'favorites' ? 'Favourites' : view === 'dates' ? 'Dates' : 'Agents'}
        </span>
        <div className="flex-1" />
        {viewToggle({
          active: searchOpen,
          title: searchOpen ? 'Close search' : 'Search titles',
          ariaExpanded: searchOpen,
          onClick: () => {
            setSearchOpen(open => {
              if (open) setSearchQuery('');   // closing the box clears the filter
              return !open;
            });
          },
          children: <Search className="w-[13px] h-[13px]" strokeWidth={1.5} />,
        })}
        {viewToggle({
          active: view === 'dates',
          title: `Group by date — ${dateFolders.length} day${dateFolders.length === 1 ? '' : 's'}`,
          onClick: () => selectView('dates'),
          children: <Calendar className="w-[13px] h-[13px]" strokeWidth={1.5} />,
        })}
        {/* Two views, side by side: Agents (one folder per agent, each holding
            that agent's chats) and Favourites (the pinned conversations, with
            the pin count on the icon). Exactly one is active. */}
        {viewToggle({
          active: view === 'agents',
          title: `All agents — ${agentFolders.length} folder${agentFolders.length === 1 ? '' : 's'}, each holding its chats`,
          onClick: () => selectView('agents'),
          children: <Users className="w-[13px] h-[13px]" strokeWidth={1.5} />,
        })}
        {viewToggle({
          active: view === 'favorites',
          title: view === 'favorites'
            ? 'Showing favourites — click Agents for all chats'
            : `Show favourites${pinnedSessions.length ? ` (${pinnedSessions.length})` : ''}`,
          onClick: () => selectView('favorites'),
          className: 'relative',
          children: (
            <>
              <Package className="w-[13px] h-[13px]" strokeWidth={1.5} />
              {pinnedSessions.length > 0 && (
                <span
                  className="absolute -top-0.5 -right-0.5 text-[9px] leading-none px-1 rounded-full"
                  style={{
                    backgroundColor: 'var(--color-primary)',
                    color: 'white',
                  }}
                >
                  {pinnedSessions.length}
                </span>
              )}
            </>
          ),
        })}
      </div>

      {/* ── Search: plain substring on the conversation title ─────── */}
      {searchOpen && (
        <div className="px-3 pb-1">
          <div className="flex items-center gap-1.5 px-2 rounded-lg"
            style={{ border: '1px solid var(--color-border)' }}
          >
            <Search className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
            <input
              autoFocus
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Escape') { setSearchQuery(''); setSearchOpen(false); }
              }}
              placeholder="Search titles…"
              className="flex-1 min-w-0 bg-transparent py-1.5 text-xs focus:outline-none"
              style={{ color: 'var(--color-text-primary)' }}
            />
            {query && (
              <button
                onClick={() => setSearchQuery('')}
                className="p-0.5 rounded hover:bg-black/5"
                title="Clear"
                style={{ color: 'var(--color-text-muted)' }}
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>
      )}

      {/* ── Projects section ─────────────────────────────────────── */}
      <div className="px-3 pt-3 pb-1">
        <button
          onClick={() => setShowProjects(!showProjects)}
          className="flex items-center gap-1 w-full text-left text-xs font-medium"
          style={{ color: 'var(--color-text-muted)' }}
        >
          {showProjects ? (
            <ChevronDown className="w-3 h-3" />
          ) : (
            <ChevronRight className="w-3 h-3" />
          )}
          Projects
        </button>
        {showProjects && (
          <div className="mt-1 px-4 py-1.5 rounded-lg text-xs flex items-center justify-between hover:bg-black/5 transition-colors cursor-pointer"
            style={{ color: 'var(--color-text-primary)' }}
          >
            <span className="font-medium truncate" title={projectName}>
              {projectName}
            </span>
          </div>
        )}
      </div>

      {/* ── Content: favourites view, search results, or agent folders ───
           The star in the top bar switches the first two in and out: off shows
           the history grouped into one folder per agent, on shows just the
           pinned conversations. Both collapse independently and remember it.
           A search lists flat matches, scoped to whichever view is active. */}
      {/* scrollbar-gutter: stable reserves the scrollbar's width whether or
          not the list is currently overflowing. Expanding a folder makes the list
          taller than the viewport, and on a machine with CLASSIC scrollbars
          (macOS "Show scroll bars: Always") the scrollbar then takes ~15px out of
          the content box — so every row narrowed and the sidebar looked like it
          had changed width. With the gutter reserved the content width is
          constant; on overlay scrollbars it costs nothing. */}
      <div className="flex-1 overflow-y-auto px-1 pb-2 space-y-0.5" style={{ scrollbarGutter: 'stable' }}>
        {query ? (
          filteredSessions.length === 0 ? (
            <div className="p-4 text-center text-xs" style={{ color: 'var(--color-text-muted)' }}>
              No titles match “{query}”
            </div>
          ) : (
            filteredSessions.map((s: ChatSession) => sessionRow(s))
          )
        ) : view === 'favorites' ? (
          pinnedSessions.length === 0 ? (
            <div className="p-4 text-center text-xs" style={{ color: 'var(--color-text-muted)' }}>
              No favourites yet — open a chat and tap ☆ in its header.
            </div>
          ) : (
            /* Flat, newest pin first: favourites cut across agents, so this
               view is deliberately not grouped into folders. */
            <div className="pl-3 space-y-0.5">
              {pinnedSessions.map((s: ChatSession) => sessionRow(s, 'favorite'))}
            </div>
          )
        ) : view === 'dates' ? (
          dateFolders.length === 0 ? (
            <div className="p-4 text-center text-xs" style={{ color: 'var(--color-text-muted)' }}>
              No conversations yet
            </div>
          ) : (
            dateFolders.map(folder => folderBlock({
              id: `date-${folder.key}`,
              label: folder.label,
              sessions: folder.sessions,
              expanded: Boolean(expandedDateFolders[folder.key]),
              onToggle: () => toggleDateFolder(folder.key),
              rowVariant: 'dated',
            }))
          )
        ) : agentFolders.length === 0 ? (
          <div className="p-4 text-center text-xs" style={{ color: 'var(--color-text-muted)' }}>
            No conversations yet
          </div>
        ) : (
          agentFolders.map(folder => folderBlock({
            id: `agent-${folder.agentId}`,
            label: folder.agentName,
            sessions: folder.sessions,
            expanded: Boolean(expandedAgentFolders[folder.agentId]),
            onToggle: () => toggleAgentFolder(folder.agentId),
          }))
        )}
      </div>

      {footer && (
        // No separator rule above this: it was a 1px #3c3c3c line on a #252526
        // column, which reads as a white line in the dark theme. The footer is
        // pinned under the list anyway, so the spacing does the separating.
        <div className="pt-1 pb-2 px-2">
          {footer}
        </div>
      )}
    </div>
  );
}
