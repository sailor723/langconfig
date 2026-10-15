/**
 * UploadFilesDialog — upload files into a knowledge base you name.
 *
 * Why a name field exists at all: the upload path used to require a knowledge base to be selected
 * already, and if none was, clicking the button did nothing at all — no error, no message, just a
 * picker that appeared to work and files that went nowhere. Worse, there was no way to *create* a
 * knowledge base from this button with a name of your choosing: `upload folder` takes the name from
 * the folder you pick, and migration takes it from a folder already on the server. Files had no
 * route to a new, deliberately named knowledge base.
 *
 * Now the name is a field. It is a combobox rather than a plain dropdown: pick an existing
 * knowledge base from the list, or type a new name and it is created. Naming something is the point,
 * and a closed list cannot be used to name anything.
 *
 * The scope rule is deliberate. Files go to the knowledge base you name, at its root — except when
 * the name is the base you are already scoped into, in which case the scope's path is kept, so
 * "upload here means here" still holds for the common case. A folder path from one knowledge base
 * means nothing inside another.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import type { LayoutTokens } from './tokens';
import apiClient from '../../lib/api-client';
import { FileUp, Loader, X } from 'lucide-react';

interface Props {
  open: boolean;
  onClose: () => void;
  /** Called after a successful upload, so the base list and document list reload. */
  onUploaded: (knowledge: string) => void;
  /** The knowledge base currently in scope, used to prefill the name. */
  currentKnowledge?: string;
  /** Folder inside the current knowledge base, e.g. `eyewear_industry/新溢眼镜`. */
  scopeFolder?: string;
  /** Existing knowledge base names, offered as suggestions. */
  existingBases: string[];
  /** Files to start with, when another control already gathered them. */
  initialFiles?: File[];
  t: LayoutTokens;
}

/** Mirrors `equivalence_key` on the server: case and separators do not make a new knowledge base. */
function equivalenceKey(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]/g, '');
}

