/**
 * TreeView — recursive tree node for the file explorer sidebar.
 *
 * Supports:
 * - Folders expand/collapse
 * - Files open as workspace tabs on click
 * - Right-click context menu (rename, delete, new file/folder)
 * - Double-click to inline rename
 */
import { useState, useCallback, useRef, useEffect } from 'react';
import { useLayoutTokens } from './tokens';
import ContextMenu, { type ContextMenuAction } from './ContextMenu';
import { ChevronRight, File, Folder, FolderOpen, Pencil, Trash2, Plus, FilePlus, FolderPlus, RefreshCw, Search } from 'lucide-react';

export interface TreeNode {
  id: string;
  label: string;
  children?: TreeNode[];
  viewType?: string;
  badge?: string;
  data?: any;
}

interface TreeViewProps {
  nodes: TreeNode[];
  onFileOpen?: (node: TreeNode) => void;
  onRename?: (node: TreeNode, newName: string) => void;
  onDelete?: (node: TreeNode) => void;
  onNewFile?: (parent?: TreeNode) => void;
  onNewFolder?: (parent?: TreeNode) => void;
  /**
   * Optional callback fired when a folder's "+" action button is clicked.
   * When set, folder rows render a small "+" button on the right side.
   */
  onFolderAction?: (node: TreeNode) => void;
  /**
   * Optional callback fired when a folder's refresh button is clicked.
   * When set, folder rows render a refresh icon before the "+" button.
   */
  onFolderRefresh?: (node: TreeNode) => void;
  /**
   * Optional search value — when set, the top-level folder row renders
   * a compact search input inline with the label and action buttons.
   */
  folderSearchValue?: string;
  /** Callback when the folder search input changes */
  onFolderSearchChange?: (value: string) => void;
  level?: number;
}

interface CMState {
  x: number;
  y: number;
  node: TreeNode;
}

export default function TreeView({
  nodes, onFileOpen, onRename, onDelete, onNewFile, onNewFolder, onFolderAction, onFolderRefresh,
  folderSearchValue, onFolderSearchChange, level = 0,
}: TreeViewProps) {
  const t = useLayoutTokens();

  return (
    <div>
      {nodes.map(node => (
        <TreeNodeItem
          key={node.id}
          node={node}
          onFileOpen={onFileOpen}
          onRename={onRename}
          onDelete={onDelete}
          onNewFile={onNewFile}
          onNewFolder={onNewFolder}
          onFolderAction={onFolderAction}
          onFolderRefresh={onFolderRefresh}
          folderSearchValue={folderSearchValue}
          onFolderSearchChange={onFolderSearchChange}
          level={level}
        />
      ))}
    </div>
  );
}

