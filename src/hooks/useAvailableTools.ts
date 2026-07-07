/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useState, useEffect, useCallback } from 'react';
import { apiClient } from '@/lib/api-client';

/**
 * Metadata for a single tool, returned by GET /api/tools/registry.
 */
export interface ToolOption {
  id: string;                           // Tool identifier (e.g., "tavily_search")
  name: string;                         // Display name (e.g., "Tavily Search")
  description: string;                  // Short description
  category: string;                     // Grouping key: web, filesystem, memory, reasoning, delegation
  requires_api_key: string | null;      // Env var of required API key, or null
}

/**
 * Hook for fetching the native tool registry from the backend.
 *
 * Replaces hardcoded tool lists in the agent editor and Studio node config
 * panel. Single source of truth lives in backend/tools/native_tools.py.
 *
 * Usage:
 * ```typescript
 * const { tools, isLoading, error, groupedByCategory, refetch } = useAvailableTools();
 *
 * // tools: flat list of all available tools
 * // groupedByCategory: { web: [...], filesystem: [...], ... }
 * ```
 */
export interface UseAvailableToolsResult {
  tools: ToolOption[];
  isLoading: boolean;
  error: string | null;
  groupedByCategory: Record<string, ToolOption[]>;
  refetch: () => Promise<void>;
}

export function useAvailableTools(): UseAvailableToolsResult {
  const [tools, setTools] = useState<ToolOption[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTools = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await apiClient.listToolRegistry();
      const data = (response.data || []) as ToolOption[];
      setTools(data);
    } catch (err: any) {
      const message = err?.response?.data?.detail || err?.message || 'Failed to load tool registry';
      setError(message);
      setTools([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTools();
  }, [fetchTools]);

  // Group tools by their category field
  const groupedByCategory = tools.reduce<Record<string, ToolOption[]>>((acc, tool) => {
    if (!acc[tool.category]) {
      acc[tool.category] = [];
    }
    acc[tool.category].push(tool);
    return acc;
  }, {});

  return { tools, isLoading, error, groupedByCategory, refetch: fetchTools };
}

/**
 * Display labels for tool categories.
 * Maps the backend's category id to a human-readable name.
 */
export const TOOL_CATEGORY_LABELS: Record<string, string> = {
  web: 'Web',
  filesystem: 'Filesystem',
  memory: 'Memory',
  reasoning: 'Reasoning',
  delegation: 'Subagent Delegation',
  todo: 'TODO Management',
};
