/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useState, useEffect } from 'react';
import { File, Trash2, Loader2, CheckCircle, AlertCircle, Clock } from 'lucide-react';
import type { SessionDocument } from '../types/chat';
import apiClient from '../../../lib/api-client';

interface SessionDocumentsPanelProps {
  sessionId: string | null;
  refreshKey?: number;
}

export default function SessionDocumentsPanel({ sessionId, refreshKey = 0 }: SessionDocumentsPanelProps) {
  const [documents, setDocuments] = useState<SessionDocument[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (sessionId) {
      loadDocuments();
    } else {
      setDocuments([]);
    }
  }, [sessionId, refreshKey]);

  const loadDocuments = async () => {
    if (!sessionId) return;

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

  const handleDelete = async (docId: number) => {
    if (!window.confirm('Delete this document?')) return;

    try {
      await apiClient.delete(`/api/chat/${sessionId}/documents/${docId}`);
      setDocuments(docs => docs.filter(d => d.id !== docId));
    } catch (error) {
      console.error('Failed to delete document:', error);
      alert('Failed to delete document');
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'ready':
        return <CheckCircle className="w-4 h-4" style={{ color: '#10b981' }} />;
      case 'indexing':
        return <Loader2 className="w-4 h-4 animate-spin" style={{ color: 'var(--color-primary)' }} />;
      case 'failed':
        return <AlertCircle className="w-4 h-4" style={{ color: '#ef4444' }} />;
      default:
        return <Clock className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />;
    }
  };

  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'ready':
        return 'Ready';
      case 'indexing':
        return 'Indexing...';
      case 'failed':
        return 'Failed';
      default:
        return 'Pending';
    }
  };

  if (!sessionId || documents.length === 0) return null;

  return (
    <div
      className="border-t px-4 py-1.5"
      style={{ borderColor: 'var(--color-border-dark)' }}
    >
      <h3
        className="text-xs font-semibold mb-1.5"
        style={{ color: 'var(--color-text-primary)' }}
      >
        Documents ({documents.length})
      </h3>

      {loading ? (
        <div className="flex items-center justify-center py-2">
          <Loader2 className="w-4 h-4 animate-spin" style={{ color: 'var(--color-primary)' }} />
        </div>
      ) : (
        <div className="flex flex-wrap justify-center gap-1.5 max-h-24 overflow-y-auto">
          {documents.map(doc => (
            <div
              key={doc.id}
              className="flex flex-col items-center gap-0.5 p-2 rounded-lg border relative"
              style={{
                backgroundColor: 'white',
                borderColor: 'var(--color-border-dark)',
                width: 'fit-content',
                minWidth: '90px'
              }}
            >
              <button
                onClick={() => handleDelete(doc.id)}
                className="absolute -top-1.5 -right-1.5 p-0.5 rounded-full transition-colors hover:bg-red-50"
                title="Delete document"
                style={{ color: '#ef4444', backgroundColor: 'white', border: '1px solid var(--color-border-dark)' }}
              >
                <Trash2 className="w-2.5 h-2.5" />
              </button>
              <div className="flex items-center justify-center gap-1 min-w-0">
                <File className="w-3 h-3 flex-shrink-0" style={{ color: 'var(--color-primary)' }} />
                <span
                  className="text-[11px] font-medium truncate max-w-[80px]"
                  style={{ color: 'var(--color-text-primary)' }}
                  title={doc.filename}
                >
                  {doc.filename}
                </span>
              </div>
              <div className="flex items-center justify-center gap-1 text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                <span>{(doc.file_size / 1024).toFixed(0)}KB</span>
                <span>•</span>
                {getStatusIcon(doc.indexing_status)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
