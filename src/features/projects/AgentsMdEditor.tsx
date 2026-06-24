/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useEffect, useState, useCallback } from 'react';
import apiClient from '../../lib/api-client';

interface AgentsMdEditorProps {
  projectId: number;
  onClose?: () => void;
}

const DEFAULT_CONTENT = `# Project Conventions

<!-- This file is loaded into every DeepAgent's system prompt via MemoryMiddleware. -->
<!-- Edit it to share project-level context (build commands, code style, architecture, etc.) -->
<!-- Agents can also update it at runtime via the \`edit_file\` tool. -->

## Overview

(Add a brief project overview here)

## Build & Test

(Add common build/test commands)

## Code Style

(Add code conventions)
`;

export default function AgentsMdEditor({ projectId, onClose }: AgentsMdEditorProps) {
  const [content, setContent] = useState<string>('');
  const [originalContent, setOriginalContent] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [exists, setExists] = useState(false);

  const hasChanges = content !== originalContent;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.getAgentsMd(projectId);
      const data = res.data;
      setContent(data.content || DEFAULT_CONTENT);
      setOriginalContent(data.content || DEFAULT_CONTENT);
      setExists(!!data.exists);
    } catch (e: any) {
      setError(e?.message || 'Failed to load AGENTS.md');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  const save = async () => {
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      await apiClient.updateAgentsMd(projectId, content);
      setOriginalContent(content);
      setExists(true);
      setSuccess('Saved');
      setTimeout(() => setSuccess(null), 2000);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const reset = () => {
    setContent(originalContent);
    setError(null);
    setSuccess(null);
  };

  const deleteFile = async () => {
    if (!confirm('Delete AGENTS.md? Next time a DeepAgent runs, a default file will be created.')) return;
    setDeleting(true);
    setError(null);
    try {
      await apiClient.deleteAgentsMd(projectId);
      setContent(DEFAULT_CONTENT);
      setOriginalContent(DEFAULT_CONTENT);
      setExists(false);
      setSuccess('Deleted');
      setTimeout(() => setSuccess(null), 2000);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Failed to delete');
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">AGENTS.md</span>
          {exists ? (
            <span className="text-xs px-1.5 py-0.5 rounded bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300">
              exists
            </span>
          ) : (
            <span className="text-xs px-1.5 py-0.5 rounded bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300">
              not created yet
            </span>
          )}
          <span className="text-xs text-gray-500">/ project {projectId}</span>
        </div>
        <div className="flex items-center gap-2">
          {onClose && (
            <button
              onClick={onClose}
              className="text-xs px-2 py-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800"
            >
              Close
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="px-4 py-2 text-sm bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-300 border-b border-red-200 dark:border-red-800">
          {error}
        </div>
      )}
      {success && (
        <div className="px-4 py-2 text-sm bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-300 border-b border-green-200 dark:border-green-800">
          {success}
        </div>
      )}

      {loading ? (
        <div className="flex-1 flex items-center justify-center text-sm text-gray-500">
          Loading...
        </div>
      ) : (
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          className="flex-1 w-full p-4 font-mono text-sm bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 resize-none focus:outline-none"
          placeholder="Markdown content..."
          spellCheck={false}
        />
      )}

      <div className="flex items-center justify-between px-4 py-2 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800">
        <div className="text-xs text-gray-500">
          {content.length} chars · {content.split('\n').length} lines
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={reset}
            disabled={!hasChanges || saving || deleting}
            className="text-xs px-3 py-1 rounded border border-gray-300 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Reset
          </button>
          <button
            onClick={deleteFile}
            disabled={!exists || saving || deleting}
            className="text-xs px-3 py-1 rounded border border-red-300 text-red-700 dark:border-red-700 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {deleting ? 'Deleting...' : 'Delete'}
          </button>
          <button
            onClick={save}
            disabled={!hasChanges || saving || deleting}
            className="text-xs px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
