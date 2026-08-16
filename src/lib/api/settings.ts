/**
 * Settings / Models API — resource module extracted from the api-client
 * god-class. Methods are attached to the APIClient prototype via
 * Object.assign in api-client.ts.
 *
 * Phase 5: the document-CRUD endpoints are gone; the Settings UI reads
 * `describeSettings()` and writes `mutateSettings()`. What remains here are
 * the utility endpoints (model registry, key testing, setup status, storage
 * mode runtime switch, search providers, directory browser).
 */
import type { APIClient } from '../api-client';

export interface SettingsApi {
  testApiKey(provider: string, apiKey?: string): Promise<any>;
  listAvailableModels(): Promise<any>;
  createModel(data: { model_id: string; display_name: string; provider: string; capabilities?: Record<string, any> }): Promise<any>;
  deleteModel(modelId: string): Promise<any>;
  modelInvoke(data: {
    model: string;
    message: string;
    system_prompt?: string;
    temperature?: number;
    max_tokens?: number;
    top_p?: number;
    frequency_penalty?: number;
    presence_penalty?: number;
    stop?: string[];
    json_mode?: boolean;
    tools?: boolean;
    stream?: boolean;
    tool_names?: string[];
    image_url?: string;
  }): Promise<any>;
  // Search Providers (Tavily, Wikipedia, DDG, Exa, Brave, SerpAPI)
  listSearchProviders(): Promise<any>;
  getSearchProvider(providerId: string): Promise<any>;
  setSearchProviderKey(providerId: string, apiKey: string): Promise<any>;
  deleteSearchProviderKey(providerId: string): Promise<any>;
  testSearchProvider(providerId: string): Promise<any>;
  // Local models (Ollama / LM Studio / vLLM / LiteLLM)
  listLocalModels(): Promise<any>;
  createLocalModel(data: {
    name: string; display_name: string; description?: string;
    provider: string; base_url: string; model_name: string; api_key?: string; tags?: string[];
  }): Promise<any>;
  updateLocalModel(id: number, data: Partial<{
    display_name: string; description?: string; base_url: string; model_name: string; api_key?: string; tags?: string[];
  }>): Promise<any>;
  deleteLocalModel(id: number): Promise<any>;
  validateLocalModel(id: number): Promise<any>;
  validateLocalConfig(baseUrl: string, apiKey?: string): Promise<any>;
  // First-run setup
  getSetupStatus(): Promise<any>;
  completeSetup(): Promise<any>;
  validateWorkspacePath(path: string): Promise<any>;
  // Storage mode (runtime switch, persisted in the storage namespace)
  getStorageMode(): Promise<any>;
  updateStorageMode(data: { mode: 'local' | 'db' }): Promise<any>;
  // Directory Browser
  browseDirectories(path?: string): Promise<any>;
  // DSH-style settings wire API (docs/settings-refactor.md §6)
  describeSettings(): Promise<any>;
  mutateSettings(data: {
    ns: string;
    ops: { op: 'set' | 'unset'; path: string[]; value?: any }[];
    expected_revision?: number;
  }): Promise<any>;
}

export const settingsApi: SettingsApi = {
  async testApiKey(this: APIClient, provider: string, apiKey?: string) {
    return this.post('/api/settings/api-keys/test', { provider, api_key: apiKey });
  },

  async listAvailableModels(this: APIClient) {
    return this.get('/api/settings/models');
  },

  async createModel(this: APIClient, data: { model_id: string; display_name: string; provider: string; capabilities?: Record<string, any> }) {
    return this.post('/api/settings/models', data);
  },

  async deleteModel(this: APIClient, modelId: string) {
    return this.delete(`/api/settings/models/${modelId}`);
  },

  async modelInvoke(this: APIClient, data: {
    model: string;
    message: string;
    system_prompt?: string;
    temperature?: number;
    max_tokens?: number;
    top_p?: number;
    frequency_penalty?: number;
    presence_penalty?: number;
    stop?: string[];
    json_mode?: boolean;
    tools?: boolean;
    stream?: boolean;
    tool_names?: string[];
    image_url?: string;
  }) {
    return this.post('/api/models/invoke', data);
  },

  // Search Providers (Tavily, Wikipedia, DDG, Exa, Brave, SerpAPI)
  async listSearchProviders(this: APIClient) {
    return this.get('/api/search-providers/');
  },

  async getSearchProvider(this: APIClient, providerId: string) {
    return this.get(`/api/search-providers/${providerId}`);
  },

  async setSearchProviderKey(this: APIClient, providerId: string, apiKey: string) {
    return this.post(`/api/search-providers/${providerId}/key`, { api_key: apiKey });
  },

  async deleteSearchProviderKey(this: APIClient, providerId: string) {
    return this.delete(`/api/search-providers/${providerId}/key`);
  },

  async testSearchProvider(this: APIClient, providerId: string) {
    return this.post(`/api/search-providers/${providerId}/test`);
  },

  // Local models (Ollama / LM Studio / vLLM / LiteLLM)
  async listLocalModels(this: APIClient) {
    return this.get('/api/local-models/');
  },

  async createLocalModel(this: APIClient, data: {
    name: string; display_name: string; description?: string;
    provider: string; base_url: string; model_name: string; api_key?: string; tags?: string[];
  }) {
    return this.post('/api/local-models/', data);
  },

  async updateLocalModel(this: APIClient, id: number, data: Partial<{
    display_name: string; description?: string; base_url: string; model_name: string; api_key?: string; tags?: string[];
  }>) {
    return this.patch(`/api/local-models/${id}`, data);
  },

  async deleteLocalModel(this: APIClient, id: number) {
    return this.delete(`/api/local-models/${id}`);
  },

  async validateLocalModel(this: APIClient, id: number) {
    return this.post(`/api/local-models/${id}/validate`);
  },

  async validateLocalConfig(this: APIClient, baseUrl: string, apiKey?: string) {
    return this.post(`/api/local-models/validate-config?base_url=${encodeURIComponent(baseUrl)}${apiKey ? `&api_key=${encodeURIComponent(apiKey)}` : ''}`);
  },

  // First-run setup
  async getSetupStatus(this: APIClient) {
    return this.get('/api/settings/setup-status');
  },

  async completeSetup(this: APIClient) {
    return this.post('/api/settings/setup-complete');
  },

  async validateWorkspacePath(this: APIClient, path: string) {
    return this.post('/api/settings/workspace/validate', { path });
  },

  // Storage mode (runtime switch, persisted in the storage namespace)
  async getStorageMode(this: APIClient) {
    return this.get('/api/settings/storage-mode');
  },

  async updateStorageMode(this: APIClient, data: { mode: 'local' | 'db' }) {
    return this.put('/api/settings/storage-mode', data);
  },

  // Directory Browser
  async browseDirectories(this: APIClient, path?: string) {
    return this.get('/api/settings/browse-directories', {
      params: { path: path || '.' }
    });
  },

  // DSH-style settings wire API (docs/settings-refactor.md §6)
  async describeSettings(this: APIClient) {
    return this.get('/api/settings/describe');
  },

  async mutateSettings(this: APIClient, data: {
    ns: string;
    ops: { op: 'set' | 'unset'; path: string[]; value?: any }[];
    expected_revision?: number;
  }) {
    return this.post('/api/settings/mutate', data);
  },
};
