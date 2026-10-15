/**
 * KnowledgeIndexPanel — give a record to every file already on disk that has none.
 *
 * Files can arrive in a knowledge base without a catalog record: copied in by hand, unzipped, or
 * restored from a backup. They are visible in the tree — which reads the filesystem — but invisible
 * to the document list and to anything that reads the catalog. This reconciles the two.
 *
 * It is a maintenance action, not part of normal use, which is why it lives in Settings rather than
 * beside the upload buttons.
 *
 * **It does not copy, move or rename anything.** It writes records. But it does have one removal
 * side effect, and it is stated here rather than discovered later: a knowledge base whose folder
 * holds nothing but its own manifest is an empty knowledge base — it lists no documents and never
 * will — so it is removed together with its catalog, along with any empty subfolders. Leaving either
 * behind would strand it, and the next scan would see a catalog with no folder.
 */
import { useState } from 'react';
import apiClient from '../../lib/api-client';
import type { SettingsPanelTokens } from './settingsPanelTokens';
import { ScanSearch, Loader, CheckCircle, AlertTriangle } from 'lucide-react';

interface BaseReport {
  knowledge: string;
  indexed: number;
  already_indexed: number;
  removed?: boolean;
  empty_folders_removed?: string[];
}

interface Props {
  /** Called after a run that changed anything, so base and document lists reload. */
  onIndexed: () => void;
  t: SettingsPanelTokens;
}

export default function KnowledgeIndexPanel({ onIndexed, t }: Props) {
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [bases, setBases] = useState<BaseReport[]>([]);
  const [removedBases, setRemovedBases] = useState<string[]>([]);
  const [removedFolders, setRemovedFolders] = useState(0);

  const run = async () => {
    setRunning(true);
    setMessage(null);
    setFailed(false);
    setBases([]);
    try {
      const resp: any = await apiClient.indexMissingKVDocuments();
      const data = resp?.data ?? resp ?? {};
      setMessage(data?.message || `Indexed ${data?.indexed ?? 0} file(s)`);
      setBases(Array.isArray(data?.bases) ? data.bases : []);
      setRemovedBases(Array.isArray(data?.removed_bases) ? data.removed_bases : []);
      setRemovedFolders(data?.removed_folders ?? 0);
      // Reload even when nothing was indexed: an empty knowledge base may have been removed, which
      // changes the list of bases.
      onIndexed();
    } catch (err: any) {
      setFailed(true);
      setMessage(`Failed: ${err?.response?.data?.detail || err?.message || 'Indexing failed'}`);
    } finally {
      setRunning(false);
    }
  };

  // Only the bases that did something are worth listing; "0 indexed, 0 already" is noise.
  const interesting = bases.filter(
    (b) => b.indexed > 0 || b.removed || (b.empty_folders_removed?.length ?? 0) > 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <div style={{ fontSize: 15, fontWeight: 500, color: t.textPrimary }}>
          Index files already on disk
        </div>
        <div style={{ marginTop: 4, fontSize: 12, lineHeight: '18px', color: t.textMuted }}>
          Gives a record to every file inside a knowledge base that does not have one — files copied
          in by hand, unzipped, or restored from a backup. The tree shows those files because it
          reads the disk, but the document list reads the catalog, so until they are indexed they
          are listed in one place and missing from the other.
        </div>
        <div style={{ marginTop: 4, fontSize: 12, lineHeight: '18px', color: t.textMuted }}>
          Nothing is copied, moved or renamed. Empty subfolders are tidied up, and a knowledge base
          holding nothing but its own manifest is removed with its catalog — it would never list
          anything, and leaving it behind would strand a catalog with no folder.
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <button
          type="button"
          onClick={run}
          disabled={running}
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '7px 16px', borderRadius: 10, fontSize: 13, fontFamily: 'inherit',
            border: 'none',
            cursor: running ? 'default' : 'pointer',
            background: running ? t.bg : t.primary,
            color: running ? t.textMuted : '#fff',
          }}
        >
          {running
            ? <Loader size={13} className="animate-spin" />
            : <ScanSearch size={13} />}
          {running ? 'Scanning…' : 'Scan and index'}
        </button>
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

      {interesting.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          {interesting.map((b) => (
            <div key={b.knowledge} style={{ fontSize: 12, color: t.textMuted }}>
              <span style={{ fontFamily: 'monospace', color: t.textPrimary }}>{b.knowledge}</span>
              {b.removed
                ? ' — removed (was empty)'
                : ` — ${b.indexed} indexed${(b.empty_folders_removed?.length ?? 0) > 0
                    ? `, ${b.empty_folders_removed!.length} empty folder(s) removed` : ''}`}
            </div>
          ))}
        </div>
      )}

      {(removedBases.length > 0 || removedFolders > 0) && (
        <div style={{ fontSize: 11.5, color: t.textMuted }}>
          {removedFolders > 0 && <>{removedFolders} empty folder(s) removed. </>}
          {removedBases.length > 0 && <>Empty knowledge base(s) removed: {removedBases.join(', ')}.</>}
        </div>
      )}
    </div>
  );
}