function TreeNodeItem({
  node, onFileOpen, onRename, onDelete, onNewFile, onNewFolder, onFolderAction, onFolderRefresh,
  folderSearchValue, onFolderSearchChange, level,
}: {
  node: TreeNode;
  onFileOpen?: (node: TreeNode) => void;
  onRename?: (node: TreeNode, newName: string) => void;
  onDelete?: (node: TreeNode) => void;
  onNewFile?: (parent?: TreeNode) => void;
  onNewFolder?: (parent?: TreeNode) => void;
  onFolderAction?: (node: TreeNode) => void;
  onFolderRefresh?: (node: TreeNode) => void;
  folderSearchValue?: string;
  onFolderSearchChange?: (value: string) => void;
  level: number;
}) {
  const t = useLayoutTokens();
  const [expanded, setExpanded] = useState(level < 1);
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState(node.label);
  const [cm, setCm] = useState<CMState | null>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);

  const isFolder = node.children && node.children.length > 0;

  // Focus rename input when renaming starts
  useEffect(() => {
    if (renaming) renameInputRef.current?.focus();
  }, [renaming]);

  const handleClick = useCallback(() => {
    if (renaming) return;
    if (isFolder) {
      setExpanded(v => !v);
    } else {
      onFileOpen?.(node);
    }
  }, [isFolder, node, onFileOpen, renaming]);

  const handleDoubleClick = useCallback(() => {
    setRenameValue(node.label);
    setRenaming(true);
  }, [node.label]);

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setCm({ x: e.clientX, y: e.clientY, node });
  }, [node]);

  const confirmRename = useCallback(() => {
    const trimmed = renameValue.trim();
    if (trimmed && trimmed !== node.label) {
      onRename?.(node, trimmed);
    }
    setRenaming(false);
  }, [renameValue, node, onRename]);

  const actions: ContextMenuAction[] = [
    ...(isFolder ? [
      { id: 'new-file', label: 'New File', icon: <FilePlus size={14} />, onClick: () => onNewFile?.(node) },
      { id: 'new-folder', label: 'New Folder', icon: <FolderPlus size={14} />, onClick: () => onNewFolder?.(node) },
      { id: 'sep-1', label: '', icon: undefined, onClick: () => {} } as any,
    ] : []),
    { id: 'rename', label: 'Rename', icon: <Pencil size={14} />, shortcut: 'F2', onClick: () => { setRenameValue(node.label); setRenaming(true); } },
    { id: 'delete', label: 'Delete', icon: <Trash2 size={14} />, danger: true, onClick: () => onDelete?.(node) },
  ].filter(a => {
    if (a.id === 'sep-1') return false;
    return true;
  });

  return (
    <div>
      {/* Row */}
      <div
        role="treeitem"
        tabIndex={0}
        aria-expanded={isFolder ? expanded : undefined}
        onClick={handleClick}
        onDoubleClick={handleDoubleClick}
        onContextMenu={handleContextMenu}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleClick(); }
          if (e.key === 'F2') { setRenameValue(node.label); setRenaming(true); }
        }}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          padding: '2px 8px 2px 6px',
          paddingLeft: 6 + level * 16,
          fontSize: 13,
          color: t.textPrimary,
          cursor: 'pointer',
          borderRadius: 0,
          userSelect: 'none',
        }}
        onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
        onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
      >
        {/* Expand/collapse chevron */}
        {isFolder ? (
          <span style={{ display: 'flex', opacity: 0.6, width: 16, height: 16, alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            <ChevronRight size={14} style={{ transform: expanded ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }} />
          </span>
        ) : (
          <span style={{ width: 16, flexShrink: 0 }} />
        )}

        {/* Folder/file icon */}
        <span style={{ display: 'flex', opacity: 0.7, flexShrink: 0 }}>
          {isFolder ? (
            expanded ? <FolderOpen size={15} /> : <Folder size={15} />
          ) : (
            <File size={15} />
          )}
        </span>

        {/* Label or rename input */}
        {renaming ? (
          <input
            ref={renameInputRef}
            value={renameValue}
            onChange={e => setRenameValue(e.target.value)}
            onBlur={confirmRename}
            onKeyDown={e => {
              if (e.key === 'Enter') confirmRename();
              if (e.key === 'Escape') setRenaming(false);
              e.stopPropagation();
            }}
            onClick={e => e.stopPropagation()}
            style={{
              flex: 1,
              minWidth: 0,
              padding: '2px 4px',
              fontSize: 13,
              background: t.bgInput,
              border: `1px solid ${t.accent}`,
              borderRadius: 3,
              color: t.textPrimary,
              outline: 'none',
            }}
          />
        ) : (
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, minWidth: 0 }}>
            {node.label}
          </span>
        )}

        {/* Folder search input — inline with label, on folder rows only */}
        {isFolder && !renaming && folderSearchValue !== undefined && onFolderSearchChange && level === 0 && (
          <div style={{ position: 'relative', flex: 1, minWidth: 80, maxWidth: 160, marginLeft: 8 }}>
            <Search size={11} style={{
              position: 'absolute', left: 6, top: '50%',
              transform: 'translateY(-50%)', color: t.textMuted, pointerEvents: 'none',
            }} />
            <input
              value={folderSearchValue}
              onChange={e => { e.stopPropagation(); onFolderSearchChange(e.target.value); }}
              onClick={e => e.stopPropagation()}
              onKeyDown={e => e.stopPropagation()}
              placeholder="Filter..."
              style={{
                width: '100%',
                padding: '2px 6px 2px 20px',
                background: t.bgInput,
                border: `1px solid ${t.border}`,
                borderRadius: 3,
                color: t.textPrimary,
                fontSize: 11,
                outline: 'none',
                boxSizing: 'border-box',
                lineHeight: '18px',
              }}
            />
          </div>
        )}

        {/* Badge */}
        {!renaming && node.badge && (
          <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 4, background: t.bgHover, color: t.textDim, flexShrink: 0 }}>
            {node.badge}
          </span>
        )}

        {/* Folder refresh button (↻) */}
        {isFolder && !renaming && onFolderRefresh && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              e.preventDefault();
              onFolderRefresh(node);
            }}
            title="Refresh"
            style={{
              width: 18,
              height: 18,
              padding: 0,
              background: 'transparent',
              border: 'none',
              borderRadius: 3,
              color: t.textDim,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = t.bgHover; e.currentTarget.style.color = t.textPrimary; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = t.textDim; }}
          >
            <RefreshCw size={12} />
          </button>
        )}

        {/* Folder action button (+ New) */}
        {isFolder && !renaming && onFolderAction && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              e.preventDefault();
              onFolderAction(node);
            }}
            title={`Add new to "${node.label}"`}
            style={{
              width: 18,
              height: 18,
              padding: 0,
              background: 'transparent',
              border: 'none',
              borderRadius: 3,
              color: t.textDim,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = t.bgHover; e.currentTarget.style.color = t.textPrimary; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = t.textDim; }}
          >
            <Plus size={13} />
          </button>
        )}
      </div>

      {/* Children */}
      {isFolder && expanded && node.children && (
        <TreeView
          nodes={node.children}
          onFileOpen={onFileOpen}
          onRename={onRename}
          onDelete={onDelete}
          onNewFile={onNewFile}
          onNewFolder={onNewFolder}
          onFolderAction={onFolderAction}
          onFolderRefresh={onFolderRefresh}
          level={level + 1}
        />
      )}

      {/* Context menu */}
      {cm && cm.node.id === node.id && (
        <ContextMenu x={cm.x} y={cm.y} actions={actions} onClose={() => setCm(null)} />
      )}
    </div>
  );
}
