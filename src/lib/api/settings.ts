/**
 * Settings / Models API — resource module extracted from the api-client
 * god-class. Methods are attached to the APIClient prototype via
 * Object.assign in api-client.ts.
 */
import type { APIClient } from '../api-client';

export interface SettingsApi {
  getSettings(): Promise<any>;
  updateSettings(data: {
    default_model?: string;
    default_temperature?: number;
    max_tokens?: number;
    embedding_model?: string;
    chunk_size?: number;
    chunk_overlap?: number;
  }): Promise<any>;
  resetSettings(): Promise<any>;
  setApiKeys(data: {
    anthropic_api_key?: string;
    openai_api_key?: string;
    google_api_key?: string;
    cohere_api_key?: string;
    replicate_api_key?: string;
    deepseek_api_key?: string;
    glm_api_key?: string;
    minimax_api_key?: string;
    tavily_api_key?: string;
    agnes_api_key?: string;
    agnes_base_url?: string;
  }): Promise<any>;
  getApiKeys(): Promise<any>;
  testApiKey(provider: string, apiKey?: string): Promise<any>;
  deleteApiKey(provider: string): Promise<any>;
  listAvailableModels(): Promise<any>;
  createModel(data: { model_id: string; display_name: string; provider: string; capabilities?: Record<string, any> }): Promise<any>;
  deleteModel(modelId: string): Promise<any>;
  getAvailableEmbeddingModels(): Promise<any>;
  listSearchProviders(): Promise<any>;
  getSearchProvider(providerId: string): Promise<any>;
  setSearchProviderKey(providerId: string, apiKey: string): Promise<any>;
  deleteSearchProviderKey(providerId: string): Promise<any>;
  testSearchProvider(providerId: string): Promise<any>;
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
  listLocalModels(params?: { only_validated?: boolean; only_active?: boolean }): Promise<any>;
  getLocalModel(id: number): Promise<any>;
  createLocalModel(data: {
    name: string;
    display_name: string;
    description?: string;
    provider: string;
    base_url: string;
    model_name: string;
    api_key?: string;
    tags?: string[];
  }): Promise<any>;
  updateLocalModel(id: number, data: Partial<any>): Promise<any>;
  deleteLocalModel(id: number, hard_delete?: boolean): Promise<any>;
  validateLocalModel(id: number): Promise<any>;
  validateLocalModelConfig(base_url: string, api_key?: string): Promise<any>;
  getGeneralSettings(): Promise<any>;
  updateGeneralSettings(data: {
    app_name?: string;
    language?: string;
    auto_save?: boolean;
    auto_save_interval?: number;
    confirm_before_delete?: boolean;
    show_notifications?: boolean;
    check_updates?: boolean;
    telemetry?: boolean;
    log_level?: string;
    theme?: string;
  }): Promise<any>;
  getLocalModelsSettings(): Promise<any>;
  updateLocalModelsSettings(data: { provider?: string; base_url?: string; model_name?: string; api_key?: string | null }): Promise<any>;
  getWorkspaceSettings(): Promise<any>;
  updateWorkspaceSettings(data: {
    workspace_path?: string;
    allow_read?: boolean;
    allow_write?: boolean;
    require_approval?: boolean;
    auto_detect_git?: boolean;
    backup_before_edit?: boolean;
  }): Promise<any>;
  getModelDefaults(): Promise<any>;
  updateModelDefaults(data: {
    primary_model?: string;
    fallback_model?: string;
    embedding_model?: string;
    routing_strategy?: string;
    daily_token_limit?: number;
    monthly_token_limit?: number;
    alert_threshold?: number;
  }): Promise<any>;
  getModelDefaultsSettings(): Promise<any>;
  updateModelDefaultsSettings(data: {
    primary_model?: string;
    fallback_models?: string[];
    temperature?: number;
    max_tokens?: number;
    top_p?: number;
    routing_strategy?: string;
    daily_token_limit?: number;
    monthly_token_limit?: number;
    alert_threshold?: number;
  }): Promise<any>;
  getStorageMode(): Promise<any>;
  updateStorageMode(data: { mode: 'local' | 'db' }): Promise<any>;
  browseDirectories(path?: string): Promise<any>;
}

