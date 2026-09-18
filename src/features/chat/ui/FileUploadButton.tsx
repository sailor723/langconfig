/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { Paperclip, Loader2, FolderUp, FileUp, ChevronUp } from 'lucide-react';
import { useState, useRef, useEffect } from 'react';
import type { SessionDocument } from '../types/chat';
import apiClient from '../../../lib/api-client';

interface FileUploadButtonProps {
  sessionId: string | null;
  projectId?: number | null;
  onFileUploaded: (file: SessionDocument) => void;
  onMultipleUploaded?: (files: SessionDocument[]) => void;
  disabled?: boolean;
}

export default function FileUploadButton({ sessionId, projectId, onFileUploaded, onMultipleUploaded, disabled }: FileUploadButtonProps) {
  const [uploading, setUploading] = useState(false);
  const [showMenu, setShowMenu] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close menu on outside click
  useEffect(() => {
    if (!showMenu) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowMenu(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showMenu]);

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0 || !sessionId) return;

    setUploading(true);
    setShowMenu(false);

    try {
      if (files.length === 1) {
        // Single file upload
        const formData = new FormData();
        formData.append('file', files[0]);

        const params: Record<string, any> = {};
        if (projectId) params.project_id = projectId;

        const response = await apiClient.post(
          `/api/chat/${sessionId}/upload`,
          formData,
          { headers: { 'Content-Type': 'multipart/form-data' }, params }
        );

        onFileUploaded(response.data);
      } else {
        // Multiple files upload (also used for folder upload — webkitdirectory
        // populates a flat FileList, not a tree, so the same code path works).
        const formData = new FormData();
        for (let i = 0; i < files.length; i++) {
          // Preserve relative path if the browser provided it (folder upload
          // exposes files via File.webkitRelativePath).
          const f = files[i] as File & { webkitRelativePath?: string };
          // Use the basename so server-side dedup-by-name works correctly
          // across nested folder paths.
          formData.append('files', f, f.name);
        }

        const params: Record<string, any> = {};
        if (projectId) params.project_id = projectId;

        const response = await apiClient.post(
          `/api/chat/${sessionId}/upload-multiple`,
          formData,
          { headers: { 'Content-Type': 'multipart/form-data' }, params }
        );

        const uploadedFiles: SessionDocument[] = response.data || [];
        uploadedFiles.forEach(f => onFileUploaded(f));
        if (onMultipleUploaded) {
          onMultipleUploaded(uploadedFiles);
        }
      }

      // Notify any open Files panels to refresh their lists
      window.dispatchEvent(new CustomEvent('chat:files-changed'));
    } catch (error: any) {
      console.error('Failed to upload file(s):', error);
      alert(error.response?.data?.detail || 'Failed to upload file(s)');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
      if (folderInputRef.current) folderInputRef.current.value = '';
    }
  };

  const isDisabled = disabled || uploading || !sessionId;

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        multiple
        onChange={handleFileSelect}
        style={{ display: 'none' }}
        accept=".txt,.md,.pdf,.json,.py,.js,.ts,.tsx,.jsx,.java,.c,.cpp,.h,.hpp,.cs,.rb,.go,.rs,.php,.swift,.kt,.scala,.r,.sql,.sh,.bash,.doc,.docx,.html,.htm,.xml,.csv,.yaml,.yml,.rtf,.odt,.epub,.ppt,.pptx,.xls,.xlsx,.png,.jpg,.jpeg,.gif,.bmp,.tiff,.webp"
        disabled={isDisabled}
      />
      <input
        ref={folderInputRef}
        type="file"
        // @ts-ignore - webkitdirectory is not in TS types
        webkitdirectory=""
        directory=""
        multiple
        onChange={handleFileSelect}
        style={{ display: 'none' }}
        disabled={isDisabled}
      />
      <div className="relative" ref={menuRef}>
        <div className="flex items-center">
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isDisabled}
            className="p-2 rounded-l-lg transition-colors disabled:opacity-50"
            style={{
              backgroundColor: 'transparent',
              color: 'var(--color-text-muted)'
            }}
            onMouseEnter={(e) => {
              if (!isDisabled) {
                e.currentTarget.style.backgroundColor = 'var(--color-panel-dark)';
              }
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
            title={!sessionId ? "Start a chat session first" : "Upload document(s)"}
          >
            {uploading ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Paperclip className="w-5 h-5" />
            )}
          </button>
          <button
            onClick={() => !isDisabled && setShowMenu(s => !s)}
            disabled={isDisabled}
            className="p-1.5 rounded-r-lg transition-colors disabled:opacity-50 border-l"
            style={{
              backgroundColor: 'transparent',
              color: 'var(--color-text-muted)',
              borderColor: 'var(--color-border)',
            }}
            onMouseEnter={(e) => {
              if (!isDisabled) {
                e.currentTarget.style.backgroundColor = 'var(--color-panel-dark)';
              }
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
            title="Upload options"
          >
            <ChevronUp className="w-3 h-3" />
          </button>
        </div>
        {showMenu && (
          <div
            className="absolute bottom-full left-0 mb-1 bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg shadow-lg overflow-hidden w-64 z-50"
            style={{ backgroundColor: 'var(--color-panel-light)' }}
          >
            <button
              onClick={() => fileInputRef.current?.click()}
              className="w-full px-3 py-2 text-left text-xs flex items-center gap-2 hover:bg-gray-100 dark:hover:bg-panel-darker transition-colors"
              style={{ color: 'var(--color-text-primary)' }}
            >
              <FileUp className="w-4 h-4 flex-shrink-0" />
              <span className="flex-1">Upload file(s)</span>
            </button>
            <button
              onClick={() => folderInputRef.current?.click()}
              className="w-full px-3 py-2 text-left text-xs flex items-center gap-2 hover:bg-gray-100 dark:hover:bg-panel-darker transition-colors border-t"
              style={{ color: 'var(--color-text-primary)', borderColor: 'var(--color-border)' }}
            >
              <FolderUp className="w-4 h-4 flex-shrink-0" />
              <span className="flex-1">Upload folder</span>
              <span
                className="text-[10px] px-1.5 py-0.5 rounded flex-shrink-0"
                style={{ backgroundColor: 'var(--color-panel-darker)', color: 'var(--color-text-muted)' }}
              >
                recursive
              </span>
            </button>
          </div>
        )}
      </div>
    </>
  );
}
