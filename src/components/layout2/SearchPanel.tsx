/**
 * SearchPanel — VS Code-style search-in-files sidebar panel.
 *
 * Shows a search input with optional replace field, then lists
 * results grouped by file. Clicking a result navigates to that file.
 */
import { useState, useCallback, useRef, useEffect } from 'react';
import { useLayoutTokens } from './tokens';
import { useLayoutState, type Tab, type ActivityId } from './useLayout';
import { Search, X, ArrowRight, ChevronRight, ChevronDown, File, Loader } from 'lucide-react';

// ── Mock search results for demo ─────────────────────────
// In production, this would call a backend search API.

interface SearchMatch {
  line: number;
  content: string;
  column?: number;
}

interface SearchResult {
  fileName: string;
  fileId: string;
  viewType: string;
  matches: SearchMatch[];
}

interface SearchPanelProps {
  onClose: () => void;
}

export default function SearchPanel({ onClose }: SearchPanelProps) {
  const t = useLayoutTokens();
  const { openTab } = useLayoutState();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState('');
  const [replaceText, setReplaceText] = useState('');
  const [showReplace, setShowReplace] = useState(false);
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [expandedFiles, setExpandedFiles] = useState<Set<string>>(new Set());
  const [searched, setSearched] = useState(false);

  // Focus search input on mount
  useEffect(() => { inputRef.current?.focus(); }, []);

  const handleSearch = useCallback(async () => {
    if (!query.trim()) return;
    setSearching(true);
    setSearched(true);

    const apiClient = (await import('../../lib/api-client')).default;

    try {
      const res = await apiClient.listWorkflows();
      const workflows = Array.isArray(res.data) ? res.data : (res.data?.items || res.data?.workflows || []);
      const q = query.toLowerCase();

      const found: SearchResult[] = [];

      for (const wf of workflows) {
        const wfId = wf.id;
        if (!wfId) continue;

        try {
          const codeRes = await apiClient.getWorkflowCode(wfId);
          const code = typeof codeRes.data === 'string' ? codeRes.data : JSON.stringify(codeRes.data, null, 2);
          const lines = code.split('\n');
          const matches: SearchMatch[] = [];

          lines.forEach((line: string, i: number) => {
            const idx = line.toLowerCase().indexOf(q);
            if (idx !== -1) {
              matches.push({ line: i + 1, content: line.trim(), column: idx + 1 });
            }
          });

          if (matches.length > 0) {
            found.push({
              fileName: wf.name || `Workflow #${wfId}`,
              fileId: `wf-${wfId}`,
              viewType: 'workflow',
              matches,
            });
          }
        } catch {
          // Skip workflows we can't read
        }
      }

      setResults(found);
      setExpandedFiles(new Set(found.map(r => r.fileId)));
    } catch {
      // No results on error
    } finally {
      setSearching(false);
    }
  }, [query]);

  // Debounced search
  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      setSearched(false);
      return;
    }
    const timer = setTimeout(handleSearch, 300);
    return () => clearTimeout(timer);
  }, [query, handleSearch]);

  const toggleExpand = (fileId: string) => {
    setExpandedFiles(prev => {
      const next = new Set(prev);
      if (next.has(fileId)) next.delete(fileId);
      else next.add(fileId);
      return next;
    });
  };

  const openResult = (result: SearchResult, match?: SearchMatch) => {
    const tab: Tab = {
      id: result.fileId,
      label: result.fileName,
      viewType: result.viewType as ActivityId,
      data: match ? { highlightLine: match.line, highlightColumn: match.column } : undefined,
    };
    openTab(tab);
  };

  const resultCount = results.reduce((sum, r) => sum + r.matches.length, 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', fontSize: 13, color: t.textPrimary }}>
      {/* ── Search header ──────────────────────────────── */}
      <div style={{ padding: '10px 12px', borderBottom: `1px solid ${t.border}` }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <span style={{ fontWeight: 600, fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.05em', color: t.textMuted }}>
            Search
          </span>
          <button
            onClick={onClose}
            style={{ width: 20, height: 20, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', borderRadius: 4, color: t.textMuted, cursor: 'pointer' }}
          >
            <X size={14} />
          </button>
        </div>

        {/* Search input */}
        <div style={{ position: 'relative' }}>
          <Search size={13} style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', color: t.textMuted }} />
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleSearch(); }}
            placeholder="Search across files..."
            spellCheck={false}
            style={{
              width: '100%',
              padding: '6px 8px 6px 28px',
              fontSize: 13,
              background: t.bgInput,
              border: `1px solid ${t.border}`,
              borderRadius: 6,
              color: t.textPrimary,
              outline: 'none',
              boxSizing: 'border-box',
            }}
          />
        </div>

        {/* Replace toggle */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 6 }}>
          <button
            onClick={() => setShowReplace(v => !v)}
            style={{ fontSize: 11, color: t.textMuted, background: 'transparent', border: 'none', cursor: 'pointer', padding: '2px 4px', borderRadius: 4 }}
          >
            <ArrowRight size={12} />
          </button>

          {showReplace && (
            <input
              value={replaceText}
              onChange={e => setReplaceText(e.target.value)}
              placeholder="Replace with..."
              spellCheck={false}
              style={{
                flex: 1,
                padding: '4px 8px',
                fontSize: 13,
                background: t.bgInput,
                border: `1px solid ${t.border}`,
                borderRadius: 6,
                color: t.textPrimary,
                outline: 'none',
              }}
            />
          )}
        </div>
      </div>

      {/* ── Results ────────────────────────────────────── */}
      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {searching && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, padding: 20, color: t.textMuted }}>
            <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
            Searching...
          </div>
        )}

        {!searching && searched && results.length === 0 && (
          <div style={{ padding: 20, textAlign: 'center', color: t.textMuted, fontStyle: 'italic' }}>
            No results found for "{query}"
          </div>
        )}

        {!searching && results.length > 0 && (
          <>
            <div style={{ padding: '6px 12px', fontSize: 11, color: t.textDim }}>
              {resultCount} result{resultCount !== 1 ? 's' : ''} in {results.length} file{results.length !== 1 ? 's' : ''}
            </div>
            {results.map(result => (
              <div key={result.fileId}>
                {/* File header */}
                <div
                  onClick={() => toggleExpand(result.fileId)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                    padding: '4px 8px',
                    cursor: 'pointer',
                    fontWeight: 500,
                    fontSize: 12,
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                >
                  {expandedFiles.has(result.fileId) ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  <File size={12} style={{ opacity: 0.5 }} />
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {result.fileName}
                  </span>
                  <span style={{ fontSize: 11, color: t.textDim }}>{result.matches.length}</span>
                </div>

                {/* Match lines */}
                {expandedFiles.has(result.fileId) && result.matches.map((match, mi) => (
                  <div
                    key={mi}
                    onClick={() => openResult(result, match)}
                    style={{
                      display: 'flex',
                      alignItems: 'baseline',
                      gap: 8,
                      padding: '2px 8px 2px 28px',
                      fontSize: 12,
                      cursor: 'pointer',
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                  >
                    <span style={{ fontSize: 11, color: t.textDim, flexShrink: 0, minWidth: 28, textAlign: 'right' }}>
                      {match.line}
                    </span>
                    <span style={{
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      fontFamily: '"SF Mono", "Fira Code", monospace',
                      fontSize: 11,
                      color: t.textMuted,
                    }}>
                      {highlightMatch(match.content, query, t.accent)}
                    </span>
                  </div>
                ))}
              </div>
            ))}
          </>
        )}

        {!searching && !searched && (
          <div style={{ padding: 20, textAlign: 'center', color: t.textDim, fontSize: 12 }}>
            Search across all your workflows and files
          </div>
        )}
      </div>
    </div>
  );
}

// ── Highlight matched text in a line ──────────────────────

function highlightMatch(text: string, query: string, accentColor: string): React.ReactNode {
  if (!query) return text;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return text;
  return (
    <>
      {text.slice(0, idx)}
      <span style={{ background: `${accentColor}33`, borderRadius: 2, padding: '0 1px' }}>
        {text.slice(idx, idx + query.length)}
      </span>
      {text.slice(idx + query.length)}
    </>
  );
}
