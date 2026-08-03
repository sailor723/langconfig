/**
 * SystemSettingsPopover — popover anchored to the ActivityBar settings gear.
 *
 * Mirrors the agent-workspace pattern:
 *   - Appearance (Dark / Warm / White theme)
 *   - Language (English / 中文)
 *   - Local Workspace (path, permissions)
 *
 * Closes on outside click or Escape.
 */
import { useEffect, useRef, useState } from 'react';
import { useLayoutTokens } from './tokens';
import { useTheme, type ThemeName } from '../../lib/themes';
import { useTranslation } from 'react-i18next';
import { Check, Sun, Moon, Flame, FolderOpen, Database } from 'lucide-react';
import apiClient from '../../lib/api-client';

interface SystemSettingsPopoverProps {
  anchorRef: React.RefObject<HTMLElement | null>;
  onClose: () => void;
}

const POPOVER_WIDTH = 260;

type SettingsTab = 'appearance' | 'language' | 'workspace' | 'storage';

const TABS: { id: SettingsTab; label: string; icon: React.ReactNode }[] = [
  { id: 'appearance', label: 'Appearance', icon: <Sun size={14} /> },
  { id: 'language',   label: 'Language',   icon: <span style={{ fontSize: 13 }}>A</span> },
  { id: 'workspace',  label: 'Workspace',  icon: <FolderOpen size={14} /> },
  { id: 'storage',    label: 'Storage',    icon: <Database size={14} /> },
];

