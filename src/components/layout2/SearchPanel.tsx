/**
 * SearchPanel — the sidebar's search.
 *
 * One request to `GET /api/workspace/search`, which scans **this account's workspace files** and
 * **workflow definitions** on the server and answers with file, kind, line, column and snippet.
 *
 * What it replaced, and why it is written down: the panel used to list the workflows and then ask for
 * each one's generated code, grepping the answers in the browser — N+1 requests whose per-workflow cost
 * is a full LangGraph code generation, and a "file search" that could only ever find workflows. The
 * history is in docs/specs/search-panel-honesty.md; this comment keeps only the rule that matters:
 * **the panel asks once and the server answers**, because the fan-out was the bug.
 *
 * Spec: docs/specs/search-panel-honesty.md (AC3 one request, AC4 visible failures, AC5 no dead replace
 * control, AC6 the docstring describes the behaviour). Ticket: docs/tickets/002-panel-uses-the-endpoint.md
 */
import { useState, useCallback, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useLayoutTokens } from './tokens';
import { useLayoutState, type Tab, type ActivityId } from './useLayout';
import { Search, X, ChevronRight, ChevronDown, File, Workflow, Loader2, AlertTriangle } from 'lucide-react';
import { WARN } from '../../features/ontology/ui';

/** Mirrors the server's cap (`MAX_QUERY_CHARS` in api/workspace/files_routes.py). */
const MAX_QUERY_CHARS = 200;

interface Match {
  file: string;
  kind: 'file' | 'workflow';
  line: number;
  column: number;
  snippet: string;
}

interface ResultGroup {
  key: string;
  label: string;
  kind: 'file' | 'workflow';
  matches: Match[];
}

interface SearchPanelProps {
  onClose: () => void;
}

