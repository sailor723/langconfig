/**
 * Simplified Knowledge Base View
 *
 * Upload documents → browse folder tree → select a folder → chat with
 * all documents in that folder as context.
 *
 * No Neo4j, no Vector RAG, no GraphIndex — just folder-based context
 * passed directly to the LLM.
 */

import { useState, useEffect, useRef, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload, FileText, Trash2, RefreshCw, Loader, Check, Database, Filter, Folder } from 'lucide-react';
import KbTreeView from './KbTreeView';
import apiClient from "../../../lib/api-client";
import { useProject } from "../../../contexts/ProjectContext";
import { useToast } from '../../../hooks/useToast';
import StorageMetrics from '../../../components/ui/StorageMetrics';
import DocumentViewer from './DocumentViewer';
import DocChatPanel from './DocChatPanel';

interface Document {
  id: number;
  project_id: number;
  name: string;
  document_type: string;
  size: number;
  chunk_count?: number;
  indexing_status: 'not_indexed' | 'indexing' | 'ready' | 'failed';
  created_at: string;
  indexed_at?: string;
  metadata?: any;
  file_path?: string;
  context_doc_id?: number;
  industry?: string | null;
  player?: string | null;
  sub_category?: string | null;
  sub_department?: string | null;
}

export type { Document };

export interface FolderNode {
  name: string;
  path: string;
  children: FolderNode[];
  doc?: Document;
}

/** Build a folder tree from a flat Document[] hierarchy metadata. */
function buildFolderTree(docs: Document[]): FolderNode {
  const root: FolderNode = { name: '', path: '', children: [] };
  for (const doc of docs) {
    const parts = [
      doc.industry, doc.player, doc.sub_category, doc.sub_department,
    ].filter((p): p is string => !!p && p.length > 0);

    if (parts.length === 0) {
      let ungrouped = root.children.find((c) => c.name === '(ungrouped)');
      if (!ungrouped) {
        ungrouped = { name: '(ungrouped)', path: '__ungrouped__', children: [] };
        root.children.push(ungrouped);
      }
      ungrouped.children.push({ name: doc.name, path: `__ungrouped__/${doc.id}`, children: [], doc });
      continue;
    }

    let current = root;
    let pathSoFar = '';
    for (let i = 0; i < parts.length; i++) {
      const segment = parts[i];
      pathSoFar = pathSoFar ? `${pathSoFar}/${segment}` : segment;
      const displayName = segment.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
      let child = current.children.find((c) => c.name === displayName && !c.doc);
      if (!child) {
        child = { name: displayName, path: pathSoFar, children: [] };
        current.children.push(child);
      }
      current = child;
    }
    current.children.push({ name: doc.name, path: `${pathSoFar}/${doc.id}`, children: [], doc });
  }

  const sortNode = (node: FolderNode) => {
    node.children.sort((a, b) => {
      if (!!a.doc !== !!b.doc) return a.doc ? 1 : -1;
      return a.name.localeCompare(b.name);
    });
    for (const c of node.children) sortNode(c);
  };
  sortNode(root);
  return root;
}

