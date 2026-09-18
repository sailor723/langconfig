/**
 * SearchModal — pop-out GraphIndex / Vector RAG search UI.
 *
 * Replaces the bottom-anchored search panel that used to live in the
 * Knowledge Base doc viewer. Triggered from a button in the title bar
 * (top right), opens a centered modal that hosts the full search UI:
 * scope indicator, query input, compare toggles, results list, and
 * the LLM answer pane.
 *
 * Why a modal? The user wanted:
 *   1. The search box in the top-right of the title bar
 *   2. The doc viewer at FULL size (no more vertical real estate taken
 *      by the bottom search panel)
 *   3. The search UI to feel like a "new window" — pop-out, focus on
 *      the search, then close to return to the doc viewer.
 */
import { useEffect, useRef } from 'react';
import { Search, Loader, X, ChevronDown, ChevronUp, Filter } from 'lucide-react';

interface SearchModalProps {
  open: boolean;
  onClose: () => void;

  // Search state (owned by parent so results survive modal close/reopen)
  searchQuery: string;
  onSearchQueryChange: (q: string) => void;
  searching: boolean;
  onSearch: () => void;

  // Mode + toggles
  searchMode: 'graphindex' | 'vector';
  compareMode: boolean;
  onCompareModeChange: (b: boolean) => void;
  useHyDE: boolean;
  onUseHyDEChange: (b: boolean) => void;
  useTOON: boolean;
  onUseTOONChange: (b: boolean) => void;

  // Display
  selectedDoc: { name: string } | null;
  showSearchResults: boolean;
  pageIndexDocs: any[];
  searchResults: any[];
  onClearSearch: () => void;

  // Result interactions
  expandedChunks: Set<number>;
  onToggleChunkExpansion: (index: number) => void;

  // i18n
  t: (key: string, opts?: Record<string, any>) => string;
}

