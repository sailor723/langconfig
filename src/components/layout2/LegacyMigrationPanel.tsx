/**
 * LegacyMigrationPanel — bring knowledge out of the old per-project layout.
 *
 * Lives in Settings rather than beside the upload buttons, because it is not a normal operation:
 * it is run once per machine, after a teammate's data has arrived in the old layout, and then never
 * again. Putting it next to "upload file" invites it to be used as one.
 *
 * This is NOT the upload-folder button, and the difference matters:
 *
 *   upload folder   you pick a folder on YOUR machine; the bytes travel to the server; the
 *                   knowledge base is FORCED to be the folder's own name; one folder per pick.
 *   migrate (here)  the folder is already on the SERVER in `data/documents/project_<id>/<folder>`;
 *                   nothing travels; you TYPE the name it becomes; many folders in one run.
 *
 * So the name is a field, not a consequence of what you picked — which is the point, because a
 * folder is often named after the job rather than the knowledge (`Carrier-Researcher SS-华阳`).
 *
 * Only selected folders are read. Files loose at a project root are not this operation's business:
 * they have no folder to inherit a name from, and they go through the ordinary upload button.
 *
 * The copy leaves the old folder byte-for-byte intact, so there is nothing to reverse, and content
 * already present is skipped by hash, so running it twice is safe. A folder that has been migrated
 * is recorded in the target knowledge base's own manifest, so it stops being offered here — across
 * reloads and across browsers, not just for this session.
 */
import { useEffect, useMemo, useState } from 'react';
import apiClient from '../../lib/api-client';
import { Loader, AlertTriangle, CheckCircle, RefreshCw } from 'lucide-react';

import type { SettingsPanelTokens } from './settingsPanelTokens';

interface LegacyFolder {
  folder: string;
  files: number;
  /** Already migrated — recorded in the target knowledge base's manifest. */
  migrated?: boolean;
  /** Migrated once, but the folder has been touched since; a repeat run would bring in the new. */
  changed?: boolean;
  migrated_into?: string;
}

interface LegacyProject {
  project: string;
  folders: LegacyFolder[];
}

interface MigrationResult {
  project: string;
  folder: string;
  knowledge: string;
  ok: boolean;
  created?: boolean;
  written?: number;
  duplicates?: number;
  refused?: Array<{ name: string; reason: string }>;
  error?: string;
}

interface Props {
  /** Called after a run that wrote something, so the base list and document list reload. */
  onMigrated: () => void;
  /** Names of the knowledge bases that already exist, for the "merges into" hint. */
  existingBases: string[];
  t: SettingsPanelTokens;
}

/**
 * Two names that differ only by case or separator are the same knowledge base. Mirrors
 * `equivalence_key` on the server, so this hint agrees with what the merge will actually do.
 */
function equivalenceKey(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]/g, '');
}

