/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload, FileText, Trash2, Search, Database, Filter, Loader, RefreshCw, Sparkles, Check } from 'lucide-react';
import apiClient from "../../../lib/api-client";
import { useProject } from "../../../contexts/ProjectContext";
import SearchMetricsDisplay from './SearchMetricsDisplay';
import SearchHistoryLog from './SearchHistoryLog';
import StorageMetrics from '../../../components/ui/StorageMetrics';

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
  const [uploading, setUploading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedStatus, setSelectedStatus] = useState<string>('all');
  const [selectedDocId, setSelectedDocId] = useState<number | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [showSearchResults, setShowSearchResults] = useState(false);
  const [useHyDE, setUseHyDE] = useState(false);
  const [useTOON, setUseTOON] = useState(false);
  const [searchMode, setSearchMode] = useState<'vector' | 'graphindex'>('graphindex');
  const [compareMode, setCompareMode] = useState(false);
  const [searchMetrics, setSearchMetrics] = useState<SearchMetrics | null>(null);
  const [comparisonMetrics, setComparisonMetrics] = useState<SearchMetrics | null>(null);
  const [comparisonResults, setComparisonResults] = useState<SearchResult[]>([]);
  const [expandedChunks, setExpandedChunks] = useState<Set<number>>(new Set());
  const [pageIndexDocs, setGraphIndexDocs] = useState<any[]>([]);
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
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<FileList | null>(null);
  const [uploadName, setUploadName] = useState('');
  const [uploadDescription, setUploadDescription] = useState('');
  const [uploadTags, setUploadTags] = useState('');
  const [extractArchives, setExtractArchives] = useState(true);
  const [isFolderUpload, setIsFolderUpload] = useState(false);

  const { activeProjectId } = useProject();
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

  // Load preview when a document is selected
  useEffect(() => {
    if (!selectedDocId || !activeProjectId) {
      setPreviewData(null);
      return;
    }
    setPreviewLoading(true);
    setPreviewData(null);
    apiClient.previewDocument(selectedDocId, 2000)
      .then(data => setPreviewData(data))
      .catch(() => setPreviewData(null))
      .finally(() => setPreviewLoading(false));
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
      const response = await apiClient.listDocuments({ ...params, signal });
      setDocuments(response.data);
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

  const handleFileSelect = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    if (!activeProjectId) {
      alert('Please select a project first');
      return;
    }
    setUploadFiles(files);
    // Set default name from first file if only one file
    if (files.length === 1) {
      setUploadName(files[0].name);
    } else {
      setUploadName('');
    }
    setShowUploadModal(true);
  };

  const handleFileUpload = async () => {
    if (!uploadFiles || !activeProjectId) return;

    setUploading(true);
    setShowUploadModal(false);
    try {
      const fileArray = Array.from(uploadFiles);
      const hasArchives = fileArray.some(f => {
        const ext = f.name.split('.').pop()?.toLowerCase();
        return ['zip', 'tar', 'gz', 'tgz', 'rar', '7z'].includes(ext || '');
      });

      // Use bulk upload if multiple files or archives with extraction enabled
      if (fileArray.length > 1 || (hasArchives && extractArchives)) {
        const metadata: any = {};
        if (uploadName) metadata.name = uploadName;
        if (uploadDescription) metadata.description = uploadDescription;
        if (uploadTags) metadata.tags = uploadTags.split(',').map(t => t.trim());

        await apiClient.uploadDocumentsBulk(
          activeProjectId,
          fileArray,
          extractArchives,
          Object.keys(metadata).length > 0 ? metadata : undefined
        );
      } else {
        // Single file upload
        for (let i = 0; i < uploadFiles.length; i++) {
          const file = uploadFiles[i];
          const metadata: any = {};
          if (uploadName) metadata.name = uploadName;
          if (uploadDescription) metadata.description = uploadDescription;
          if (uploadTags) metadata.tags = uploadTags.split(',').map(t => t.trim());
          await apiClient.uploadDocument(activeProjectId, file, Object.keys(metadata).length > 0 ? metadata : undefined);
        }
      }

      setSelectedStatus('all');
      await loadDocuments(undefined, 'all');
      setUploadName('');
      setUploadDescription('');
      setUploadTags('');
      setUploadFiles(null);
      setExtractArchives(true);
      setIsFolderUpload(false);
    } catch (error) {
      console.error('Failed to upload files:', error);
      alert('Failed to upload some files. Check console for details.');
    } finally {
      setUploading(false);
    }
  };

  // Phase 9 / Step L1 — import the `graphindex_chat` agent template
  // into the langconfig DeepAgent library. One click creates a new
  // user-editable DeepAgent that uses the 4 graphindex_* native tools.
  // (Backend reference: phase9/graphindex_chat_template.py; this payload
  // is the exact .langconfig JSON that file would emit.)
  const [importingGraphindexChat, setImportingGraphindexChat] = useState(false);
  const [importedGraphindexChatId, setImportedGraphindexChatId] = useState<number | null>(null);

  const GRAPHINDEX_CHAT_TEMPLATE_PAYLOAD = JSON.stringify({
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
        "  - graphindex_list_docs(project_id)         — list available doc names\n" +
        "  - graphindex_search(query, project_id)     — find the best primary + 0-3 supporting docs\n" +
        "  - graphindex_load(context_doc_id)          — read a single doc's full text\n" +
        "  - graphindex_multi_doc_load(query, project_id)  — one-shot: route + load primary + supporting\n\n" +
        "Workflow:\n" +
        "  1. If unsure what docs exist, call graphindex_list_docs first (cheap).\n" +
        "  2. To answer a question, prefer graphindex_multi_doc_load — it does routing + loading in one call.\n" +
        "  3. Synthesize the final answer from the loaded context. Cite the document name and page when relevant.\n\n" +
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
    },
  });

  const handleImportGraphindexChat = async () => {
    if (importingGraphindexChat) return;
    setImportingGraphindexChat(true);
    try {
      const response = await apiClient.importDeepAgent(GRAPHINDEX_CHAT_TEMPLATE_PAYLOAD);
      const id = response?.data?.id;
      setImportedGraphindexChatId(id ?? null);
      console.log(
        `[Phase 9 / L1] Imported graphindex_chat agent (id=${id}). ` +
        `View at: GET /api/deepagents/${id}`
      );
    } catch (error: any) {
      console.error('Failed to import graphindex_chat agent:', error);
      // 409 / "already exists" — silently treat as success; the user
      // can find the existing one in the agent library.
      const detail = error?.response?.data?.detail || '';
      if (String(detail).toLowerCase().includes('exists') || error?.response?.status === 409) {
        setImportedGraphindexChatId(-1);
        console.log('[Phase 9 / L1] graphindex_chat agent already exists in library.');
      } else {
        alert(`Failed to import graphindex_chat agent: ${detail || 'unknown error'}`);
      }
    } finally {
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
      {/* Upload Metadata Modal */}
      {showUploadModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowUploadModal(false)}>
          <div className="bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg p-6 max-w-md w-full m-4" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold mb-4" style={{ color: 'var(--color-text-primary)' }}>
              Upload {uploadFiles?.length} Document{uploadFiles?.length !== 1 ? 's' : ''}
            </h3>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1.5" style={{ color: 'var(--color-text-primary)' }}>
                  Document Name
                </label>
                <input
                  type="text"
                  value={uploadName}
                  onChange={(e) => setUploadName(e.target.value)}
                  placeholder="Enter document name..."
                  className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-border-dark rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
                  style={{
                    backgroundColor: 'var(--color-input-background)',
                    color: 'var(--color-text-primary)'
                  }}
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1.5" style={{ color: 'var(--color-text-primary)' }}>
                  Description (Optional)
                </label>
                <textarea
                  value={uploadDescription}
                  onChange={(e) => setUploadDescription(e.target.value)}
                  placeholder="Brief description of this document..."
                  rows={3}
                  className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-border-dark rounded-lg focus:outline-none focus:ring-2 focus:ring-primary resize-none"
                  style={{
                    backgroundColor: 'var(--color-input-background)',
                    color: 'var(--color-text-primary)'
                  }}
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1.5" style={{ color: 'var(--color-text-primary)' }}>
                  Tags (Optional)
                </label>
                <input
                  type="text"
                  value={uploadTags}
                  onChange={(e) => setUploadTags(e.target.value)}
                  placeholder="tag1, tag2, tag3"
                  className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-border-dark rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
                  style={{
                    backgroundColor: 'var(--color-input-background)',
                    color: 'var(--color-text-primary)'
                  }}
                />
                <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                  Separate tags with commas
                </p>
              </div>

              {/* Archive Extraction Option */}
              {uploadFiles && Array.from(uploadFiles).some(f => {
                const ext = f.name.split('.').pop()?.toLowerCase();
                return ['zip', 'tar', 'gz', 'tgz', 'rar', '7z'].includes(ext || '');
              }) && (
                <div className="flex items-center gap-2 p-3 bg-blue-50 dark:bg-blue-500/10 rounded-lg border border-blue-200 dark:border-blue-500/30">
                  <input
                    type="checkbox"
                    id="extract-archives"
                    checked={extractArchives}
                    onChange={(e) => setExtractArchives(e.target.checked)}
                    className="w-4 h-4 rounded border-gray-300 dark:border-border-dark text-primary focus:ring-primary"
                  />
                  <label htmlFor="extract-archives" className="text-sm cursor-pointer" style={{ color: 'var(--color-text-primary)' }}>
                    Extract and index files from archives
                  </label>
                </div>
              )}
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => {
                  setShowUploadModal(false);
                  setUploadFiles(null);
                  setUploadName('');
                  setUploadDescription('');
                  setUploadTags('');
                }}
                className="flex-1 px-4 py-2 text-sm font-medium border border-gray-300 dark:border-border-dark rounded-lg hover:bg-gray-50 dark:hover:bg-white/5 transition-colors"
                style={{ color: 'var(--color-text-primary)' }}
              >
                Cancel
              </button>
              <button
                onClick={handleFileUpload}
                className="flex-1 px-4 py-2 text-sm font-medium bg-primary text-white rounded-lg hover:opacity-90 transition-opacity"
              >
                Upload
              </button>
            </div>
          </div>
        </div>
      )}
      {/* Header */}
      <div className="bg-white dark:bg-panel-dark border-b border-gray-200 dark:border-border-dark p-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold mb-1" style={{ color: 'var(--color-text-primary)' }}>
              {t('kb_title')}
            </h1>
            <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
              {t('kb_title_desc')}
            </p>
          </div>
          <div className="flex items-center gap-2">
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-hidden p-4">
        <div className="flex h-full gap-4">
          <div className="w-72 flex-shrink-0 bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg p-3 overflow-hidden flex flex-col">
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
                  <h4 className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>
                    {t('kb_indexed')}
                  </h4>
                  <span className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>{readyDocuments.length}</span>
                </div>
                <div className="space-y-1.5">
                  {readyDocuments.map(doc => (
                    <button
                      key={doc.id}
                      onClick={() => setSelectedDocId(doc.id)}
                      className={`w-full text-left rounded-lg border px-2.5 py-2 transition-all ${
                        selectedDocId === doc.id
                          ? 'border-amber-300 dark:border-amber-500/40 bg-amber-50 dark:bg-amber-500/10'
                          : 'border-gray-200 dark:border-border-dark hover:bg-gray-50 dark:hover:bg-white/5'
                      }`}
                    >
                      <div className="flex items-start gap-2">
                        <div className="mt-0.5 h-2.5 w-2.5 rounded-full bg-amber-500 flex-shrink-0" />
                        <div className="min-w-0 flex-1">
                          <div className="text-xs font-medium truncate" style={{ color: 'var(--color-text-primary)' }}>
                            {doc.name}
                          </div>
                          <div className="text-[10px] mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
                            {formatFileSize(doc.size)} · {doc.chunk_count || 0} chunks
                          </div>
                        </div>
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
                      </div>
                    </button>
                  ))}
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

          <div className="min-w-0 flex-1 flex flex-col gap-3 overflow-hidden">
            {/* Document Preview Panel */}
            {selectedDocId && (
              <div className="bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg p-3 overflow-y-auto max-h-48">
                {previewLoading ? (
                  <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--color-text-muted)' }}>
                    <Loader className="w-3 h-3 animate-spin" />
                    Loading preview...
                  </div>
                ) : previewData ? (
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <FileText className="w-3.5 h-3.5" style={{ color: 'var(--color-primary)' }} />
                        <span className="text-xs font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                          {previewData.doc_name}
                        </span>
                        <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-gray-100 dark:bg-white/10" style={{ color: 'var(--color-text-muted)' }}>
                          {previewData.type} · {previewData.page_count} pages
                        </span>
                      </div>
                      <span className="text-[9px]" style={{ color: 'var(--color-text-muted)' }}>
                        {previewData.total_chars.toLocaleString()} chars
                      </span>
                    </div>
                    <div className="text-[10px] leading-relaxed whitespace-pre-wrap max-h-28 overflow-y-auto" style={{ color: 'var(--color-text-secondary)' }}>
                      {previewData.content_preview}
                    </div>
                    {previewData.has_more && (
                      <p className="text-[9px] mt-1 italic" style={{ color: 'var(--color-text-muted)' }}>
                        ... (preview truncated, {previewData.total_chars.toLocaleString()} total chars)
                      </p>
                    )}
                  </div>
                ) : null}
              </div>
            )}

            {/* Search Box */}
            <div className="bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg p-3 flex-shrink-0">
              <div className="flex items-center gap-1.5 mb-2">
                <Search className="w-3.5 h-3.5" style={{ color: 'var(--color-primary)' }} />
                <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                  {searchMode === 'graphindex' ? 'GraphIndex' : 'Vector RAG'} {t('kb_title')}
                </h3>
              </div>

              <div className="space-y-2">
                <div className="flex gap-0.5 p-0.5 bg-gray-100 dark:bg-white/5 rounded-lg">
                  <button onClick={() => { setSearchMode('graphindex'); setShowSearchResults(false); setGraphIndexDocs([]); }}
                    className={`flex-1 px-2 py-1 text-[11px] font-medium rounded-md transition-all ${searchMode === 'graphindex' ? 'bg-white dark:bg-white/10 shadow-sm' : 'hover:bg-white/50 dark:hover:bg-white/5'}`}
                    style={{ color: 'var(--color-text-primary)' }}>
                    {t('kb_graph_index')}
                  </button>
                  <button onClick={() => { setSearchMode('vector'); setShowSearchResults(false); setGraphIndexDocs([]); }}
                    className={`flex-1 px-2 py-1 text-[11px] font-medium rounded-md transition-all ${searchMode === 'vector' ? 'bg-white dark:bg-white/10 shadow-sm' : 'hover:bg-white/50 dark:hover:bg-white/5'}`}
                    style={{ color: 'var(--color-text-primary)' }}>
                    {t('kb_vector_rag')}
                  </button>
                </div>

                <div className="rounded-lg border border-gray-200 dark:border-border-dark px-2.5 py-2" style={{ backgroundColor: 'var(--color-input-background)' }}>
                  <div className="text-[10px] mb-0.5" style={{ color: 'var(--color-text-muted)' }}>
                    {searchMode === 'graphindex' ? t('kb_search_scope') : t('kb_selected_doc')}
                  </div>
                  <div className="text-xs font-medium" style={{ color: 'var(--color-text-primary)' }}>
                    {searchMode === 'graphindex'
                      ? t('kb_all_docs')
                      : selectedDoc
                        ? selectedDoc.name
                        : t('kb_choose_doc')}
                  </div>
                </div>

                <div className="flex gap-1.5">
                  <div className="relative flex-1">
                    <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3" style={{ color: 'var(--color-text-muted)' }} />
                    <input type="text"
                      placeholder={searchMode === 'graphindex' ? t('kb_search_graphindex_placeholder') : t('kb_search_placeholder')}
                      value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                      className="w-full pl-7 pr-2 py-2 border border-gray-200 dark:border-border-dark rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-primary"
                      style={{ backgroundColor: 'var(--color-input-background)', color: 'var(--color-text-primary)' }}
                    />
                  </div>
                  <button onClick={handleSearch} disabled={searching || !searchQuery.trim()}
                    className="px-3 py-2 bg-primary text-white rounded-lg hover:opacity-90 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-1 text-xs font-medium">
                    {searching ? <Loader className="w-3 h-3 animate-spin" /> : <Search className="w-3 h-3" />}
                  </button>
                </div>

                <div className="flex items-center gap-2 text-[10px] flex-wrap">
                  {searchMode === 'vector' && (
                    <>
                      <label className="flex items-center gap-1 cursor-pointer hover:opacity-70" style={{ color: 'var(--color-text-primary)' }}>
                        <input type="checkbox" checked={useHyDE} onChange={(e) => setUseHyDE(e.target.checked)}
                          className="w-3 h-3 rounded border-gray-300 dark:border-border-dark text-primary focus:ring-primary" />
                        <span>{t('kb_hyde')}</span>
                      </label>
                      <label className="flex items-center gap-1 cursor-pointer hover:opacity-70" style={{ color: 'var(--color-text-primary)' }}>
                        <input type="checkbox" checked={useTOON} onChange={(e) => setUseTOON(e.target.checked)}
                          className="w-3 h-3 rounded border-gray-300 dark:border-border-dark text-purple-600 focus:ring-purple-600" />
                        <span>{t('kb_toon')}</span>
                      </label>
                    </>
                  )}
                  <label className="flex items-center gap-1 cursor-pointer hover:opacity-70" style={{ color: 'var(--color-text-primary)' }}>
                    <input type="checkbox" checked={compareMode} onChange={(e) => setCompareMode(e.target.checked)}
                      className="w-3 h-3 rounded border-gray-300 dark:border-border-dark text-orange-600 focus:ring-orange-600" />
                    <span>{t('kb_compare')}</span>
                  </label>
                  {showSearchResults && (
                    <button onClick={clearSearch}
                      className="ml-auto text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-white/10 hover:bg-gray-200 dark:hover:bg-white/20 transition-all"
                      style={{ color: 'var(--color-text-primary)' }}>
                      {t('kb_clear_results')}
                    </button>
                  )}
                </div>
              </div>
            </div>

            <div className="flex-1 bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg p-3 overflow-y-auto">
              {!showSearchResults ? (
                <div className="h-full flex items-center justify-center">
                  <div className="text-center">
                    <Search className="w-8 h-8 mx-auto mb-2 opacity-50" style={{ color: 'var(--color-text-muted)' }} />
                    <p className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
                      {searchMode === 'graphindex' ? t('kb_search_hint_graph') : t('kb_search_hint_vector')}
                    </p>
                    <p className="text-[11px] mt-1" style={{ color: 'var(--color-text-muted)' }}>
                      {searchMode === 'graphindex'
                        ? t('kb_search_desc_graph')
                        : t('kb_search_desc_vector')}
                    </p>
                  </div>
                </div>
              ) : (
                <>
                  <h3 className="text-[11px] font-semibold mb-2" style={{ color: 'var(--color-text-primary)' }}>
                    {pageIndexDocs.length > 0
                      ? `${t('kb_search_results_graph')} (${pageIndexDocs.length})`
                      : `${t('kb_search_results_vector')} (${searchResults.length})`
                    }
                  </h3>

                  {pageIndexDocs.length > 0 && (
                    <div className="space-y-1.5">
                      {pageIndexDocs.map((doc: any) => (
                        <div key={doc.doc_id} className="border border-gray-200 dark:border-border-dark rounded-lg p-2">
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-[11px] font-medium" style={{ color: 'var(--color-text-primary)' }}>{doc.doc_name}</span>
                            <div className="flex items-center gap-1.5">
                              <span className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>{doc.page_count} {t('kb_pages')}</span>
                              <button
                                onClick={() => handleGraphIndexAnswer(doc)}
                                disabled={answerLoading}
                                className="text-[10px] px-1.5 py-0.5 rounded bg-primary text-white hover:opacity-80 transition-all disabled:opacity-50"
                              >
                                {answerLoading ? '...' : t('kb_answer')}
                              </button>
                            </div>
                          </div>
                          {doc.structure && doc.structure.length > 0 && (
                            <div className="ml-3 space-y-0.5">
                              {doc.structure.slice(0, 4).map((node: any, idx: number) => (
                                <div key={idx} className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                                  <span className="inline-block w-2">-</span>
                                  {node.title}{node.page && <span className="ml-0.5 opacity-60">(p.{node.page})</span>}
                                </div>
                              ))}
                              {doc.structure.length > 4 && (
                                <div className="text-[10px] italic" style={{ color: 'var(--color-text-muted)' }}>
                                  {t('kb_more_sections', { count: doc.structure.length - 4 })}
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* GraphIndex Answer Result */}
                  {answerResult && (
                    <div className="mt-3 border border-primary/30 dark:border-primary/20 rounded-lg p-3 bg-primary/5 dark:bg-primary/10">
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-1.5">
                          <span className="text-[11px] font-medium" style={{ color: 'var(--color-text-primary)' }}>
                            {t('kb_answer_from')} {answerResult.doc_name}
                          </span>
                          <span className="text-[9px] px-1 py-0.5 rounded bg-gray-200 dark:bg-white/10" style={{ color: 'var(--color-text-muted)' }}>
                            {answerResult.model}
                          </span>
                        </div>
                        <span className="text-[9px]" style={{ color: 'var(--color-text-muted)' }}>
                            {t('kb_pages_loaded', { pages: answerResult.pages_loaded, chars: answerResult.content_chars })}
                          </span>
                      </div>
                      <div className="text-xs leading-relaxed whitespace-pre-wrap" style={{ color: 'var(--color-text-primary)' }}>
                        {answerResult.answer}
                      </div>
                    </div>
                  )}

                  {searchResults.length > 0 && (
                    <div className="space-y-1.5">
                      {searchResults.map((result, index) => (
                        <div key={index} className="bg-gray-50 dark:bg-background-dark border border-gray-200 dark:border-border-dark rounded-lg p-2">
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-[11px] font-medium text-primary">{result.document_name}</span>
                            <div className="flex items-center gap-1.5">
                              <span className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                                {(result.similarity_score * 100).toFixed(0)}%
                              </span>
                              <button onClick={() => toggleChunkExpansion(index)}
                                className="text-[10px] text-primary hover:underline font-medium">
                                {expandedChunks.has(index) ? t('kb_hide') : t('kb_show')}
                              </button>
                            </div>
                          </div>
                          {expandedChunks.has(index) && result.chunk_id && (
                            <div className="mb-1 pb-1 border-b border-gray-200 dark:border-border-dark text-[10px]">
                              <span className="font-mono" style={{ color: 'var(--color-text-muted)' }}>#{result.chunk_id}</span>
                              {result.chunk_token_count && <span className="ml-1" style={{ color: 'var(--color-text-muted)' }}>{result.chunk_token_count} {t('kb_tokens')}</span>}
                            </div>
                          )}
                          <pre className="text-[10px] whitespace-pre-wrap font-mono p-1 rounded overflow-x-auto max-h-28 leading-snug"
                            style={{ backgroundColor: 'var(--color-input-background)', color: 'var(--color-text-primary)' }}>
                            {result.chunk_text}
                          </pre>
                        </div>
                      ))}
                    </div>
                  )}

                  {searchResults.length === 0 && pageIndexDocs.length === 0 && (
                    <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>{t('kb_no_results_for')} "{searchQuery}"</p>
                  )}
                </>
              )}
            </div>
          </div>

          <div className="w-72 flex-shrink-0 overflow-y-auto space-y-3">
            {/* Upload Zone */}
            <div
              className={`border-2 border-dashed rounded-lg p-2.5 transition-all ${isDragging
                ? 'border-primary bg-primary/5'
                : 'border-gray-300 dark:border-border-dark bg-white dark:bg-panel-dark'
                }`}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
                  {uploading ? (
                    <Loader className="w-4 h-4 text-primary animate-spin" />
                  ) : (
                    <Upload className="w-4 h-4 text-primary" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-[10px] truncate" style={{ color: 'var(--color-text-muted)' }}>
                    {uploading ? t('kb_uploading') : t('kb_upload_drop')}
                  </p>
                </div>
                <div className="flex items-center gap-1">
                  <label className="flex items-center gap-1 px-2 py-1 bg-primary text-white rounded-lg hover:opacity-90 transition-all cursor-pointer text-[10px] font-medium">
                    <Upload className="w-3 h-3" />
                    <span>{t('kb_browse')}</span>
                    <input type="file" multiple accept={SUPPORTED_FILES}
                      onChange={(e) => { setIsFolderUpload(false); handleFileSelect(e.target.files); }}
                      className="hidden" disabled={uploading} />
                  </label>
                  <label className="flex items-center gap-1 px-2 py-1 bg-purple-600 text-white rounded-lg hover:opacity-90 transition-all cursor-pointer text-[10px] font-medium">
                    <Database className="w-3 h-3" />
                    <span>{t('kb_select_folder')}</span>
                    <input type="file" // @ts-ignore - webkitdirectory is not in TS types
                      webkitdirectory="" directory="" multiple
                      onChange={(e) => { setIsFolderUpload(true); handleFileSelect(e.target.files); }}
                      className="hidden" disabled={uploading} />
                  </label>
                </div>
              </div>
            </div>

            {/* Phase 9 / Step L1 — one-click import of the `graphindex_chat`
                agent template into the langconfig DeepAgent library.
                Once imported, the user can edit it like any other agent
                (swap model, change prompt, add subagents) or use it
                directly in the chat panel. */}
            <div
              className="rounded-lg p-2.5 border border-purple-200 dark:border-purple-800/40"
              style={{
                backgroundColor: 'var(--color-panel-light)',
                backgroundImage: 'linear-gradient(135deg, rgba(168, 85, 247, 0.05), rgba(99, 102, 241, 0.05))',
              }}
            >
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0" style={{ backgroundColor: 'rgba(168, 85, 247, 0.12)' }}>
                  <Sparkles className="w-4 h-4" style={{ color: '#a855f7' }} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-[11px] font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                    {t('kb_graphindex_chat_title', 'graphindex_chat (Phase 9)')}
                  </p>
                  <p className="text-[10px] truncate" style={{ color: 'var(--color-text-muted)' }}>
                    {t('kb_graphindex_chat_desc', 'LLM-semantic-routed chat with 4 GraphIndex tools. Click to add to agent builder.')}
                  </p>
                </div>
                <button
                  onClick={handleImportGraphindexChat}
                  disabled={importingGraphindexChat}
                  className="flex items-center gap-1 px-2.5 py-1 rounded-lg transition-all text-[10px] font-medium disabled:opacity-50"
                  style={{
                    backgroundColor: importedGraphindexChatId ? 'rgba(34, 197, 94, 0.15)' : 'rgba(168, 85, 247, 0.15)',
                    color: importedGraphindexChatId ? '#16a34a' : '#a855f7',
                  }}
                  title={
                    importedGraphindexChatId
                      ? `Imported (id=${importedGraphindexChatId}) — open Agent Builder to edit`
                      : 'Import the graphindex_chat agent template into your DeepAgent library'
                  }
                >
                  {importingGraphindexChat ? (
                    <Loader className="w-3 h-3 animate-spin" />
                  ) : importedGraphindexChatId ? (
                    <Check className="w-3 h-3" />
                  ) : (
                    <Sparkles className="w-3 h-3" />
                  )}
                  <span>
                    {importingGraphindexChat
                      ? t('kb_importing', 'Importing…')
                      : importedGraphindexChatId
                        ? t('kb_imported', 'In library')
                        : t('kb_use_in_builder', 'Use in agent builder')}
                  </span>
                </button>
              </div>
            </div>

            {/* Quick Stats */}
            <div className="bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg p-2.5">
              <div className="flex items-center gap-3 text-[10px]">
                <div className="flex items-center gap-1">
                  <FileText className="w-2.5 h-2.5" style={{ color: 'var(--color-primary)' }} />
                  <span style={{ color: 'var(--color-text-muted)' }}>{t('kb_documents')}:</span>
                  <span className="font-semibold text-[11px]" style={{ color: 'var(--color-text-primary)' }}>{totalDocuments}</span>
                </div>
                <div className="flex items-center gap-1">
                  <Filter className="w-2.5 h-2.5" style={{ color: 'var(--color-text-muted)' }} />
                  <span style={{ color: 'var(--color-text-muted)' }}>{t('kb_indexed')}:</span>
                  <span className="font-semibold text-[11px]" style={{ color: 'var(--color-text-primary)' }}>{readyCount}</span>
                </div>
                <div className="flex items-center gap-1">
                  <Database className="w-2.5 h-2.5" style={{ color: 'var(--color-text-muted)' }} />
                  <span style={{ color: 'var(--color-text-muted)' }}>{t('kb_total_chunks')}:</span>
                  <span className="font-semibold text-[11px]" style={{ color: 'var(--color-text-primary)' }}>{totalChunks}</span>
                </div>
              </div>
              <div className="flex items-center justify-between mt-1.5 pt-1.5 border-t border-gray-100 dark:border-border-dark">
                <div className="flex items-center gap-1 text-[10px]">
                  <Database className="w-2.5 h-2.5" style={{ color: 'var(--color-text-muted)' }} />
                  <span style={{ color: 'var(--color-text-muted)' }}>Storage:</span>
                  <span className="font-semibold text-[11px]" style={{ color: 'var(--color-text-primary)' }}>{formatFileSize(totalSize)}</span>
                </div>
                <button onClick={() => loadDocuments()} className="flex items-center gap-1 px-1.5 py-0.5 rounded hover:bg-gray-100 dark:hover:bg-white/10 transition-all text-[10px]" style={{ color: 'var(--color-text-primary)' }}>
                  <RefreshCw className="w-2.5 h-2.5" style={{ color: 'var(--color-primary)' }} />
                  {t('kb_refresh')}
                </button>
              </div>
            </div>

            {activeProjectId && (
              <StorageMetrics
                projectId={activeProjectId}
                onRefresh={loadDocuments}
                compact
                labels={{
                  storageMetrics: t('kb_storage_metrics'),
                  totalStorage: t('kb_total_storage'),
                  indexedChunks: t('kb_indexed_chunks'),
                  status: t('kb_status'),
                  storageBreakdown: t('kb_storage_breakdown'),
                  data: t('kb_data'),
                  index: t('kb_label_index'),
                  chunkSize: t('kb_chunk_size'),
                  overlap: t('kb_overlap'),
                  embedding: t('kb_embedding'),
                  refresh: t('kb_refresh'),
                  loading: t('kb_loading'),
                  noData: t('kb_no_data'),
                  noDataDesc: t('kb_no_data_desc'),
                }}
              />
            )}

            {showSearchResults && searchMetrics && (
              <SearchMetricsDisplay
                metrics={searchMetrics}
                comparisonMetrics={comparisonMetrics || undefined}
              />
            )}

            {showSearchResults && activeProjectId && (
              <div className="bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg p-3">
                <SearchHistoryLog
                  projectId={activeProjectId}
                  onRerun={handleRerunFromHistory}
                />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
