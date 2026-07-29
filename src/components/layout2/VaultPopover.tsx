/**
 * VaultPopover — Obsidian-style vault switcher popover.
 *
 * Anchored to the vault button in the ActivityBar. Lists all projects
 * (vaults) and lets the user select one. Closes on selection or outside click.
 */
import { useEffect, useRef } from 'react';
import { useLayoutTokens } from './tokens';
import { useProject } from '../../contexts/ProjectContext';
import { Folder, CheckCircle, Loader } from 'lucide-react';

interface VaultPopoverProps {
  anchorRef: React.RefObject<HTMLElement | null>;
  onClose: () => void;
}

export default function VaultPopover({ anchorRef, onClose }: VaultPopoverProps) {
  const t = useLayoutTokens();
  const { activeProjectId, projects, setActiveProjectId, loading } = useProject();
  const popoverRef = useRef<HTMLDivElement | null>(null);

  // Close on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        popoverRef.current &&
        !popoverRef.current.contains(target) &&
        anchorRef.current &&
        !anchorRef.current.contains(target)
      ) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [anchorRef, onClose]);

  // Close on Escape
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [onClose]);

  const handleSelect = (id: number) => {
    setActiveProjectId(id);
    onClose();
  };

  return (
    <div
      ref={popoverRef}
      style={{
        position: 'absolute',
        left: 56,
        top: 0,
        width: 260,
        maxHeight: 400,
        overflowY: 'auto',
        background: t.bgSidebar,
        border: `1px solid ${t.border}`,
        borderRadius: 8,
        boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
        zIndex: 1000,
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '12px 14px 8px',
          fontSize: 11,
          fontWeight: 600,
          letterSpacing: 0.3,
          textTransform: 'uppercase',
          color: t.textMuted,
          borderBottom: `1px solid ${t.border}`,
        }}
      >
        Switch Vault
      </div>

      {/* Project list */}
      <div style={{ padding: '6px' }}>
        {loading ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '12px 8px', fontSize: 12, color: t.textMuted }}>
            <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
            Loading vaults...
          </div>
        ) : projects.length === 0 ? (
          <div style={{ padding: '16px 8px', textAlign: 'center', fontSize: 12, color: t.textMuted }}>
            No projects found
          </div>
        ) : (
          projects.map((project) => {
            const isActive = project.id === activeProjectId;
            return (
              <button
                key={project.id}
                onClick={() => handleSelect(project.id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  width: '100%',
                  padding: '8px 10px',
                  borderRadius: 6,
                  border: 'none',
                  background: isActive ? t.bgHover : 'transparent',
                  color: t.textPrimary,
                  cursor: 'pointer',
                  fontSize: 12,
                  textAlign: 'left',
                  marginBottom: 2,
                }}
                onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = 'rgba(255,255,255,0.04)'; }}
                onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
              >
                <Folder size={15} style={{ color: isActive ? t.accent : t.textMuted, flexShrink: 0 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {project.name}
                  </div>
                  {project.description && (
                    <div style={{ fontSize: 10, color: t.textMuted, marginTop: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {project.description}
                    </div>
                  )}
                </div>
                {isActive && (
                  <CheckCircle size={14} style={{ color: '#22c55e', flexShrink: 0 }} />
                )}
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