export default function LegacyMigrationPanel({ onMigrated, existingBases, t }: Props) {
  const [projects, setProjects] = useState<LegacyProject[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<MigrationResult[] | null>(null);
  // Immediate feedback between a run finishing and the list being refetched. The durable answer is
  // the server's `migrated` flag, which comes from the knowledge base's own manifest; this only
  // ORs with it.
  const [justMigrated, setJustMigrated] = useState<Record<string, boolean>>({});

  const load = useMemo(() => async () => {
    setLoading(true);
    try {
      const res: any = await apiClient.listLegacyKnowledge();
      const data = res?.data ?? res ?? {};
      const list: LegacyProject[] = Array.isArray(data.projects) ? data.projects : [];
      setProjects(list);
      const nextNames: Record<string, string> = {};
      const nextSelected: Record<string, boolean> = {};
      list.forEach((p) => {
        p.folders.forEach((f) => {
          const key = `${p.project}::${f.folder}`;
          // Prefilled with the folder's own name and pre-ticked: the common case is that the folder
          // is already named what it should be, and the field is there for when it is not.
          nextNames[key] = f.folder.trim();
          nextSelected[key] = !f.migrated;
        });
      });
      setNames(nextNames);
      setSelected(nextSelected);
    } catch {
      setProjects([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const existingKeys = useMemo(
    () => new Set(existingBases.map(equivalenceKey)),
    [existingBases]
  );

  const isDone = (project: string, f: LegacyFolder) =>
    !!f.migrated || !!justMigrated[`${project}::${f.folder}`];

  const chosen = useMemo(() => {
    const out: Array<{ project: string; folder: string; knowledge: string }> = [];
    projects.forEach((p) => {
      p.folders.forEach((f) => {
        const key = `${p.project}::${f.folder}`;
        if (!selected[key] || isDone(p.project, f)) return;   // already done stays done
        const name = (names[key] || '').trim();
        if (name) out.push({ project: p.project, folder: f.folder, knowledge: name });
      });
    });
    return out;
  }, [projects, selected, names, justMigrated]);

  const folderCount = projects.reduce((n, p) => n + p.folders.length, 0);
  const remaining = projects.reduce(
    (n, p) => n + p.folders.filter((f) => !isDone(p.project, f)).length, 0);
  const allDone = folderCount > 0 && remaining === 0;

  const handleRun = async () => {
    if (chosen.length === 0) return;
    setRunning(true);
    try {
      const res: any = await apiClient.migrateLegacyFolders(chosen);
      const data = res?.data ?? res ?? {};
      const list: MigrationResult[] = Array.isArray(data.results) ? data.results : [];
      setResults(list);
      setJustMigrated((m) => {
        const next = { ...m };
        list.forEach((r) => {
          if (r.ok && r.project && r.folder) next[`${r.project}::${r.folder}`] = true;
        });
        return next;
      });
      // Refresh even on partial success: a knowledge base that was created is real whether or not
      // its neighbour failed.
      if (list.some((r) => (r.written ?? 0) > 0)) onMigrated();
    } catch (err: any) {
      setResults([{
        project: '', folder: '', knowledge: '', ok: false,
        error: err?.response?.data?.detail || err?.message || 'Migration failed',
      }]);
    } finally {
      setRunning(false);
    }
  };

  const inputStyle: React.CSSProperties = {
    height: 28, padding: '0 8px', boxSizing: 'border-box',
    background: t.bg, border: `1px solid ${t.border}`,
    borderRadius: 8, color: t.textPrimary, fontSize: 12, outline: 'none',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ flex: 1, fontSize: 15, fontWeight: 500, color: t.textPrimary }}>
            Knowledge migration
          </div>
          <button
            type="button" onClick={load} disabled={loading}
            title="Scan the old layout again"
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              width: 28, height: 28, border: 'none', borderRadius: 8,
              background: 'transparent', color: t.textMuted,
              cursor: loading ? 'default' : 'pointer',
            }}
            onMouseEnter={(e) => { if (!loading) e.currentTarget.style.background = t.hover; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : undefined} />
          </button>
        </div>
        <div style={{ marginTop: 4, fontSize: 12, lineHeight: '18px', color: t.textMuted }}>
          Folders already on this machine, under the old per-project layout. Pick the ones to bring
          across and name the knowledge base each becomes. This is a one-time step — it runs after a
          teammate's data has arrived, not as part of normal use.
        </div>
      </div>

      {loading && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: t.textMuted, fontSize: 12 }}>
          <Loader size={12} className="animate-spin" />
          Looking at the old layout…
        </div>
      )}

      {!loading && folderCount === 0 && (
        <div style={{ fontSize: 12, color: t.textMuted }}>
          Nothing left in the old layout — every folder has already been migrated.
        </div>
      )}

      {!loading && folderCount > 0 && (
        <>
          <div style={{ fontSize: 12, color: t.textMuted }}>
            {allDone
              ? 'Every folder here has been migrated. The old layout is left in place — it is the '
                + 'source, not a copy, so nothing here deletes it.'
              : <>
                  {remaining} folder{remaining === 1 ? '' : 's'} available. Files are copied, so the
                  old layout is left exactly as it is, and documents already here are skipped.
                </>}
          </div>

          {projects.map((p) => (
            <div key={p.project} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ fontSize: 11, color: t.textMuted, fontFamily: 'monospace' }}>
                {p.project}
              </div>
              {p.folders.map((f) => {
                const key = `${p.project}::${f.folder}`;
                const name = names[key] ?? '';
                const empty = name.trim().length === 0;
                const done = isDone(p.project, f);
                const willMerge = !empty && !done && existingKeys.has(equivalenceKey(name));
                return (
                  <div
                    key={key}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10,
                      padding: '7px 10px', borderRadius: 10,
                      background: t.bg, border: `1px solid ${t.border}`,
                      opacity: done ? 0.65 : 1,
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={!!selected[key] && !done}
                      disabled={done}
                      onChange={(e) => setSelected((s) => ({ ...s, [key]: e.target.checked }))}
                      style={{ flexShrink: 0 }}
                    />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div
                        title={f.folder}
                        style={{
                          fontSize: 12.5, color: t.textPrimary,
                          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                        }}
                      >
                        {f.folder}
                      </div>
                      <div style={{
                        fontSize: 11,
                        color: done ? '#22c55e' : f.changed ? '#e0a020' : t.textMuted,
                      }}>
                        {done
                          ? `migrated${f.migrated_into ? ` into ${f.migrated_into}` : ''}`
                          : f.changed
                            ? `${f.files} files · migrated earlier, folder has changed since`
                            : `${f.files} file${f.files === 1 ? '' : 's'}`}
                        {willMerge && ' · merges into the knowledge base that already exists'}
                      </div>
                    </div>
                    <input
                      value={name}
                      placeholder="knowledge base name"
                      disabled={done}
                      onChange={(e) => setNames((n) => ({ ...n, [key]: e.target.value }))}
                      style={{
                        ...inputStyle,
                        width: 210, flexShrink: 0,
                        borderColor: !done && empty ? '#e5484d' : t.border,
                      }}
                    />
                  </div>
                );
              })}
            </div>
          ))}
        </>
      )}

      {results && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ fontSize: 11, color: t.textMuted, textTransform: 'uppercase', letterSpacing: 0.4 }}>
            Result
          </div>
          {results.map((r, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 6, fontSize: 12 }}>
              {r.ok
                ? <CheckCircle size={14} color="#22c55e" style={{ marginTop: 2, flexShrink: 0 }} />
                : <AlertTriangle size={14} color="#e5484d" style={{ marginTop: 2, flexShrink: 0 }} />}
              <div style={{ color: t.textPrimary }}>
                {r.error ? r.error : (
                  <>
                    <span style={{ fontFamily: 'monospace' }}>{r.knowledge}</span>
                    {' — '}
                    {r.written} copied
                    {r.created ? ', knowledge base created' : ', merged'}
                    {r.duplicates ? `, ${r.duplicates} already present` : ''}
                  </>
                )}
                {!!r.refused?.length && (
                  <div style={{ fontSize: 11, color: '#e5484d' }}>
                    {r.refused.map((x) => `${x.name}: ${x.reason}`).join('; ')}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <button
          type="button"
          onClick={handleRun}
          disabled={running || chosen.length === 0}
          title={allDone
            ? 'Every folder has been migrated'
            : chosen.length === 0 ? 'Select at least one folder' : undefined}
          style={{
            padding: '7px 16px', borderRadius: 10, fontSize: 13, fontFamily: 'inherit',
            border: 'none',
            cursor: running || chosen.length === 0 ? 'default' : 'pointer',
            background: running || chosen.length === 0 ? t.bg : t.primary,
            color: running || chosen.length === 0 ? t.textMuted : '#fff',
          }}
        >
          {running
            ? 'Migrating…'
            : allDone
              ? 'Migration complete'
              : chosen.length === 0
                ? 'Nothing selected'
                : `Migrate ${chosen.length} folder${chosen.length === 1 ? '' : 's'}`}
        </button>
      </div>
    </div>
  );
}
