/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload, FileText, Trash2, Search, Database, Filter, Loader, RefreshCw, Sparkles, Check, ChevronDown, ChevronUp, X, Plus } from 'lucide-react';
import SearchModal from './SearchModal';
import apiClient from "../../../lib/api-client";
import { useProject } from "../../../contexts/ProjectContext";
import { useToast } from '../../../hooks/useToast';
import SearchMetricsDisplay from './SearchMetricsDisplay';
import SearchHistoryLog from './SearchHistoryLog';
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
  /** True if the doc came from the Neo4j catalog but isn't in the
      Postgres context_documents table (i.e. the chat can see it but
      the upload pipeline skipped the Postgres step). The card still
      renders normally; opening it uses file_path + context_doc_id. */
  neo4j_only?: boolean;
  file_path?: string;
  context_doc_id?: number;
}

interface SearchResult {
  document_id: number;
  document_name: string;
  chunk_text: string;
  similarity_score: number;
  metadata: any;
  chunk_id?: string;
  chunk_index?: number;
  total_chunks_in_doc?: number;
  chunk_token_count?: number;
  chunk_char_count?: number;
  source_location?: string;
  retrieval_rank?: number;
}

interface SearchMetrics {
  query: string;
  use_hyde: boolean;
  hyde_auto_detected: boolean;
  use_toon: boolean;
  top_k: number;
  retrieval_duration_ms: number;
  query_tokens: number;
  total_context_tokens: number;
  results_count: number;
  avg_similarity_score: number;
  max_similarity_score: number;
  min_similarity_score: number;
}

