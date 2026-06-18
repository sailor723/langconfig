/**
 * Global model cache — single source of truth for available models.
 *
 * - Settings page writes to cache after saving API keys.
 * - All other panels read from cache (instant, no API call).
 * - Falls back to API if cache is empty (fresh load).
 */

import { apiClient } from './api-client';
import type { ModelOption } from '@/hooks/useAvailableModels';

let cachedModels: ModelOption[] | null = null;
let cachedCloudModels: ModelOption[] | null = null;
let cachedLocalModels: ModelOption[] | null = null;

export function getCachedModels(): ModelOption[] {
  return cachedModels ?? [];
}

export function getCachedCloudModels(): ModelOption[] {
  return cachedCloudModels ?? [];
}

export function getCachedLocalModels(): ModelOption[] {
  return cachedLocalModels ?? [];
}

export function clearModelCache(): void {
  cachedModels = null;
  cachedCloudModels = null;
  cachedLocalModels = null;
}

export async function fetchAndCacheModels(): Promise<{
  models: ModelOption[];
  cloudModels: ModelOption[];
  localModels: ModelOption[];
}> {
  const response = await apiClient.listAvailableModels();
  const cloudRaw = response.data.cloud_models || [];
  const localRaw = response.data.local_models || [];

  const cloudModels: ModelOption[] = cloudRaw.map((m: any) => ({
    id: m.model_id,
    name: m.display_name,
    provider: m.provider.charAt(0).toUpperCase() + m.provider.slice(1),
    type: 'cloud' as const,
    capabilities: m.capabilities || {},
  }));

  const localModels: ModelOption[] = localRaw
    .filter((m: any) => m.is_validated)
    .map((m: any) => ({
      id: m.name,
      name: `${m.display_name} (${m.provider.charAt(0).toUpperCase() + m.provider.slice(1)} - Local)`,
      provider: m.provider,
      type: 'local' as const,
      is_validated: m.is_validated,
      capabilities: m.capabilities,
    }));

  cachedCloudModels = cloudModels;
  cachedLocalModels = localModels;
  cachedModels = [...cloudModels, ...localModels];

  return { models: cachedModels, cloudModels, localModels };
}