export const settingsApi: SettingsApi = {
  // Settings
  async getSettings(this: APIClient) {
    return this.get('/api/settings/');
  },

  async updateSettings(this: APIClient, data: {
    default_model?: string;
    default_temperature?: number;
    max_tokens?: number;
    embedding_model?: string;
    chunk_size?: number;
    chunk_overlap?: number;
  }) {
    return this.patch('/api/settings/', data);
  },

  async resetSettings(this: APIClient) {
    return this.post('/api/settings/reset');
  },

  async setApiKeys(this: APIClient, data: {
    anthropic_api_key?: string;
    openai_api_key?: string;
    google_api_key?: string;
    cohere_api_key?: string;
    replicate_api_key?: string;
    deepseek_api_key?: string;
    glm_api_key?: string;
    minimax_api_key?: string;
    tavily_api_key?: string;
    agnes_api_key?: string;
    agnes_base_url?: string;
  }) {
    return this.post('/api/settings/api-keys', data);
  },

  async getApiKeys(this: APIClient) {
    return this.get('/api/settings/api-keys');
  },

  async testApiKey(this: APIClient, provider: string, apiKey?: string) {
    return this.post('/api/settings/api-keys/test', { provider, api_key: apiKey });
  },

  async deleteApiKey(this: APIClient, provider: string) {
    return this.delete(`/api/settings/api-keys/${provider}`);
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

  async getAvailableEmbeddingModels(this: APIClient) {
    return this.get('/api/settings/embedding-models');
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

  // Local Models
  async listLocalModels(this: APIClient, params?: { only_validated?: boolean; only_active?: boolean }) {
    return this.get('/api/local-models/', { params });
  },

  async getLocalModel(this: APIClient, id: number) {
    return this.get(`/api/local-models/${id}`);
  },

  async createLocalModel(this: APIClient, data: {
    name: string;
    display_name: string;
    description?: string;
    provider: string;
    base_url: string;
    model_name: string;
    api_key?: string;
    tags?: string[];
  }) {
    return this.post('/api/local-models/', data);
  },

  async updateLocalModel(this: APIClient, id: number, data: Partial<any>) {
    return this.patch(`/api/local-models/${id}`, data);
  },

  async deleteLocalModel(this: APIClient, id: number, hard_delete: boolean = false) {
    return this.delete(`/api/local-models/${id}`, {
      params: { hard_delete }
    });
  },

  async validateLocalModel(this: APIClient, id: number) {
    return this.post(`/api/local-models/${id}/validate`);
  },

  async validateLocalModelConfig(this: APIClient, base_url: string, api_key?: string) {
    return this.post('/api/local-models/validate-config', null, {
      params: { base_url, api_key }
    });
  },

  // New Settings Endpoints
  async getGeneralSettings(this: APIClient) {
    return this.get('/api/settings/general');
  },

  async updateGeneralSettings(this: APIClient, data: {
    app_name?: string;
    language?: string;
    auto_save?: boolean;
    auto_save_interval?: number;
    confirm_before_delete?: boolean;
    show_notifications?: boolean;
    check_updates?: boolean;
    telemetry?: boolean;
    log_level?: string;
    theme?: string;
  }) {
    return this.post('/api/settings/general', data);
  },

  async getLocalModelsSettings(this: APIClient) {
    return this.get('/api/settings/local-models');
  },

  async updateLocalModelsSettings(this: APIClient, data: {
    provider?: string;
    base_url?: string;
    model_name?: string;
    api_key?: string | null;
  }) {
    return this.post('/api/settings/local-models', data);
  },

  async getWorkspaceSettings(this: APIClient) {
    return this.get('/api/settings/workspace');
  },

  async updateWorkspaceSettings(this: APIClient, data: {
    workspace_path?: string;
    allow_read?: boolean;
    allow_write?: boolean;
    require_approval?: boolean;
    auto_detect_git?: boolean;
    backup_before_edit?: boolean;
  }) {
    return this.post('/api/settings/workspace', data);
  },

  async getModelDefaults(this: APIClient) {
    return this.get('/api/settings/model-defaults');
  },

  async updateModelDefaults(this: APIClient, data: {
    primary_model?: string;
    fallback_model?: string;
    embedding_model?: string;
    routing_strategy?: string;
    daily_token_limit?: number;
    monthly_token_limit?: number;
    alert_threshold?: number;
  }) {
    return this.post('/api/settings/model-defaults', data);
  },

  async getModelDefaultsSettings(this: APIClient) {
    return this.get('/api/settings/model-defaults');
  },

  async updateModelDefaultsSettings(this: APIClient, data: {
    primary_model?: string;
    fallback_models?: string[];
    temperature?: number;
    max_tokens?: number;
    top_p?: number;
    routing_strategy?: string;
    daily_token_limit?: number;
    monthly_token_limit?: number;
    alert_threshold?: number;
  }) {
    return this.post('/api/settings/model-defaults', data);
  },

  // Storage mode (docs/system-architecture.md §15 Phase 5) — runtime switch
  // between 'local' (disk, default) and 'db' (PostgreSQL BYTEA).
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
};
