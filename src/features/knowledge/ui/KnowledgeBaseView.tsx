/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload, FileText, Trash2, Search, Database, Filter, Loader } from 'lucide-react';
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
  const [isDragging, setIsDragging] = useState(false);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [showSearchResults, setShowSearchResults] = useState(false);
  const [useHyDE, setUseHyDE] = useState(false);
  const [useTOON, setUseTOON] = useState(false);
  const [searchMode, setSearchMode] = useState<'vector' | 'pageindex'>('vector');
  const [compareMode, setCompareMode] = useState(false);
  const [searchMetrics, setSearchMetrics] = useState<SearchMetrics | null>(null);
  const [comparisonMetrics, setComparisonMetrics] = useState<SearchMetrics | null>(null);
  const [comparisonResults, setComparisonResults] = useState<SearchResult[]>([]);
  const [expandedChunks, setExpandedChunks] = useState<Set<number>>(new Set());
  const [pageIndexDocs, setPageIndexDocs] = useState<any[]>([]);
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

  const loadDocuments = async (signal?: AbortSignal) => {
    if (!activeProjectId) return;

    try {
      setLoading(true);
      const params: any = { project_id: activeProjectId };
      if (selectedStatus !== 'all') {
        params.status = selectedStatus;
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

      await loadDocuments();
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

    try {
      setSearching(true);

      if (compareMode) {

        const response1 = await apiClient.searchDocuments({
          query: searchQuery,
          project_id: activeProjectId,
          top_k: 10,
          use_hyde: useHyDE,
          search_mode: 'pageindex',
        });
        const data1 = response1 as any;
        if (data1.search_mode === 'pageindex') {
          setSearchResults([]);
          setPageIndexDocs(data1.documents || []);
        } else {
          setPageIndexDocs([]);
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
        if (data2.search_mode === 'pageindex') {
          setComparisonResults([]);
        } else {
          setComparisonResults(data2.results || []);
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
        if (data.search_mode === 'pageindex') {
          setSearchResults([]);
          setPageIndexDocs(data.documents || []);
          setSearchMetrics(null);
        } else {
          setPageIndexDocs([]);
          setSearchResults(data.results || []);
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

  const filteredDocuments = documents.filter(doc => {
    if (!doc.name) return false;
    const matchesSearch = doc.name.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesSearch;
  });

  const totalDocuments = documents.length;
  const totalChunks = documents.reduce((sum, doc) => sum + (doc.chunk_count || 0), 0);
  const totalSize = documents.reduce((sum, doc) => sum + (doc.size || 0), 0);
  const readyCount = documents.filter(d => d.indexing_status === 'ready').length;

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

      {/* Main layout: left = upload + doc grid, right = stats + search */}
      <div className="flex-1 overflow-hidden flex gap-4 p-4">
        {/* ===== Left Column ===== */}
        <div className="flex-1 flex flex-col gap-3 overflow-hidden">

          {/* Upload area - compact */}
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
                <p className="text-xs truncate" style={{ color: 'var(--color-text-muted)' }}>
                  {uploading ? t('kb_uploading') : t('kb_upload_drop')}
                </p>
              </div>
              <div className="flex items-center gap-1.5">
                <label className="flex items-center gap-1.5 px-2.5 py-1.5 bg-primary text-white rounded-lg hover:opacity-90 transition-all cursor-pointer text-xs font-medium">
                  <Upload className="w-3.5 h-3.5" />
                  <span>{t('kb_browse')}</span>
                  <input type="file" multiple accept={SUPPORTED_FILES}
                    onChange={(e) => { setIsFolderUpload(false); handleFileSelect(e.target.files); }}
                    className="hidden" disabled={uploading} />
                </label>
                <label className="flex items-center gap-1.5 px-2.5 py-1.5 bg-purple-600 text-white rounded-lg hover:opacity-90 transition-all cursor-pointer text-xs font-medium">
                  <Database className="w-3.5 h-3.5" />
                  <span>{t('kb_select_folder')}</span>
                  <input type="file" // @ts-ignore - webkitdirectory is not in TS types
                    webkitdirectory="" directory="" multiple
                    onChange={(e) => { setIsFolderUpload(true); handleFileSelect(e.target.files); }}
                    className="hidden" disabled={uploading} />
                </label>
              </div>
            </div>
          </div>

          {/* Stats bar - compact horizontal */}
          <div className="bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg px-4 py-2.5">
            <div className="flex items-center gap-6 text-xs">
              <div className="flex items-center gap-1.5">
                <FileText className="w-3.5 h-3.5" style={{ color: 'var(--color-primary)' }} />
                <span style={{ color: 'var(--color-text-muted)' }}>{t('kb_documents')}:</span>
                <span className="font-semibold text-sm" style={{ color: 'var(--color-text-primary)' }}>{totalDocuments}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <Filter className="w-3.5 h-3.5" style={{ color: 'var(--color-text-muted)' }} />
                <span style={{ color: 'var(--color-text-muted)' }}>{t('kb_indexed')}:</span>
                <span className="font-semibold text-sm" style={{ color: 'var(--color-text-primary)' }}>{readyCount}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <Database className="w-3.5 h-3.5" style={{ color: 'var(--color-text-muted)' }} />
                <span style={{ color: 'var(--color-text-muted)' }}>Chunks:</span>
                <span className="font-semibold text-sm" style={{ color: 'var(--color-text-primary)' }}>{totalChunks}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <Database className="w-3.5 h-3.5" style={{ color: 'var(--color-text-muted)' }} />
                <span style={{ color: 'var(--color-text-muted)' }}>Storage:</span>
                <span className="font-semibold text-sm" style={{ color: 'var(--color-text-primary)' }}>{formatFileSize(totalSize)}</span>
              </div>
              <div className="ml-auto">
                <select value={selectedStatus} onChange={(e) => setSelectedStatus(e.target.value)}
                  className="px-2 py-1 border border-gray-200 dark:border-border-dark rounded text-xs focus:outline-none focus:ring-1 focus:ring-primary"
                  style={{ backgroundColor: 'var(--color-input-background)', color: 'var(--color-text-primary)' }}>
                  <option value="all">{t('kb_all')}</option>
                  <option value="ready">{t('kb_indexed')}</option>
                  <option value="indexing">Processing</option>
                  <option value="not_indexed">Pending</option>
                  <option value="failed">Failed</option>
                </select>
              </div>
            </div>
          </div>

          {/* Document Cards Grid - 6 per row */}
          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="flex items-center justify-center h-full">
                <div className="text-center">
                  <Loader className="w-10 h-10 text-primary mx-auto mb-2 animate-spin" />
                  <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>{t('kb_loading')}</p>
                </div>
              </div>
            ) : filteredDocuments.length === 0 ? (
              <div className="flex items-center justify-center h-full">
                <div className="text-center">
                  <FileText className="w-10 h-10 mx-auto mb-2 opacity-50" style={{ color: 'var(--color-text-muted)' }} />
                  <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>{t('kb_empty')}</p>
                  <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                    {searchQuery ? t('kb_no_results', { query: searchQuery }) : ''}
                  </p>
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-6 gap-2">
                {filteredDocuments.map(doc => (
                  <div key={doc.id}
                    className="bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg p-2.5 hover:shadow-sm transition-shadow group"
                  >
                    <div className="flex flex-col items-center text-center">
                      <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center mb-1.5">
                        <FileText className="w-4 h-4 text-primary" />
                      </div>
                      <h4 className="text-xs font-medium leading-tight line-clamp-2 mb-1" style={{ color: 'var(--color-text-primary)' }}>
                        {doc.name}
                      </h4>
                      <div className="text-[10px] leading-tight" style={{ color: 'var(--color-text-muted)' }}>
                        <div>{formatFileSize(doc.size)}</div>
                        <div className="flex items-center justify-center gap-1">
                          <Database className="w-2.5 h-2.5" />
                          {doc.chunk_count || 0} chunks
                        </div>
                      </div>
                      <div className="mt-1 flex items-center gap-1">
                        <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${
                          doc.indexing_status === 'ready'
                            ? 'bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400'
                            : doc.indexing_status === 'indexing'
                              ? 'bg-yellow-100 dark:bg-yellow-500/20 text-yellow-700 dark:text-yellow-400'
                              : doc.indexing_status === 'failed'
                                ? 'bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400'
                                : 'bg-gray-100 dark:bg-gray-500/20'
                        }`}>
                          {getStatusDisplay(doc.indexing_status)}
                        </span>
                        <button onClick={() => handleDelete(doc.id)}
                          className="p-1 opacity-0 group-hover:opacity-100 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10 rounded transition-all"
                          style={{ color: 'var(--color-text-muted)' }} title="Delete">
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ===== Right Column - Stats + Search ===== */}
        <div className="w-80 flex-shrink-0 overflow-y-auto space-y-3">

          {/* Storage Metrics */}
          {activeProjectId && (
            <StorageMetrics
              projectId={activeProjectId}
              onRefresh={loadDocuments}
            />
          )}

          {/* Semantic Search */}
          <div className="bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg p-3">
            <div className="flex items-center gap-1.5 mb-2">
              <Search className="w-3.5 h-3.5" style={{ color: 'var(--color-primary)' }} />
              <h3 className="text-xs font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                {searchMode === 'pageindex' ? 'Document Navigation (PageIndex)' : 'Semantic Search'}
              </h3>
            </div>

            <div className="space-y-2">
              {/* Mode selector */}
              <div className="flex gap-0.5 p-0.5 bg-gray-100 dark:bg-white/5 rounded-lg">
                <button onClick={() => { setSearchMode('vector'); setShowSearchResults(false); setPageIndexDocs([]); }}
                  className={`flex-1 px-2 py-1 text-[11px] font-medium rounded-md transition-all ${
                    searchMode === 'vector' ? 'bg-white dark:bg-white/10 shadow-sm' : 'hover:bg-white/50 dark:hover:bg-white/5'
                  }`}
                  style={{ color: 'var(--color-text-primary)' }}>
                  {t('kb_vector_rag')}
                </button>
                <button onClick={() => { setSearchMode('pageindex'); setShowSearchResults(false); setPageIndexDocs([]); }}
                  className={`flex-1 px-2 py-1 text-[11px] font-medium rounded-md transition-all ${
                    searchMode === 'pageindex' ? 'bg-white dark:bg-white/10 shadow-sm' : 'hover:bg-white/50 dark:hover:bg-white/5'
                  }`}
                  style={{ color: 'var(--color-text-primary)' }}>
                  {t('kb_page_index')}
                </button>
              </div>

              {/* Search input */}
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3" style={{ color: 'var(--color-text-muted)' }} />
                <input type="text"
                  placeholder={searchMode === 'pageindex' ? t('kb_search_pageindex_placeholder') : t('kb_search_placeholder')}
                  value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                  className="w-full pl-8 pr-3 py-1.5 border border-gray-200 dark:border-border-dark rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-primary"
                  style={{ backgroundColor: 'var(--color-input-background)', color: 'var(--color-text-primary)' }}
                />
              </div>

              {/* Options row */}
              <div className="flex items-center gap-2 text-[11px] flex-wrap">
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
              </div>

              {/* Search button */}
              <button onClick={handleSearch} disabled={searching || !searchQuery.trim()}
                className="w-full px-3 py-1.5 bg-primary text-white rounded-lg hover:opacity-90 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-1.5 text-xs font-medium">
                {searching ? (
                  <><Loader className="w-3 h-3 animate-spin" /><span>{t('kb_searching')}</span></>
                ) : (
                  <><Search className="w-3 h-3" /><span>{t('kb_search_action')}</span></>
                )}
              </button>

              {showSearchResults && (
                <button onClick={clearSearch}
                  className="w-full px-3 py-1.5 bg-gray-100 dark:bg-white/5 rounded-lg hover:bg-gray-200 dark:hover:bg-white/10 transition-all border border-gray-200 dark:border-border-dark text-xs font-medium"
                  style={{ color: 'var(--color-text-primary)' }}>
                  {t('kb_clear_results')}
                </button>
              )}
            </div>
          </div>

          {/* Search Results */}
          {showSearchResults && (
            <div className="space-y-3">
              {searchMetrics && (
                <SearchMetricsDisplay
                  metrics={searchMetrics}
                  comparisonMetrics={comparisonMetrics || undefined}
                />
              )}

              <div className="bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg p-3">
                <h3 className="text-xs font-semibold mb-2" style={{ color: 'var(--color-text-primary)' }}>
                  {pageIndexDocs.length > 0
                    ? `Indexed Documents (${pageIndexDocs.length})`
                    : `Search Results (${searchResults.length})`
                  }
                </h3>

                {/* PageIndex Results */}
                {pageIndexDocs.length > 0 && (
                  <div className="space-y-2">
                    {pageIndexDocs.map((doc: any) => (
                      <div key={doc.doc_id} className="border border-gray-200 dark:border-border-dark rounded-lg p-2">
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="flex items-center gap-1.5">
                            <span className="material-symbols-outlined text-xs" style={{ color: 'var(--color-primary)' }}>
                              {doc.type === 'pdf' ? 'picture_as_pdf' : 'description'}
                            </span>
                            <span className="text-xs font-medium" style={{ color: 'var(--color-text-primary)' }}>
                              {doc.doc_name}
                            </span>
                          </div>
                          <span className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                            {doc.page_count} {t('kb_pages')}
                          </span>
                        </div>
                        {doc.structure && doc.structure.length > 0 && (
                          <div className="ml-4 space-y-0.5">
                            {doc.structure.slice(0, 5).map((node: any, idx: number) => (
                              <div key={idx} className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                                <span className="inline-block w-3">-</span>
                                {node.title}
                                {node.page && <span className="ml-1 opacity-60">(p.{node.page})</span>}
                              </div>
                            ))}
                            {doc.structure.length > 5 && (
                              <div className="text-[10px] italic" style={{ color: 'var(--color-text-muted)' }}>
                                {t('kb_more_sections', { count: doc.structure.length - 5 })}
                              </div>
                            )}
                          </div>
                        )}
                        <div className="mt-1.5">
                          <button onClick={async () => {
                            try {
                              const res = await apiClient.searchDocuments({
                                query: `Read page 1-3 of ${doc.doc_name}`,
                                project_id: activeProjectId || 0,
                                top_k: 1,
                                search_mode: 'pageindex',
                              });
                              const data = res as any;
                              if (data.search_mode === 'pageindex') {
                                setSearchResults([]);
                                setPageIndexDocs(data.documents || []);
                              }
                            } catch {}
                          }}
                            className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-white/10 hover:bg-gray-200 dark:hover:bg-white/20 transition-colors"
                            style={{ color: 'var(--color-text-primary)' }}>
                            Browse
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Vector Results */}
                {searchResults.length > 0 && (
                  <div className="space-y-2">
                    {searchResults.map((result, index) => (
                      <div key={index} className="bg-gray-50 dark:bg-background-dark border border-gray-200 dark:border-border-dark rounded-lg p-2">
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="text-xs font-medium text-primary">{result.document_name}</span>
                          <div className="flex items-center gap-2">
                            <span className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                              Similarity: {(result.similarity_score * 100).toFixed(1)}%
                            </span>
                            {result.chunk_token_count && (
                              <span className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                                {result.chunk_token_count} tokens
                              </span>
                            )}
                            <button onClick={() => toggleChunkExpansion(index)}
                              className="text-[10px] text-primary hover:underline font-medium">
                              {expandedChunks.has(index) ? 'Hide' : 'Show'}
                            </button>
                          </div>
                        </div>

                        {expandedChunks.has(index) && (
                          <div className="mb-1.5 pb-1.5 border-b border-gray-200 dark:border-border-dark text-[10px] space-y-0.5">
                            {result.chunk_id && (
                              <div><span style={{ color: 'var(--color-text-muted)' }}>Chunk ID:</span>{' '}
                                <span className="font-mono" style={{ color: 'var(--color-text-primary)' }}>{result.chunk_id}</span>
                              </div>
                            )}
                            {result.chunk_index !== undefined && (
                              <div><span style={{ color: 'var(--color-text-muted)' }}>Chunk Index:</span>{' '}
                                <span style={{ color: 'var(--color-text-primary)' }}>{result.chunk_index} of {result.total_chunks_in_doc || '?'}</span>
                              </div>
                            )}
                            {result.chunk_token_count && (
                              <div><span style={{ color: 'var(--color-text-muted)' }}>Token Count:</span>{' '}
                                <span className="font-semibold" style={{ color: 'var(--color-text-primary)' }}>{result.chunk_token_count} tokens</span>
                              </div>
                            )}
                            {result.chunk_char_count && (
                              <div><span style={{ color: 'var(--color-text-muted)' }}>Character Count:</span>{' '}
                                <span style={{ color: 'var(--color-text-primary)' }}>{result.chunk_char_count} chars</span>
                              </div>
                            )}
                          </div>
                        )}

                        <pre className="text-[10px] whitespace-pre-wrap font-mono p-1.5 rounded overflow-x-auto max-h-20"
                          style={{ backgroundColor: 'var(--color-input-background)', color: 'var(--color-text-primary)' }}>
                          {result.chunk_text}
                        </pre>
                      </div>
                    ))}
                  </div>
                )}

                {searchResults.length === 0 && pageIndexDocs.length === 0 && (
                  <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                    No results found for "{searchQuery}"
                  </p>
                )}
              </div>

              {activeProjectId && (
                <SearchHistoryLog
                  projectId={activeProjectId}
                  onRerun={handleRerunFromHistory}
                />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
