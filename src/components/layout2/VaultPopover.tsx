/**
 * VaultPopover — Obsidian-style vault switcher popover.
 *
 * Anchored to the vault button in the ActivityBar. Lists all projects
 * (vaults) and lets the user select one. Closes on selection or outside click.
 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLayoutTokens } from './tokens';
import { useProject } from '../../contexts/ProjectContext';
import { Folder, CheckCircle, Loader, Plus, X } from 'lucide-react';
import apiClient from '../../lib/api-client';

interface VaultPopoverProps {
  anchorRef: React.RefObject<HTMLElement | null>;
  onClose: () => void;
}

export default function VaultPopover({ anchorRef, onClose }: VaultPopoverProps) {
  const t = useLayoutTokens();
  const navigate = useNavigate();
  const { activeProjectId, projects, setActiveProjectId, refreshProjects, loading } = useProject();
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [error, setError] = useState<string | null>(null);

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
    navigate('/project');
  };

  const handleCreate = async () => {
    const name = newName.trim();
    // NOTE: `creating` is true while the form is open, so it must not gate
    // the submit — only an empty name blocks it.
    if (!name) return;
    setCreating(true);
    setError(null);
    try {
      const res = await apiClient.createProject({ name });
      const newProject = res.data;
      await refreshProjects();
      setActiveProjectId(newProject.id);
      setNewName('');
      onClose();
      navigate('/project');
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? err?.message ?? 'Failed to create project';
      setError(typeof detail === 'string' ? detail : 'Failed to create project');
      setCreating(false);
    }
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

      {/* New project */}
      <div style={{ padding: '8px 10px', borderTop: `1px solid ${t.border}` }}>
        {creating ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <input
              autoFocus
              value={newName}
              onChange={e => setNewName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleCreate(); if (e.key === 'Escape') { setCreating(false); setNewName(''); } }}
              placeholder="Project name…"
              style={{
                flex: 1, height: 24, padding: '0 6px',
                background: t.bgContent, border: `1px solid ${t.border}`,
                borderRadius: 4, color: t.textPrimary, fontSize: 12, outline: 'none',
              }}
            />
            <button
              onClick={handleCreate}
              disabled={!newName.trim()}
              title="Create project"
              style={{
                height: 24, padding: '0 10px', border: 'none', borderRadius: 4,
                background: t.accent, color: '#fff', fontSize: 11, fontWeight: 600,
                cursor: newName.trim() ? 'pointer' : 'not-allowed', opacity: newName.trim() ? 1 : 0.5,
              }}
            >
              Create
            </button>
            <button
              onClick={() => { setCreating(false); setNewName(''); }}
              title="Cancel"
              style={{
                height: 24, width: 24, display: 'flex', alignItems: 'center', justifyContent: 'center',
                border: 'none', borderRadius: 4, background: 'transparent', color: t.textMuted, cursor: 'pointer',
              }}
            >
              <X size={13} />
            </button>
          </div>
        ) : (
          <button
            onClick={() => setCreating(true)}
            style={{
              display: 'flex', alignItems: 'center', gap: 6, width: '100%',
              padding: '6px 8px', borderRadius: 4, border: 'none',
              background: 'transparent', color: t.accent, cursor: 'pointer', fontSize: 12, fontWeight: 500,
            }}
          >
            <Plus size={13} /> New Project
          </button>
        )}
        {error && (
          <div style={{ fontSize: 10, color: '#ef4444', marginTop: 4 }}>{error}</div>
        )}
      </div>
    </div>
  );
}
