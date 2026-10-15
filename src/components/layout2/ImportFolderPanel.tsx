/**
 * ImportFolderPanel — pick a folder, name the knowledge base it becomes.
 *
 * This is `upload folder`, with the one thing it lacks: a name field. The sidebar's folder button
 * takes the knowledge base name from the folder you happened to pick — fine when the folder is
 * already named what it should be, wrong when it is named after the job instead
 * (`Carrier-Researcher SS-华阳`). So the name is prefilled from the folder and editable.
 *
 * Two sources, because the folder can be in two places:
 *
 *   a path      the folder is already on the machine running the backend — nothing is transferred,
 *               which matters when "the machine running the backend" IS the machine you are sitting
 *               at, and the alternative is uploading a large folder to the computer it is already on
 *   a picker    the folder is somewhere the backend cannot see, so the browser sends it, using the
 *               same mechanism as `upload folder`: `webkitRelativePath` becomes the hierarchy, so
 *               everything below the picked folder is the path inside the knowledge base
 *
 * Whichever you fill in wins; setting one clears the other, because a mixture would silently ignore
 * one of them.
 *
 * It sits in Settings next to migration because both are "bring existing material in" rather than
 * ordinary work, and because after migration reports nothing left to do, this is what a user with a
 * folder somewhere else actually needs.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import apiClient from '../../lib/api-client';
import type { SettingsPanelTokens } from './settingsPanelTokens';
import { FolderUp, Loader, CheckCircle, AlertTriangle } from 'lucide-react';

interface Props {
  /** Called after a successful import, so the base list and document list reload. */
  onImported: () => void;
  /** Existing knowledge base names, offered as suggestions. */
  existingBases: string[];
  t: SettingsPanelTokens;
}

/** Mirrors `equivalence_key` on the server: case and separators do not make a new base. */
function equivalenceKey(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]/g, '');
}

