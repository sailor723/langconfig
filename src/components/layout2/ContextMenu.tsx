/**
 * ContextMenu — VS Code-style right-click menu for tree items.
 *
 * Appears at mouse position, offers actions like Rename, Delete,
 * New File, New Folder. Closes on click outside or Escape.
 */
import { useEffect, useRef, useCallback } from 'react';
import { useLayoutTokens } from './tokens';
import { MenuButton } from './ui-system';

export interface ContextMenuAction {
  id: string;
  label: string;
  icon?: React.ReactNode;
  shortcut?: string;
  danger?: boolean;
  onClick: () => void;
}

interface ContextMenuProps {
  x: number;
  y: number;
  actions: ContextMenuAction[];
  onClose: () => void;
}

export default function ContextMenu({ x, y, actions, onClose }: ContextMenuProps) {
  const t = useLayoutTokens();
  const ref = useRef<HTMLDivElement>(null);

  // Close on click outside
  const handleClick = useCallback((e: MouseEvent) => {
    if (ref.current && !ref.current.contains(e.target as Node)) {
      onClose();
    }
  }, [onClose]);

  // Close on Escape
  const handleKey = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') onClose();
  }, [onClose]);

  useEffect(() => {
    document.addEventListener('mousedown', handleClick, true);
    document.addEventListener('keydown', handleKey, true);
    return () => {
      document.removeEventListener('mousedown', handleClick, true);
      document.removeEventListener('keydown', handleKey, true);
    };
  }, [handleClick, handleKey]);

  // Adjust position to stay within viewport
  const adjustedX = Math.min(x, window.innerWidth - 200);
  const adjustedY = Math.min(y, window.innerHeight - actions.length * 32);

  return (
    <div
      ref={ref}
      style={{
        position: 'fixed',
        top: adjustedY,
        left: adjustedX,
        minWidth: 180,
        background: t.bgBase,
        border: `1px solid ${t.border}`,
        borderRadius: 8,
        boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
        padding: '4px',
        zIndex: 10000,
      }}
    >
      {actions.map((action, i) => (
        <MenuButton
          key={action.id}
          onClick={() => { action.onClick(); onClose(); }}
          icon={action.icon}
          shortcut={action.shortcut}
          danger={action.danger}
          t={t}
        >
          {action.label}
        </MenuButton>
      ))}
    </div>
  );
}