export default function UploadFilesDialog({
  open, onClose, onUploaded, currentKnowledge, scopeFolder, existingBases, initialFiles, t,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [knowledge, setKnowledge] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setKnowledge(currentKnowledge || '');
    // Seeded when a control already gathered files — picking them again would be busywork.
    setFiles(initialFiles || []);
    setError(null);
  }, [open, currentKnowledge, initialFiles]);

  const trimmed = knowledge.trim();
  const existing = useMemo(
    () => existingBases.find((b) => equivalenceKey(b) === equivalenceKey(trimmed)),
    [existingBases, trimmed]
  );

  // The scope's path only means anything inside the knowledge base it came from, so it is dropped
  // when the name points somewhere else — otherwise files land in a folder that belongs to another
  // base, which is how a document ends up somewhere nobody looks for it.
  const keepScope = !!existing && !!currentKnowledge
    && equivalenceKey(existing) === equivalenceKey(currentKnowledge);
  const scopeParts = keepScope && scopeFolder ? scopeFolder.split('/').filter(Boolean) : [];

  const totalBytes = files.reduce((n, f) => n + f.size, 0);

  const handleUpload = async () => {
    if (!trimmed || files.length === 0) return;
    setUploading(true);
    setError(null);
    try {
      const scopeMeta: any = {};
      if (scopeParts.length >= 1) scopeMeta.industry = scopeParts[0];
      if (scopeParts.length >= 2) scopeMeta.player = scopeParts[1];
      if (scopeParts.length >= 3) scopeMeta.sub_category = scopeParts[2];
      if (scopeParts.length >= 4) scopeMeta.sub_department = scopeParts[3];

      const fileMetadata = files.map((f) => {
        const relPath: string = (f as any).webkitRelativePath || f.name;
        const meta: any = { ...scopeMeta };
        const parts = relPath.split('/').filter(Boolean);
        // A picked folder's own name is not a folder inside the base — it names a base. Only a
        // *nested* path adds levels.
        if (parts.length >= 3) meta.industry = parts[1];
        if (parts.length >= 4) meta.player = parts[2];
        if (parts.length >= 5) meta.sub_category = parts[3];
        if (parts.length >= 6) meta.sub_department = parts[4];
        return meta;
      });

      await apiClient.uploadKVDocumentsBulk(trimmed, files, fileMetadata);
      onUploaded(trimmed);
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  if (!open) return null;

  const inputStyle: React.CSSProperties = {
    width: '100%', height: 30, padding: '0 8px', boxSizing: 'border-box',
    background: t.bgInput, border: `1px solid ${t.border}`,
    borderRadius: 4, color: t.textPrimary, fontSize: 12.5, outline: 'none',
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(0,0,0,0.45)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 440, maxWidth: '92vw',
          background: t.bgSidebar, border: `1px solid ${t.border}`,
          borderRadius: 8, padding: 16, display: 'flex', flexDirection: 'column', gap: 12,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <FileUp size={15} color={t.textMuted} />
          <div style={{ flex: 1, fontSize: 14, fontWeight: 600, color: t.textPrimary }}>
            Upload files
          </div>
          <button
            onClick={onClose}
            title="Close"
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              width: 22, height: 22, border: 'none', borderRadius: 3,
              background: 'transparent', color: t.textMuted, cursor: 'pointer',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = t.bgHover; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
          >
            <X size={14} />
          </button>
        </div>

        <div>
          <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4 }}>
            Knowledge base
          </div>
          <input
            value={knowledge}
            list="upload-kb-names"
            placeholder="Pick one, or type a new name"
            onChange={(e) => setKnowledge(e.target.value)}
            style={{
              ...inputStyle,
              borderColor: trimmed && !existing ? t.accent : t.border,
            }}
          />
          <datalist id="upload-kb-names">
            {existingBases.map((b) => <option key={b} value={b} />)}
          </datalist>
          <div style={{ marginTop: 4, fontSize: 11, color: t.textMuted }}>
            {!trimmed
              ? 'Name the knowledge base these files belong to.'
              : existing
                ? <>into the existing <span style={{ fontFamily: 'monospace' }}>{existing}</span>
                    {keepScope && scopeParts.length > 0 && <> · folder {scopeFolder}</>}</>
                : <>a new knowledge base called <span style={{ fontFamily: 'monospace' }}>{trimmed}</span> will be created</>}
          </div>
        </div>

        <div>
          <input
            ref={inputRef}
            type="file"
            multiple
            onChange={(e) => setFiles(Array.from(e.target.files || []))}
            style={{ display: 'none' }}
          />
          <button
            onClick={() => inputRef.current?.click()}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
              width: '100%', padding: '8px 12px', boxSizing: 'border-box',
              background: 'transparent', border: `1px dashed ${t.border}`,
              borderRadius: 4, color: t.textMuted, fontSize: 12.5,
              fontFamily: 'inherit', cursor: 'pointer',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = t.bgHover; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
          >
            <FileUp size={13} />
            {files.length === 0
              ? 'Choose files'
              : `${files.length} file${files.length === 1 ? '' : 's'} · ${(totalBytes / 1024).toFixed(0)} KB`}
          </button>
          {files.length > 0 && (
            <div style={{ marginTop: 5, fontSize: 11, color: t.textMuted }}>
              {files.slice(0, 4).map((f) => f.name).join(', ')}
              {files.length > 4 ? `, and ${files.length - 4} more` : ''}
            </div>
          )}
        </div>

        {error && (
          <div style={{ fontSize: 11.5, color: '#e5484d' }}>{error}</div>
        )}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button
            onClick={onClose}
            style={{
              padding: '6px 14px', borderRadius: 4, cursor: 'pointer',
              background: 'transparent', border: `1px solid ${t.border}`,
              color: t.textPrimary, fontSize: 12.5, fontFamily: 'inherit',
            }}
          >Cancel</button>
          <button
            onClick={handleUpload}
            disabled={uploading || !trimmed || files.length === 0}
            title={!trimmed ? 'Name a knowledge base first'
              : files.length === 0 ? 'Choose files first' : undefined}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '6px 14px', borderRadius: 4, fontSize: 12.5, fontFamily: 'inherit',
              border: 'none',
              cursor: uploading || !trimmed || files.length === 0 ? 'default' : 'pointer',
              background: uploading || !trimmed || files.length === 0 ? t.bgContent : t.accent,
              color: uploading || !trimmed || files.length === 0 ? t.textMuted : '#fff',
            }}
          >
            {uploading && <Loader size={12} style={{ animation: 'spin 1s linear infinite' }} />}
            {uploading ? 'Uploading…' : 'Upload'}
          </button>
        </div>
      </div>
    </div>
  );
}