export default function KnowledgeBaseView() {
  const { t } = useTranslation('chat');
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);

  // Resizable column widths
  const [leftWidth, setLeftWidth] = useState<number>(() => {
    const v = typeof window !== 'undefined' ? localStorage.getItem('kb.leftWidth') : null;
    return v ? Math.max(180, Math.min(600, parseInt(v, 10) || 288)) : 288;
  });
  const [rightWidth, setRightWidth] = useState<number>(() => {
    const v = typeof window !== 'undefined' ? localStorage.getItem('kb.rightWidth') : null;
    return v ? Math.max(280, Math.min(800, parseInt(v, 10) || 448)) : 448;
  });
  const draggingRef = useRef<'left' | 'right' | null>(null);

  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const pathInputRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => {
    const el = folderInputRef.current;
    if (el) {
      el.setAttribute('webkitdirectory', '');
      el.setAttribute('directory', '');
    }
  }, []);

  // Drag resize handlers (same as before)
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!draggingRef.current) return;
      const container = document.querySelector('.kb-cols') as HTMLElement | null;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      if (draggingRef.current === 'left') {
        setLeftWidth(Math.max(180, Math.min(600, e.clientX - rect.left)));
      } else {
        setRightWidth(Math.max(280, Math.min(800, rect.right - e.clientX)));
      }
    };
    const onUp = () => {
      if (draggingRef.current === 'left') localStorage.setItem('kb.leftWidth', String(leftWidth));
      else if (draggingRef.current === 'right') localStorage.setItem('kb.rightWidth', String(rightWidth));
      draggingRef.current = null;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
  }, [leftWidth, rightWidth]);

  const startDrag = (side: 'left' | 'right') => (e: React.MouseEvent) => {
    e.preventDefault();
    draggingRef.current = side;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };

  // Upload state
  const [folderPathInput, setFolderPathInput] = useState('');
  const [uploading, setUploading] = useState(false);
  const [selectedStatus, setSelectedStatus] = useState<string>('all');
  const [selectedDocId, setSelectedDocId] = useState<number | null>(null);
  const [selectedFolderPath, setSelectedFolderPath] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  const [uploadProgress, setUploadProgress] = useState<{
    phase: 'idle' | 'uploading' | 'indexing' | 'done' | 'error';
    fileName: string;
    fileCount: number;
    percent: number;
    pendingDocIds: number[];
  }>({ phase: 'idle', fileName: '', fileCount: 0, percent: 0, pendingDocIds: [] });

  const { activeProjectId } = useProject();
  const { showToast } = useToast();
  const SUPPORTED_FILES = '.txt,.md,.pdf,.json,.py,.js,.ts,.tsx,.jsx,.java,.c,.cpp,.h,.hpp,.cs,.rb,.go,.rs,.php,.swift,.kt,.scala,.r,.sql,.sh,.bash,.doc,.docx,.html,.htm,.xml,.csv,.yaml,.yml,.zip,.tar,.gz,.tgz,.rar,.7z,.rtf,.odt,.epub,.ppt,.pptx,.xls,.xlsx,.png,.jpg,.jpeg,.gif,.bmp,.tiff,.webp';

  // Sidebar view mode
  const [sidebarView, setSidebarView] = useState<'list' | 'tree'>(() => {
    const v = typeof window !== 'undefined' ? localStorage.getItem('kb.sidebarView') : null;
    return v === 'tree' ? 'tree' : 'list';
  });
  useEffect(() => {
    try { localStorage.setItem('kb.sidebarView', sidebarView); } catch {}
  }, [sidebarView]);

  // Expanded folders state
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(() => {
    const v = typeof window !== 'undefined' ? localStorage.getItem('kb.expandedFolders') : null;
    try { return new Set(v ? JSON.parse(v) : []); } catch { return new Set(); }
  });
  useEffect(() => {
    try { localStorage.setItem('kb.expandedFolders', JSON.stringify([...expandedFolders])); } catch {}
  }, [expandedFolders]);
  const toggleFolder = (path: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path); else next.add(path);
      return next;
    });
  };

  // Load documents
  useEffect(() => {
    const abort = new AbortController();
    if (activeProjectId) loadDocuments(abort.signal);
    return () => abort.abort();
  }, [selectedStatus, activeProjectId]);

  // Poll for indexing status
  useEffect(() => {
    const hasIndexingDocs = documents.some(d => d.indexing_status === 'indexing');
    const interval = setInterval(() => loadDocuments(), hasIndexingDocs ? 2000 : 10000);
    return () => clearInterval(interval);
  }, [documents]);

  // Auto-select first doc
  useEffect(() => {
    if (documents.length === 0) { setSelectedDocId(null); return; }
    if (!documents.some(d => d.id === selectedDocId)) {
      const first = documents.find(d => d.indexing_status === 'ready');
      setSelectedDocId(first?.id ?? documents[0].id);
    }
  }, [documents, selectedDocId]);

  const loadDocuments = async (signal?: AbortSignal) => {
    if (!activeProjectId) return;
    try {
      setLoading(true);
      const params: any = { project_id: activeProjectId };
      if (selectedStatus !== 'all') params.status = selectedStatus;
      // Simplified: only load from Postgres (no more Neo4j merge)
      const pgRes = await apiClient.listDocuments({ ...params, signal }).catch((e) => {
        if (signal?.aborted) throw e;
        return { data: [] as any[] };
      });
      setDocuments((pgRes.data || []) as Document[]);
    } catch (error: any) {
      if (error?.name === 'AbortError' || error?.name === 'CanceledError') return;
      console.error('Failed to load documents:', error);
    } finally {
      setLoading(false);
    }
  };

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
  };

  // Folder path ingest
  const handleIngestFromPath = async () => {
    if (!activeProjectId) { alert('Please select a project first'); return; }
    const folder = folderPathInput.trim();
    if (!folder) return;
    setUploading(true);
    setUploadProgress({ phase: 'uploading', fileName: folder, fileCount: 0, percent: 0, pendingDocIds: [] });
    try {
      const resp = await apiClient.ingestFolderFromPath({ project_id: activeProjectId, folder_path: folder });
      const data = resp.data as any;
      alert(`Ingested ${data.files_ingested} files (${data.created} new, ${data.updated} metadata-backfilled, ${data.failed} failed)`);
      setUploadProgress({ phase: 'indexing', fileName: 'Indexing in background…', fileCount: data.files_ingested, percent: 100, pendingDocIds: [] });
      await loadDocuments();
      setFolderPathInput('');
      setTimeout(() => setUploadProgress({ phase: 'idle', fileName: '', fileCount: 0, percent: 0, pendingDocIds: [] }), 3000);
    } catch (error: any) {
      const detail = error?.response?.data?.detail || error?.message || 'Ingest failed';
      alert(`Ingest failed: ${detail}`);
      setUploadProgress({ phase: 'error', fileName: detail, fileCount: 0, percent: 0, pendingDocIds: [] });
      setTimeout(() => setUploadProgress({ phase: 'idle', fileName: '', fileCount: 0, percent: 0, pendingDocIds: [] }), 5000);
    } finally { setUploading(false); }
  };

  // File upload
  const handleFileSelect = async (files: FileList | null) => {
    if (!files || files.length === 0 || !activeProjectId) return;
    setUploading(true);
    const fileArray = Array.from(files);
    setUploadProgress({ phase: 'uploading', fileName: files.length === 1 ? files[0].name : `${files.length} files`, fileCount: files.length, percent: 0, pendingDocIds: [] });
    try {
      const hasArchives = fileArray.some(f => ['zip', 'tar', 'gz', 'tgz', 'rar', '7z'].includes(f.name.split('.').pop()?.toLowerCase() || ''));
      const fileMetadata = fileArray.map((f) => {
        const relPath: string = (f as any).webkitRelativePath || f.name;
        const meta: any = { name: f.name, tags: [] };
        const parts = relPath.split('/').filter(Boolean);
        if (parts.length >= 2) meta.industry = parts[0];
        if (parts.length >= 3) meta.player = parts[1];
        if (parts.length >= 4) meta.sub_category = parts[2];
        if (parts.length >= 5) meta.sub_department = parts[3];
        if (meta.industry) meta.tags.push(meta.industry);
        if (meta.player) meta.tags.push(meta.player);
        if (meta.sub_category) meta.tags.push(meta.sub_category);
        if (meta.sub_department) meta.tags.push(meta.sub_department);
        return meta;
      });

      if (fileArray.length > 1 || hasArchives) {
        await apiClient.uploadDocumentsBulk(activeProjectId, fileArray, true, undefined, (pct: number) => setUploadProgress(cur => cur.phase === 'uploading' ? { ...cur, percent: pct } : cur), fileMetadata);
      } else {
        const singleMeta = fileMetadata[0];
        const uploadMeta: any = singleMeta ? { tags: singleMeta.tags } : undefined;
        if (singleMeta && !singleMeta.industry && selectedFolderPath) {
          const parts = selectedFolderPath.split('/').filter(Boolean);
          if (parts.length >= 1) uploadMeta.industry = parts[0];
          if (parts.length >= 2) uploadMeta.player = parts[1];
          if (parts.length >= 3) uploadMeta.sub_category = parts[2];
          if (parts.length >= 4) uploadMeta.sub_department = parts[3];
        }
        await apiClient.uploadDocument(activeProjectId, files[0], uploadMeta, (pct: number) => setUploadProgress(cur => cur.phase === 'uploading' ? { ...cur, percent: pct } : cur));
      }

      setUploadProgress(cur => ({ ...cur, phase: 'indexing', percent: 100, fileName: 'Saved. Indexing in background…' }));
      setSelectedStatus('all');
      await loadDocuments();
      showToast(files.length === 1 ? `Uploaded "${files[0].name}"` : `Uploaded ${files.length} files`, 'success', 3000);
    } catch (error: any) {
      setUploadProgress(cur => ({ ...cur, phase: 'error' }));
      showToast(error?.response?.data?.detail ? `Upload failed: ${error.response.data.detail}` : 'Upload failed', 'error', 5000);
      setTimeout(() => setUploadProgress({ phase: 'idle', fileName: '', fileCount: 0, percent: 0, pendingDocIds: [] }), 5000);
    } finally { setUploading(false); }
  };

  // Watch indexing progress
  useEffect(() => {
    if (uploadProgress.phase !== 'indexing' || uploadProgress.pendingDocIds.length === 0) return;
    const stillPending = uploadProgress.pendingDocIds.filter(id => {
      const doc = documents.find(d => d.id === id);
      return doc && doc.indexing_status !== 'ready' && doc.indexing_status !== 'failed';
    });
    const failed = uploadProgress.pendingDocIds.filter(id => {
      const doc = documents.find(d => d.id === id);
      return doc && doc.indexing_status === 'failed';
    });
    if (stillPending.length === 0) {
      const fc = failed.length;
      setUploadProgress(cur => ({ ...cur, phase: 'done', fileName: fc === 0 ? `✓ ${uploadProgress.pendingDocIds.length - fc} doc(s) ready` : `${uploadProgress.pendingDocIds.length - fc} ready, ${fc} failed` }));
      showToast(`All ${uploadProgress.pendingDocIds.length - fc} doc(s) ready`, 'success', 3000);
      setTimeout(() => setUploadProgress({ phase: 'idle', fileName: '', fileCount: 0, percent: 0, pendingDocIds: [] }), 4000);
    }
  }, [documents, uploadProgress.phase, uploadProgress.pendingDocIds, showToast]);

  // Drag-and-drop handlers
  const [isDragging, setIsDragging] = useState(false);
  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); setIsDragging(true); };
  const handleDragLeave = (e: React.DragEvent) => { e.preventDefault(); setIsDragging(false); };
  const handleDrop = (e: React.DragEvent) => { e.preventDefault(); setIsDragging(false); handleFileSelect(e.dataTransfer.files); };

  const handleDelete = async (id: number) => {
    if (!confirm('Are you sure you want to delete this document?')) return;
    try { await apiClient.deleteDocument(id); await loadDocuments(); }
    catch (error) { console.error('Failed to delete document:', error); alert('Failed to delete document'); }
  };

  // Computed values
  const totalDocuments = documents.length;
  const totalChunks = documents.reduce((sum, doc) => sum + (doc.chunk_count || 0), 0);
  const totalSize = documents.reduce((sum, doc) => sum + (doc.size || 0), 0);
  const readyCount = documents.filter(d => d.indexing_status === 'ready').length;
  const selectedDoc = documents.find(doc => doc.id === selectedDocId) ?? null;
  const readyDocuments = documents.filter(doc => doc.indexing_status === 'ready');
  const notReadyDocuments = documents.filter(doc => doc.indexing_status !== 'ready');
  const folderTree = useMemo(() => buildFolderTree(readyDocuments), [readyDocuments]);

  const getStatusDisplay = (status: string) => {
    switch (status) {
      case 'not_indexed': return 'pending';
      case 'indexing': return 'processing';
      case 'ready': return 'ready';
      case 'failed': return 'failed';
      default: return status;
    }
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-background-light dark:bg-background-dark">
      {/* Header */}
      <div className="bg-white dark:bg-panel-dark border-b border-gray-200 dark:border-border-dark p-4">
        <div className="flex items-center justify-between gap-4">
          <h1 className="text-xl font-bold" style={{ color: 'var(--color-text-primary)' }}>
            Knowledge
          </h1>
          <div className="flex items-center gap-2 flex-shrink-0">
            <MetricPill icon={<FileText className="w-3 h-3" />} label="Docs" value={totalDocuments} color="#3b82f6" />
            <MetricPill icon={<Check className="w-3 h-3" />} label="Indexed" value={`${readyCount}/${totalDocuments}`} color="#f59e0b" />
            <MetricPill icon={<Database className="w-3 h-3" />} label="Chunks" value={totalChunks} color="#8b5cf6" />
            <MetricPill icon={<Filter className="w-3 h-3" />} label="Storage" value={formatFileSize(totalSize)} color="#10b981" />

            {/* Selected folder indicator */}
            {selectedFolderPath && (
              <div className="flex items-center gap-1 px-2 py-1 rounded-lg border text-[11px]" style={{ borderColor: 'var(--color-primary)', backgroundColor: 'var(--color-primary-alpha)' }}>
                <Folder className="w-3 h-3" />
                <span className="truncate max-w-[120px]">
                  {selectedFolderPath.split('/').map(s => s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())).join(' › ')}
                </span>
                <button onClick={() => setSelectedFolderPath(null)} className="ml-0.5 hover:bg-white/20 rounded p-0.5"><span className="text-xs">✕</span></button>
              </div>
            )}

            <button
              onClick={() => loadDocuments()}
              className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-white/10 transition-all"
              style={{ color: 'var(--color-text-primary)' }}
              title="Refresh"
            >
              <RefreshCw className="w-3.5 h-3.5" style={{ color: 'var(--color-primary)' }} />
            </button>
          </div>
        </div>
        {/* Upload row */}
        <div className="flex items-center gap-2 mt-2">
          <label className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-primary text-white transition-all text-[11px] font-medium cursor-pointer hover:opacity-90">
            <Upload className="w-3 h-3" />
            <span>Browse files</span>
            <input type="file" multiple accept={SUPPORTED_FILES} onChange={(e) => handleFileSelect(e.target.files)} className="hidden" disabled={uploading} />
          </label>
          <button
            type="button"
            onClick={() => pathInputRef.current?.focus()}
            className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-purple-600 text-white transition-all text-[11px] font-medium hover:opacity-90"
          >
            <Database className="w-3 h-3" />
            <span>Select folder</span>
          </button>
          <input ref={pathInputRef} type="text" value={folderPathInput} onChange={(e) => setFolderPathInput(e.target.value)}
            placeholder="Paste folder path..." disabled={uploading}
            className="px-2 py-1 border border-gray-200 dark:border-border-dark rounded text-[10px] focus:outline-none focus:ring-1 focus:ring-primary w-48"
            style={{ backgroundColor: 'var(--color-input-background)', color: 'var(--color-text-primary)' }}
            onKeyDown={(e) => { if (e.key === 'Enter' && folderPathInput.trim() && !uploading) handleIngestFromPath(); }}
          />
          <button onClick={handleIngestFromPath} disabled={!folderPathInput.trim() || uploading}
            className={`px-2 py-1 rounded text-[10px] font-medium transition-all ${!folderPathInput.trim() || uploading ? 'opacity-50 cursor-not-allowed bg-gray-200 dark:bg-white/10' : 'bg-indigo-600 text-white hover:opacity-90 cursor-pointer'}`}
          >
            {uploading ? 'Uploading...' : 'Ingest'}
          </button>
        </div>
      </div>

      {/* Upload progress banner */}
      {uploadProgress.phase !== 'idle' && (
        <div className="flex items-center gap-3 px-6 py-1.5 border-b border-gray-200 dark:border-border-dark text-[11px]" style={{ backgroundColor: uploadProgress.phase === 'error' ? 'rgba(239,68,68,0.04)' : uploadProgress.phase === 'done' ? 'rgba(34,197,94,0.04)' : 'rgba(59,130,246,0.04)' }}>
          <Loader className={`w-3 h-3 ${uploadProgress.phase === 'uploading' || uploadProgress.phase === 'indexing' ? 'animate-spin' : ''}`} />
          <span className="flex-1 truncate">{uploadProgress.fileName}</span>
          <button onClick={() => setUploadProgress({ phase: 'idle', fileName: '', fileCount: 0, percent: 0, pendingDocIds: [] })} className="text-[10px] underline">clear</button>
        </div>
      )}

      <div className="flex-1 overflow-hidden p-3">
        <div className="flex h-full gap-0 kb-cols">
          {/* Left column: doc list / tree */}
          <div className="flex-shrink-0 bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg p-3 overflow-hidden flex flex-col" style={{ width: leftWidth }}>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-semibold" style={{ color: 'var(--color-text-primary)' }}>Documents</h3>
              <div className="flex items-center gap-1">
                <div className="flex items-center rounded border border-gray-200 dark:border-border-dark overflow-hidden">
                  <button onClick={() => setSidebarView('list')}
                    className="px-1.5 py-0.5 text-[10px]"
                    style={{ backgroundColor: sidebarView === 'list' ? 'var(--color-primary)' : 'transparent', color: sidebarView === 'list' ? 'white' : 'var(--color-text-muted)' }}
                  >List</button>
                  <button onClick={() => setSidebarView('tree')}
                    className="px-1.5 py-0.5 text-[10px]"
                    style={{ backgroundColor: sidebarView === 'tree' ? 'var(--color-primary)' : 'transparent', color: sidebarView === 'tree' ? 'white' : 'var(--color-text-muted)' }}
                  >Tree</button>
                </div>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-gray-100 dark:bg-white/10" style={{ color: 'var(--color-text-muted)' }}>{documents.length}</span>
                <select value={selectedStatus} onChange={(e) => setSelectedStatus(e.target.value)}
                  className="px-1 py-0.5 border border-gray-200 dark:border-border-dark rounded text-[10px] focus:outline-none"
                  style={{ backgroundColor: 'var(--color-input-background)', color: 'var(--color-text-primary)' }}>
                  <option value="all">All</option>
                  <option value="ready">Indexed</option>
                  <option value="indexing">Indexing</option>
                  <option value="not_indexed">Pending</option>
                  <option value="failed">Failed</option>
                </select>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto space-y-4">
              <div>
                <h4 className="text-[11px] font-semibold uppercase tracking-wide mb-1" style={{ color: 'var(--color-text-muted)' }}>Ready</h4>
                <div className="space-y-1">
                  {sidebarView === 'tree' ? (
                    <KbTreeView
                      folderTree={folderTree}
                      readyDocuments={readyDocuments}
                      selectedDocId={selectedDocId}
                      highlightedDocId={null}
                      expandedFolders={expandedFolders}
                      toggleFolder={toggleFolder}
                      scopeDocIds={new Set()}
                      toggleScopeDoc={() => {}}
                      setSelectedDocId={setSelectedDocId}
                      onFolderSelect={setSelectedFolderPath}
                      handleDelete={handleDelete}
                      t={t}
                      formatFileSize={formatFileSize}
                    />
                  ) : (
                    readyDocuments.map(doc => (
                      <button key={doc.id} data-doc-card-id={doc.id}
                        onClick={() => setSelectedDocId(doc.id)}
                        className={`w-full text-left rounded-lg border px-2.5 py-1.5 transition-all text-[11px] ${
                          selectedDocId === doc.id
                            ? 'border-amber-300 dark:border-amber-500/40 bg-amber-50 dark:bg-amber-500/10'
                            : 'border-gray-200 dark:border-border-dark hover:bg-gray-50 dark:hover:bg-white/5'
                        }`}
                      >
                        <div className="flex items-center gap-1.5">
                          <div className="w-2 h-2 rounded-full bg-amber-500 flex-shrink-0" />
                          <span className="truncate flex-1" style={{ color: 'var(--color-text-primary)' }}>{doc.name}</span>
                          <span className="text-[9px]" style={{ color: 'var(--color-text-muted)' }}>{formatFileSize(doc.size)}</span>
                          <button onClick={(e) => { e.stopPropagation(); handleDelete(doc.id); }}
                            className="p-0.5 rounded hover:bg-red-50 dark:hover:bg-red-500/10" style={{ color: 'var(--color-text-muted)' }}>
                            <Trash2 className="w-2.5 h-2.5" />
                          </button>
                        </div>
                      </button>
                    ))
                  )}
                  {readyDocuments.length === 0 && <p className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>No ready documents.</p>}
                </div>
              </div>

              <div>
                <h4 className="text-[11px] font-semibold uppercase tracking-wide mb-1" style={{ color: 'var(--color-text-muted)' }}>
                  Not ready <span className="font-normal lowercase">({notReadyDocuments.length})</span>
                </h4>
                <div className="space-y-1">
                  {notReadyDocuments.map(doc => (
                    <div key={doc.id} className="rounded-lg border border-gray-200 dark:border-border-dark px-2.5 py-1.5">
                      <div className="flex items-center gap-1.5">
                        <div className={`w-2 h-2 rounded-full flex-shrink-0 ${
                          doc.indexing_status === 'indexing' ? 'bg-blue-500' : doc.indexing_status === 'failed' ? 'bg-red-500' : 'bg-gray-400'
                        }`} />
                        <span className="text-[11px] truncate flex-1" style={{ color: 'var(--color-text-primary)' }}>{doc.name}</span>
                        <span className="text-[9px]" style={{ color: 'var(--color-text-muted)' }}>{getStatusDisplay(doc.indexing_status)}</span>
                        <button onClick={() => handleDelete(doc.id)} className="p-0.5 rounded hover:bg-red-50 dark:hover:bg-red-500/10" style={{ color: 'var(--color-text-muted)' }}>
                          <Trash2 className="w-2.5 h-2.5" />
                        </button>
                      </div>
                    </div>
                  ))}
                  {notReadyDocuments.length === 0 && <p className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>All documents are ready.</p>}
                </div>
              </div>
            </div>
          </div>

          {/* Left divider */}
          <div onMouseDown={startDrag('left')} className="w-1.5 flex-shrink-0 cursor-col-resize hover:bg-purple-200/40 dark:hover:bg-purple-500/20 transition-colors" />

          {/* Center: Document viewer */}
          <div className="min-w-0 flex-1 flex flex-col gap-3 overflow-hidden">
            {selectedDocId && selectedDoc ? (
              <div className="flex-1 min-h-0 bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg overflow-hidden flex flex-col">
                <div className="flex items-center justify-between px-3 py-1.5 border-b border-gray-200 dark:border-border-dark flex-shrink-0">
                  <div className="flex items-center gap-2">
                    <FileText className="w-3 h-3" style={{ color: 'var(--color-primary)' }} />
                    <span className="text-xs font-semibold truncate max-w-[300px]" style={{ color: 'var(--color-text-primary)' }}>{selectedDoc.name}</span>
                    <span className="text-[9px] px-1 py-0.5 rounded-full bg-gray-100 dark:bg-white/10" style={{ color: 'var(--color-text-muted)' }}>{selectedDoc.document_type || 'pdf'}</span>
                  </div>
                  <a href={`/api/rag/documents/${selectedDocId}/file`} target="_blank" rel="noreferrer" className="text-[9px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-white/10 hover:opacity-80" style={{ color: 'var(--color-text-primary)' }}>Open ↗</a>
                </div>
                <div className="flex-1 min-h-0 overflow-hidden">
                  <DocumentViewer
                    key={selectedDocId}
                    documentId={selectedDocId}
                    documentName={selectedDoc.name}
                    documentType={selectedDoc.document_type}
                  />
                </div>
              </div>
            ) : (
              <div className="flex-1 flex items-center justify-center bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg">
                <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Select a document to preview</p>
              </div>
            )}
          </div>

          {/* Right divider */}
          <div onMouseDown={startDrag('right')} className="w-1.5 flex-shrink-0 cursor-col-resize hover:bg-purple-200/40 dark:hover:bg-purple-500/20 transition-colors" />

          {/* Right column: simplified Doc Chat */}
          <div className="flex-shrink-0 overflow-hidden flex flex-col" style={{ width: rightWidth }}>
            <DocChatPanel
              folderPath={selectedFolderPath ?? ''}
              projectId={activeProjectId}
              onOpenDoc={(docName) => {
                const match = documents.find(d => d.name === docName);
                if (match) setSelectedDocId(match.id);
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function MetricPill({ icon, label, value, color }: { icon: React.ReactNode; label: string; value: number | string; color: string }) {
  return (
    <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg border bg-white dark:bg-panel-dark text-xs" style={{ borderColor: 'var(--color-border-dark, #e5e7eb)' }}>
      <span style={{ color }}>{icon}</span>
      <span className="text-[9px] uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>{label}</span>
      <span className="font-semibold tabular-nums" style={{ color: 'var(--color-text-primary)' }}>{value}</span>
    </div>
  );
}