export default function ImportFolderPanel({ onImported, existingBases, t }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [folderName, setFolderName] = useState('');
  const [path, setPath] = useState('');
  const [knowledge, setKnowledge] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  // `webkitdirectory` is not in the TS types and must be set on the element itself.
  useEffect(() => {
    const el = inputRef.current;
    if (el) {
      el.setAttribute('webkitdirectory', '');
      el.setAttribute('directory', '');
    }
  }, []);

  const trimmed = knowledge.trim();
  const existing = useMemo(
    () => existingBases.find((b) => equivalenceKey(b) === equivalenceKey(trimmed)),
    [existingBases, trimmed]
  );
  const folderCount = useMemo(() => {
    const dirs = new Set<string>();
    files.forEach((f) => {
      const rel = (f as any).webkitRelativePath || '';
      const parts = rel.split('/').filter(Boolean);
      if (parts.length > 2) dirs.add(parts.slice(1, -1).join('/'));
    });
    return dirs.size;
  }, [files]);

  const handlePick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files || []);
    setFiles(picked);
    setMessage(null);
    // The picked folder's own name is the knowledge base name, exactly as `upload folder` does —
    // the difference is that here it is a starting point you can change.
    setPath('');                      // one source at a time, so neither is silently ignored
    const first = ((picked[0] as any)?.webkitRelativePath || '').split('/').filter(Boolean)[0];
    if (first) {
      setFolderName(first);
      if (!knowledge.trim()) setKnowledge(first);
    }
  };

  const handlePathChange = (value: string) => {
    setPath(value);
    if (value.trim() && files.length) {
      setFiles([]);
      setFolderName('');
      if (inputRef.current) inputRef.current.value = '';
    }
    // A path's last segment is the folder's name, so it names the knowledge base the same way a
    // picked folder does — until the user types something of their own.
    const last = value.trim().replace(/[/\\]+$/, '').split(/[/\\]/).filter(Boolean).pop();
    if (last && !knowledge.trim()) setKnowledge(last);
  };

  const canImport = !!trimmed && (files.length > 0 || !!path.trim());

  const handleImport = async () => {
    if (!canImport) return;
    setBusy(true);
    setMessage(null);
    setFailed(false);
    try {
      if (path.trim() && files.length === 0) {
        // Already on this machine: copy straight into the knowledge root, transferring nothing.
        const res: any = await apiClient.importFolder({ path: path.trim(), knowledge: trimmed });
        const d = res?.data ?? res ?? {};
        const refused = d.refused?.[0];
        if (refused) {
          setFailed(true);
          setMessage(`Nothing imported — ${refused.name}: ${refused.reason}`);
        } else {
          setMessage(
            `Copied ${d.written ?? 0} file${(d.written ?? 0) === 1 ? '' : 's'} into `
            + `"${d.knowledge || trimmed}"`
            + (d.duplicates ? `, ${d.duplicates} already present` : '')
            + (d.merged_into ? ' (merged with the knowledge base already there)' : '') + '.');
        }
        onImported();
        setPath('');
        return;
      }
      // Everything BELOW the picked folder is the path inside the knowledge base: a file directly
      // in the picked folder has no inner path and goes to the base's root.
      const fileMetadata = files.map((f) => {
        const relPath: string = (f as any).webkitRelativePath || f.name;
        const inner = relPath.split('/').filter(Boolean).slice(1, -1);   // drop folder + filename
        const meta: any = {};
        if (inner.length >= 1) meta.industry = inner[0];
        if (inner.length >= 2) meta.player = inner[1];
        if (inner.length >= 3) meta.sub_category = inner[2];
        if (inner.length >= 4) meta.sub_department = inner[3];
        return meta;
      });

      await apiClient.uploadKVDocumentsBulk(trimmed, files, fileMetadata);
      setMessage(
        `Uploaded ${files.length} file${files.length === 1 ? '' : 's'} into `
        + `"${trimmed}"${existing ? ' (merged with the knowledge base already there)' : ''}.`);
      onImported();
      setFiles([]);
      setFolderName('');
      if (inputRef.current) inputRef.current.value = '';
    } catch (err: any) {
      setFailed(true);
      setMessage(`Failed: ${err?.response?.data?.detail || err?.message || 'import failed'}`);
    } finally {
      setBusy(false);
    }
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', height: 30, padding: '0 8px', boxSizing: 'border-box',
    background: t.bg, border: `1px solid ${t.border}`,
    borderRadius: 8, color: t.textPrimary, fontSize: 12.5, outline: 'none',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <div style={{ fontSize: 15, fontWeight: 500, color: t.textPrimary }}>
          Import a folder
        </div>
        <div style={{ marginTop: 4, fontSize: 12, lineHeight: '18px', color: t.textMuted }}>
          Name the knowledge base a folder becomes, and give the folder either way — by its path on
          this machine, or by picking it. Structure is kept either way, and files already there are
          left alone.
        </div>
      </div>

      <input
        ref={inputRef}
        type="file"
        onChange={handlePick}
        style={{ display: 'none' }}
      />

      <div>
        <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4 }}>
          Path on this machine
        </div>
        <input
          value={path}
          placeholder="/Users/you/Downloads/EBL_OS_docs — or pick the folder below"
          onChange={(e) => handlePathChange(e.target.value)}
          style={{ ...inputStyle, fontFamily: '"SF Mono", monospace', fontSize: 11.5 }}
        />
        <div style={{ marginTop: 4, fontSize: 11, color: t.textMuted }}>
          For a folder already on the machine running the backend. Nothing is transferred — the
          files are copied straight into the knowledge root.
        </div>
      </div>

      <div>
        <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4 }}>
          …or pick a folder
        </div>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
            width: '100%', padding: '9px 12px', boxSizing: 'border-box',
            background: 'transparent', border: `1px dashed ${t.border}`,
            borderRadius: 8, color: t.textMuted, fontSize: 12.5,
            fontFamily: 'inherit', cursor: 'pointer',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = t.hover; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
        >
          <FolderUp size={14} />
          {files.length === 0
            ? 'Select folder'
            : `${folderName || 'folder'} · ${files.length} file${files.length === 1 ? '' : 's'}`
              + (folderCount > 0 ? `, ${folderCount} subfolder${folderCount === 1 ? '' : 's'}` : '')}
        </button>
      </div>

      <div>
        <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4 }}>
          Knowledge base
        </div>
        <input
          value={knowledge}
          list="import-kb-names"
          placeholder="Prefilled from the folder — change it to whatever it should be called"
          onChange={(e) => setKnowledge(e.target.value)}
          style={{ ...inputStyle, borderColor: trimmed && !existing ? t.primary : t.border }}
        />
        <datalist id="import-kb-names">
          {existingBases.map((b) => <option key={b} value={b} />)}
        </datalist>
        <div style={{ marginTop: 4, fontSize: 11, color: t.textMuted }}>
          {!trimmed
            ? 'Name the knowledge base this folder becomes.'
            : existing
              ? <>merges into the existing <span style={{ fontFamily: 'monospace' }}>{existing}</span></>
              : <>a new knowledge base called <span style={{ fontFamily: 'monospace' }}>{trimmed}</span> will be created</>}
        </div>
      </div>

      {message && (
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: 6,
          fontSize: 12.5, color: failed ? '#e5484d' : t.textPrimary,
        }}>
          {failed
            ? <AlertTriangle size={14} color="#e5484d" style={{ marginTop: 2, flexShrink: 0 }} />
            : <CheckCircle size={14} color="#22c55e" style={{ marginTop: 2, flexShrink: 0 }} />}
          <span>{message}</span>
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <button
          type="button"
          onClick={handleImport}
          disabled={busy || !canImport}
          title={!trimmed ? 'Name a knowledge base first'
            : !canImport ? 'Give a path or pick a folder first' : undefined}
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '7px 16px', borderRadius: 10, fontSize: 13, fontFamily: 'inherit',
            border: 'none',
            cursor: busy || !canImport ? 'default' : 'pointer',
            background: busy || !canImport ? t.bg : t.primary,
            color: busy || !canImport ? t.textMuted : '#fff',
          }}
        >
          {busy && <Loader size={13} className="animate-spin" />}
          {busy
            ? 'Importing…'
            : path.trim() && files.length === 0
              ? 'Import from path'
              : 'Upload folder'}
        </button>
      </div>
    </div>
  );
}
