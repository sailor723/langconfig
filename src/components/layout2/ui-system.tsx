/**
 * ui-system — shared UI primitives for the layout2 shell.
 *
 * Consolidates the duplicated inline-style button patterns found in
 * LeftSidebar, WorkflowEditor, FileEditor, etc. into reusable components
 * that all consume LayoutTokens consistently.
 */
import type { ReactNode, CSSProperties } from 'react';
import type { LayoutTokens } from './tokens';

// ── Props shared across all primitives ────────────────────

interface BaseProps {
  onClick?: () => void;
  title?: string;
  children: ReactNode;
  style?: CSSProperties;
  t: LayoutTokens;
}

// ── Icon-only button ──────────────────────────────────────
// 26×26 square, used for toolbars and header actions.

interface IconButtonProps extends BaseProps {
  /** When true, render 36×36 for the ActivityBar scale */
  large?: boolean;
}

export function IconButton({ onClick, title, children, style, t, large = false }: IconButtonProps) {
  const size = large ? 36 : 26;
  return (
    <button
      title={title}
      onClick={onClick}
      style={{
        width: size,
        height: size,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'transparent',
        border: 'none',
        borderRadius: 4,
        color: t.textMuted,
        cursor: 'pointer',
        flexShrink: 0,
        ...style,
      }}
      onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
      onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
    />
  );
}

// ── Toolbar button ────────────────────────────────────────
// 26px tall with text (optionally icon), visible border, hover.
// Used in WorkflowEditor and FileEditor toolbars.

interface ToolbarButtonProps extends BaseProps {
  danger?: boolean;
  disabled?: boolean;
  /** Force a specific active/selected background (e.g. for toggle state) */
  active?: boolean;
}

export function ToolbarButton({
  onClick, title, children, style, t, danger = false, disabled = false, active = false,
}: ToolbarButtonProps) {
  return (
    <button
      onClick={disabled ? undefined : onClick}
      title={title}
      disabled={disabled}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 4,
        height: 26,
        padding: '0 8px',
        fontSize: 12,
        color: danger ? '#e5484d' : (disabled ? t.textDim : t.textPrimary),
        background: active ? t.bgSelected : 'transparent',
        border: `1px solid ${danger ? '#e5484d44' : t.border}`,
        borderRadius: 4,
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        whiteSpace: 'nowrap',
        flexShrink: 0,
        ...style,
      }}
      onMouseEnter={e => {
        if (!disabled) e.currentTarget.style.background = active ? t.bgSelected : t.bgHover;
      }}
      onMouseLeave={e => {
        e.currentTarget.style.background = active ? t.bgSelected : 'transparent';
      }}
    >
      {children}
    </button>
  );
}

// ── Menu button ───────────────────────────────────────────
// Full-width row for context menus and dropdown panels.

interface MenuButtonProps {
  onClick: () => void;
  children: ReactNode;
  t: LayoutTokens;
  icon?: ReactNode;
  shortcut?: string;
  danger?: boolean;
}

export function MenuButton({ onClick, children, t, icon, shortcut, danger = false }: MenuButtonProps) {
  return (
    <button
      onClick={onClick}
      onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
      onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        width: '100%',
        padding: '6px 10px',
        fontSize: 13,
        color: danger ? '#e5484d' : t.textPrimary,
        background: 'transparent',
        border: 'none',
        borderRadius: 4,
        cursor: 'pointer',
        textAlign: 'left',
      }}
    >
      {icon && <span style={{ display: 'flex', width: 16, opacity: 0.7, flexShrink: 0 }}>{icon}</span>}
      <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {children}
      </span>
      {shortcut && (
        <span style={{ fontSize: 11, color: t.textDim, flexShrink: 0 }}>{shortcut}</span>
      )}
    </button>
  );
}

// ── Header label ──────────────────────────────────────────
// Uppercase section label used in sidebar headers.

interface HeaderLabelProps {
  children: string;
  t: LayoutTokens;
}

export function HeaderLabel({ children, t }: HeaderLabelProps) {
  return (
    <span
      style={{
        fontSize: 12,
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        color: t.textMuted,
        userSelect: 'none',
      }}
    >
      {children}
    </span>
  );
}

// ── Panel header ──────────────────────────────────────────
// Reusable header row for sidebars and panels (title + close btn).

interface PanelHeaderProps {
  title: string;
  onClose?: () => void;
  t: LayoutTokens;
  children?: ReactNode;
}

export function PanelHeader({ title, onClose, t, children }: PanelHeaderProps) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '10px 12px',
        borderBottom: `1px solid ${t.border}`,
        minHeight: 40,
      }}
    >
      <span style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary }}>
        {title}
      </span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        {children}
        {onClose && (
          <IconButton onClick={onClose} title="Close" t={t}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </IconButton>
        )}
      </div>
    </div>
  );
}
