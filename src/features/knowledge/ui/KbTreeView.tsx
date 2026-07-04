/**
 * KbTreeView — Sidebar Tree view for the Knowledge Base doc list.
 *
 * Renders the folder tree (industry > player > sub_category >
 * sub_department > file) as a collapsible list. Folders show their
 * doc count and can be expanded/collapsed by clicking the chevron.
 * Files render as the same doc-card as the List view.
 *
 * Step N+1: this component is shown when the sidebar toggle is set
 * to "Tree" (kb.sidebarView === 'tree'). It only renders docs that
 * have hierarchy metadata; docs without metadata are still shown by
 * the parent KnowledgeBaseView's "(ungrouped)" bucket.
 */
import { ChevronRight, ChevronDown, Folder, FolderOpen, FileText, Trash2 } from 'lucide-react';
import type { ReactNode } from 'react';
import type { Document, FolderNode } from './KnowledgeBaseView';

export interface KbTreeViewProps {
  folderTree: FolderNode;
  readyDocuments: Document[];
  selectedDocId: number | null;
  highlightedDocId: number | null;
  expandedFolders: Set<string>;
  toggleFolder: (path: string) => void;
  scopeDocIds: Set<number>;
  toggleScopeDoc: (id: number) => void;
  setSelectedDocId: (id: number) => void;
  onFolderSelect?: (path: string | null) => void;
  handleDelete: (id: number) => Promise<void>;
  t: (key: string) => string;
  formatFileSize: (bytes: number) => string;
}

interface FolderRowProps {
  node: FolderNode;
  depth: number;
  isExpanded: boolean;
  onToggle: () => void;
  childCount: number;
  docCount: number;
}

function FolderRow({ node, depth, isExpanded, onToggle, childCount, docCount }: FolderRowProps) {
  // Indent each level by ~10px (subtle — keeps the tree visually flat).
  const indentStyle = { paddingLeft: `${depth * 10}px` };
  return (
    <button
      onClick={onToggle}
      className="w-full text-left flex items-center gap-1 px-1.5 py-1 rounded hover:bg-gray-50 dark:hover:bg-white/5 text-[11px]"
      style={{ color: 'var(--color-text-primary)' }}
      data-testid={`kb-tree-folder-${node.path}`}
    >
      {/* Chevron — rotates 90° when expanded */}
      {isExpanded
        ? <ChevronDown className="w-3 h-3 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
        : <ChevronRight className="w-3 h-3 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
      }
      {/* Folder icon */}
      {isExpanded
        ? <FolderOpen className="w-3 h-3 flex-shrink-0" style={{ color: '#a855f7' }} />
        : <Folder className="w-3 h-3 flex-shrink-0" style={{ color: '#a855f7' }} />
      }
      <span className="font-medium truncate flex-1" style={indentStyle}>
        {node.name}
      </span>
      {/* Doc count badge — only show counts when there's > 1 doc */}
      <span className="text-[9px] px-1 py-0.5 rounded bg-gray-100 dark:bg-white/10 flex-shrink-0"
            style={{ color: 'var(--color-text-muted)' }}>
        {docCount}
      </span>
    </button>
  );
}

interface DocCardMiniProps {
  doc: Document;
  depth: number;
  isSelected: boolean;
  isHighlighted: boolean;
  inScope: boolean;
  onSelect: () => void;
  onToggleScope: () => void;
  onDelete: () => void;
  t: (key: string) => string;
  formatFileSize: (bytes: number) => string;
}

