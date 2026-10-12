/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { Plus, Loader2, FolderUp, FileUp } from 'lucide-react';
import { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import type { SessionDocument } from '../types/chat';
import apiClient from '../../../lib/api-client';

/** Menu width in px — needed to keep it on screen, so it is not just layout. */
const MENU_WIDTH = 240;

/** Gap between the button and the menu above it. */
const MENU_GAP = 6;

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
  // Viewport coordinates for the portalled menu. Computed when it opens rather
  // than left to CSS: an absolutely positioned menu would be laid out inside the
  // composer card, which clips its overflow to keep its rounded corners, and the
  // menu opens upward well past the card's top edge.
  const [menuPos, setMenuPos] = useState<{ left: number; bottom: number } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  // The portalled panel is no longer a descendant of menuRef, so outside-click
  // detection has to know about it separately.
  const panelRef = useRef<HTMLDivElement>(null);

  const isDisabled = disabled || uploading || !sessionId;

  const placeMenu = () => {
    const r = menuRef.current?.getBoundingClientRect();
    if (!r) return;
    setMenuPos({
      // Keep it inside the viewport on the right as well as the left.
      left: Math.max(8, Math.min(r.left, window.innerWidth - MENU_WIDTH - 8)),
      bottom: window.innerHeight - r.top + MENU_GAP,
    });
  };

  const toggleMenu = () => {
    if (isDisabled) return;
    if (showMenu) { setShowMenu(false); return; }
    placeMenu();
    setShowMenu(true);
  };

  // Close menu on outside click
  useEffect(() => {
    if (!showMenu) return;
    const handler = (e: MouseEvent) => {
      const t = e.target as Node;
      if (menuRef.current?.contains(t) || panelRef.current?.contains(t)) return;
      setShowMenu(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showMenu]);

  // Follow the button if the window is resized or anything scrolls while open.
  useEffect(() => {
    if (!showMenu) return;
    const update = () => placeMenu();
    window.addEventListener('resize', update);
    window.addEventListener('scroll', update, true);
    return () => {
      window.removeEventListener('resize', update);
      window.removeEventListener('scroll', update, true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
        {/* One circled "+", as in the DeepSeek Harness composer: 28px circle,
            14px stroke plus, subtle neutral fill, and the fill (not a border)
            is what marks hover. DSH pairs it with a 34px send circle, so the "+"
            reads as the smaller, quieter control; this app's send button is
            32px, and 28px keeps that same relationship.
            The button opens the upload menu rather than the picker directly —
            that is DSH's own pattern for its "+" (aria-haspopup + a menu), and
            it is what keeps "Upload folder" reachable now that the separate
            chevron is gone. */}
        <button
          type="button"
          onClick={toggleMenu}
          disabled={isDisabled}
          aria-label="Upload files or a folder"
          aria-haspopup="menu"
          aria-expanded={showMenu}
          className="w-7 h-7 rounded-full grid place-items-center flex-shrink-0
                     transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          style={{
            border: 'none',
            // Neutral translucent fill so one value works on the composer's
            // white (light themes) and #3c3c3c (dark) card alike.
            backgroundColor: showMenu ? 'rgba(128,128,128,0.28)' : 'rgba(128,128,128,0.18)',
            color: 'var(--color-text-primary)',
          }}
          onMouseEnter={(e) => { if (!isDisabled) e.currentTarget.style.backgroundColor = 'rgba(128,128,128,0.28)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = showMenu ? 'rgba(128,128,128,0.28)' : 'rgba(128,128,128,0.18)'; }}
          title={!sessionId ? 'Start a chat session first' : 'Upload files or a folder'}
        >
          {uploading ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Plus className="w-3.5 h-3.5" />
          )}
        </button>
        {/* Portalled to <body> so the composer card's overflow clip — which is
            what rounds its corners — cannot cut the menu off. The card is 90px
            tall and the menu opens upward, so it needs to escape the card
            entirely, not merely sit on top of it. */}
        {showMenu && menuPos && createPortal(
          <div
            ref={panelRef}
            role="menu"
            className="chat-composer-menu fixed border rounded-lg shadow-lg overflow-hidden z-[60]"
            style={{
              left: menuPos.left,
              bottom: menuPos.bottom,
              width: MENU_WIDTH,
              borderColor: 'var(--color-border-dark, #3c3c3c)',
            }}
          >
            <button
              role="menuitem"
              onClick={() => fileInputRef.current?.click()}
              className="w-full px-3 py-1.5 text-left text-[11px] flex items-center gap-2 transition-colors hover:bg-black/10"
              style={{ color: 'var(--color-text-primary)' }}
            >
              <FileUp className="w-3.5 h-3.5 flex-shrink-0" />
              <span className="flex-1">Upload file(s)</span>
            </button>
            <button
              role="menuitem"
              onClick={() => folderInputRef.current?.click()}
              className="w-full px-3 py-1.5 text-left text-[11px] flex items-center gap-2 transition-colors hover:bg-black/10 border-t"
              style={{ color: 'var(--color-text-primary)', borderColor: 'var(--color-border-dark, #3c3c3c)' }}
            >
              <FolderUp className="w-3.5 h-3.5 flex-shrink-0" />
              <span className="flex-1">Upload folder</span>
              <span
                className="text-[10px] px-1.5 py-0.5 rounded flex-shrink-0"
                style={{ backgroundColor: 'rgba(128,128,128,0.18)', color: 'var(--color-text-muted)' }}
              >
                recursive
              </span>
            </button>
          </div>,
          document.body
        )}
      </div>
    </>
  );
}