export default function KnowledgeBaseView() {
  const { t } = useTranslation('chat');
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);

  // ----- Resizable column widths (px) -----
  // Left = doc cards list, Right = chat panel. Center is flex-1.
  // Drag the divider between columns to resize. Persists to localStorage
  // so the user's preferred width is remembered across visits.
  const [leftWidth, setLeftWidth] = useState<number>(() => {
    const v = typeof window !== 'undefined' ? localStorage.getItem('kb.leftWidth') : null;
    return v ? Math.max(180, Math.min(600, parseInt(v, 10) || 288)) : 288;
  });
  const [rightWidth, setRightWidth] = useState<number>(() => {
    const v = typeof window !== 'undefined' ? localStorage.getItem('kb.rightWidth') : null;
    return v ? Math.max(280, Math.min(800, parseInt(v, 10) || 448)) : 448;
  });
  // Track which column is being dragged (for cursor + style)
  const draggingRef = useRef<'left' | 'right' | null>(null);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!draggingRef.current) return;
      // The layout container is at .kb-cols — we measure its left/right
      // edge to compute widths in pixels.
      const container = document.querySelector('.kb-cols') as HTMLElement | null;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      if (draggingRef.current === 'left') {
        const w = Math.max(180, Math.min(600, e.clientX - rect.left));
        setLeftWidth(w);
      } else {
        const w = Math.max(280, Math.min(800, rect.right - e.clientX));
        setRightWidth(w);
      }
    };
    const onUp = () => {
      if (draggingRef.current === 'left') {
        localStorage.setItem('kb.leftWidth', String(leftWidth));
      } else if (draggingRef.current === 'right') {
        localStorage.setItem('kb.rightWidth', String(rightWidth));
      }
      draggingRef.current = null;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [leftWidth, rightWidth]);

  const startDrag = (side: 'left' | 'right') => (e: React.MouseEvent) => {
    e.preventDefault();
    draggingRef.current = side;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };
  const [uploading, setUploading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedStatus, setSelectedStatus] = useState<string>('all');
  const [selectedDocId, setSelectedDocId] = useState<number | null>(null);
  // Doc that was just selected by the chat (auto-clears after 2.5s)
  const [highlightedDocId, setHighlightedDocId] = useState<number | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [showSearchResults, setShowSearchResults] = useState(false);
  const [useHyDE, setUseHyDE] = useState(false);
  const [useTOON, setUseTOON] = useState(false);
  const [searchMode, setSearchMode] = useState<'vector' | 'graphindex'>('graphindex');
  const [compareMode, setCompareMode] = useState(false);

  // Whether the pop-out search modal is open. The full search UI lives
  // in `SearchModal.tsx` and is triggered from a button in the title bar.
  // When the modal is open, the doc viewer doesn't have to share its
  // vertical space with a bottom-anchored search panel — it gets full size.
  const [searchModalOpen, setSearchModalOpen] = useState(false);
  const [searchMetrics, setSearchMetrics] = useState<SearchMetrics | null>(null);
  const [comparisonMetrics, setComparisonMetrics] = useState<SearchMetrics | null>(null);
  const [comparisonResults, setComparisonResults] = useState<SearchResult[]>([]);
  const [expandedChunks, setExpandedChunks] = useState<Set<number>>(new Set());
  const [pageIndexDocs, setGraphIndexDocs] = useState<any[]>([]);
  // Note: the previous bottom-anchored "search panel" (with a chevron to
  // collapse it) has been moved out into `SearchModal.tsx`. The state +
  // handlers it used are still here because the modal re-uses them
  // (searchQuery, searchResults, useHyDE, compareMode, etc.).
  const [answerLoading, setAnswerLoading] = useState(false);
  const [answerResult, setAnswerResult] = useState<{
    doc_id: string;
    doc_name: string;
    answer: string;
    pages_loaded: number;
    content_chars: number;
    model: string;
  } | null>(null);
  const [previewData, setPreviewData] = useState<{
    doc_id: string;
    context_doc_id: number;
    doc_name: string;
    type: string;
    page_count: number;
    content_preview: string;
    has_more: boolean;
    total_chars: number;
  } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Active doc scope — when non-empty, the chat agent only considers / reads
  // docs whose ID is in this set. Maps 1:1 to the backend's `scope` field
  // (resolved to doc NAMES at chat-send time).
  // - empty set  → no filter (all docs visible, current behavior)
  // - some IDs   → only those docs are visible to the chat
  // The user toggles membership via the checkbox on each doc card, or the
  // "Select all" / "Clear" buttons above the ready-docs section.
  const [scopeDocIds, setScopeDocIds] = useState<Set<number>>(new Set());

  const toggleScopeDoc = (docId: number) => {
    setScopeDocIds((prev) => {
      const next = new Set(prev);
      if (next.has(docId)) next.delete(docId);
      else next.add(docId);
      return next;
    });
  };

  const clearScope = () => setScopeDocIds(new Set());
  const selectAllScope = () => {
    // Only "ready" docs are selectable (indexed + has file_path).
    setScopeDocIds(new Set(readyDocuments.map((d) => d.id)));
  };

  const inScopeCount = scopeDocIds.size;
  const isScopeActive = inScopeCount > 0;

  // Agent info for the right-column chat panel. The DocChatPanel looks
  // up its agent by name ("graphindex_chat") on mount, then pushes the
  // resolved name + description up to us via onAgentInfoChange. We show
  // it as a pill in the Knowledge Base header (next to the kb_search
  // button) so the user can see at a glance which agent the chat is
  // wired to without needing to inspect the chat panel itself.
  const [chatAgentInfo, setChatAgentInfo] = useState<{ name: string; description: string } | null>(null);
  // Upload progress state — drives the progress bar in the upload zone
  // and (after completion) the background-indexing indicator that
  // auto-clears once all uploaded docs reach `ready` status.
  const [uploadProgress, setUploadProgress] = useState<{
    phase: 'idle' | 'uploading' | 'indexing' | 'done' | 'error';
    fileName: string;
    fileCount: number;
    percent: number; // 0-100, only meaningful in 'uploading' phase
    pendingDocIds: number[]; // doc ids still in 'not_indexed' / 'indexing'
  }>({
    phase: 'idle',
    fileName: '',
    fileCount: 0,
    percent: 0,
    pendingDocIds: [],
  });

  const { activeProjectId } = useProject();
  const { showToast } = useToast();
  // Expanded file type support - includes code files, documents, images, and archives
  const SUPPORTED_FILES = '.txt,.md,.pdf,.json,.py,.js,.ts,.tsx,.jsx,.java,.c,.cpp,.h,.hpp,.cs,.rb,.go,.rs,.php,.swift,.kt,.scala,.r,.sql,.sh,.bash,.doc,.docx,.html,.htm,.xml,.csv,.yaml,.yml,.zip,.tar,.gz,.tgz,.rar,.7z,.rtf,.odt,.epub,.ppt,.pptx,.xls,.xlsx,.png,.jpg,.jpeg,.gif,.bmp,.tiff,.webp';

  useEffect(() => {
    const abortController = new AbortController();

    if (activeProjectId) {
      loadDocuments(abortController.signal);
    }

    return () => {
      abortController.abort();
    };
  }, [selectedStatus, activeProjectId]);

  // Poll for document updates: every 2s if indexing, every 10s otherwise
  useEffect(() => {
    const hasIndexingDocs = documents.some(doc => doc.indexing_status === 'indexing');
    const interval = setInterval(() => {
      loadDocuments();
    }, hasIndexingDocs ? 2000 : 10000);

    return () => clearInterval(interval);
  }, [documents]);

  useEffect(() => {
    if (documents.length === 0) {
      if (selectedDocId !== null) setSelectedDocId(null);
      return;
    }

    const selectedStillExists = documents.some(doc => doc.id === selectedDocId);
    if (selectedStillExists) return;

    const firstReadyDoc = documents.find(doc => doc.indexing_status === 'ready');
    setSelectedDocId(firstReadyDoc?.id ?? documents[0].id);
  }, [documents, selectedDocId]);

  // Load preview when a document is selected.
  // BUG FIX: the old /api/rag/documents/{id}/preview endpoint read from
  // Postgres.file_path and 404'd for docs whose Postgres record is stale
  // (e.g. re-ingested via CLI). The doc header is now derived from the
  // already-loaded `documents` list (selectedDoc is declared further
  // down at line ~542). The PDF viewer (TwoPagePdfViewer) gets the file
  // from /file (which uses Neo4j).
  useEffect(() => {
    if (!selectedDocId || !activeProjectId) {
      setPreviewData(null);
      return;
    }
    // Stub: keep the state empty. The JSX uses selectedDoc for the header
    // and TwoPagePdfViewer for the actual rendering.
    setPreviewData(null);
  }, [selectedDocId, activeProjectId]);

  const loadDocuments = async (signal?: AbortSignal, overrideStatus?: string) => {
    if (!activeProjectId) return;

    try {
      setLoading(true);
      const params: any = { project_id: activeProjectId };
      const effectiveStatus = overrideStatus ?? selectedStatus;
      if (effectiveStatus !== 'all') {
        params.status = effectiveStatus;
      }
      // Fetch BOTH lists in parallel. The Postgres list is the
      // "official" one (with all the upload pipeline metadata), but
      // the Neo4j list is what the chat actually uses. Merging by
      // `name` keeps the sidebar in sync with the chat.
      const [pgRes, neo4jRes] = await Promise.all([
        apiClient.listDocuments({ ...params, signal }).catch((e) => {
          if (signal?.aborted) throw e;
          console.warn('Postgres doc list failed:', e);
          return { data: [] as any[] };
        }),
        apiClient.listNeo4jDocuments({ project_id: activeProjectId, signal }).catch((e) => {
          if (signal?.aborted) throw e;
          console.warn('Neo4j doc list failed:', e);
          return { data: { documents: [] as any[] } } as any;
        }),
      ]);
      const pgDocs: Document[] = pgRes.data || [];
      const neo4jDocs: any[] = neo4jRes.data?.documents || [];
      // Index Postgres docs by name so we can quickly detect
      // overlap. Neo4j-only docs (not in Postgres) become
      // "virtual" cards with negative IDs.
      const pgByName = new Map<string, Document>();
      for (const d of pgDocs) pgByName.set(d.name, d);
      // Start with the Postgres list (has all the upload metadata)
      const merged: Document[] = [...pgDocs];
      // For each Neo4j doc not in Postgres, append a virtual card
      let virtualId = -1;
      for (const n of neo4jDocs) {
        if (!pgByName.has(n.name)) {
          merged.push({
            id: virtualId--,
            project_id: activeProjectId,
            name: n.name,
            document_type: (n.name.split('.').pop() || 'unknown'),
            size: 0,  // unknown — file is on disk but Postgres didn't index it
            chunk_count: n.chunk_count ?? undefined,
            indexing_status: 'ready',  // it's in Neo4j, so it's been enriched
            created_at: n.indexed_at || new Date().toISOString(),
            indexed_at: n.indexed_at || undefined,
            metadata: { about: n.about, page_count: n.page_count, doc_index_id: n.doc_index_id },
            neo4j_only: true,
            file_path: n.file_path,
            context_doc_id: n.context_doc_id,
          });
        }
      }
      setDocuments(merged);
    } catch (error) {
      // Ignore abort errors
      if (error instanceof Error && (error.name === 'AbortError' || error.name === 'CanceledError')) {
        return;
      }
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

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const handleFileSelect = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    if (!activeProjectId) {
      alert('Please select a project first');
      return;
    }

    setUploading(true);

    const fileArray = Array.from(files);
    const label =
      files.length === 1 ? files[0].name : `${files.length} files`;

    // Phase 1 — uploading (with real progress from axios)
    setUploadProgress({
      phase: 'uploading',
      fileName: label,
      fileCount: files.length,
      percent: 0,
      pendingDocIds: [],
    });

    try {
      const extractArchives = true;
      const hasArchives = fileArray.some(f => {
        const ext = f.name.split('.').pop()?.toLowerCase();
        return ['zip', 'tar', 'gz', 'tgz', 'rar', '7z'].includes(ext || '');
      });

      const onProgress = (pct: number) => {
        setUploadProgress((cur) =>
          cur.phase === 'uploading' ? { ...cur, percent: pct } : cur
        );
      };

      // Use bulk upload if multiple files or archives with extraction enabled
      if (fileArray.length > 1 || hasArchives) {
        await apiClient.uploadDocumentsBulk(
          activeProjectId,
          fileArray,
          extractArchives,
          undefined,
          onProgress
        );
      } else {
        // Single file upload
        await apiClient.uploadDocument(activeProjectId, files[0], undefined, onProgress);
      }

      // Phase 2 — server saved files, refresh list to get new doc ids,
      // then switch to 'indexing' phase (background tasks running).
      // We fetch the doc list directly (instead of relying on the stale
      // `documents` closure variable) so we can capture the actual new
      // doc ids immediately.
      setUploadProgress((cur) => ({
        ...cur,
        phase: 'indexing',
        percent: 100,
        fileName: 'Saved. Indexing in background…',
      }));
      setSelectedStatus('all');

      // Fetch the fresh doc list right now (bypass the cache)
      let newDocs: Document[] = [];
      try {
        const fresh = await apiClient.listDocuments({
          project_id: activeProjectId,
        });
        const uploadedNames = new Set(fileArray.map((f) => f.name));
        newDocs = (fresh.data as Document[]).filter((d) => uploadedNames.has(d.name));
        // Also update the sidebar state
        setDocuments(fresh.data);
      } catch (e) {
        console.warn('Could not refresh doc list after upload:', e);
      }

      const newDocIds = newDocs.map((d) => d.id);

      setUploadProgress((cur) => ({
        ...cur,
        fileName:
          newDocIds.length === 0
            ? 'Indexing in background…'
            : `Indexing ${newDocIds.length} doc(s)…`,
        pendingDocIds: newDocIds,
      }));

      // Auto-select the first newly uploaded doc so the user sees it
      if (newDocs.length > 0) {
        setSelectedDocId(newDocs[0].id);
      }

      // Toast on upload-completion (the indexing phase continues in
      // background; the progress card stays until all are 'ready').
      showToast(
        files.length === 1
          ? `Uploaded "${files[0].name}"`
          : `Uploaded ${files.length} files`,
        'success',
        3000
      );

      // Once all pending docs reach 'ready' (or one fails), clear the
      // progress card. The polling effect below will detect this.
    } catch (error: any) {
      console.error('Failed to upload files:', error);
      setUploadProgress((cur) => ({ ...cur, phase: 'error' }));
      showToast(
        error?.response?.data?.detail
          ? `Upload failed: ${error.response.data.detail}`
          : 'Upload failed',
        'error',
        5000
      );
      setTimeout(() => {
        setUploadProgress({
          phase: 'idle',
          fileName: '',
          fileCount: 0,
          percent: 0,
          pendingDocIds: [],
        });
      }, 5000);
    } finally {
      setUploading(false);
    }
  };

  // Watch the documents list and clear the progress card once all
  // pending uploads have finished indexing (or one fails). This pairs
  // with the polling effect above.
  useEffect(() => {
    if (uploadProgress.phase !== 'indexing') return;
    if (uploadProgress.pendingDocIds.length === 0) return;

    const stillPending = uploadProgress.pendingDocIds.filter((id) => {
      const doc = documents.find((d) => d.id === id);
      return doc && doc.indexing_status !== 'ready' && doc.indexing_status !== 'failed';
    });
    const failed = uploadProgress.pendingDocIds.filter((id) => {
      const doc = documents.find((d) => d.id === id);
      return doc && doc.indexing_status === 'failed';
    });

    if (stillPending.length === 0) {
      const failedCount = failed.length;
      const successCount = uploadProgress.pendingDocIds.length - failedCount;
      setUploadProgress((cur) => ({
        ...cur,
        phase: 'done',
        fileName:
          failedCount === 0
            ? `✓ ${successCount} doc(s) ready`
            : `${successCount} ready, ${failedCount} failed`,
      }));
      if (failedCount > 0) {
        showToast(`${failedCount} doc(s) failed to index`, 'error', 5000);
      } else {
        showToast(`All ${successCount} doc(s) indexed and ready`, 'success', 3000);
      }
      setTimeout(() => {
        setUploadProgress({
          phase: 'idle',
          fileName: '',
          fileCount: 0,
          percent: 0,
          pendingDocIds: [],
        });
      }, 4000);
    }
  }, [documents, uploadProgress.phase, uploadProgress.pendingDocIds, showToast]);

  // Failsafe: if the upload phase is still going after 60s, force-clear
  // and re-fetch the doc list. This handles edge cases where:
  //   - the network dropped after the server already saved the file
  //   - the backend hung and never responded
  //   - the watcher missed a state transition
  useEffect(() => {
    if (uploadProgress.phase !== 'uploading') return;
    const t = setTimeout(() => {
      console.warn('Upload phase exceeded 60s, force-clearing progress UI');
      setUploadProgress((cur) =>
        cur.phase === 'uploading'
          ? {
              phase: 'idle',
              fileName: '',
              fileCount: 0,
              percent: 0,
              pendingDocIds: [],
            }
          : cur
      );
      setUploading(false);
      loadDocuments();
      showToast('Upload timed out — refreshing doc list', 'warning', 4000);
    }, 60_000);
    return () => clearTimeout(t);
  }, [uploadProgress.phase, showToast]);

  // Phase 9 / Step L1 — import the `graphindex_chat` agent template
  // into the langconfig DeepAgent library. One click creates a new
  // user-editable DeepAgent that uses the 4 graphindex_* native tools.
  // (Backend reference: phase9/graphindex_chat_template.py; this payload
  // is the exact .langconfig JSON that file would emit.)
  const [importingGraphindexChat, setImportingGraphindexChat] = useState(false);
  const [importedGraphindexChatId, setImportedGraphindexChatId] = useState<number | null>(null);

  // Phase 9 / Step L0 — template payload for the `graphindex_chat` agent.
  // Pass as a *parsed object* to apiClient.importDeepAgent (which stringifies
  // it inside the JSON envelope) — passing a pre-stringified string would
  // cause axios to send Content-Type: text/plain and the server would
  // reject with 422 ValidationError.
  const GRAPHINDEX_CHAT_TEMPLATE_PAYLOAD = {
    version: "1.0",
    export_type: "deepagent",
    agent: {
      name: "graphindex_chat",
      description: "LLM-semantic-routed chat with project documents (Phase 9). 4 native tools: list, search, load, multi_doc_load.",
      category: "research",
      model: "minimax-m3",
      temperature: 0.0,
      max_tokens: 8192,
      system_prompt:
        "You are **graphindex_chat** — a conversational research assistant for the user's project documents. (Phase 9 / LLM semantic routing)\n\n" +
        "You have 4 native tools (from langconfig's GraphIndex toolset, Phase 9):\n\n" +
        "  - graphindex_list_docs(project_id)         — list available doc names (cheap)\n" +
        "  - graphindex_search(query, project_id)     — find the best primary + 0-3 supporting docs\n" +
        "  - graphindex_load(context_doc_id)          — read a single doc's full text (no char cap by default)\n" +
        "  - graphindex_multi_doc_load(query, project_id)  — one-shot: route + load primary + supporting\n\n" +
        "CRITICAL — project_id:\n" +
        "  - Current project_id is an INTEGER (e.g. 1). ALWAYS pass it as a number, never as a string like \"default\".\n" +
        "  - graphindex_load and graphindex_search return context_doc_id values you can pass to graphindex_load.\n\n" +
        "Workflow:\n" +
        "  1. If unsure what docs exist, call graphindex_list_docs(project_id=1) first (cheap).\n" +
        "  2. To answer a question, prefer graphindex_multi_doc_load(query=<q>, project_id=1) — it does routing + loading in one call.\n" +
        "  3. For long docs, you can call graphindex_load(context_doc_id) WITHOUT taking the first-turn default cap — the backend now returns the FULL document (up to 10M chars safety cap, effectively no limit for normal docs).\n" +
        "  4. Synthesize the final answer from the loaded context. Cite the document name and page when relevant.\n\n" +
        "If the user asks something unrelated to the project documents, say so politely.\n" +
        "Don't make up document names — always check the catalog. Output language matches the query.",
      tools: [
        "graphindex_list_docs",
        "graphindex_search",
        "graphindex_load",
        "graphindex_multi_doc_load",
      ],
      mcp_tools: [],
      cli_tools: [],
      middleware: [
        { type: "todo_list", enabled: true, config: {} },
        { type: "filesystem", enabled: true, config: {} },
      ],
      subagents: [],
      backend: { type: "state", config: {} },
      guardrails: {},
      // Opt the chat into the Phase 9 single-agent path. When the
      // backend sees this flag at /api/chat/message/stream, it
      // routes through phase9.graphindex_chat_agent.stream_graphindex_chat_events
      // (the proven 5-tool + progressive-disclosure deepagent) instead
      // of building its own agent via DeepAgentFactory.
      use_phase9_graphindex: true,
    },
  };

  const handleImportGraphindexChat = async () => {
    if (importingGraphindexChat) return;
    setImportingGraphindexChat(true);
    console.log('[Phase 9 / L1] Starting graphindex_chat import...');
    try {
      const response = await apiClient.importDeepAgent(GRAPHINDEX_CHAT_TEMPLATE_PAYLOAD);
      const id = response?.data?.id;
      setImportedGraphindexChatId(id ?? null);
      console.log(
        `[Phase 9 / L1] Imported graphindex_chat agent (id=${id}). ` +
        `View at: GET /api/deepagents/${id}`
      );
    } catch (error: any) {
      // Comprehensive error reporting — handle BOTH axios-style errors
      // (have .response.status, .response.data.detail) and native
      // fetch errors (just .message).
      const status = error?.response?.status;
      const data = error?.response?.data;
      const message = error?.message || 'unknown error';
      console.error('[Phase 9 / L1] Import failed:', {
        status,
        data,
        message,
        full: error,
      });
      const detail = data?.detail || '';
      if (status === 409 || String(detail).toLowerCase().includes('exists')) {
        setImportedGraphindexChatId(-1);
        console.log('[Phase 9 / L1] graphindex_chat agent already exists in library.');
      } else {
        // Build a human-readable error message from whichever fields we have.
        let userMsg = `Failed to import graphindex_chat agent.`;
        if (status) userMsg += `\n\nHTTP ${status}`;
        if (data?.detail) {
          userMsg += `: ${typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)}`;
        } else if (message && !message.includes('Network Error')) {
          userMsg += `\n\n${message}`;
        } else if (message) {
          userMsg += `\n\nNetwork error — please ensure the backend is running on port 8765.`;
        }
        alert(userMsg);
      }
    } finally {
      // ALWAYS reset the loading state so the button doesn't get stuck
      console.log('[Phase 9 / L1] Import flow complete, resetting state.');
      setImportingGraphindexChat(false);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const files = e.dataTransfer.files;
    handleFileSelect(files);
  };

  const handleDelete = async (id: number) => {
    if (!confirm('Are you sure you want to delete this document?')) return;

    try {
      await apiClient.deleteDocument(id);
      await loadDocuments();
    } catch (error) {
      console.error('Failed to delete document:', error);
      alert('Failed to delete document');
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim() || !activeProjectId) return;
    if ((searchMode === 'vector' || compareMode) && !selectedDocId) {
      alert('Please select a ready document first for Vector RAG search.');
      return;
    }

    try {
      setSearching(true);

      if (compareMode) {

        const response1 = await apiClient.searchDocuments({
          query: searchQuery,
          project_id: activeProjectId,
          top_k: 10,
          use_hyde: useHyDE,
          search_mode: 'graphindex',
        });
        const data1 = response1 as any;
        if (data1.search_mode === 'graphindex') {
          setSearchResults([]);
          setGraphIndexDocs(data1.documents || []);
        } else {
          setGraphIndexDocs([]);
          setSearchResults(data1.results || []);
        }

        const response2 = await apiClient.searchDocuments({
          query: searchQuery,
          project_id: activeProjectId,
          top_k: 10,
          use_hyde: useHyDE,
          search_mode: 'vector',
        });
        const data2 = response2 as any;
        if (data2.search_mode === 'graphindex') {
          setComparisonResults([]);
        } else {
          const vectorResults = (data2.results || []).filter((result: SearchResult) =>
            selectedDocId ? result.document_id === selectedDocId : true
          );
          setComparisonResults(vectorResults);
        }
        if (data2.metrics) setComparisonMetrics(data2.metrics);

      } else {
        const response = await apiClient.searchDocuments({
          query: searchQuery,
          project_id: activeProjectId,
          top_k: 10,
          use_hyde: useHyDE,
          search_mode: searchMode,
        });
        const data = response as any;
        if (data.search_mode === 'graphindex') {
          setSearchResults([]);
          setGraphIndexDocs(data.documents || []);
          setSearchMetrics(null);
        } else {
          const vectorResults = (data.results || []).filter((result: SearchResult) =>
            selectedDocId ? result.document_id === selectedDocId : true
          );
          setGraphIndexDocs([]);
          setSearchResults(vectorResults);
          setSearchMetrics(data.metrics || null);
        }
        setComparisonMetrics(null);
        setComparisonResults([]);
      }

      setShowSearchResults(true);
    } catch (error) {
      console.error('Search failed:', error);
      alert('Search failed. Make sure your project is indexed.');
    } finally {
      setSearching(false);
    }
  };

  const handleGraphIndexAnswer = async (doc: any) => {
    if (!activeProjectId || !searchQuery.trim()) return;
    try {
      setAnswerLoading(true);
      setAnswerResult(null);
      const result = await apiClient.pageIndexAnswer({
        query: searchQuery,
        project_id: activeProjectId,
        context_doc_id: doc.context_doc_id,
      });
      setAnswerResult(result);
    } catch (error) {
      console.error('GraphIndex answer failed:', error);
      alert('Failed to get answer from document.');
    } finally {
      setAnswerLoading(false);
    }
  };

  const handleRerunFromHistory = (query: string, hyde: boolean, toon: boolean) => {
    setSearchQuery(query);
    setUseHyDE(hyde);
    setUseTOON(toon);
    setTimeout(() => handleSearch(), 100);
  };

  const clearSearch = () => {
    setSearchQuery('');
    setSearchResults([]);
    setShowSearchResults(false);
    setSearchMetrics(null);
    setComparisonMetrics(null);
    setComparisonResults([]);
    setExpandedChunks(new Set());
  };

  const toggleChunkExpansion = (index: number) => {
    const newExpanded = new Set(expandedChunks);
    if (newExpanded.has(index)) {
      newExpanded.delete(index);
    } else {
      newExpanded.add(index);
    }
    setExpandedChunks(newExpanded);
  };

  const totalDocuments = documents.length;
  const totalChunks = documents.reduce((sum, doc) => sum + (doc.chunk_count || 0), 0);
  const totalSize = documents.reduce((sum, doc) => sum + (doc.size || 0), 0);
  const readyCount = documents.filter(d => d.indexing_status === 'ready').length;
  const selectedDoc = documents.find(doc => doc.id === selectedDocId) ?? null;
  const readyDocuments = documents.filter(doc => doc.indexing_status === 'ready');
  const notReadyDocuments = documents.filter(doc => doc.indexing_status !== 'ready');

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
      <div className="bg-white dark:bg-panel-dark border-b border-gray-200 dark:border-border-dark p-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold mb-1" style={{ color: 'var(--color-text-primary)' }}>
              {t('kb_title')}
            </h1>
            <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
              {t('kb_title_desc')}
            </p>
          </div>
          {/* Right-side: overall knowledge metrics overview */}
          <div className="flex items-center gap-2 flex-shrink-0">
            <MetricPill
              icon={<FileText className="w-3.5 h-3.5" />}
              label="Docs"
              value={totalDocuments}
              color="#3b82f6"
            />
            <MetricPill
              icon={<Check className="w-3.5 h-3.5" />}
              label="Indexed"
              value={`${readyCount}/${totalDocuments}`}
              color="#f59e0b"
            />
            <MetricPill
              icon={<Database className="w-3.5 h-3.5" />}
              label="Chunks"
              value={totalChunks}
              color="#8b5cf6"
            />
            <MetricPill
              icon={<Filter className="w-3.5 h-3.5" />}
              label="Storage"
              value={formatFileSize(totalSize)}
              color="#10b981"
            />
            {/* Chat-agent pill — shows which agent the right-column
                chat panel is wired to. The pill is pushed up from
                DocChatPanel via onAgentInfoChange. Sits next to the
                search button so the user can see both KB-wide actions
                (search + active chat agent) in the same group. Hidden
                until the agent is resolved (null while loading). */}
            {chatAgentInfo && (
              <div
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border bg-white dark:bg-panel-dark flex-shrink-0"
                style={{ borderColor: 'var(--color-border-dark, #e5e7eb)' }}
                title={chatAgentInfo.description || chatAgentInfo.name}
                data-testid="kb-chat-agent-pill"
              >
                <Sparkles className="w-3.5 h-3.5 flex-shrink-0" style={{ color: '#a855f7' }} />
                <div className="flex flex-col leading-tight min-w-0">
                  <span
                    className="text-[9px] uppercase tracking-wide"
                    style={{ color: 'var(--color-text-muted)' }}
                  >
                    Chat Agent
                  </span>
                  <span
                    className="text-[11px] font-semibold truncate max-w-[140px]"
                    style={{ color: 'var(--color-text-primary)' }}
                  >
                    {chatAgentInfo.name}
                  </span>
                </div>
              </div>
            )}

            {/* Search button — opens the pop-out SearchModal.
                Replaces the old bottom-anchored search panel so the
                doc viewer can take the full height of the row. */}
            <button
              onClick={() => setSearchModalOpen(true)}
              data-testid="kb-open-search-modal"
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-gray-200 dark:border-border-dark hover:bg-gray-50 dark:hover:bg-white/5 transition-all text-[11px] font-medium"
              style={{ color: 'var(--color-text-primary)' }}
              title={t('kb_search_modal_title')}
            >
              <Search className="w-3.5 h-3.5" />
              <span>{t('kb_search')}</span>
            </button>

            {/* Upload buttons — moved from right column to title bar
                to free up vertical space for the chat column. */}
            <label
              className={`flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-primary text-white transition-all text-[11px] font-medium ${uploading ? 'opacity-50 cursor-not-allowed' : 'hover:opacity-90 cursor-pointer'}`}
              title={t('kb_upload_browse')}
            >
              <Upload className="w-3.5 h-3.5" />
              <span>{t('kb_browse')}</span>
              <input type="file" multiple accept={SUPPORTED_FILES}
                onChange={(e) => { handleFileSelect(e.target.files); }}
                className="hidden" disabled={uploading} />
            </label>
            <label
              className={`flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-purple-600 text-white transition-all text-[11px] font-medium ${uploading ? 'opacity-50 cursor-not-allowed' : 'hover:opacity-90 cursor-pointer'}`}
              title={t('kb_upload_folder')}
            >
              <Database className="w-3.5 h-3.5" />
              <span>{t('kb_select_folder')}</span>
              <input type="file" // @ts-ignore - webkitdirectory is not in TS types
                webkitdirectory="" directory="" multiple
                onChange={(e) => { handleFileSelect(e.target.files); }}
                className="hidden" disabled={uploading} />
            </label>
            <button
              onClick={() => loadDocuments()}
              className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-white/10 transition-all ml-1"
              style={{ color: 'var(--color-text-primary)' }}
              title={t('kb_refresh')}
            >
              <RefreshCw className="w-3.5 h-3.5" style={{ color: 'var(--color-primary)' }} />
            </button>
          </div>
        </div>
      </div>

      {/* Upload progress — slim banner under the title bar, visible only
          during uploading/indexing/error phases. Does not steal space from
          the chat column. */}
      {uploadProgress.phase !== 'idle' && (
        <UploadProgressBanner
          phase={uploadProgress.phase}
          fileName={uploadProgress.fileName}
          fileCount={uploadProgress.fileCount}
          percent={uploadProgress.percent}
          pendingDocIds={uploadProgress.pendingDocIds}
          documents={documents}
          onClear={() => {
            setUploadProgress({
              phase: 'idle',
              fileName: '',
              fileCount: 0,
              percent: 0,
              pendingDocIds: [],
            });
            setUploading(false);
            loadDocuments();
          }}
        />
      )}

      <div className="flex-1 overflow-hidden p-4">
        <div className="flex h-full gap-0 kb-cols">
          <div
            className="flex-shrink-0 bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg p-3 overflow-hidden flex flex-col"
            style={{ width: leftWidth }}
          >
            <div className="flex items-center justify-between mb-3">
              <div>
                <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-primary)' }}>{t('kb_documents')}</h3>
                <p className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                  {t('kb_indexed')}: {readyCount} / {totalDocuments}
                </p>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-gray-100 dark:bg-white/10" style={{ color: 'var(--color-text-muted)' }}>
                  {documents.length}
                </span>
                <select value={selectedStatus} onChange={(e) => setSelectedStatus(e.target.value)}
                  className="px-1 py-0.5 border border-gray-200 dark:border-border-dark rounded text-[10px] focus:outline-none focus:ring-1 focus:ring-primary"
                  style={{ backgroundColor: 'var(--color-input-background)', color: 'var(--color-text-primary)' }}>
                  <option value="all">{t('kb_all')}</option>
                  <option value="ready">{t('kb_indexed')}</option>
                  <option value="indexing">{t('kb_indexing')}</option>
                  <option value="not_indexed">{t('kb_pending')}</option>
                  <option value="failed">{t('kb_failed')}</option>
                </select>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto space-y-4">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <h4 className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>
                      {t('kb_indexed')}
                    </h4>
                    {isScopeActive && (
                      <span
                        className="text-[10px] px-1.5 py-0.5 rounded font-medium bg-indigo-100 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300"
                        title={`${inScopeCount} of ${readyDocuments.length} docs are in scope for the chat`}
                      >
                        {inScopeCount} in scope
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1">
                    {isScopeActive && (
                      <button
                        onClick={clearScope}
                        className="text-[10px] px-1.5 py-0.5 rounded hover:bg-gray-100 dark:hover:bg-white/5"
                        style={{ color: 'var(--color-text-muted)' }}
                        title="Clear scope (chat will consider all docs)"
                      >
                        Clear
                      </button>
                    )}
                    {readyDocuments.length > 0 && inScopeCount < readyDocuments.length && (
                      <button
                        onClick={selectAllScope}
                        className="text-[10px] px-1.5 py-0.5 rounded hover:bg-gray-100 dark:hover:bg-white/5"
                        style={{ color: 'var(--color-text-muted)' }}
                        title="Add all ready docs to scope"
                      >
                        Select all
                      </button>
                    )}
                  </div>
                </div>
                <div className="space-y-1.5">
                  {readyDocuments.map(doc => {
                    const inScope = scopeDocIds.has(doc.id);
                    return (
                    <button
                      key={doc.id}
                      data-doc-card-id={doc.id}
                      onClick={() => setSelectedDocId(doc.id)}
                      className={`w-full text-left rounded-lg border px-2.5 py-2 transition-all ${
                        selectedDocId === doc.id
                          ? 'border-amber-300 dark:border-amber-500/40 bg-amber-50 dark:bg-amber-500/10'
                          : inScope
                            ? 'border-indigo-300 dark:border-indigo-500/40 bg-indigo-50/40 dark:bg-indigo-500/5'
                            : 'border-gray-200 dark:border-border-dark hover:bg-gray-50 dark:hover:bg-white/5'
                      } ${
                        highlightedDocId === doc.id
                          ? 'ring-2 ring-purple-500 shadow-lg shadow-purple-500/30'
                          : ''
                      }`}
                    >
                      <div className="flex items-start gap-2">
                        <div className={`mt-0.5 h-2.5 w-2.5 rounded-full flex-shrink-0 ${
                          doc.neo4j_only ? 'bg-purple-500' : 'bg-amber-500'
                        }`} title={doc.neo4j_only ? 'Indexed in Neo4j only (no Postgres context_documents row)' : 'Indexed in Postgres context_documents'} />
                        <div className="min-w-0 flex-1">
                          <div className="text-xs font-medium truncate" style={{ color: 'var(--color-text-primary)' }}>
                            {doc.name}
                          </div>
                          <div className="text-[10px] mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
                            {doc.neo4j_only
                              ? `Neo4j-only · ${doc.chunk_count || 0} chunks`
                              : `${formatFileSize(doc.size)} · ${doc.chunk_count || 0} chunks`}
                          </div>
                        </div>
                        {/* Scope checkbox — toggles chat scope membership.
                            Stop propagation so clicking the checkbox doesn't also select the doc. */}
                        <label
                          className="flex items-center p-0.5 rounded hover:bg-indigo-50 dark:hover:bg-indigo-500/10"
                          title={inScope ? 'Remove from chat scope' : 'Add to chat scope'}
                          onClick={(e) => e.stopPropagation()}
                        >
                          <input
                            type="checkbox"
                            checked={inScope}
                            onChange={() => toggleScopeDoc(doc.id)}
                            className="h-3.5 w-3.5 cursor-pointer accent-indigo-600"
                            aria-label={`Toggle ${doc.name} in chat scope`}
                          />
                        </label>
                        {!doc.neo4j_only && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDelete(doc.id);
                            }}
                            className="p-1 rounded hover:bg-red-50 dark:hover:bg-red-500/10"
                            style={{ color: 'var(--color-text-muted)' }}
                            title={t('kb_delete')}
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        )}
                      </div>
                    </button>
                    );
                  })}
                  {readyDocuments.length === 0 && (
                    <p className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>{t('kb_no_ready_docs')}</p>
                  )}
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>
                    {t('kb_not_ready')}
                  </h4>
                  <span className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>{notReadyDocuments.length}</span>
                </div>
                <div className="space-y-1.5">
                  {notReadyDocuments.map(doc => (
                    <div
                      key={doc.id}
                      className="rounded-lg border border-gray-200 dark:border-border-dark px-2.5 py-2"
                    >
                      <div className="flex items-start gap-2">
                        <div className={`mt-0.5 h-2.5 w-2.5 rounded-full flex-shrink-0 ${
                          doc.indexing_status === 'indexing'
                            ? 'bg-blue-500'
                            : doc.indexing_status === 'failed'
                              ? 'bg-red-500'
                              : 'bg-gray-400'
                        }`} />
                        <div className="min-w-0 flex-1">
                          <div className="text-xs font-medium truncate" style={{ color: 'var(--color-text-primary)' }}>
                            {doc.name}
                          </div>
                          <div className="text-[10px] mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
                            {getStatusDisplay(doc.indexing_status)} · {formatFileSize(doc.size)}
                          </div>
                        </div>
                        <button
                          onClick={() => handleDelete(doc.id)}
                          className="p-1 rounded hover:bg-red-50 dark:hover:bg-red-500/10"
                          style={{ color: 'var(--color-text-muted)' }}
                          title={t('kb_delete')}
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    </div>
                  ))}
                  {notReadyDocuments.length === 0 && (
                    <p className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>All documents are ready</p>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Left divider — drag to resize the doc cards column */}
          <div
            onMouseDown={startDrag('left')}
            className="w-1.5 flex-shrink-0 cursor-col-resize hover:bg-purple-200/40 dark:hover:bg-purple-500/20 transition-colors"
            title="Drag to resize"
          />

          <div className="min-w-0 flex-1 flex flex-col gap-3 overflow-hidden">
            {/* Document Preview Panel — shows the actual file (PDF rendered by
                the browser's built-in PDF viewer, text/markdown/code in a
                <pre>). Backed by GET /api/rag/documents/{id}/file. */}
            {selectedDocId && (
              // Full-size: takes all remaining vertical space in the center
              // column (`flex-1` + `min-h-0` lets it shrink/grow inside the
              // parent flex column). No more fixed vh cap, so the doc viewer
              // uses every available pixel between the title bar and the
              // bottom of the column.
              <div className="flex-1 min-h-0 bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg overflow-hidden flex flex-col mb-3">
                {previewLoading ? (
                  <div className="flex items-center justify-center gap-2 text-xs p-4" style={{ color: 'var(--color-text-muted)' }}>
                    <Loader className="w-3 h-3 animate-spin" />
                    Loading preview...
                  </div>
                ) : selectedDoc ? (
                  <>
                    <div className="flex items-center justify-between px-3 py-2 border-b border-gray-200 dark:border-border-dark flex-shrink-0">
                      <div className="flex items-center gap-2">
                        <FileText className="w-3.5 h-3.5" style={{ color: 'var(--color-primary)' }} />
                        <span className="text-xs font-semibold truncate max-w-[300px]" style={{ color: 'var(--color-text-primary)' }}>
                          {selectedDoc.name}
                        </span>
                        <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-gray-100 dark:bg-white/10" style={{ color: 'var(--color-text-muted)' }}>
                          {selectedDoc.document_type || 'pdf'} · {selectedDoc.chunk_count ?? 0} chunks
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-[9px]" style={{ color: 'var(--color-text-muted)' }}>
                          {(selectedDoc.size ?? 0).toLocaleString()} bytes
                        </span>
                        <a
                          href={`/api/rag/documents/${selectedDocId}/file`}
                          target="_blank"
                          rel="noreferrer"
                          className="text-[9px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-white/10 hover:opacity-80"
                          style={{ color: 'var(--color-text-primary)' }}
                          title="Open in new tab"
                        >
                          Open ↗
                        </a>
                      </div>
                    </div>
                    {(() => {
                      // Delegate all rendering decisions to DocumentViewer.
                      // It picks PDF / image / MD / CSV / DOCX / PPTX / XLSX /
                      // code based on extension, fetches extracted text from
                      // /api/rag/documents/{id}/content when needed.
                      // For Neo4j-only docs (id < 0), use the file-by-name
                      // endpoint at /api/graphindex/file instead.
                      //
                      // Wrapper div: `flex-1 min-h-0` lets the viewer fill
                      // the remaining height below the file header, and
                      // `overflow-hidden` clips the canvas overflow so the
                      // viewer's own scroll container handles it. Without
                      // `min-h-0` the child couldn't shrink below its
                      // intrinsic canvas height and scroll wouldn't work.
                      const isNeo4jOnly = !!selectedDoc?.neo4j_only;
                      return (
                        <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
                          <DocumentViewer
                            key={selectedDocId}
                            documentId={selectedDocId}
                            documentName={selectedDoc.name}
                            documentType={selectedDoc.document_type}
                            projectId={isNeo4jOnly ? activeProjectId : undefined}
                          />
                        </div>
                      );
                    })()}
                  </>
                ) : null}
              </div>
            )}

            {/* Search Box REMOVED — moved to a pop-out modal triggered from
                the title bar (top right). The bottom-anchored search panel
                used to take ~15% of the doc viewer's vertical space; with
                it gone, the doc viewer has full size. The state, handlers,
                and translation keys are still in this file (re-used by the
                SearchModal). */}
          </div>

          {/* Right divider — drag to resize the chat panel */}
          <div
            onMouseDown={startDrag('right')}
            className="w-1.5 flex-shrink-0 cursor-col-resize hover:bg-purple-200/40 dark:hover:bg-purple-500/20 transition-colors"
            title="Drag to resize"
          />

          {/* Right column: chat panel powered by graphindex_chat agent */}
          <div
            className="flex-shrink-0 overflow-hidden flex flex-col"
            style={{ width: rightWidth }}
          >
            <DocChatPanel
              projectId={activeProjectId}
              scope={isScopeActive
                ? documents
                    .filter((d) => scopeDocIds.has(d.id))
                    .map((d) => d.name)
                : null}
              onScopeChange={setScopeDocIds}
              onAgentInfoChange={setChatAgentInfo}
              onDocSelected={(docName) => {
                // When the chat picks a doc, find it in our list and
                // select + scroll-to + flash-highlight it. This is the
                // "auto-focus" UX — the user's eyes are on the chat
                // and we want the viewer to follow the LLM.
                const match = documents.find(d => d.name === docName);
                if (match) {
                  setSelectedDocId(match.id);
                  setHighlightedDocId(match.id);
                  // Scroll the card into view (it's a button in the left column)
                  setTimeout(() => {
                    const el = document.querySelector(`[data-doc-card-id="${match.id}"]`);
                    el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                  }, 50);
                  // Clear highlight after 2.5s
                  setTimeout(() => setHighlightedDocId(null), 2500);
                }
              }}
            />
          </div>
        </div>
      </div>

      {/* Pop-out search modal. Triggered from the "Search" button in the
          title bar (top right). Hosts the full search UI that used to be
          anchored at the bottom of the doc viewer — moving it to a modal
          gives the doc viewer full vertical real estate. The modal uses
          `fixed` positioning so it overlays the page regardless of where
          it sits in the tree. */}
      <SearchModal
        open={searchModalOpen}
        onClose={() => setSearchModalOpen(false)}
        searchQuery={searchQuery}
        onSearchQueryChange={setSearchQuery}
        searching={searching}
        onSearch={handleSearch}
        searchMode={searchMode}
        compareMode={compareMode}
        onCompareModeChange={setCompareMode}
        useHyDE={useHyDE}
        onUseHyDEChange={setUseHyDE}
        useTOON={useTOON}
        onUseTOONChange={setUseTOON}
        selectedDoc={selectedDoc}
        showSearchResults={showSearchResults}
        pageIndexDocs={pageIndexDocs}
        searchResults={searchResults}
        onClearSearch={clearSearch}
        onGraphIndexAnswer={handleGraphIndexAnswer}
        answerLoading={answerLoading}
        answerResult={answerResult}
        expandedChunks={expandedChunks}
        onToggleChunkExpansion={toggleChunkExpansion}
        t={t}
      />
    </div>
  );
}