function DocCardMini({
  doc, depth, isSelected, isHighlighted, inScope,
  onSelect, onToggleScope, onDelete, t, formatFileSize,
}: DocCardMiniProps) {
  const indentStyle = { paddingLeft: `${depth * 10 + 12}px` };
  return (
    <button
      data-doc-card-id={doc.id}
      onClick={onSelect}
      className={`w-full text-left rounded-lg border px-2 py-1.5 transition-all text-left ${
        isSelected
          ? 'border-amber-300 dark:border-amber-500/40 bg-amber-50 dark:bg-amber-500/10'
          : inScope
            ? 'border-indigo-300 dark:border-indigo-500/40 bg-indigo-50/40 dark:bg-indigo-500/5'
            : 'border-gray-200 dark:border-border-dark hover:bg-gray-50 dark:hover:bg-white/5'
      } ${
        isHighlighted
          ? 'ring-2 ring-purple-500 shadow-lg shadow-purple-500/30'
          : ''
      }`}
      style={indentStyle}
    >
      <div className="flex items-start gap-1.5">
        <FileText
          className="w-3 h-3 mt-0.5 flex-shrink-0"
          style={{ color: 'var(--color-text-muted)' }}
        />
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-medium truncate" style={{ color: 'var(--color-text-primary)' }}>
            {doc.name}
          </div>
          <div className="text-[9px] mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
            {formatFileSize(doc.size)} · {doc.chunk_count || 0} chunks
          </div>
        </div>
        {/* Scope checkbox — stop propagation so it doesn't also select */}
        <label
          className="flex items-center p-0.5 rounded hover:bg-indigo-50 dark:hover:bg-indigo-500/10"
          title={inScope ? 'Remove from chat scope' : 'Add to chat scope'}
          onClick={(e) => e.stopPropagation()}
        >
          <input
            type="checkbox"
            checked={inScope}
            onChange={onToggleScope}
            className="h-3 w-3 cursor-pointer accent-indigo-600"
            aria-label={`Toggle ${doc.name} in chat scope`}
          />
        </label>
        {!doc.neo4j_only && (
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            className="p-0.5 rounded hover:bg-red-50 dark:hover:bg-red-500/10"
            style={{ color: 'var(--color-text-muted)' }}
            title={t('kb_delete')}
          >
            <Trash2 className="w-2.5 h-2.5" />
          </button>
        )}
      </div>
    </button>
  );
}

/** Count the number of leaf documents under a folder node. */
function countDocs(node: FolderNode): number {
  if (node.doc) return 1;
  return node.children.reduce((sum: number, c: FolderNode) => sum + countDocs(c), 0);
}

/** Recursively render a folder tree. */
function renderNode(
  node: FolderNode,
  depth: number,
  selectedDocId: number | null,
  highlightedDocId: number | null,
  expandedFolders: Set<string>,
  toggleFolder: (path: string) => void,
  scopeDocIds: Set<number>,
  toggleScopeDoc: (id: number) => void,
  setSelectedDocId: (id: number) => void,
  onFolderSelect: ((path: string | null) => void) | undefined,
  handleDelete: (id: number) => Promise<void>,
  t: (key: string) => string,
  formatFileSize: (bytes: number) => string,
): ReactNode[] {
  // Leaf doc node — render as doc card
  if (node.doc) {
    return [
      <DocCardMini
        key={node.path}
        doc={node.doc}
        depth={depth}
        isSelected={selectedDocId === node.doc.id}
        isHighlighted={highlightedDocId === node.doc.id}
        inScope={scopeDocIds.has(node.doc.id)}
        onSelect={() => setSelectedDocId(node.doc!.id)}
        onToggleScope={() => toggleScopeDoc(node.doc!.id)}
        onDelete={() => handleDelete(node.doc!.id)}
        t={t}
        formatFileSize={formatFileSize}
      />,
    ];
  }

  // Folder node — render as folder row + recursively render children
  const isExpanded = expandedFolders.has(node.path);
  const docCount = countDocs(node);
  const childCount = node.children.length;
  const result: ReactNode[] = [
    <FolderRow
      key={`folder-${node.path}`}
      node={node}
      depth={depth}
      isExpanded={isExpanded}
      onToggle={() => {
        toggleFolder(node.path);
        onFolderSelect?.(node.path);
      }}
      childCount={childCount}
      docCount={docCount}
    />,
  ];
  if (isExpanded) {
    for (const child of node.children) {
      result.push(
        ...renderNode(
          child, depth + 1,
          selectedDocId, highlightedDocId,
          expandedFolders, toggleFolder,
          scopeDocIds, toggleScopeDoc,
          setSelectedDocId, onFolderSelect, handleDelete,
          t, formatFileSize,
        ),
      );
    }
  }
  return result;
}

export default function KbTreeView(props: KbTreeViewProps) {
  const {
    folderTree,
    selectedDocId,
    highlightedDocId,
    expandedFolders,
    toggleFolder,
    scopeDocIds,
    toggleScopeDoc,
    setSelectedDocId,
    onFolderSelect,
    handleDelete,
    t,
    formatFileSize,
  } = props;

  if (folderTree.children.length === 0) {
    return (
      <p className="text-[11px] px-2 py-2" style={{ color: 'var(--color-text-muted)' }}>
        No indexed documents yet.
      </p>
    );
  }

  // Render the top-level children of the root folder. Each is either a
  // folder (rendered with chevron + recursive children) or a leaf doc.
  return (
    <div className="space-y-0.5">
      {folderTree.children.flatMap((node) =>
        renderNode(
          node, 0,
          selectedDocId, highlightedDocId,
          expandedFolders, toggleFolder,
          scopeDocIds, toggleScopeDoc,
          setSelectedDocId, onFolderSelect, handleDelete,
          t, formatFileSize,
        ),
      )}
    </div>
  );
}