export default function SearchModal({
  open,
  onClose,
  searchQuery,
  onSearchQueryChange,
  searching,
  onSearch,
  searchMode,
  compareMode,
  onCompareModeChange,
  useHyDE,
  onUseHyDEChange,
  useTOON,
  onUseTOONChange,
  selectedDoc,
  showSearchResults,
  pageIndexDocs,
  searchResults,
  onClearSearch,
  expandedChunks,
  onToggleChunkExpansion,
  t,
}: SearchModalProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-focus the search input when the modal opens
  useEffect(() => {
    if (open) {
      // Slight delay so the focus lands after the modal's enter animation
      const t = setTimeout(() => inputRef.current?.focus(), 50);
      return () => clearTimeout(t);
    }
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-12 px-4 bg-black/40 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={t('kb_search_modal_title')}
    >
      <div
        className="bg-white dark:bg-panel-dark rounded-xl shadow-2xl w-full max-w-3xl max-h-[80vh] flex flex-col border border-gray-200 dark:border-border-dark"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 dark:border-border-dark">
          <div className="flex items-center gap-2">
            <Search className="w-4 h-4" style={{ color: 'var(--color-primary, #6366f1)' }} />
            <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text-primary)' }}>
              {t('kb_search_modal_title')}
            </h2>
            <span
              className="text-[10px] px-1.5 py-0.5 rounded font-medium"
              style={{
                color: 'var(--color-text-muted)',
                backgroundColor: 'var(--color-input-background, rgba(0,0,0,0.05))',
              }}
            >
              {searchMode === 'graphindex' ? t('kb_search_mode_graph') : t('kb_search_mode_vector')}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-white/5 transition-all"
            aria-label="Close"
          >
            <X className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
          </button>
        </div>

        {/* Body — scrollable */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
          {/* Scope indicator */}
          <div
            className="rounded-lg border border-gray-200 dark:border-border-dark px-3 py-2"
            style={{ backgroundColor: 'var(--color-input-background)' }}
          >
            <div className="text-[10px] mb-0.5" style={{ color: 'var(--color-text-muted)' }}>
              {searchMode === 'graphindex' ? t('kb_search_scope') : t('kb_selected_doc')}
            </div>
            <div className="text-xs font-medium" style={{ color: 'var(--color-text-primary)' }}>
              {searchMode === 'graphindex'
                ? t('kb_all_docs')
                : selectedDoc
                  ? selectedDoc.name
                  : t('kb_choose_doc')}
            </div>
          </div>

          {/* Search input + button */}
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search
                className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5"
                style={{ color: 'var(--color-text-muted)' }}
              />
              <input
                ref={inputRef}
                type="text"
                placeholder={
                  searchMode === 'graphindex'
                    ? t('kb_search_graphindex_placeholder')
                    : t('kb_search_placeholder')
                }
                value={searchQuery}
                onChange={(e) => onSearchQueryChange(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && onSearch()}
                className="w-full pl-8 pr-2 py-2 border border-gray-200 dark:border-border-dark rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-primary"
                style={{
                  backgroundColor: 'var(--color-input-background)',
                  color: 'var(--color-text-primary)',
                }}
              />
            </div>
            <button
              onClick={onSearch}
              disabled={searching || !searchQuery.trim()}
              className="px-4 py-2 bg-primary text-white rounded-lg hover:opacity-90 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-1.5 text-xs font-medium"
            >
              {searching ? (
                <Loader className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Search className="w-3.5 h-3.5" />
              )}
              <span>{t('kb_search')}</span>
            </button>
          </div>

          {/* Toggles row */}
          <div className="flex items-center gap-3 text-[10px] flex-wrap">
            {searchMode === 'vector' && (
              <>
                <label className="flex items-center gap-1 cursor-pointer hover:opacity-70" style={{ color: 'var(--color-text-primary)' }}>
                  <input
                    type="checkbox"
                    checked={useHyDE}
                    onChange={(e) => onUseHyDEChange(e.target.checked)}
                    className="w-3 h-3 rounded border-gray-300 dark:border-border-dark text-primary focus:ring-primary"
                  />
                  <span>{t('kb_hyde')}</span>
                </label>
                <label className="flex items-center gap-1 cursor-pointer hover:opacity-70" style={{ color: 'var(--color-text-primary)' }}>
                  <input
                    type="checkbox"
                    checked={useTOON}
                    onChange={(e) => onUseTOONChange(e.target.checked)}
                    className="w-3 h-3 rounded border-gray-300 dark:border-border-dark text-purple-600 focus:ring-purple-600"
                  />
                  <span>{t('kb_toon')}</span>
                </label>
              </>
            )}
            <label className="flex items-center gap-1 cursor-pointer hover:opacity-70" style={{ color: 'var(--color-text-primary)' }}>
              <input
                type="checkbox"
                checked={compareMode}
                onChange={(e) => onCompareModeChange(e.target.checked)}
                className="w-3 h-3 rounded border-gray-300 dark:border-border-dark text-orange-600 focus:ring-orange-600"
              />
              <span>{t('kb_compare')}</span>
            </label>
            {showSearchResults && (
              <button
                onClick={onClearSearch}
                className="ml-auto text-[10px] px-2 py-0.5 rounded bg-gray-100 dark:bg-white/10 hover:bg-gray-200 dark:hover:bg-white/20 transition-all"
                style={{ color: 'var(--color-text-primary)' }}
              >
                {t('kb_clear_results')}
              </button>
            )}
          </div>

          {/* Results — only show when there's a search */}
          {showSearchResults && (
            <>
              <h3
                className="text-[11px] font-semibold mt-4 mb-2"
                style={{ color: 'var(--color-text-primary)' }}
              >
                {pageIndexDocs.length > 0
                  ? `${t('kb_search_results_graph')} (${pageIndexDocs.length})`
                  : `${t('kb_search_results_vector')} (${searchResults.length})`}
              </h3>

              {/* GraphIndex doc cards */}
              {pageIndexDocs.length > 0 && (
                <div className="space-y-1.5">
                  {pageIndexDocs.map((doc: any) => (
                    <div
                      key={doc.doc_id}
                      className="border border-gray-200 dark:border-border-dark rounded-lg p-2"
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span
                          className="text-[11px] font-medium"
                          style={{ color: 'var(--color-text-primary)' }}
                        >
                          {doc.doc_name}
                        </span>
                        <span
                          className="text-[10px]"
                          style={{ color: 'var(--color-text-muted)' }}
                        >
                          {doc.page_count} {t('kb_pages')}
                        </span>
                      </div>
                      {doc.structure && doc.structure.length > 0 && (
                        <div className="ml-3 space-y-0.5">
                          {doc.structure.slice(0, 4).map((node: any, idx: number) => (
                            <div
                              key={idx}
                              className="text-[10px]"
                              style={{ color: 'var(--color-text-muted)' }}
                            >
                              <span className="inline-block w-2">-</span>
                              {node.title}
                              {node.page && (
                                <span className="ml-0.5 opacity-60">(p.{node.page})</span>
                              )}
                            </div>
                          ))}
                          {doc.structure.length > 4 && (
                            <div
                              className="text-[10px] italic"
                              style={{ color: 'var(--color-text-muted)' }}
                            >
                              {t('kb_more_sections', { count: doc.structure.length - 4 })}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Vector RAG chunk results */}
              {searchResults.length > 0 && (
                <div className="space-y-1.5">
                  {searchResults.map((result, index) => (
                    <div
                      key={index}
                      className="bg-gray-50 dark:bg-background-dark border border-gray-200 dark:border-border-dark rounded-lg p-2"
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[11px] font-medium text-primary">
                          {result.document_name}
                        </span>
                        <div className="flex items-center gap-1.5">
                          <span
                            className="text-[10px]"
                            style={{ color: 'var(--color-text-muted)' }}
                          >
                            {(result.similarity_score * 100).toFixed(0)}%
                          </span>
                          <button
                            onClick={() => onToggleChunkExpansion(index)}
                            className="text-[10px] text-primary hover:underline font-medium"
                          >
                            {expandedChunks.has(index) ? t('kb_hide') : t('kb_show')}
                          </button>
                        </div>
                      </div>
                      {expandedChunks.has(index) && result.chunk_id && (
                        <div className="mb-1 pb-1 border-b border-gray-200 dark:border-border-dark text-[10px]">
                          <span
                            className="font-mono"
                            style={{ color: 'var(--color-text-muted)' }}
                          >
                            #{result.chunk_id}
                          </span>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {/* Empty state when no search yet */}
          {!showSearchResults && (
            <div className="h-full flex items-center justify-center py-12">
              <div className="text-center">
                <Search
                  className="w-10 h-10 mx-auto mb-3 opacity-50"
                  style={{ color: 'var(--color-text-muted)' }}
                />
                <p
                  className="text-sm"
                  style={{ color: 'var(--color-text-primary)' }}
                >
                  {searchMode === 'graphindex'
                    ? t('kb_search_hint_graph')
                    : t('kb_search_hint_vector')}
                </p>
                <p
                  className="text-[11px] mt-1"
                  style={{ color: 'var(--color-text-muted)' }}
                >
                  {searchMode === 'graphindex'
                    ? t('kb_search_desc_graph')
                    : t('kb_search_desc_vector')}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Footer hint */}
        <div
          className="px-5 py-2 border-t border-gray-200 dark:border-border-dark text-[10px] flex items-center justify-between"
          style={{ color: 'var(--color-text-muted)' }}
        >
          <span>Press <kbd className="px-1 py-0.5 rounded bg-gray-100 dark:bg-white/10 font-mono">Esc</kbd> to close</span>
          <span>{t('kb_search_modal_hint')}</span>
        </div>
      </div>
    </div>
  );
}
