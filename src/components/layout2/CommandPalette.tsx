/**
 * CommandPalette — VS Code-style Cmd+Shift+P command palette.
 *
 * Opens on Cmd+Shift+P / Ctrl+Shift+P. Lists available commands
 * with fuzzy search, keyboard navigation, and keyboard shortcut hints.
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useLayoutTokens } from './tokens';
import { useLayoutState, ACTIVITIES, type ActivityId, type Tab } from './useLayout';
import { Search, ArrowUpDown } from 'lucide-react';

// ── Command definitions ──────────────────────────────────

interface Command {
  id: string;
  label: string;
  shortcut?: string;
  /** Icon name shown in the result list */
  icon: string;
  execute: () => void;
}

interface CommandPaletteProps {
  onClose: () => void;
  /** Callback to open the quick file picker (Cmd+P) */
  onOpenQuickPicker?: () => void;
}

export default function CommandPalette({ onClose, onOpenQuickPicker }: CommandPaletteProps) {
  const t = useLayoutTokens();
  const {
    activeActivity, setActiveActivity,
    sidebarOpen, toggleSidebar,
    bottomPanelOpen, toggleBottomPanel,
    closeTab, activeTabId, tabs, setActiveTab,
    openTab,
  } = useLayoutState();

  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);

  // Build command list
  const commands = useMemo<Command[]>(() => {
    const cmds: Command[] = [];

    // Navigation
    if (onOpenQuickPicker) {
      cmds.push({ id: 'quick-picker', label: 'Quick File Picker', shortcut: 'Cmd+P', icon: 'file', execute: () => { onOpenQuickPicker(); onClose(); } });
    }

    cmds.push({ id: 'toggle-sidebar', label: sidebarOpen ? 'Hide Sidebar' : 'Show Sidebar', shortcut: 'Cmd+B', icon: 'sidebar', execute: () => { toggleSidebar(); onClose(); } });
    cmds.push({ id: 'toggle-bottom', label: bottomPanelOpen ? 'Hide Bottom Panel' : 'Show Bottom Panel', shortcut: 'Cmd+J', icon: 'bottom', execute: () => { toggleBottomPanel(); onClose(); } });

    // Tabs
    if (tabs.length > 0) {
      cmds.push({ id: 'close-tab', label: 'Close Active Tab', shortcut: 'Cmd+W', icon: 'close', execute: () => { if (activeTabId) closeTab(activeTabId); onClose(); } });
    }

    // Activity switching
    for (const act of ACTIVITIES) {
      cmds.push({
        id: `activity-${act.id}`,
        label: `Switch to ${act.label}`,
        icon: 'activity',
        execute: () => { setActiveActivity(act.id); onClose(); },
      });
    }

    // New file
    cmds.push({
      id: 'new-file',
      label: 'New File',
      shortcut: 'Cmd+N',
      icon: 'new',
      execute: () => {
        const tab: Tab = {
          id: `new-${Date.now()}`,
          label: 'Untitled',
          viewType: activeActivity,
          data: { new: true },
        };
        openTab(tab);
        onClose();
      },
    });

    return cmds;
  }, [activeActivity, activeTabId, bottomPanelOpen, closeTab, onClose, onOpenQuickPicker, openTab, setActiveActivity, sidebarOpen, tabs, toggleBottomPanel, toggleSidebar]);

  // Filter commands based on query
  const filtered = useMemo(() => {
    if (!query.trim()) return commands;
    const q = query.toLowerCase();
    return commands.filter(cmd =>
      cmd.label.toLowerCase().includes(q) ||
      (cmd.shortcut && cmd.shortcut.toLowerCase().includes(q))
    );
  }, [commands, query]);

  // Reset selection when results change
  useEffect(() => setSelectedIndex(0), [filtered.length]);

  // Focus input
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Scroll selected item into view
  useEffect(() => {
    const el = listRef.current?.children[selectedIndex] as HTMLElement | undefined;
    el?.scrollIntoView({ block: 'nearest' });
  }, [selectedIndex]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setSelectedIndex(i => Math.min(i + 1, filtered.length - 1));
        break;
      case 'ArrowUp':
        e.preventDefault();
        setSelectedIndex(i => Math.max(i - 1, 0));
        break;
      case 'Enter':
        e.preventDefault();
        if (filtered[selectedIndex]) {
          filtered[selectedIndex].execute();
        }
        break;
      case 'Escape':
        e.preventDefault();
        onClose();
        break;
    }
  }, [filtered, selectedIndex, onClose]);

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'flex-start',
        paddingTop: '15vh',
      }}
      onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      {/* Backdrop */}
      <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.3)' }} />

      {/* Dialog */}
      <div
        style={{
          position: 'relative',
          width: 520,
          maxWidth: '90vw',
          background: t.bgBase,
          border: `1px solid ${t.border}`,
          borderRadius: 12,
          boxShadow: '0 16px 48px rgba(0,0,0,0.4)',
          overflow: 'hidden',
        }}
      >
        {/* Search input */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '12px 16px', borderBottom: `1px solid ${t.border}` }}>
          <Search size={16} style={{ color: t.textMuted, flexShrink: 0 }} />
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a command..."
            spellCheck={false}
            style={{
              flex: 1,
              background: 'transparent',
              border: 'none',
              color: t.textPrimary,
              fontSize: 15,
              outline: 'none',
            }}
          />
        </div>

        {/* Results */}
        <div
          ref={listRef}
          style={{
            maxHeight: 320,
            overflowY: 'auto',
            padding: 4,
          }}
        >
          {filtered.length === 0 && (
            <div style={{ padding: '16px 20px', color: t.textMuted, fontSize: 13, textAlign: 'center' }}>
              {query ? 'No matching commands' : 'No commands available'}
            </div>
          )}
          {filtered.map((cmd, i) => (
            <div
              key={cmd.id}
              onClick={() => cmd.execute()}
              onMouseEnter={() => setSelectedIndex(i)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '8px 12px',
                borderRadius: 6,
                cursor: 'pointer',
                background: i === selectedIndex ? t.bgHover : 'transparent',
                color: t.textPrimary,
                fontSize: 13,
              }}
            >
              <span style={{ width: 18, height: 18, display: 'flex', alignItems: 'center', justifyContent: 'center', opacity: 0.5, flexShrink: 0 }}>
                <CommandIcon name={cmd.icon} />
              </span>
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {cmd.label}
              </span>
              {cmd.shortcut && (
                <span style={{ fontSize: 11, color: t.textDim, flexShrink: 0, fontFamily: '"SF Mono", "Fira Code", monospace' }}>
                  {cmd.shortcut}
                </span>
              )}
            </div>
          ))}
        </div>

        {/* Footer hint */}
        <div style={{ padding: '6px 12px', borderTop: `1px solid ${t.border}`, display: 'flex', gap: 12, fontSize: 11, color: t.textDim }}>
          <span>↑↓ Navigate</span>
          <span>↵ Execute</span>
          <span>Esc Close</span>
        </div>
      </div>
    </div>
  );
}

// ── Simple icon renderer for command types ────────────────

function CommandIcon({ name }: { name: string }) {
  switch (name) {
    case 'file':
      return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>;
    case 'sidebar':
      return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg>;
    case 'bottom':
      return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="15" x2="21" y2="15"/></svg>;
    case 'close':
      return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>;
    case 'activity':
      return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>;
    case 'new':
      return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>;
    default:
      return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="10"/></svg>;
  }
}
