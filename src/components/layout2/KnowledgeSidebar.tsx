/**
 * KnowledgeSidebar — left-sidebar browser for knowledge-base documents.
 *
 * Shows a hierarchical folder tree built from document metadata
 * (industry -> player -> sub_category -> sub_department).
 * Individual documents appear as clickable leaf items.
 * Docs without hierarchy metadata appear under "(ungrouped)".
 */
import { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { useLayoutTokens } from './tokens';
import { useLayoutState } from './useLayout';
import apiClient from '../../lib/api-client';
import { splitScope } from '../../features/knowledge/knowledgeScope';
import {
  Folder, FileText, CheckCircle, Loader, RefreshCw, Plus, FileUp, FolderUp, MessagesSquare, ScanSearch,
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

function formatSize(bytes?: number): string {
  if (bytes === undefined) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} K`;
  return `${(bytes / 1024 / 1024).toFixed(1)} M`;
}

interface TreeEntry {
  name: string;
  path: string;
  type: 'dir' | 'file';
  size?: number;
  children?: TreeEntry[];
}

interface KnowledgeBase {
  key: string;
  name: string;
  document_count: number;
  folder: string;
  root: string;
}

interface FolderNode {
  name: string;
  path: string;
  children: FolderNode[];
  docs: Document[];   // documents belonging to this folder level
  docCount: number;
}

/* ── Folder tree builder ──────────────────────────────── */

/**
 * Group documents by their hierarchy metadata, which is the folder path they were filed under.
 *
 * This is the CATALOG's view: what has been indexed, therefore what Doc Chat can answer from. It
 * is the list the panel shows, because it is the knowledge — a file on disk that nothing has
 * ingested is not knowledge yet, and listing it beside the real documents invited the impression
 * that it was.
 */
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
  const {
    openTab, setRightPanelTab, openRightPanel,
    knowledgeBase, knowledgeFolder, setKnowledgeBase, setKnowledgeFolder,
  } = useLayoutState();

  const [folderTree, setFolderTree] = useState<FolderNode[]>([]);
  const [ungroupedDocs, setUngroupedDocs] = useState<Document[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The knowledge base root starts open: it holds the documents themselves, and collapsing it
  // by default is what made a knowledge base look empty.
  const [expanded, setExpanded] = useState<Set<string>>(new Set(['__kb__']));

  // Ingest state
  const [folderPathInput, setFolderPathInput] = useState('');
  const [ingesting, setIngesting] = useState(false);
  const [ingestMsg, setIngestMsg] = useState<string | null>(null);
  // Batch-indexing the files that are on disk but not in any catalog.
  const [indexing, setIndexing] = useState(false);
  const [indexMsg, setIndexMsg] = useState<string | null>(null);

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

  // The knowledge bases under the knowledge root, straight from the filesystem. This is what
  // the panel shows: knowledge is not scoped to a project, so the list is the knowledge folders
  // themselves, not the active project's documents.
  const [bases, setBases] = useState<KnowledgeBase[]>([]);

  /** The knowledge bases on disk — the first-level folders under the knowledge root. */
  const loadBases = useCallback(async () => {
    try {
      const r = await apiClient.listKnowledgeBases();
      setBases(Array.isArray(r?.data?.bases) ? r.data.bases : []);
    } catch {
      setBases([]);
    }
  }, []);

  useEffect(() => { loadBases(); }, [loadBases]);

  // The scope is SHARED, not this panel's own. It is chosen in the Doc Chat dropdown and read
  // here, so the document list, the tree, the uploads and that chat all act on the same folder.
  // This panel used to keep its own copy, which is the drift the shared state exists to remove.
  //
  // The fallback to the first base is a starting view, not a target: anything that WRITES names
  // its scope explicitly, because writing into whichever base happens to sort first is how a
  // folder once ended up in a knowledge base nobody chose.
  const knowledge = knowledgeBase || bases[0]?.key || '';
  const scopeFolder = knowledgeFolder;
  const selectedBase = bases.find((b) => b.key === knowledge) ?? bases[0] ?? null;

  // Persist the starting view so Doc Chat opens on a real scope rather than on nothing.
  useEffect(() => {
    if (!knowledgeBase && bases.length > 0) setKnowledgeBase(bases[0].key);
  }, [knowledgeBase, bases, setKnowledgeBase]);

  const loadDocuments = useCallback(async () => {
    if (!knowledge) {
      setFolderTree([]);
      setUngroupedDocs([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.listKVDocuments({ knowledge });
      const all: Document[] = Array.isArray(res.data) ? res.data : [];
      const docs = scopeFolder
        ? all.filter((doc) => {
            const folder = [doc.industry, doc.player, doc.sub_category, doc.sub_department]
              .filter((part): part is string => !!part && part.length > 0)
              .join('/');
            return folder === scopeFolder || folder.startsWith(`${scopeFolder}/`);
          })
        : all;
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
  }, [knowledge, scopeFolder]);

  useEffect(() => { loadDocuments(); }, [loadDocuments]);

  /** Open Doc Chat in the right panel — sits aside the doc viewer, not in its place */
  const handleOpenDocPlayground = useCallback(() => {
    setRightPanelTab('doc-chat');
    openRightPanel('');
  }, [setRightPanelTab, openRightPanel]);


  /** Open a document, scoped to the folder it sits in. */
  const handleOpenDoc = useCallback((doc: Document) => {
    const parts = [doc.industry, doc.player, doc.sub_category, doc.sub_department]
      .filter((p): p is string => !!p && p.length > 0);
    openTab({
      id: `kb-${doc.id}`,
      label: doc.name,
      viewType: 'knowledge-view',
      data: { folderPath: parts.join('/'), knowledge, docId: doc.id, docName: doc.name },
    });
  }, [openTab, knowledge]);

  /** Open a knowledge view scoped to a folder path (for DocChat) */
  const handleOpenFolder = useCallback((folderPath: string, folderName: string) => {
    openTab({
      id: `kb-${knowledge}-${folderPath}`,
      label: folderName,
      viewType: 'knowledge-view',
      data: { folderPath, knowledge },
    });
  }, [openTab, knowledge]);

  /** Toggle expand/collapse */
  const toggleExpand = (path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  /**
   * Index every file on disk that has no record yet, in every knowledge base.
   *
   * The document list is built from the catalog, so a file copied into a knowledge base by hand is
   * present, readable by Doc Chat, and invisible here. This gives those files records — in place,
   * copying nothing — so they appear like anything else. Additive and idempotent: files that
   * already have a record are left alone, and running it twice changes nothing.
   */
  const handleIndexMissing = useCallback(async () => {
    setIndexing(true);
    setIndexMsg(null);
    try {
      const resp = await apiClient.indexMissingKVDocuments();
      const data = resp.data as any;
      // The backend distinguishes "indexed some", "all already indexed" and "no files on disk";
      // saying "nothing to index" for an empty folder reads as a failure that did not happen.
      setIndexMsg(data?.message || `Indexed ${data?.indexed ?? 0} file(s)`);
      await Promise.all([loadBases(), loadDocuments()]);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || 'Indexing failed';
      setIndexMsg(`Failed: ${detail}`);
    } finally {
      setIndexing(false);
      setTimeout(() => setIndexMsg(null), 6000);
    }
  }, [loadBases, loadDocuments]);

  /** Ingest a folder by path */
  const handleIngest = useCallback(async () => {
    const path = folderPathInput.trim();
    if (!path || !knowledge) return;
    setIngesting(true);
    setIngestMsg(null);
    try {
      const resp = await apiClient.ingestKVDocumentFolder({ knowledge, folder_path: path });
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
  }, [folderPathInput, knowledge, loadDocuments]);

  /** Upload files via file picker */
  const handleFilePick = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0 || !knowledge) return;
    setUploading(true);
    try {
      const fileArray = Array.from(files);
      // Files picked go into the current scope, so "upload here" means here. The scope's path
      // becomes the hierarchy the writer turns into folders — the same four levels the tree and
      // the document list are grouped by, so a file uploaded while scoped to
      // `eyewear_industry/新溢眼镜` appears in that folder rather than at the base root.
      const scopeParts = scopeFolder ? scopeFolder.split('/').filter(Boolean) : [];
      const scopeMeta: any = {};
      if (scopeParts.length >= 1) scopeMeta.industry = scopeParts[0];
      if (scopeParts.length >= 2) scopeMeta.player = scopeParts[1];
      if (scopeParts.length >= 3) scopeMeta.sub_category = scopeParts[2];
      if (scopeParts.length >= 4) scopeMeta.sub_department = scopeParts[3];

      const fileMetadata = fileArray.map((f) => {
        const relPath: string = (f as any).webkitRelativePath || f.name;
        const meta: any = { ...scopeMeta };
        const parts = relPath.split('/').filter(Boolean);
        // A picked folder's own name is not a folder inside the scope: it was the knowledge base
        // under the old rules, and under the new ones it names one. Only a *nested* path adds
        // levels.
        if (parts.length >= 3) meta.industry = parts[1];
        if (parts.length >= 4) meta.player = parts[2];
        if (parts.length >= 5) meta.sub_category = parts[3];
        if (parts.length >= 6) meta.sub_department = parts[4];
        return meta;
      });
      await apiClient.uploadKVDocumentsBulk(knowledge, fileArray, fileMetadata);
      loadDocuments();
    } catch (err: any) {
      console.error('Upload failed:', err);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }, [knowledge, scopeFolder, loadDocuments]);

  /** Upload folder via webkitdirectory picker */
  const handleFolderPick = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    const fileArray = Array.from(files);
    const relPaths = fileArray.map((f) => (f as any).webkitRelativePath || f.name);

    // The folder you pick IS the knowledge base. Every file arrives as "<Folder>/<rest…>", and
    // that first segment names the knowledge base rather than becoming a subfolder inside one
    // somebody else's — picking `business_model` gives you a knowledge base called
    // `business_model`, sitting directly under the knowledge root.
    const kb = (relPaths[0] || '').split('/').filter(Boolean)[0];
    if (!kb) return;      // a plain file selection has no folder name to make a base out of

    setFolderUploading(true);
    try {
      // Everything BELOW the picked folder is the path inside the knowledge base, so
      // `business_model/a/b.md` lands at `a/b.md` in `business_model` — the same shape a folder
      // copied in by hand would have. A file directly in the picked folder has no inner path and
      // goes to the knowledge base's root.
      const fileMetadata = relPaths.map((relPath) => {
        const inner = relPath.split('/').filter(Boolean).slice(1, -1);   // drop folder + filename
        const meta: any = {};
        if (inner.length >= 1) meta.industry = inner[0];
        if (inner.length >= 2) meta.player = inner[1];
        if (inner.length >= 3) meta.sub_category = inner[2];
        if (inner.length >= 4) meta.sub_department = inner[3];
        return meta;
      });

      await apiClient.uploadKVDocumentsBulk(kb, fileArray, fileMetadata);
      await loadBases();      // the knowledge base may be brand new; show it in the selector
      if (kb === knowledge) {
        loadDocuments();
      } else {
        // Move the shared scope onto the knowledge base just created. Selecting it re-derives
        // `knowledge` here and in Doc Chat, so both reload onto it.
        setKnowledgeBase(kb);
        setKnowledgeFolder('');
      }
    } catch (err: any) {
      console.error('Folder upload failed:', err);
    } finally {
      setFolderUploading(false);
      if (folderInputRef.current) folderInputRef.current.value = '';
    }
  }, [knowledge, loadDocuments, loadBases, setKnowledgeBase, setKnowledgeFolder]);

  /* ── Render helpers ────────────────────────────── */

  /** Render a single document as a leaf item */
  const renderDocItem = (doc: Document, depth: number) => (
    <div
      key={doc.id}
      onClick={() => handleOpenDoc(doc)}
      title={`${doc.name} (${(doc.size / 1024).toFixed(1)} KB)`}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 8px',
        paddingLeft: 6 + depth * 14 + 14,  // extra indent vs folder
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
      <FileText size={12} style={{ color: '#6b7280', flexShrink: 0 }} />
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', flex: 1 }}>
        {doc.name}
      </span>
      <span style={{ fontSize: 10, color: t.textMuted, flexShrink: 0 }}>
        {(doc.size / 1024).toFixed(0)}K
      </span>
    </div>
  );

  /** Render a folder node (with its doc children) */
  const renderFolderNode = (node: FolderNode, depth: number) => {
    const isExpanded = expanded.has(node.path);
    const hasChildren = node.children.length > 0;
    const hasDocs = node.docs.length > 0;

    return (
      <div key={node.path}>
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
            paddingLeft: 6 + depth * 14,
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
          {/* No disclosure triangle: the row itself opens and closes the folder, and the mark in
              front of every folder read as clutter rather than as an affordance. The slot it
              occupied is gone too, so folder rows and the files under them start at the same
              place instead of the whole list sitting one icon-width too far in. */}
          <Folder size={14} style={{ flexShrink: 0, color: '#d4a84b' }} />
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', flex: 1 }}>{node.name}</span>
          <span style={{ fontSize: 11, color: t.textMuted, flexShrink: 0 }}>{node.docCount}</span>
        </div>

        {isExpanded && (
          <>
            {hasChildren && node.children.map((child) => renderFolderNode(child, depth + 1))}
            {hasDocs && node.docs.map((doc) => renderDocItem(doc, depth + 1))}
          </>
        )}
      </div>
    );
  };


  const hasItems = folderTree.length > 0 || ungroupedDocs.length > 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
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
            onClick={handleIndexMissing}
            disabled={indexing}
            title="Index files already on disk — lists files that were copied in by hand, without copying them again"
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              width: 22, height: 22,
              border: 'none', background: 'transparent', color: t.textMuted,
              cursor: indexing ? 'default' : 'pointer', borderRadius: 3,
              opacity: indexing ? 0.5 : 1,
            }}
            onMouseEnter={(e) => { if (!indexing) e.currentTarget.style.background = t.bgHover; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
          >
            {indexing ? <Loader size={12} style={{ animation: 'spin 1s linear infinite' }} /> : <ScanSearch size={14} />}
          </button>
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

      {/* ── Knowledge base ────────────────────────
          The first-level folders under the knowledge root, which is what a knowledge base is.
          Picking one sets the shared scope to it — so the document list, Doc Chat and the folders
          below all follow — and the tree underneath then shows that base's own folders. */}
      {bases.length > 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6,
          padding: '6px 10px',
          borderBottom: `1px solid ${t.border}`,
          flexShrink: 0,
        }}>
          <span style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.4, color: t.textMuted, flexShrink: 0 }}>
            Base
          </span>
          <select
            value={knowledge}
            onChange={(ev) => {
              setKnowledgeBase(ev.target.value);
              setKnowledgeFolder('');
            }}
            title={selectedBase?.folder || knowledge}
            style={{
              flex: 1, minWidth: 0,
              background: t.bgContent,
              border: `1px solid ${t.border}`,
              borderRadius: 4,
              padding: '3px 6px',
              fontSize: 12,
              color: t.textPrimary,
              outline: 'none',
            }}
          >
            {bases.map((b) => (
              <option key={b.key} value={b.key}>
                {b.name}{b.document_count ? ` (${b.document_count})` : ''}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* ── Tree view ──────────────────────────────────
          The grouped knowledge tree, and below it the knowledge folder exactly as it is on
          disk. One section: what the catalogs know, then the files themselves. */}
      <div style={{ flex: 1, overflow: 'auto', padding: '4px 0' }}>
        {loading && !hasItems ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '16px 20px', fontSize: 13, color: t.textMuted }}>
            <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
            Loading…
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
            {/* The knowledge base IS the root of this list. Its documents sit directly inside it,
                which is the normal shape now — a knowledge base is a folder — so they appear there
                rather than in an "(ungrouped)" bucket that read like a filing mistake. Documents
                filed under a path keep their folders below. */}
            <div
              onClick={() => toggleExpand('__kb__')}
              title={selectedBase?.folder || knowledge}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                padding: '3px 8px',
                paddingLeft: 6,
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
              <Folder size={14} style={{ flexShrink: 0, color: t.accent }} />
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', flex: 1, fontWeight: 500 }}>
                {selectedBase?.name || knowledge}
              </span>
              <span style={{ fontSize: 11, color: t.textMuted, flexShrink: 0 }}>
                {folderTree.reduce((sum, f) => sum + f.docCount, 0) + ungroupedDocs.length}
              </span>
            </div>

            {expanded.has('__kb__') && (
              <>
                {folderTree.map((node) => renderFolderNode(node, 1))}
                {ungroupedDocs.map((doc) => renderDocItem(doc, 1))}
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
        {indexMsg && (
          <div style={{ fontSize: 11, color: indexMsg.startsWith('Failed') ? '#e5484d' : '#10b981', marginTop: 4 }}>
            {indexMsg}
          </div>
        )}
      </div>
    </div>
  );
}
