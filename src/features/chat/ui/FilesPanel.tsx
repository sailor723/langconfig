import { useState, useEffect, useMemo } from 'react';
import { File, FolderOpen, Folder, Download, X, Loader2, CheckCircle, AlertCircle, Clock, RefreshCw, ChevronRight, ChevronDown } from 'lucide-react';
import type { SessionDocument } from '../types/chat';
import apiClient from '../../../lib/api-client';
import { downloadFile } from '../utils/downloadFile';

interface FilesPanelProps {
  sessionId: string | null;
  onClose: () => void;
}

interface GeneratedFile {
  filename: string;
  path: string;
  size_bytes: number;
  size_human?: string;
  modified_at?: string;
  folder?: string;
}

export default function FilesPanel({ sessionId, onClose }: FilesPanelProps) {
  const [documents, setDocuments] = useState<SessionDocument[]>([]);
  const [generatedFiles, setGeneratedFiles] = useState<GeneratedFile[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadDocuments();
    loadGeneratedFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // Refresh whenever a new file/folder is uploaded (FileUploadButton fires
  // 'chat:files-changed' after a successful upload)
  useEffect(() => {
    const handleFilesChanged = () => {
      loadDocuments();
      loadGeneratedFiles();
    };
    window.addEventListener('chat:files-changed', handleFilesChanged);
    return () => window.removeEventListener('chat:files-changed', handleFilesChanged);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadDocuments = async () => {
    if (!sessionId) {
      setDocuments([]);
      return;
    }
    setLoading(true);
    try {
      const response = await apiClient.get(`/api/chat/${sessionId}/documents`);
      setDocuments(response.data || []);
    } catch (error) {
      console.error('Failed to load documents:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadGeneratedFiles = async () => {
    if (!sessionId) {
      setGeneratedFiles([]);
      return;
    }
    try {
      const response = await apiClient.get(`/api/chat/${sessionId}/generated-files`);
      const files = Array.isArray(response.data?.files) ? response.data.files : [];
      setGeneratedFiles(files);
    } catch (error) {
      console.error('Failed to load generated files:', error);
    }
  };

  // Manual reload of both lists (uploaded + generated files).
  const handleRefresh = () => {
    loadDocuments();
    loadGeneratedFiles();
  };

  const statusIcon = (status: string) => {
    switch (status) {
      case 'ready': return <CheckCircle className="w-3 h-3" style={{ color: '#10b981' }} />;
      case 'indexing': return <Loader2 className="w-3 h-3 animate-spin" style={{ color: 'var(--color-primary)' }} />;
      case 'failed': return <AlertCircle className="w-3 h-3" style={{ color: '#ef4444' }} />;
      default: return <Clock className="w-3 h-3" style={{ color: 'var(--color-text-muted)' }} />;
    }
  };

  // Cascading (nested) view: group files by their workspace folder
  // (generated/ · upload/ · skills/ · other/ · workspace).
  const folders = useMemo(() => {
    const order = ['generated', 'upload', 'skills', 'other', 'workspace'];
    const map = new Map<string, GeneratedFile[]>();
    for (const f of generatedFiles) {
      const key = f.folder || 'workspace';
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(f);
    }
    const names = Array.from(map.keys()).sort(
      (a, b) => (order.indexOf(a) === -1 ? 99 : order.indexOf(a)) - (order.indexOf(b) === -1 ? 99 : order.indexOf(b)),
    );
    return names.map(name => ({ name, files: map.get(name)! }));
  }, [generatedFiles]);

  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const toggleFolder = (name: string) => {
    setCollapsed(prev => ({ ...prev, [name]: !prev[name] }));
  };

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ color: 'var(--color-text-primary)' }}>
      <div className="flex items-center justify-between px-3 py-2 border-b" style={{ borderColor: 'var(--color-border-dark)' }}>
        <span className="text-xs font-semibold flex items-center gap-1.5">
          <FolderOpen className="w-3.5 h-3.5" style={{ color: 'var(--color-primary)' }} />
          Files
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={handleRefresh}
            className="p-1 rounded hover:bg-black/5 transition-colors"
            title="Refresh"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button onClick={onClose} className="p-1 rounded hover:bg-black/5 transition-colors" title="Close">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-4">
        {loading ? (
          <div className="text-center text-xs" style={{ color: 'var(--color-text-muted)' }}>Loading...</div>
        ) : documents.length > 0 ? (
          <div>
            <div className="text-[11px] font-semibold mb-1.5" style={{ color: 'var(--color-text-muted)' }}>
              Uploaded ({documents.length})
            </div>
            <div className="space-y-1">
              {documents.map(doc => (
                <div key={doc.id} className="flex items-center gap-2 px-2 py-1.5 rounded-lg" style={{ backgroundColor: 'var(--color-background-light)' }}>
                  <File className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-primary)' }} />
                  <span className="text-xs truncate flex-1" title={doc.filename}>{doc.original_filename || doc.filename}</span>
                  {statusIcon(doc.indexing_status)}
                  <button
                    onClick={() => downloadFile(
                      `/api/chat/${sessionId}/documents/${doc.id}/download`,
                      undefined,
                      doc.original_filename || doc.filename,
                    )}
                    className="p-1 rounded hover:bg-white/10"
                    title="Download"
                  >
                    <Download className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {generatedFiles.length > 0 && (
          <div>
            <div className="text-[11px] font-semibold mb-1.5" style={{ color: 'var(--color-text-muted)' }}>
              Workspace files ({generatedFiles.length})
            </div>
            <div className="space-y-2">
              {folders.map(group => {
                const isCollapsed = !!collapsed[group.name];
                const folderLabel = group.name === 'workspace' ? '(workspace root)' : `${group.name}/`;
                return (
                  <div key={group.name} className="rounded-lg" style={{ backgroundColor: 'var(--color-background-light)' }}>
                    <button
                      onClick={() => toggleFolder(group.name)}
                      className="w-full flex items-center gap-1.5 px-2 py-1.5 rounded-lg hover:bg-black/5 transition-colors text-left"
                    >
                      {isCollapsed
                        ? <ChevronRight className="w-3 h-3 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />
                        : <ChevronDown className="w-3 h-3 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }} />}
                      <Folder className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-primary)' }} />
                      <span className="text-xs font-medium truncate flex-1">{folderLabel}</span>
                      <span className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                        {group.files.length}
                      </span>
                    </button>
                    {!isCollapsed && (
                      <div className="pl-6 pr-2 pb-1.5 space-y-1">
                        {group.files.map(file => (
                          <div key={file.path} className="flex items-center gap-2 px-2 py-1 rounded-lg" style={{ backgroundColor: 'var(--color-background-light)' }}>
                            <File className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--color-primary)' }} />
                            <span className="text-xs truncate flex-1" title={file.path}>{file.filename}</span>
                            <span className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                              {file.size_human || `${(file.size_bytes / 1024).toFixed(0)}KB`}
                            </span>
                            <button
                              onClick={() => downloadFile(
                                '/api/workspace/by-path/download',
                                { file_path: file.path },
                                file.filename,
                              )}
                              className="p-1 rounded hover:bg-white/10"
                              title="Download"
                            >
                              <Download className="w-3 h-3" />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {!loading && documents.length === 0 && generatedFiles.length === 0 && (
          <div className="text-center text-xs py-6" style={{ color: 'var(--color-text-muted)' }}>
            No files yet
          </div>
        )}
      </div>
    </div>
  );
}
