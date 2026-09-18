/**
 * KnowledgeSidebar — left-sidebar browser for knowledge-base documents.
 *
 * Shows a hierarchical folder tree built from document metadata
 * (industry -> player -> sub_category -> sub_department).
 * Individual documents appear as clickable leaf items.
 * Docs without hierarchy metadata appear under "(ungrouped)".
 */
import { useEffect, useState, useCallback, useRef } from 'react';
import { useLayoutTokens } from './tokens';
import { useLayoutState } from './useLayout';
import { useProject } from '../../contexts/ProjectContext';
import apiClient from '../../lib/api-client';
import {
  Folder, FileText, ChevronRight, ChevronDown, CheckCircle, Loader, RefreshCw, Plus, FileUp, FolderUp, MessagesSquare,
} from 'lucide-react';

/* ── Types ────────────────────────────────────────────── */

interface Document {
  id: string;  // KV store uses string IDs
  name: string;
  original_filename: string;
  document_type: string;
  size: number;
  industry?: string | null;
  player?: string | null;
  sub_category?: string | null;
  sub_department?: string | null;
  created_at: number;
}

interface FolderNode {
  name: string;
  path: string;
  children: FolderNode[];
  docs: Document[];   // documents belonging to this folder level
  docCount: number;
}

/* ── Folder tree builder ──────────────────────────────── */

function buildFolderTree(docs: Document[]): { folders: FolderNode[]; ungrouped: Document[] } {
  const root: FolderNode[] = [];
  const ungrouped: Document[] = [];

  for (const doc of docs) {
    const parts = [
      doc.industry, doc.player, doc.sub_category, doc.sub_department,
    ].filter((p): p is string => !!p && p.length > 0);

    // Docs without hierarchy go to ungrouped
    if (parts.length === 0) {
      ungrouped.push(doc);
      continue;
    }

    let currentList = root;
    let pathSoFar = '';
    let node: FolderNode | undefined;

    for (let i = 0; i < parts.length; i++) {
      const segment = parts[i];
      pathSoFar = pathSoFar ? `${pathSoFar}/${segment}` : segment;
      const displayName = segment.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
      node = currentList.find((n) => n.name === displayName && n.path === pathSoFar);
      if (!node) {
        node = { name: displayName, path: pathSoFar, children: [], docs: [], docCount: 0 };
        currentList.push(node);
      }
      currentList = node.children;
    }

    // Add doc to the leaf folder (last node in the chain)
    if (node) {
      node.docs.push(doc);
    }
  }

  // Count total docs per folder (including children)
  const countDocs = (folder: FolderNode): number => {
    let count = folder.docs.length;
    for (const child of folder.children) {
      count += countDocs(child);
    }
    folder.docCount = count;
    return count;
  };

  for (const folder of root) countDocs(folder);

  // Sort alphabetically
  const sortNodes = (nodes: FolderNode[]) => {
    nodes.sort((a, b) => a.name.localeCompare(b.name));
    for (const n of nodes) sortNodes(n.children);
  };
  sortNodes(root);

  // Sort docs by name within each folder
  const sortDocs = (nodes: FolderNode[]) => {
    for (const n of nodes) {
      n.docs.sort((a, b) => a.name.localeCompare(b.name));
      sortDocs(n.children);
    }
  };
  sortDocs(root);

  ungrouped.sort((a, b) => a.name.localeCompare(b.name));

  return { folders: root, ungrouped };
}

/* ── Sidebar component ────────────────────────────────── */

