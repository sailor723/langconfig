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
import { ChevronRight, File, Folder, FolderOpen, Pencil, Trash2, Plus, FilePlus, FolderPlus } from 'lucide-react';

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
  level?: number;
}

interface CMState {
  x: number;
  y: number;
  node: TreeNode;
}

export default function TreeView({ nodes, onFileOpen, onRename, onDelete, onNewFile, onNewFolder, level = 0 }: TreeViewProps) {
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
          level={level}
        />
      ))}
    </div>
  );
}

function TreeNodeItem({
  node, onFileOpen, onRename, onDelete, onNewFile, onNewFolder, level,
}: {
  node: TreeNode;
  onFileOpen?: (node: TreeNode) => void;
  onRename?: (node: TreeNode, newName: string) => void;
  onDelete?: (node: TreeNode) => void;
  onNewFile?: (parent?: TreeNode) => void;
  onNewFolder?: (parent?: TreeNode) => void;
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
    if (onRename) {
      setRenameValue(node.label);
      setRenaming(true);
    }
  }, [node.label, onRename]);

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
          padding: '3px 8px 3px 0',
          paddingLeft: 8 + level * 16,
          fontSize: 13,
          color: t.textPrimary,
          cursor: 'pointer',
          borderRadius: 4,
          margin: '0 8px',
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

        {/* Badge */}
        {!renaming && node.badge && (
          <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 4, background: t.bgHover, color: t.textDim, flexShrink: 0 }}>
            {node.badge}
          </span>
        )}
      </div>

      {/* Children */}
      {isFolder && expanded && node.children && (
        <TreeView nodes={node.children} onFileOpen={onFileOpen} onRename={onRename} onDelete={onDelete} onNewFile={onNewFile} onNewFolder={onNewFolder} level={level + 1} />
      )}

      {/* Context menu */}
      {cm && cm.node.id === node.id && (
        <ContextMenu x={cm.x} y={cm.y} actions={actions} onClose={() => setCm(null)} />
      )}
    </div>
  );
}
