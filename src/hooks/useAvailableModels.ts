/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useState, useEffect, useCallback } from 'react';
import { getCachedModels, getCachedCloudModels, getCachedLocalModels, fetchAndCacheModels } from '@/lib/modelCache';

export interface ModelOption {
  id: string;
  name: string;
  provider: string;
  type: 'cloud' | 'local';
  is_validated?: boolean;
  capabilities?: {
    streaming?: boolean;
    tools?: boolean;
    max_context?: number;
    [key: string]: any;
  };
}

export interface UseAvailableModelsOptions {
  includeLocal?: boolean;
  onlyValidated?: boolean;
}

export interface UseAvailableModelsResult {
  models: ModelOption[];
  cloudModels: ModelOption[];
  localModels: ModelOption[];
  isLoading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

export function useAvailableModels(
  options: UseAvailableModelsOptions = {}
): UseAvailableModelsResult {
  const { includeLocal = true } = options;

  const [models, setModels] = useState<ModelOption[]>(() => getCachedModels());
  const [cloudModels, setCloudModels] = useState<ModelOption[]>(() => getCachedCloudModels());
  const [localModels, setLocalModels] = useState<ModelOption[]>(() => getCachedLocalModels());
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchModels = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const result = await fetchAndCacheModels();
      setModels(result.models);
      setCloudModels(result.cloudModels);
      setLocalModels(result.localModels);
    } catch (err) {
      console.error('Failed to fetch available models:', err);
      setError(err instanceof Error ? err.message : 'Failed to fetch models');
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Fetch only if cache is empty (first load)
  useEffect(() => {
    if (getCachedModels().length === 0) {
      fetchModels();
    }
  }, [fetchModels]);

  // Subscribe to cache updates — re-read from cache whenever we re-render
  // This ensures any component calling refetch() propagates to all consumers
  useEffect(() => {
    const interval = setInterval(() => {
      const fresh = getCachedModels();
      if (fresh.length > 0) {
        setModels(fresh);
        setCloudModels(getCachedCloudModels());
        setLocalModels(getCachedLocalModels());
      }
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  return {
    models,
    cloudModels,
    localModels,
    isLoading,
    error,
    refetch: fetchModels,
  };
}