export default function SearchPanel({ onClose }: SearchPanelProps) {
  const t = useLayoutTokens();
  const { t: tr } = useTranslation('chat');
  const { openTab } = useLayoutState();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [groups, setGroups] = useState<ResultGroup[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [searched, setSearched] = useState(false);
  /** The failure, as the user should see it: an empty list and a dead backend must not look alike. */
  const [error, setError] = useState<{ status: number | null; text: string } | null>(null);
  const [truncated, setTruncated] = useState(false);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const runSearch = useCallback(async (term: string) => {
    const q = term.trim();
    if (!q) return;
    setSearching(true);
    setSearched(true);
    setError(null);

    try {
      // ONE request. No per-workflow fan-out: the server walks its own tree and returns matches.
      const apiClient = (await import('../../lib/api-client')).default;
      const res = await apiClient.get('/api/workspace/search', { params: { q } });
      const matches: Match[] = Array.isArray(res?.data?.matches) ? res.data.matches : [];

      const byFile = new Map<string, ResultGroup>();
      for (const m of matches) {
        const key = `${m.kind}:${m.file}`;
        const group = byFile.get(key) || {
          key, label: m.file, kind: m.kind, matches: [],
        };
        group.matches.push(m);
        byFile.set(key, group);
      }
      const ordered = [...byFile.values()];
      setGroups(ordered);
      setTruncated(Boolean(res?.data?.truncated));
      setExpanded(new Set(ordered.map(g => g.key)));
    } catch (err: any) {
      // axios puts the status on the response; a network failure has none, which is itself the message.
      const status = err?.response?.status ?? null;
      const detail = err?.response?.data?.detail
        || (status === null ? 'the backend did not answer' : err?.message)
        || 'search failed';
      setError({ status, text: String(detail) });
      setGroups([]);
      setTruncated(false);
    } finally {
      setSearching(false);
    }
  }, []);

  // Debounced: one request per pause, not one per keystroke.
  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setGroups([]);
      setSearched(false);
      setError(null);
      setTruncated(false);
      return;
    }
    const timer = setTimeout(() => { void runSearch(q); }, 300);
    return () => clearTimeout(timer);
  }, [query, runSearch]);

  const toggle = (key: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const openMatch = async (group: ResultGroup, match: Match) => {
    if (group.kind === 'workflow') {
      const tab: Tab = {
        id: group.key,
        label: group.label.replace(/^workflow:/, ''),
        viewType: 'workflow' as ActivityId,
        data: { highlightLine: match.line },
      };
      openTab(tab);
      return;
    }
    // A workspace file: fetch its text so the editor opens with content, not a blank pane.
    try {
      const apiClient = (await import('../../lib/api-client')).default;
      const res = await apiClient.get('/api/workspace/by-path/content', {
        params: { file_path: group.label },
        responseType: 'text',
      });
      const tab: Tab = {
        id: group.label,
        label: group.label.split('/').pop() || group.label,
        viewType: 'library' as ActivityId,
        data: { path: group.label, content: res.data, highlightLine: match.line },
      };
      openTab(tab);
    } catch (err: any) {
      // Do not pretend the file opened: say why.
      const status = err?.response?.status ?? null;
      setError({
        status,
        text: `could not open ${group.label}${status ? ` (HTTP ${status})` : ''}`,
      });
    }
  };

  const matchCount = groups.reduce((sum, g) => sum + g.matches.length, 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', fontSize: 13, color: t.textPrimary }}>
      <div style={{ padding: '10px 12px', borderBottom: `1px solid ${t.border}` }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <span style={{ fontWeight: 600, fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.05em', color: t.textMuted }}>
            Search
          </span>
          <button
            onClick={onClose}
            title="close search"
            style={{ width: 20, height: 20, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', borderRadius: 4, color: t.textMuted, cursor: 'pointer' }}
          >
            <X size={14} />
          </button>
        </div>

        <div style={{ position: 'relative' }}>
          <Search size={13} style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', color: t.textMuted }} />
          <input
            ref={inputRef}
            value={query}
            maxLength={MAX_QUERY_CHARS}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') void runSearch(query); }}
            placeholder={tr('sp_search_files_ph')}
            spellCheck={false}
            style={{
              width: '100%', padding: '6px 8px 6px 28px', fontSize: 13,
              background: t.bgInput, border: `1px solid ${t.border}`, borderRadius: 6,
              color: t.textPrimary, outline: 'none', boxSizing: 'border-box',
            }}
          />
          {searching && (
            <Loader2 size={13} className="animate-spin"
                     style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)', color: t.textMuted }} />
          )}
        </div>

        <div style={{ marginTop: 6, fontSize: 10.5, color: t.textDim, lineHeight: 1.5 }}>
          workspace files · workflow definitions
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {/* A failure is shown, not swallowed: the old version rendered the same empty list for
            "no matches" and "the backend is down", which is the difference a reader needs most. */}
        {error && (
          <div style={{ margin: 10, padding: '8px 10px', borderRadius: 8, border: `1px solid ${t.border}`, background: `${WARN}14`, color: t.textPrimary, fontSize: 12 }}>
            <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
              <AlertTriangle size={13} style={{ flex: 'none', marginTop: 2 }} />
              <span>
                search failed
                {error.status !== null ? ` · HTTP ${error.status}` : ''}
                <br />
                <span style={{ color: t.textMuted, fontSize: 11.5 }}>{error.text}</span>
              </span>
            </div>
          </div>
        )}

        {!searching && !error && searched && groups.length === 0 && (
          <div style={{ padding: 20, textAlign: 'center', color: t.textMuted, fontStyle: 'italic' }}>
            No results found for "{query}"
          </div>
        )}

        {!error && groups.length > 0 && (
          <>
            <div style={{ padding: '6px 12px', fontSize: 11, color: t.textDim }}>
              {matchCount} match{matchCount !== 1 ? 'es' : ''} in {groups.length} source{groups.length !== 1 ? 's' : ''}
              {truncated && <span style={{ color: WARN }}> · truncated, narrow the query</span>}
            </div>
            {groups.map(group => (
              <div key={group.key}>
                <div
                  onClick={() => toggle(group.key)}
                  style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '4px 8px', cursor: 'pointer', fontWeight: 500, fontSize: 12 }}
                  onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                >
                  {expanded.has(group.key) ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  {group.kind === 'workflow'
                    ? <Workflow size={12} style={{ opacity: 0.5 }} />
                    : <File size={12} style={{ opacity: 0.5 }} />}
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {group.kind === 'workflow' ? group.label.replace(/^workflow:/, '') : group.label}
                  </span>
                  <span style={{ fontSize: 11, color: t.textDim }}>{group.matches.length}</span>
                </div>

                {expanded.has(group.key) && group.matches.map((match, mi) => (
                  <div
                    key={`${match.line}-${mi}`}
                    onClick={() => void openMatch(group, match)}
                    onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                    style={{ display: 'flex', alignItems: 'baseline', gap: 8, padding: '2px 8px 2px 28px', fontSize: 12, cursor: 'pointer' }}
                  >
                    <span style={{ fontSize: 11, color: t.textDim, flexShrink: 0, minWidth: 28, textAlign: 'right' }}>
                      {match.line}
                    </span>
                    <span style={{
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      fontFamily: '"SF Mono", "Fira Code", monospace', fontSize: 11, color: t.textMuted,
                    }}>
                      {highlightMatch(match.snippet, query, t.accent)}
                    </span>
                  </div>
                ))}
              </div>
            ))}
          </>
        )}

        {!searching && !searched && (
          <div style={{ padding: 20, textAlign: 'center', color: t.textDim, fontSize: 12 }}>
            Search your workspace files and your workflow definitions
          </div>
        )}
      </div>
    </div>
  );
}

// ── Highlight matched text in a line ──────────────────────

function highlightMatch(text: string, query: string, accentColor: string): React.ReactNode {
  const q = query.trim();
  if (!q) return text;
  const idx = text.toLowerCase().indexOf(q.toLowerCase());
  if (idx === -1) return text;
  return (
    <>
      {text.slice(0, idx)}
      <span style={{ background: `${accentColor}33`, borderRadius: 2, padding: '0 1px' }}>
        {text.slice(idx, idx + q.length)}
      </span>
      {text.slice(idx + q.length)}
    </>
  );
}