export default function SystemSettingsPopover({ anchorRef, onClose }: SystemSettingsPopoverProps) {
  const { t: _t, i18n } = useTranslation('chat');
  const { theme: activeTheme, setTheme } = useTheme();
  const tk = useLayoutTokens();
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const [activeTab, setActiveTab] = useState<SettingsTab>('appearance');

  // ── Local workspace state ──
  const [workspacePath, setWorkspacePath] = useState('');
  const [allowRead, setAllowRead] = useState(true);
  const [allowWrite, setAllowWrite] = useState(true);
  const [requireApproval, setRequireApproval] = useState(true);
  const [workspaceLoading, setWorkspaceLoading] = useState(true);
  const [workspaceSaved, setWorkspaceSaved] = useState(false);

  // ── Storage mode state (docs/system-architecture.md §15, Phase 5) ──
  const [storageMode, setStorageMode] = useState<'local' | 'db'>('local');
  const [storageSource, setStorageSource] = useState<'env' | 'db'>('env');

  // Load workspace settings on mount
  useEffect(() => {
    apiClient.getWorkspaceSettings().then((res: any) => {
      const d = res.data;
      setWorkspacePath(d.workspace_path || '');
      setAllowRead(d.allow_read ?? true);
      setAllowWrite(d.allow_write ?? true);
      setRequireApproval(d.require_approval ?? true);
    }).catch(() => {}).finally(() => setWorkspaceLoading(false));

    // Load current storage mode
    apiClient.getStorageMode().then((res: any) => {
      const d = res.data;
      if (d.mode === 'local' || d.mode === 'db') setStorageMode(d.mode);
      if (d.source === 'env' || d.source === 'db') setStorageSource(d.source);
    }).catch(() => {});
  }, []);

  // Switch storage backend at runtime — takes effect immediately (the backend
  // drops its cached backend via reset_storage()) and persists the choice.
  const switchStorageMode = async (mode: 'local' | 'db') => {
    if (mode === storageMode) return;
    try {
      const res = await apiClient.updateStorageMode({ mode });
      setStorageMode(res.data.mode);
      setStorageSource('db');
    } catch {}
  };

  const saveWorkspace = async () => {
    try {
      await apiClient.updateWorkspaceSettings({
        workspace_path: workspacePath,
        allow_read: allowRead,
        allow_write: allowWrite,
        require_approval: requireApproval,
      });
      setWorkspaceSaved(true);
      setTimeout(() => setWorkspaceSaved(false), 2000);
    } catch {}
  };

  // Close on outside click or Escape
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      const target = e.target as Node;
      if (popoverRef.current?.contains(target) || anchorRef.current?.contains(target)) return;
      onClose();
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [onClose, anchorRef]);

  // Popover position
  const [position, setPosition] = useState<{ left: number; bottom: number } | null>(null);
  useEffect(() => {
    const anchor = anchorRef.current;
    if (!anchor) return;
    const rect = anchor.getBoundingClientRect();
    setPosition({ left: rect.right + 4, bottom: window.innerHeight - rect.bottom });
  }, [anchorRef]);

  if (!position) return null;

  const THEME_OPTIONS: { id: ThemeName; label: string; Icon: typeof Sun }[] = [
    { id: 'dark',  label: 'Dark',  Icon: Moon },
    { id: 'warm',  label: 'Warm',  Icon: Flame },
    { id: 'white', label: 'White', Icon: Sun },
  ];

  const inputStyle: React.CSSProperties = {
    width: '100%',
    height: 28,
    padding: '0 8px',
    background: tk.bgInput,
    border: `1px solid ${tk.border}`,
    borderRadius: 3,
    color: tk.textPrimary,
    fontSize: 12,
    outline: 'none',
    boxSizing: 'border-box',
  };

  return (
    <div
      ref={popoverRef}
      role="dialog"
      aria-label="Settings"
      style={{
        position: 'fixed',
        left: position.left,
        bottom: position.bottom,
        width: POPOVER_WIDTH,
        background: tk.bgDropdown,
        border: `1px solid ${tk.border}`,
        borderRadius: 4,
        boxShadow: '0 4px 16px rgba(0,0,0,0.18)',
        zIndex: 200,
        fontSize: 13,
        color: tk.textPrimary,
        overflow: 'hidden',
      }}
    >
      {/* ── Header ── */}
      <div
        style={{
          padding: '8px 12px',
          borderBottom: `1px solid ${tk.border}`,
          color: tk.textMuted,
          fontSize: 11,
          fontWeight: 500,
          letterSpacing: 0.5,
          textTransform: 'uppercase',
        }}
      >
        Settings
      </div>

      {/* ── Tab bar ── */}
      <div style={{ display: 'flex', borderBottom: `1px solid ${tk.border}`, padding: '0 4px' }}>
        {TABS.map(tab => {
          const isActive = tab.id === activeTab;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{
                flex: 1,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 4,
                height: 30,
                background: 'transparent',
                border: 'none',
                borderBottom: isActive ? `2px solid ${tk.accent}` : '2px solid transparent',
                color: isActive ? tk.textPrimary : tk.textMuted,
                fontSize: 11,
                cursor: 'pointer',
                padding: '0 6px',
              }}
            >
              {tab.icon}
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* ── Appearance ── */}
      {activeTab === 'appearance' && (
        <div style={{ padding: '6px 8px' }}>
          {THEME_OPTIONS.map(({ id, label, Icon }) => {
            const isActive = activeTheme.name === id;
            return (
              <button
                key={id}
                onClick={() => { setTheme(id); apiClient.updateGeneralSettings({ theme: id }).catch(() => {}); }}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  width: '100%',
                  padding: '6px 10px',
                  background: isActive ? tk.bgSelected : 'transparent',
                  border: 'none',
                  borderRadius: 3,
                  cursor: 'pointer',
                  color: tk.textPrimary,
                  fontSize: 13,
                  textAlign: 'left',
                }}
                onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = tk.bgHover; }}
                onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
              >
                <Icon size={14} strokeWidth={1.5} style={{ color: tk.textMuted }} />
                <span style={{ flex: 1 }}>{label}</span>
                {isActive && <Check size={14} strokeWidth={2} style={{ color: tk.accent }} />}
              </button>
            );
          })}
        </div>
      )}

      {/* ── Language ── */}
      {activeTab === 'language' && (
        <div style={{ padding: '6px 8px' }}>
          {[
            { id: 'en', label: 'English' },
            { id: 'zh', label: '中文' },
          ].map(({ id, label }) => {
            const isActive = i18n.language.startsWith(id);
            return (
              <button
                key={id}
                onClick={() => i18n.changeLanguage(id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  width: '100%',
                  padding: '6px 10px',
                  background: isActive ? tk.bgSelected : 'transparent',
                  border: 'none',
                  borderRadius: 3,
                  cursor: 'pointer',
                  color: tk.textPrimary,
                  fontSize: 13,
                  textAlign: 'left',
                }}
                onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = tk.bgHover; }}
                onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
              >
                <span style={{ flex: 1 }}>{label}</span>
                {isActive && <Check size={14} strokeWidth={2} style={{ color: tk.accent }} />}
              </button>
            );
          })}
        </div>
      )}

      {/* ── Workspace ── */}
      {activeTab === 'workspace' && (
        <div style={{ padding: '8px 10px' }}>
          {workspaceLoading ? (
            <div style={{ textAlign: 'center', padding: 12, color: tk.textMuted, fontSize: 12 }}>
              Loading...
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {/* Path input */}
              <div>
                <div style={{ fontSize: 10, color: tk.textMuted, textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 3 }}>
                  Workspace Path
                </div>
                <input
                  value={workspacePath}
                  onChange={e => setWorkspacePath(e.target.value)}
                  placeholder="/path/to/project"
                  style={inputStyle}
                />
              </div>

              {/* Permissions */}
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 12 }}>
                <input type="checkbox" checked={allowRead} onChange={e => setAllowRead(e.target.checked)} style={{ margin: 0 }} />
                Allow Read
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 12 }}>
                <input type="checkbox" checked={allowWrite} onChange={e => setAllowWrite(e.target.checked)} style={{ margin: 0 }} />
                Allow Write
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: !allowWrite ? 'not-allowed' : 'pointer', opacity: !allowWrite ? 0.5 : 1, fontSize: 12 }}>
                <input type="checkbox" checked={requireApproval} onChange={e => setRequireApproval(e.target.checked)} disabled={!allowWrite} style={{ margin: 0 }} />
                Require Approval
              </label>

              {/* Save button */}
              <button
                onClick={saveWorkspace}
                style={{
                  width: '100%',
                  height: 28,
                  background: tk.accent,
                  color: tk.textWhite,
                  border: 'none',
                  borderRadius: 3,
                  cursor: 'pointer',
                  fontSize: 12,
                  fontWeight: 500,
                  marginTop: 4,
                }}
              >
                {workspaceSaved ? 'Saved ✓' : 'Save'}
              </button>
            </div>
          )}
        </div>
      )}

      {/* ── Storage mode ── */}
      {activeTab === 'storage' && (
        <div style={{ padding: '6px 8px' }}>
          {([
            { id: 'local' as const, label: 'Local disk', desc: 'Default. Files on the local filesystem.' },
            { id: 'db' as const, label: 'PostgreSQL (BYTEA)', desc: 'Durable blobs in storage_objects.' },
          ]).map(({ id, label, desc }) => {
            const isActive = storageMode === id;
            return (
              <button
                key={id}
                onClick={() => switchStorageMode(id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  width: '100%',
                  padding: '6px 10px',
                  background: isActive ? tk.bgSelected : 'transparent',
                  border: 'none',
                  borderRadius: 3,
                  cursor: 'pointer',
                  color: tk.textPrimary,
                  fontSize: 13,
                  textAlign: 'left',
                }}
                onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = tk.bgHover; }}
                onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
              >
                <Database size={14} strokeWidth={1.5} style={{ color: tk.textMuted }} />
                <span style={{ flex: 1 }}>
                  <span style={{ display: 'block' }}>{label}</span>
                  <span style={{ display: 'block', fontSize: 11, color: tk.textMuted }}>{desc}</span>
                </span>
                {isActive && <Check size={14} strokeWidth={2} style={{ color: tk.accent }} />}
              </button>
            );
          })}
          <div style={{ padding: '6px 10px', fontSize: 11, color: tk.textMuted, lineHeight: 1.5 }}>
            Source: {storageSource === 'db' ? 'persisted (overrides .env)' : '.env / default'}. Switching does
            not migrate data — use CLI/batch scripts.
          </div>
        </div>
      )}
    </div>
  );
}