/**
 * Compact metric pill used in the title-bar overview.
 * Shows: [icon] [label] [value] with a color-coded accent.
 */
function MetricPill({
  icon,
  label,
  value,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | string;
  color: string;
}) {
  return (
    <div
      className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border bg-white dark:bg-panel-dark"
      style={{ borderColor: 'var(--color-border-dark, #e5e7eb)' }}
      title={`${label}: ${value}`}
    >
      <span style={{ color }}>{icon}</span>
      <div className="flex flex-col leading-tight">
        <span className="text-[9px] uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>
          {label}
        </span>
        <span className="text-[12px] font-semibold tabular-nums" style={{ color: 'var(--color-text-primary)' }}>
          {value}
        </span>
      </div>
    </div>
  );
}

/**
 * Slim upload-progress banner shown under the title bar. Designed to
 * take minimal vertical space (single line + thin progress bar) so the
 * chat column gets the full height of the panel.
 */
function UploadProgressBanner({
  phase,
  fileName,
  fileCount,
  percent,
  pendingDocIds,
  documents,
  onClear,
}: {
  phase: 'idle' | 'uploading' | 'indexing' | 'done' | 'error';
  fileName: string;
  fileCount: number;
  percent: number;
  pendingDocIds: number[];
  documents: Array<{ id: number; indexing_status?: string }>;
  onClear: () => void;
}) {
  const readyCount = pendingDocIds.filter(id => {
    const doc = documents.find(d => d.id === id);
    return doc && doc.indexing_status === 'ready';
  }).length;
  const failedCount = pendingDocIds.filter(id => {
    const doc = documents.find(d => d.id === id);
    return doc && doc.indexing_status === 'failed';
  }).length;
  const total = pendingDocIds.length;
  const completed = readyCount + failedCount;
  const segmentPct = total > 0 ? Math.round((completed / total) * 100) : 0;

  let barColor = 'bg-primary';
  let iconColor = 'text-primary';
  if (phase === 'indexing') {
    barColor = 'bg-blue-500';
    iconColor = 'text-blue-500';
  } else if (phase === 'done') {
    barColor = 'bg-green-500';
    iconColor = 'text-green-500';
  } else if (phase === 'error') {
    barColor = 'bg-red-500';
    iconColor = 'text-red-500';
  }

  return (
    <div
      className="flex items-center gap-3 px-6 py-2 border-b border-gray-200 dark:border-border-dark"
      style={{
        backgroundColor:
          phase === 'error' ? 'rgba(239, 68, 68, 0.04)'
          : phase === 'done' ? 'rgba(34, 197, 94, 0.04)'
          : 'rgba(59, 130, 246, 0.04)',
      }}
    >
      <Loader className={`w-3.5 h-3.5 ${iconColor} ${phase === 'uploading' || phase === 'indexing' ? 'animate-spin' : ''}`} />
      <p className="text-[11px] truncate flex-1 min-w-0" style={{ color: 'var(--color-text-primary)' }}>
        {fileName}
      </p>
      <span className="text-[10px] font-semibold tabular-nums" style={{ color: 'var(--color-text-muted)' }}>
        {phase === 'uploading' && `${percent}%`}
        {phase === 'indexing' && (total > 0 ? `${completed}/${total} ready` : 'indexing…')}
        {phase === 'done' && '✓ done'}
        {phase === 'error' && '✗ failed'}
      </span>
      <div className="w-32 h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden flex-shrink-0">
        <div
          className={`h-full ${barColor} transition-all duration-200 rounded-full`}
          style={{
            width:
              phase === 'uploading' ? `${percent}%`
              : phase === 'indexing' && total > 0 ? `${segmentPct}%`
              : '100%',
          }}
        />
      </div>
      <button
        onClick={onClear}
        className="text-[10px] underline hover:opacity-70"
        style={{ color: 'var(--color-text-muted)' }}
        title="Clear the progress banner"
      >
        clear
      </button>
    </div>
  );
}
