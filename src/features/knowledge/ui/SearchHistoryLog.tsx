/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useState, useEffect } from 'react';
import { Search, Clock, Hash, Activity, ChevronDown, ChevronUp, RefreshCw } from 'lucide-react';
import apiClient from "../../../lib/api-client";

interface SearchHistoryItem {
  id: number;
  project_id: number;
  query: string;
  use_hyde: boolean;
  hyde_auto_detected: boolean;
  use_toon: boolean;
  top_k: number;
  results_count: number;
  retrieval_duration_ms: number;
  query_tokens: number;
  total_context_tokens: number;
  avg_similarity: number;
  max_similarity: number;
  min_similarity: number;
  created_at: string;
}

interface SearchHistoryLogProps {
  projectId: number;
  onRerun?: (query: string, useHyde: boolean, useToon: boolean) => void;
  className?: string;
}

export default function SearchHistoryLog({ projectId, onRerun, className = '' }: SearchHistoryLogProps) {
  const [history, setHistory] = useState<SearchHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(true);
  const [limit, setLimit] = useState(20);

  useEffect(() => {
    const abortController = new AbortController();

    loadHistory(abortController.signal);

    return () => {
      abortController.abort();
    };
  }, [projectId, limit]);

  const loadHistory = async (signal?: AbortSignal) => {
    try {
      setLoading(true);
      const response = await apiClient.getSearchHistory({
        project_id: projectId,
        limit,
        skip: 0,
        signal
      } as any);
      setHistory(response.data);
    } catch (error) {
      // Ignore abort errors
      if (error instanceof Error && (error.name === 'AbortError' || error.name === 'CanceledError')) {
        return;
      }
      console.error('Failed to load search history:', error);
    } finally {
      setLoading(false);
    }
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;

    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const formatScore = (score: number) => (score * 100).toFixed(1) + '%';

  return (
    <div className={`bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg ${className}`}>
      {/* Header */}
      <div
        className="flex items-center justify-between p-2 cursor-pointer hover:bg-gray-50 dark:hover:bg-white/5 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-1.5">
          <Search className="w-3.5 h-3.5" style={{ color: 'var(--color-primary)' }} />
          <h3 className="text-xs font-semibold" style={{ color: 'var(--color-text-primary)' }}>
            Search History
          </h3>
          <span className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
            ({history.length})
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={(e) => {
              e.stopPropagation();
              loadHistory();
            }}
            className="p-0.5 hover:bg-gray-200 dark:hover:bg-white/10 rounded transition-colors"
            title="Refresh"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} style={{ color: 'var(--color-text-muted)' }} />
          </button>
          {expanded ? (
            <ChevronUp className="w-3.5 h-3.5" style={{ color: 'var(--color-text-muted)' }} />
          ) : (
            <ChevronDown className="w-3.5 h-3.5" style={{ color: 'var(--color-text-muted)' }} />
          )}
        </div>
      </div>

      {/* History List */}
      {expanded && (
        <div className="border-t border-gray-200 dark:border-border-dark">
          {loading ? (
            <div className="p-4 text-center">
              <RefreshCw className="w-6 h-6 mx-auto mb-2 animate-spin" style={{ color: 'var(--color-primary)' }} />
              <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Loading history...</p>
            </div>
          ) : history.length === 0 ? (
            <div className="p-4 text-center">
              <Search className="w-6 h-6 mx-auto mb-2" style={{ color: 'var(--color-text-muted)', opacity: 0.5 }} />
              <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>No search history yet</p>
              <p className="text-[10px] mt-1" style={{ color: 'var(--color-text-muted)' }}>Run a search to see metrics here</p>
            </div>
          ) : (
            <div className="divide-y divide-gray-200 dark:divide-border-dark max-h-[500px] overflow-y-auto">
              {history.map((item) => (
                <div
                  key={item.id}
                  className="px-2 py-1.5 hover:bg-gray-50 dark:hover:bg-white/5 transition-colors"
                >
                  {/* Query & Time */}
                  <div className="flex items-start justify-between mb-1">
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium truncate" style={{ color: 'var(--color-text-primary)' }}>
                        "{item.query}"
                      </p>
                      <div className="flex items-center gap-1 mt-0.5 text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                        <Clock className="w-2.5 h-2.5" />
                        <span>{formatDate(item.created_at)}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-0.5 ml-1">
                      {item.use_hyde && (
                        <span className="px-1 py-0.5 bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-400 rounded text-[9px]">
                          H
                        </span>
                      )}
                      {item.use_toon && (
                        <span className="px-1 py-0.5 bg-purple-100 dark:bg-purple-500/20 text-purple-700 dark:text-purple-400 rounded text-[9px]">
                          T
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Metrics Grid */}
                  <div className="grid grid-cols-4 gap-1.5">
                    <div className="flex flex-col">
                      <span className="text-[9px]" style={{ color: 'var(--color-text-muted)' }}>Results</span>
                      <span className="text-xs font-semibold flex items-center gap-0.5" style={{ color: 'var(--color-text-primary)' }}>
                        <Hash className="w-2.5 h-2.5" />
                        {item.results_count}
                      </span>
                    </div>
                    <div className="flex flex-col">
                      <span className="text-[9px]" style={{ color: 'var(--color-text-muted)' }}>Tokens</span>
                      <span className="text-xs font-semibold flex items-center gap-0.5" style={{ color: 'var(--color-text-primary)' }}>
                        <Activity className="w-2.5 h-2.5" />
                        {item.total_context_tokens}
                      </span>
                    </div>
                    <div className="flex flex-col">
                      <span className="text-[9px]" style={{ color: 'var(--color-text-muted)' }}>Time</span>
                      <span className="text-xs font-semibold flex items-center gap-0.5" style={{ color: 'var(--color-text-primary)' }}>
                        <Clock className="w-2.5 h-2.5" />
                        {item.retrieval_duration_ms.toFixed(0)}ms
                      </span>
                    </div>
                    <div className="flex flex-col">
                      <span className="text-[9px]" style={{ color: 'var(--color-text-muted)' }}>Similarity</span>
                      <span className="text-xs font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                        {formatScore(item.avg_similarity)}
                      </span>
                    </div>
                  </div>

                  {/* Actions */}
                  {onRerun && (
                    <div className="flex items-center gap-1.5 mt-1">
                      <button
                        onClick={() => onRerun(item.query, item.use_hyde, item.use_toon)}
                        className="text-[10px] px-1.5 py-0.5 bg-primary/10 text-primary hover:bg-primary/20 rounded transition-colors"
                      >
                        Re-run
                      </button>
                      {!item.use_toon && (
                        <button
                          onClick={() => onRerun(item.query, item.use_hyde, true)}
                          className="text-[10px] px-1.5 py-0.5 bg-purple-100 dark:bg-purple-500/20 text-purple-700 dark:text-purple-400 hover:bg-purple-200 dark:hover:bg-purple-500/30 rounded transition-colors"
                        >
                          Compare with TOON
                        </button>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Load More */}
          {history.length >= limit && (
            <div className="p-2 border-t border-gray-200 dark:border-border-dark text-center">
              <button
                onClick={() => setLimit(limit + 20)}
                className="text-[10px] hover:opacity-70 font-medium"
                style={{ color: 'var(--color-primary)' }}
              >
                Load More
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
