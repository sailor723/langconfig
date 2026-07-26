/**
 * TreeView — recursive tree node for the file explorer sidebar.
 *
 * Supports nested folders (expand/collapse) and leaf files (click → open tab).
 * Modeled after Obsidian's file explorer and VS Code's tree view.
 */
import { useState, useCallback, type ReactNode } from 'react';
import { useLayoutTokens } from './tokens';
import { ChevronRight, File, Folder, FolderOpen } from 'lucide-react';

export interface TreeNode {
  id: string;
  label: string;
  /** Nested children — if present, this node acts as a folder */
  children?: TreeNode[];
  /** Override view type when this node is opened as a tab */
  viewType?: string;
  /** Extra badge label (e.g. file extension) */
  badge?: string;
}

interface TreeViewProps {
  nodes: TreeNode[];
  /** Called when a leaf node (file) is clicked */
  onFileOpen?: (node: TreeNode) => void;
  /** Depth level for indentation */
  level?: number;
}

export default function TreeView({ nodes, onFileOpen, level = 0 }: TreeViewProps) {
  const t = useLayoutTokens();

  return (
    <div>
      {nodes.map(node => (
        <TreeNodeItem
          key={node.id}
          node={node}
          onFileOpen={onFileOpen}
          level={level}
        />
      ))}
    </div>
  );
}

function TreeNodeItem({ node, onFileOpen, level }: { node: TreeNode; onFileOpen?: (node: TreeNode) => void; level: number }) {
  const t = useLayoutTokens();
  const [expanded, setExpanded] = useState(level < 1); // auto-expand first level

  const isFolder = node.children && node.children.length > 0;

  const handleClick = useCallback(() => {
    if (isFolder) {
      setExpanded(v => !v);
    } else {
      onFileOpen?.(node);
    }
  }, [isFolder, node, onFileOpen]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      handleClick();
    }
  }, [handleClick]);

  return (
    <div>
      {/* Row */}
      <div
        role="treeitem"
        tabIndex={0}
        aria-expanded={isFolder ? expanded : undefined}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
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
        {/* Expand/collapse chevron for folders */}
        {isFolder ? (
          <span style={{ display: 'flex', opacity: 0.6, width: 16, height: 16, alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            <ChevronRight
              size={14}
              style={{ transform: expanded ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }}
            />
          </span>
        ) : (
          <span style={{ width: 16, flexShrink: 0 }} />
        )}

        {/* Folder icon or file icon */}
        <span style={{ display: 'flex', opacity: 0.7, flexShrink: 0 }}>
          {isFolder ? (
            expanded ? <FolderOpen size={15} /> : <Folder size={15} />
          ) : (
            <File size={15} />
          )}
        </span>

        {/* Label */}
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {node.label}
        </span>

        {/* Badge */}
        {node.badge && (
          <span
            style={{
              fontSize: 10,
              padding: '1px 5px',
              borderRadius: 4,
              background: t.bgHover,
              color: t.textDim,
              marginLeft: 'auto',
              flexShrink: 0,
            }}
          >
            {node.badge}
          </span>
        )}
      </div>

      {/* Children (expanded folders) */}
      {isFolder && expanded && node.children && (
        <TreeView nodes={node.children} onFileOpen={onFileOpen} level={level + 1} />
      )}
    </div>
  );
}