export default function KnowledgeSidebar() {
  const t = useLayoutTokens();
  const { openTab, setRightPanelTab, openRightPanel } = useLayoutState();
  const { activeProjectId, activeProject, projects, setActiveProjectId } = useProject();

  const [folderTree, setFolderTree] = useState<FolderNode[]>([]);
  const [ungroupedDocs, setUngroupedDocs] = useState<Document[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [showProjectPicker, setShowProjectPicker] = useState(false);

  // Ingest state
  const [folderPathInput, setFolderPathInput] = useState('');
  const [ingesting, setIngesting] = useState(false);
  const [ingestMsg, setIngestMsg] = useState<string | null>(null);

  // File upload state
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  // Folder upload state
  const folderInputRef = useRef<HTMLInputElement>(null);
  const [folderUploading, setFolderUploading] = useState(false);
  useEffect(() => {
    const el = folderInputRef.current;
    if (el) {
      el.setAttribute('webkitdirectory', '');
      el.setAttribute('directory', '');
    }
  }, []);

  const projectId = activeProjectId ?? 1;

  const loadDocuments = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.listKVDocuments({ project_id: projectId });
      const docs: Document[] = Array.isArray(res.data) ? res.data : [];
      const { folders, ungrouped } = buildFolderTree(docs);
      setFolderTree(folders);
      setUngroupedDocs(ungrouped);
    } catch (err: any) {
      const msg = err?.response?.status === 0 || err?.code === 'ERR_NETWORK'
        ? 'Backend not reachable. Is the server running?'
        : err?.message || 'Failed to load documents';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { loadDocuments(); }, [loadDocuments]);

  /** Open a knowledge view scoped to a folder path (for DocChat) */
  const handleOpenFolder = useCallback((folderPath: string, folderName: string) => {
    openTab({
      id: `kb-${folderPath}`,
      label: folderName,
      viewType: 'knowledge-view',
      data: { folderPath, projectId },
    });
  }, [openTab, projectId]);

  /** Open Doc Chat in the right panel — sits aside the doc viewer, not in its place */
  const handleOpenDocPlayground = useCallback(() => {
    setRightPanelTab('doc-chat');
    openRightPanel('');
  }, [setRightPanelTab, openRightPanel]);

  /** Open a document view with chat, scoped to the doc's containing folder */
  const handleOpenDoc = useCallback((doc: Document) => {
    // Build folder path from the doc's hierarchy metadata
    const parts = [doc.industry, doc.player, doc.sub_category, doc.sub_department]
      .filter((p): p is string => !!p && p.length > 0);
    const folderPath = parts.join('/');
    openTab({
      id: `kb-${doc.id}`,
      label: doc.name,
      viewType: 'knowledge-view',
      data: { folderPath, projectId, docId: doc.id, docName: doc.name },
    });
  }, [openTab, projectId]);

  /** Toggle expand/collapse */
  const toggleExpand = (path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  /** Ingest a folder by path */
  const handleIngest = useCallback(async () => {
    const path = folderPathInput.trim();
    if (!path || !projectId) return;
    setIngesting(true);
    setIngestMsg(null);
    try {
      const resp = await apiClient.ingestKVDocumentFolder({ project_id: projectId, folder_path: path });
      const data = resp.data as any;
      setIngestMsg(`Ingested ${data.files_ingested} files`);
      setFolderPathInput('');
      setTimeout(() => setIngestMsg(null), 3000);
      loadDocuments();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || 'Ingest failed';
      setIngestMsg(`Failed: ${detail}`);
      setTimeout(() => setIngestMsg(null), 5000);
    } finally {
      setIngesting(false);
    }
  }, [folderPathInput, projectId, loadDocuments]);

  /** Upload files via file picker */
  const handleFilePick = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0 || !projectId) return;
    setUploading(true);
    try {
      const fileArray = Array.from(files);
      const fileMetadata = fileArray.map((f) => {
        const relPath: string = (f as any).webkitRelativePath || f.name;
        const meta: any = {};
        const parts = relPath.split('/').filter(Boolean);
        if (parts.length >= 2) meta.industry = parts[0];
        if (parts.length >= 3) meta.player = parts[1];
        if (parts.length >= 4) meta.sub_category = parts[2];
        if (parts.length >= 5) meta.sub_department = parts[3];
        return meta;
      });
      await apiClient.uploadKVDocumentsBulk(projectId, fileArray, fileMetadata);
      loadDocuments();
    } catch (err: any) {
      console.error('Upload failed:', err);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }, [projectId, loadDocuments]);

  /** Upload folder via webkitdirectory picker */
  const handleFolderPick = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0 || !projectId) return;
    setFolderUploading(true);
    try {
      const fileArray = Array.from(files);
      const fileMetadata = fileArray.map((f) => {
        const relPath: string = (f as any).webkitRelativePath || f.name;
        const meta: any = {};
        const parts = relPath.split('/').filter(Boolean);
        if (parts.length >= 2) meta.industry = parts[0];
        if (parts.length >= 3) meta.player = parts[1];
        if (parts.length >= 4) meta.sub_category = parts[2];
        if (parts.length >= 5) meta.sub_department = parts[3];
        return meta;
      });
      await apiClient.uploadKVDocumentsBulk(projectId, fileArray, fileMetadata);
      loadDocuments();
    } catch (err: any) {
      console.error('Folder upload failed:', err);
    } finally {
      setFolderUploading(false);
      if (folderInputRef.current) folderInputRef.current.value = '';
    }
  }, [projectId, loadDocuments]);

  /* ── Render helpers ────────────────────────────── */

  /** Render a single document as a leaf item */
  const renderDocItem = (doc: Document, depth: number) => {
    const icon = doc.document_type === 'pdf' ? '📄' : null;
    return (
      <div
        key={doc.id}
        onClick={() => handleOpenDoc(doc)}
        title={`${doc.name} (${(doc.size / 1024).toFixed(1)} KB)`}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          padding: '2px 8px',
          paddingLeft: 12 + depth * 16 + 16,  // extra indent vs folder
          fontSize: 12,
          color: t.textMuted,
          cursor: 'pointer',
          borderRadius: 3,
          userSelect: 'none',
          whiteSpace: 'nowrap',
        }}
        onMouseEnter={(e) => { e.currentTarget.style.background = t.bgHover; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
      >
        <span style={{ width: 14, flexShrink: 0, display: 'flex', justifyContent: 'center' }}>
          <FileText size={12} style={{ color: '#6b7280' }} />
        </span>
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', flex: 1 }}>
          {doc.name}
        </span>
        <span style={{ fontSize: 10, color: t.textMuted, flexShrink: 0 }}>
          {(doc.size / 1024).toFixed(0)}K
        </span>
      </div>
    );
  };

  /** Render a folder node (with its doc children) */
  const renderFolderNode = (node: FolderNode, depth: number) => {
    const isExpanded = expanded.has(node.path);
    const hasChildren = node.children.length > 0;
    const hasDocs = node.docs.length > 0;

    return (
      <div key={node.path}>
        {/* Folder header row */}
        <div
          onClick={() => {
            if (hasChildren || hasDocs) toggleExpand(node.path);
            handleOpenFolder(node.path, node.name);
          }}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            padding: '3px 8px',
            paddingLeft: 12 + depth * 16,
            fontSize: 13,
            color: t.textPrimary,
            cursor: 'pointer',
            borderRadius: 3,
            userSelect: 'none',
            whiteSpace: 'nowrap',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = t.bgHover; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
        >
          {(hasChildren || hasDocs) ? (
            <span style={{ display: 'flex', width: 14, flexShrink: 0 }}>
              {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            </span>
          ) : (
            <span style={{ width: 14, flexShrink: 0 }} />
          )}
          <Folder size={14} style={{ flexShrink: 0, color: '#d4a84b' }} />
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', flex: 1 }}>{node.name}</span>
          <span style={{ fontSize: 11, color: t.textMuted, flexShrink: 0 }}>
            {node.docCount}
          </span>
        </div>

        {/* Expanded children */}
        {isExpanded && (
          <>
            {/* Sub-folders */}
            {hasChildren && node.children.map((child) => renderFolderNode(child, depth + 1))}
            {/* Individual docs inside this folder */}
            {hasDocs && node.docs.map((doc) => renderDocItem(doc, depth + 1))}
          </>
        )}
      </div>
    );
  };

  const hasItems = folderTree.length > 0 || ungroupedDocs.length > 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* ── Active project header + quick switcher ─────── */}
      <div style={{ position: 'relative', flexShrink: 0 }}>
        <button
          onClick={() => setShowProjectPicker(v => !v)}
          title="Switch project (vault)"
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            width: '100%', padding: '6px 10px',
            border: 'none', background: 'transparent', cursor: 'pointer',
            color: t.textPrimary, fontSize: 12, textAlign: 'left',
            borderBottom: `1px solid ${t.border}`,
            userSelect: 'none',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = t.bgHover; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
        >
          <Folder size={13} style={{ color: t.accent, flexShrink: 0 }} />
          <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: 500 }}>
            {activeProject?.name ?? `Project ${projectId}`}
          </span>
          <span style={{ display: 'flex', color: t.textMuted }}>
            {showProjectPicker ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </span>
        </button>

        {showProjectPicker && (
          <div
            style={{
              position: 'absolute', left: 6, right: 6, top: '100%', zIndex: 1000,
              background: t.bgSidebar, border: `1px solid ${t.border}`, borderRadius: 6,
              boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
              maxHeight: 300, overflowY: 'auto', padding: 4,
            }}
          >
            {projects.filter((p) => p.id > 0).map((p) => {
              const isActive = p.id === projectId;
              return (
                <button
                  key={p.id}
                  onClick={() => { setActiveProjectId(p.id); setShowProjectPicker(false); }}
                  title={`Project ${p.id}`}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 6, width: '100%',
                    padding: '7px 10px', borderRadius: 4,
                    border: 'none', background: isActive ? t.bgHover : 'transparent',
                    color: t.textPrimary, cursor: 'pointer', fontSize: 12, textAlign: 'left',
                    userSelect: 'none',
                  }}
                  onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = t.bgHover; }}
                  onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
                >
                  <Folder size={12} style={{ color: isActive ? t.accent : t.textMuted, flexShrink: 0 }} />
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</span>
                  {isActive && <CheckCircle size={12} style={{ color: '#22c55e', flexShrink: 0 }} />}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Toolbar ──────────────────────────────────── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '6px 10px',
          borderBottom: `1px solid ${t.border}`,
          flexShrink: 0,
        }}
      >
        <span style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', color: t.textMuted }}>
          Knowledge Base
        </span>
        <div style={{ display: 'flex', gap: 2 }}>
          <button
            onClick={handleOpenDocPlayground}
            title="Doc Playground — chat with the knowledge base"
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              width: 22, height: 22,
              border: 'none', background: 'transparent', color: t.accent,
              cursor: 'pointer', borderRadius: 3,
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = t.bgHover; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
          >
            <MessagesSquare size={13} />
          </button>
          <button
            onClick={() => fileInputRef.current?.click()}
            title="Upload files"
            disabled={uploading}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              width: 22, height: 22,
              border: 'none', background: 'transparent', color: t.textMuted,
              cursor: uploading ? 'default' : 'pointer', borderRadius: 3,
              opacity: uploading ? 0.5 : 1,
            }}
            onMouseEnter={(e) => { if (!uploading) e.currentTarget.style.background = t.bgHover; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
          >
            {uploading ? <Loader size={12} style={{ animation: 'spin 1s linear infinite' }} /> : <Plus size={14} />}
          </button>
          <button
            onClick={() => folderInputRef.current?.click()}
            title="Upload folder (preserves hierarchy)"
            disabled={folderUploading}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              width: 22, height: 22,
              border: 'none', background: 'transparent', color: t.textMuted,
              cursor: folderUploading ? 'default' : 'pointer', borderRadius: 3,
              opacity: folderUploading ? 0.5 : 1,
            }}
            onMouseEnter={(e) => { if (!folderUploading) e.currentTarget.style.background = t.bgHover; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
          >
            {folderUploading ? <Loader size={12} style={{ animation: 'spin 1s linear infinite' }} /> : <FolderUp size={14} />}
          </button>
          <input ref={fileInputRef} type="file" multiple onChange={handleFilePick} style={{ display: 'none' }} />
          <input ref={folderInputRef} type="file" onChange={handleFolderPick} style={{ display: 'none' }} />
          <button
            onClick={loadDocuments}
            title="Refresh"
            disabled={loading}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              width: 22, height: 22,
              border: 'none', background: 'transparent', color: t.textMuted,
              cursor: loading ? 'default' : 'pointer', borderRadius: 3,
              opacity: loading ? 0.5 : 1,
            }}
            onMouseEnter={(e) => { if (!loading) e.currentTarget.style.background = t.bgHover; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
          >
            {loading ? <Loader size={12} style={{ animation: 'spin 1s linear infinite' }} /> : <RefreshCw size={12} />}
          </button>
        </div>
      </div>

      {/* ── Tree view ────────────────────────────────── */}
      <div style={{ flex: 1, overflow: 'auto', padding: '4px 0' }}>
        {loading && !hasItems ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '16px 20px', fontSize: 13, color: t.textMuted }}>
            <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
            Loading documents...
          </div>
        ) : error ? (
          <div style={{ padding: '16px 20px', fontSize: 13, color: '#e5484d' }}>
            <p style={{ margin: 0 }}>{error}</p>
            <button
              onClick={loadDocuments}
              style={{
                marginTop: 8, padding: '4px 10px', fontSize: 12,
                border: `1px solid ${t.border}`, borderRadius: 4,
                background: 'transparent', color: t.textPrimary, cursor: 'pointer',
              }}
            >
              Retry
            </button>
          </div>
        ) : !hasItems ? (
          <div style={{ padding: '16px 20px', fontSize: 13, color: t.textMuted }}>
            <p style={{ margin: 0 }}>No documents yet.</p>
            <p style={{ margin: '8px 0 0', fontSize: 12 }}>
              Use the ingest field below or click <strong>+</strong> to upload files.
            </p>
          </div>
        ) : (
          <>
            {/* Hierarchical folders */}
            {folderTree.map((node) => renderFolderNode(node, 0))}

            {/* Ungrouped docs (no hierarchy metadata) */}
            {ungroupedDocs.length > 0 && (
              <>
                <div
                  onClick={() => toggleExpand('__ungrouped__')}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                    padding: '3px 8px',
                    paddingLeft: 12,
                    fontSize: 13,
                    color: t.textMuted,
                    cursor: 'pointer',
                    borderRadius: 3,
                    userSelect: 'none',
                    whiteSpace: 'nowrap',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = t.bgHover; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
                >
                  <span style={{ display: 'flex', width: 14, flexShrink: 0 }}>
                    {expanded.has('__ungrouped__') ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  </span>
                  <Folder size={14} style={{ flexShrink: 0, color: '#9ca3af' }} />
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', flex: 1, fontStyle: 'italic' }}>
                    (ungrouped)
                  </span>
                  <span style={{ fontSize: 11, color: t.textMuted, flexShrink: 0 }}>
                    {ungroupedDocs.length}
                  </span>
                </div>
                {expanded.has('__ungrouped__') && ungroupedDocs.map((doc) => renderDocItem(doc, 1))}
              </>
            )}
          </>
        )}
      </div>

      {/* ── Ingest section ───────────────────────────── */}
      <div
        style={{
          borderTop: `1px solid ${t.border}`,
          padding: '8px 10px',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <input
            type="text"
            value={folderPathInput}
            onChange={(e) => setFolderPathInput(e.target.value)}
            placeholder="Folder path (e.g. industry/player)"
            style={{
              flex: 1,
              background: t.bgContent,
              border: `1px solid ${t.border}`,
              borderRadius: 4,
              padding: '5px 8px',
              fontSize: 11,
              color: t.textPrimary,
              outline: 'none',
            }}
            onKeyDown={(e) => { if (e.key === 'Enter') handleIngest(); }}
          />
          <button
            onClick={handleIngest}
            disabled={ingesting || !folderPathInput.trim()}
            title="Ingest folder"
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              width: 26, height: 26, flexShrink: 0,
              border: 'none', borderRadius: 4,
              background: ingesting ? t.textMuted : '#a855f7',
              color: '#fff', cursor: ingesting ? 'default' : 'pointer',
              opacity: ingesting || !folderPathInput.trim() ? 0.5 : 1,
            }}
          >
            {ingesting ? (
              <Loader size={12} style={{ animation: 'spin 1s linear infinite' }} />
            ) : (
              <FileUp size={12} />
            )}
          </button>
        </div>
        {ingestMsg && (
          <div style={{ fontSize: 11, color: ingestMsg.startsWith('Failed') ? '#e5484d' : '#10b981', marginTop: 4 }}>
            {ingestMsg}
          </div>
        )}
      </div>
    </div>
  );
}
