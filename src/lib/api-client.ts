/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import axios, { AxiosInstance, AxiosError } from 'axios';
import type { ApiError, ConflictError, RateLimitError } from '@/types/api';

/**
 * Custom Error Classes
 */
export class ConflictErrorClass extends Error {
  constructor(
    message: string,
    public detail: ConflictError['detail']
  ) {
    super(message);
    this.name = 'ConflictError';
  }
}

export class RateLimitErrorClass extends Error {
  constructor(
    message: string,
    public detail: RateLimitError['detail']
  ) {
    super(message);
    this.name = 'RateLimitError';
  }
}

/**
 * API Client for LangConfig backend
 * Enhanced features:
 * - Optimistic locking (409 handling)
 * - Rate limiting (429 handling)
 * - Automatic toast notifications
 */
import { API_BASE_URL } from '../config/api';

/**
 * API Client for LangConfig backend
 * Enhanced features:
 * - Optimistic locking (409 handling)
 * - Rate limiting (429 handling)
 * - Automatic toast notifications
 */
class APIClient {
  private client: AxiosInstance;
  public baseURL: string = API_BASE_URL;

  constructor() {
    this.client = axios.create({
      baseURL: this.baseURL,
      timeout: 300000,  // 5 min timeout for agent responses; individual endpoints can override
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Interceptor to remove Content-Type for FormData
    this.client.interceptors.request.use((config) => {
      if (config.data instanceof FormData) {
        delete config.headers['Content-Type'];
      }
      return config;
    });

    // Error handling interceptor
    this.client.interceptors.response.use(
      (response) => response,
      (error: AxiosError<ApiError>) => {
        return this.handleError(error);
      }
    );
  }

  /**
   * Generic fetch wrapper for endpoints not yet typed in the client
   */
  async apiFetch(url: string, options?: any) {
    const response = await fetch(url, options);
    if (!response.ok) {
      throw new Error(`API request failed: ${response.statusText}`);
    }
    return response.json();
  }

  /**
   * Generic axios helpers for ad-hoc endpoints.
   * Prefer adding typed methods over time, but these unblock components safely.
   */
  get(url: string, config?: any) {
    return this.client.get(url, config);
  }

  post(url: string, data?: any, config?: any) {
    return this.client.post(url, data, config);
  }

  put(url: string, data?: any, config?: any) {
    return this.client.put(url, data, config);
  }

  patch(url: string, data?: any, config?: any) {
    return this.client.patch(url, data, config);
  }

  delete(url: string, config?: any) {
    return this.client.delete(url, config);
  }

  /**
   * Enhanced error handling
   */
  private handleError(error: AxiosError<ApiError>) {
    const status = error.response?.status;
    const errorData = error.response?.data;

    switch (status) {
      case 409: {
        // Conflict - prefer the actual backend message when available so
        // errors like "Tool with ID 'x' already exists" reach the user
        // instead of a generic optimistic-locking fallback.
        const detail = (errorData as ConflictError)?.detail;
        const detailMsg = typeof detail === 'string'
          ? detail
          : (detail && typeof detail === 'object' && 'message' in detail
            ? String((detail as { message: unknown }).message)
            : undefined);
        const message = errorData?.message || detailMsg || 'Resource was modified by another user';
        this.showToast(message, 'warning');
        throw new ConflictErrorClass(message, detail);
      }

      case 429: {
        // Rate limit exceeded
        const retryAfter = error.response?.headers['retry-after'] || '60';
        const message = errorData?.message || `Rate limit exceeded. Please wait ${retryAfter} seconds.`;
        const detail = (errorData as RateLimitError)?.detail || {
          limit: 60,
          window: '1 minute',
          retry_after: parseInt(retryAfter)
        };
        this.showToast(message, 'error');
        throw new RateLimitErrorClass(message, detail);
      }

      case 422: {
        // Validation error
        const message = errorData?.message || 'Validation failed';
        this.showToast(message, 'error');
        throw error;
      }

      case 404: {
        // Not found
        const message = errorData?.message || 'Resource not found';
        this.showToast(message, 'error');
        throw error;
      }

      case 403: {
        // Forbidden
        const message = errorData?.message || 'Access denied';
        this.showToast(message, 'error');
        throw error;
      }

      case 500:
      case 502:
      case 503: {
        // Server error
        const message = errorData?.message || 'Server error. Please try again later.';
        this.showToast(message, 'error');
        throw error;
      }

      default: {
        // Other errors
        if (error.response) {
          const message = errorData?.message || `Request failed with status ${status}`;
          this.showToast(message, 'error');
        } else if (error.request) {
          this.showToast('Network error. Please check your connection.', 'error');
        }
        throw error;
      }
    }
  }

  /**
   * Show toast notification
   * Compatible with react-hot-toast
   */
  private showToast(message: string, type: 'success' | 'error' | 'warning' | 'info') {
    if (typeof window === 'undefined') return;

    // Try to use react-hot-toast if available
    if ('toast' in window && typeof (window as any).toast === 'object') {
      const toast = (window as any).toast;
      switch (type) {
        case 'success':
          toast.success(message);
          break;
        case 'error':
          toast.error(message);
          break;
        case 'warning':
          toast(message, { icon: '⚠️' });
          break;
        case 'info':
          toast(message);
          break;
      }
    } else {
      console[type === 'error' ? 'error' : 'log'](`[${type.toUpperCase()}]`, message);
    }
  }

  // Health Check
  async healthCheck() {
    return this.client.get('/health');
  }

  // Workflows
  async listWorkflows(config?: { project_id?: number; skip?: number; limit?: number; signal?: AbortSignal }) {
    const { signal, ...params } = config || {};
    return this.client.get('/api/workflows/', { params: Object.keys(params).length ? params : undefined, signal });
  }

  async getWorkflow(id: number) {
    return this.client.get(`/api/workflows/${id}`);
  }

  async createWorkflow(data: {
    name: string;
    project_id?: number;  // Optional - project association
    strategy_type?: string;  // Optional - only needed for predefined strategy workflows
    configuration: object;
    schema_output_config?: object;
    output_schema?: string;
    blueprint?: object;
  }) {
    return this.client.post('/api/workflows/', data);
  }

  async updateWorkflow(id: number, data: Partial<any>) {
    return this.client.patch(`/api/workflows/${id}`, data);
  }

  async deleteWorkflow(id: number) {
    return this.client.delete(`/api/workflows/${id}`);
  }

  async getWorkflowCode(id: number) {
    return this.client.get(`/api/workflows/${id}/code`, {
      responseType: 'text'
    });
  }

  async debugWorkflow(id: number) {
    return this.client.get(`/api/debug/workflow/${id}`);
  }

  async getWorkflowVersions(id: number) {
    return this.client.get(`/api/workflows/${id}/versions`);
  }

  async createWorkflowVersion(id: number, data: any) {
    return this.client.post(`/api/workflows/${id}/versions`, data);
  }

  async getWorkflowVersion(id: number, versionId: number) {
    return this.client.get(`/api/workflows/${id}/versions/${versionId}`);
  }

  async compareWorkflowVersions(id: number, v1: number, v2: number) {
    return this.client.get(`/api/workflows/${id}/versions/${v1}/compare/${v2}`);
  }

  async continueWorkflow(id: number, data: any) {
    return this.client.post(`/api/workflows/${id}/continue`, data);
  }

  async exportWorkflowExecutionDocx(executionId: number) {
    return this.client.get(`/api/workflows/executions/${executionId}/export/docx`, {
      responseType: 'blob'
    });
  }

  async getWorkflowCostMetrics(id: number, days: number = 30) {
    return this.client.get(`/api/workflows/${id}/metrics/cost`, {
      params: { days }
    });
  }


  // Workflow Memory
  async getWorkflowMemory(workflowId: number) {
    return this.client.get(`/api/workflows/${workflowId}/memory`);
  }

  async addWorkflowMemoryItem(workflowId: number, data: {
    namespace: string[];
    key: string;
    value: any;
  }) {
    return this.client.post(`/api/workflows/${workflowId}/memory`, data);
  }

  async deleteWorkflowMemoryItem(workflowId: number, key: string) {
    return this.client.delete(`/api/workflows/${workflowId}/memory/${key}`);
  }

  async clearWorkflowMemory(workflowId: number) {
    return this.client.delete(`/api/workflows/${workflowId}/memory`);
  }

  async batchUpdateWorkflowMemory(workflowId: number, items: any[]) {
    return this.client.post(`/api/workflows/${workflowId}/memory/batch`, { items });
  }

  // Orchestration
  async executeWorkflow(data: {
    workflow_id: number;
    project_id: number;
    input_data: object;
    context_documents?: number[];
    attachments?: Array<{
      type: string;
      name: string;
      mime_type: string;
      data?: string;
      size?: number;
    }>;
    continue_from_task_id?: number;  // Follow-up from a previous task
  }) {
    return this.client.post('/api/orchestration/execute', data);
  }

  async getTaskStatus(taskId: number) {
    return this.client.get(`/api/orchestration/tasks/${taskId}`);
  }

  async cancelTask(taskId: number) {
    return this.client.post(`/api/orchestration/tasks/${taskId}/cancel`);
  }

  async listTaskFiles(taskId: number) {
    return this.client.get(`/api/orchestration/tasks/${taskId}/files`);
  }

  async downloadTaskFile(taskId: number, filename: string) {
    return this.client.get(`/api/orchestration/tasks/${taskId}/files/${filename}`, {
      responseType: 'blob', // Important for file downloads
    });
  }

  // Projects
  async listProjects(config?: { skip?: number; limit?: number; status?: string; signal?: AbortSignal }) {
    const { signal, ...params } = config || {};
    return this.client.get('/api/projects/', { params: Object.keys(params).length ? params : undefined, signal });
  }

  async getProject(id: number) {
    return this.client.get(`/api/projects/${id}`);
  }

  async createProject(data: {
    name: string;
    description?: string;
    configuration?: object;
  }) {
    return this.client.post('/api/projects/', data);
  }

  async updateProject(id: number, data: Partial<any>) {
    return this.client.patch(`/api/projects/${id}`, data);
  }

  async deleteProject(id: number) {
    return this.client.delete(`/api/projects/${id}`);
  }

  async indexProject(id: number) {
    return this.client.post(`/api/projects/${id}/index`);
  }

  // AGENTS.md (MemoryMiddleware for DeepAgent)
  async getAgentsMd(projectId: number) {
    return this.client.get(`/api/projects/${projectId}/agents-md`);
  }

  async updateAgentsMd(projectId: number, content: string) {
    return this.client.put(`/api/projects/${projectId}/agents-md`, { content });
  }

  async deleteAgentsMd(projectId: number) {
    return this.client.delete(`/api/projects/${projectId}/agents-md`);
  }

  // Tasks
  async listTasks(params?: {
    skip?: number;
    limit?: number;
    project_id?: number;
    status?: string;
  }) {
    return this.client.get('/api/tasks/', { params });
  }

  async getTask(id: number) {
    return this.client.get(`/api/tasks/${id}`);
  }

  async getRecentProjectTasks(projectId: number, limit: number = 10) {
    return this.client.get(`/api/tasks/project/${projectId}/recent`, {
      params: { limit },
    });
  }

  async getTaskStats(projectId?: number) {
    return this.client.get('/api/tasks/stats/summary', {
      params: { project_id: projectId },
    });
  }

  async deleteTask(id: number) {
    return this.client.delete(`/api/tasks/${id}`);
  }

  // RAG / Documents
  async uploadDocument(
    projectId: number,
    file: File,
    metadata?: {
    description?: string;
    tags?: string[];
    industry?: string;
    player?: string;
    sub_category?: string;
    sub_department?: string;
  },
    onUploadProgress?: (percent: number) => void
  ) {
    const formData = new FormData();
    formData.append('file', file);
    if (metadata) {
      formData.append('metadata', JSON.stringify(metadata));
    }

    return this.client.post('/api/rag/upload', formData, {
      params: { project_id: projectId },
      onUploadProgress: onUploadProgress
        ? (event: any) => {
            // axios progress event for multipart uploads
            if (event.total) {
              onUploadProgress(Math.round((event.loaded * 100) / event.total));
            }
          }
        : undefined,
    });
  }

  async uploadDocumentsBulk(
    projectId: number,
    files: File[],
    extractArchives: boolean = true,
    metadata?: { description?: string; tags?: string[]; name?: string },
    onUploadProgress?: (percent: number) => void,
    /**
     * Step N+1: per-file metadata for folder uploads. When the user
     * picks a folder via the browser-native file picker (webkitdirectory),
     * each File has a `webkitRelativePath` like
     * "electric_vehicle_industry/tesla/marketing/01-product-lineup.md".
     * The frontend parses the path into industry/player/sub_category/
     * sub_department and sends ONE metadata dict per file in this array.
     * The backend applies them in order to the corresponding file.
     * If omitted, all files share `metadata`.
     */
    fileMetadata?: Array<{
      description?: string;
      tags?: string[];
      name?: string;
      industry?: string;
      player?: string;
      sub_category?: string;
      sub_department?: string;
    }>
  ) {
    const formData = new FormData();

    // Append all files
    files.forEach((file) => {
      formData.append('files', file);
    });

    // Add form fields (not query params)
    formData.append('project_id', projectId.toString());
    formData.append('extract_archives', extractArchives.toString());

    // Add shared metadata if provided
    if (metadata) {
      formData.append('metadata', JSON.stringify(metadata));
    }

    // Add per-file metadata if provided (folder upload). JSON-encoded
    // list, one entry per file index. Empty list = no per-file metadata.
    if (fileMetadata && fileMetadata.length > 0) {
      formData.append('file_metadata', JSON.stringify(fileMetadata));
    }

    return this.client.post('/api/rag/upload-bulk', formData, {
      onUploadProgress: onUploadProgress
        ? (event: any) => {
            if (event.total) {
              onUploadProgress(Math.round((event.loaded * 100) / event.total));
            }
          }
        : undefined,
    });
  }

  async listDocuments(config: {
    project_id: number;
    skip?: number;
    limit?: number;
    status?: string;
    signal?: AbortSignal;
  }) {
    const { signal, ...params } = config;
    return this.client.get('/api/rag/documents', { params, signal });
  }

  /**
   * Step N+1: server-side folder ingest (Safari / Firefox fallback).
   * The user pastes an absolute folder path; the server walks it
   * and ingests every supported file, deriving industry/player/
   * sub_category metadata from the path.
   */
  async ingestFolderFromPath(params: {
    project_id: number;
    folder_path: string;
    industry?: string;
    player?: string;
  }) {
    return this.client.post('/api/rag/ingest-folder', params);
  }

  /**
   * List documents from the Neo4j graphindex catalog (the chat's view
   * of the project's docs). Complements /api/rag/documents (Postgres
   * context_documents) — the UI merges the two so the sidebar stays
   * in sync with what the chat can actually find. See Step M of the
   * Phase 9 README.
   */
  async listNeo4jDocuments(config: { project_id: number; signal?: AbortSignal }) {
    return this.client.get('/api/graphindex/neo4j-documents', { params: config, signal: config.signal });
  }

  async getDocument(id: number) {
    return this.client.get(`/api/rag/documents/${id}`);
  }

  /**
   * Fetch the text content of a doc by Neo4j catalog name (not
   * by Postgres id). For docs that exist in Neo4j but not in the
   * context_documents table. See Phase 9 / Step M.
   */
  async getNeo4jDocumentContent(config: { project_id: number; name: string; max_chars?: number }) {
    const response = await this.client.get('/api/graphindex/content', { params: config });
    return response.data as {
      doc_id: number;
      doc_name: string;
      content: string;
      char_count: number;
      source: string;
      file_path: string;
    };
  }

  async deleteDocument(id: number) {
    return this.client.delete(`/api/rag/documents/${id}`);
  }

  // ── KV Document Store (simple file-based, no DB) ─────────────

  /**
   * List documents from the KV store (file-based, no PostgreSQL/Neo4j).
   */
  async listKVDocuments(config: { project_id: number }) {
    return this.client.get('/api/kv/documents', { params: config });
  }

  /**
   * Upload files to the KV store.
   */
  async uploadKVDocumentsBulk(
    projectId: number,
    files: File[],
    fileMetadata?: Array<{
      industry?: string;
      player?: string;
      sub_category?: string;
      sub_department?: string;
    }>
  ) {
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));
    formData.append('project_id', projectId.toString());
    if (fileMetadata && fileMetadata.length > 0) {
      formData.append('file_metadata', JSON.stringify(fileMetadata));
    }
    return this.client.post('/api/kv/upload-bulk', formData);
  }

  /**
   * Ingest a folder from the server's disk into the KV store.
   */
  async ingestKVDocumentFolder(params: { project_id: number; folder_path: string }) {
    return this.client.post('/api/kv/ingest-folder', params);
  }

  /**
   * Delete a document from the KV store.
   */
  async deleteKVDocument(docId: string, projectId: number) {
    return this.client.delete(`/api/kv/documents/${docId}?project_id=${projectId}`);
  }

  async searchDocuments(data: {
    query: string;
    project_id: number;
    top_k?: number;
    use_hyde?: boolean;
    search_mode?: string; // "vector" or "graphindex"
  }) {
    const response = await this.client.post('/api/rag/search', data);
    return response.data;
  }

  // (pageIndexAnswer removed — unused)

  async getSearchHistory(params: {
    project_id: number;
    limit?: number;
    skip?: number;
  }) {
    return this.client.get('/api/rag/search-history', { params });
  }

  async getProjectStorageStats(projectId: number) {
    return this.client.get(`/api/rag/projects/${projectId}/storage-stats`);
  }

  // (previewDocument removed — unused)

  // Get extracted text/structured content for inline rendering in the
  // Knowledge panel. Supports MD, TXT, CSV, JSON, YAML, HTML, XML, code,
  // DOCX, PPTX, XLSX. Returns `{ kind, content, rows?, sheet_names?,
  // sheet_rows?, truncated }`.
  async getDocumentContent(documentId: number) {
    const response = await this.client.get(`/api/rag/documents/${documentId}/content`);
    return response.data as {
      kind: 'markdown' | 'csv' | 'html' | 'code' | 'plain';
      content: string;
      rows?: string[][];
      sheet_names?: string[];
      sheet_rows?: string[][][];
      truncated: boolean;
    };
  }

  // Settings
  async getSettings() {
    return this.client.get('/api/settings/');
  }

  async updateSettings(data: {
    default_model?: string;
    default_temperature?: number;
    max_tokens?: number;
    embedding_model?: string;
    chunk_size?: number;
    chunk_overlap?: number;
  }) {
    return this.client.patch('/api/settings/', data);
  }

  async resetSettings() {
    return this.client.post('/api/settings/reset');
  }

  async setApiKeys(data: {
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
    return this.client.post('/api/settings/api-keys', data);
  }

  async getApiKeys() {
    return this.client.get('/api/settings/api-keys');
  }

  async testApiKey(provider: string, apiKey?: string) {
    return this.client.post('/api/settings/api-keys/test', { provider, api_key: apiKey });
  }

  async deleteApiKey(provider: string) {
    return this.client.delete(`/api/settings/api-keys/${provider}`);
  }

  async listAvailableModels() {
    return this.client.get('/api/settings/models');
  }

  async createModel(data: { model_id: string; display_name: string; provider: string; capabilities?: Record<string, any> }) {
    return this.client.post('/api/settings/models', data);
  }

  async deleteModel(modelId: string) {
    return this.client.delete(`/api/settings/models/${modelId}`);
  }

  async getAvailableEmbeddingModels() {
    return this.client.get('/api/settings/embedding-models');
  }

  // Search Providers (Tavily, Wikipedia, DDG, Exa, Brave, SerpAPI)
  async listSearchProviders() {
    return this.client.get('/api/search-providers/');
  }

  async getSearchProvider(providerId: string) {
    return this.client.get(`/api/search-providers/${providerId}`);
  }

  async setSearchProviderKey(providerId: string, apiKey: string) {
    return this.client.post(`/api/search-providers/${providerId}/key`, { api_key: apiKey });
  }

  async deleteSearchProviderKey(providerId: string) {
    return this.client.delete(`/api/search-providers/${providerId}/key`);
  }

  async testSearchProvider(providerId: string) {
    return this.client.post(`/api/search-providers/${providerId}/test`);
  }

  async modelInvoke(data: {
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
    return this.client.post('/api/models/invoke', data);
  }

  // Local Models
  async listLocalModels(params?: { only_validated?: boolean; only_active?: boolean }) {
    return this.client.get('/api/local-models/', { params });
  }

  async getLocalModel(id: number) {
    return this.client.get(`/api/local-models/${id}`);
  }

  async createLocalModel(data: {
    name: string;
    display_name: string;
    description?: string;
    provider: string;
    base_url: string;
    model_name: string;
    api_key?: string;
    tags?: string[];
  }) {
    return this.client.post('/api/local-models/', data);
  }

  async updateLocalModel(id: number, data: Partial<any>) {
    return this.client.patch(`/api/local-models/${id}`, data);
  }

  async deleteLocalModel(id: number, hard_delete: boolean = false) {
    return this.client.delete(`/api/local-models/${id}`, {
      params: { hard_delete }
    });
  }

  async validateLocalModel(id: number) {
    return this.client.post(`/api/local-models/${id}/validate`);
  }

  async validateLocalModelConfig(base_url: string, api_key?: string) {
    return this.client.post('/api/local-models/validate-config', null, {
      params: { base_url, api_key }
    });
  }

  // New Settings Endpoints
  async getGeneralSettings() {
    return this.client.get('/api/settings/general');
  }

  async updateGeneralSettings(data: {
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
    return this.client.post('/api/settings/general', data);
  }

  async getLocalModelsSettings() {
    return this.client.get('/api/settings/local-models');
  }

  async updateLocalModelsSettings(data: {
    provider?: string;
    base_url?: string;
    model_name?: string;
    api_key?: string | null;
  }) {
    return this.client.post('/api/settings/local-models', data);
  }

  async getWorkspaceSettings() {
    return this.client.get('/api/settings/workspace');
  }

  async updateWorkspaceSettings(data: {
    workspace_path?: string;
    allow_read?: boolean;
    allow_write?: boolean;
    require_approval?: boolean;
    auto_detect_git?: boolean;
    backup_before_edit?: boolean;
  }) {
    return this.client.post('/api/settings/workspace', data);
  }

  async getModelDefaults() {
    return this.client.get('/api/settings/model-defaults');
  }

  async updateModelDefaults(data: {
    primary_model?: string;
    fallback_model?: string;
    embedding_model?: string;
    routing_strategy?: string;
    daily_token_limit?: number;
    monthly_token_limit?: number;
    alert_threshold?: number;
  }) {
    return this.client.post('/api/settings/model-defaults', data);
  }

  async getModelDefaultsSettings() {
    return this.client.get('/api/settings/model-defaults');
  }

  async updateModelDefaultsSettings(data: {
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
    return this.client.post('/api/settings/model-defaults', data);
  }

  // Workflow History
  async getWorkflowHistory(workflowId: number, limit: number = 50, offset: number = 0) {
    return this.client.get(`/api/orchestration/workflows/${workflowId}/history`, {
      params: { limit, offset }
    });
  }

  // DeepAgents
  async createDeepAgent(data: {
    name: string;
    description?: string;
    category: string;
    config: any;
    base_template_id?: string;
  }) {
    return this.client.post('/api/deepagents/', data);
  }

  async listDeepAgents(config?: { category?: string; public_only?: boolean; signal?: AbortSignal }) {
    const { signal, ...params } = config || {};
    return this.client.get('/api/deepagents/', { params: Object.keys(params).length ? params : undefined, signal });
  }

  async listDeepAgentTemplates(config?: { signal?: AbortSignal }) {
    const { signal } = config || {};
    return this.client.get('/api/deepagents/templates', { signal });
  }

  async getDeepAgent(id: number) {
    return this.client.get(`/api/deepagents/${id}`);
  }

  async updateDeepAgent(id: number, data: Partial<any>) {
    return this.client.put(`/api/deepagents/${id}`, data);
  }

  async deleteDeepAgent(id: number) {
    return this.client.delete(`/api/deepagents/${id}`);
  }

  async previewPromptAssembly(model: string, systemPrompt?: string, customPrompt?: string, customSuffix?: string) {
    return this.client.post('/api/deepagents/prompt-preview', { model, system_prompt: systemPrompt, custom_prompt: customPrompt, custom_suffix: customSuffix });
  }

  async saveAgentPrompt(agentId: number, customPrompt?: string, customSuffix?: string) {
    return this.client.patch(`/api/deepagents/${agentId}/prompt`, { custom_prompt: customPrompt, custom_suffix: customSuffix });
  }

  // Generation
  async generateAgentConfig(data: {
    name: string;
    description: string;
    agent_type: string;
    category: string;
  }) {
    return this.client.post('/api/generation/generate', data);
  }

  async exportDeepAgent(id: number, data: {
    export_type: string;
    include_chat_ui: boolean;
    include_docker: boolean;
  }) {
    return this.client.post(`/api/deepagents/${id}/export`, data);
  }

  /**
   * Import a DeepAgent from a .langconfig payload.
   * Used by Phase 9 / Step L0 to register the `graphindex_chat` template
   * from the Knowledge panel.
   *
   * NOTE: Accepts a *parsed object* (not a pre-stringified string).
   * The BE endpoint expects `langconfig_content` as a JSON string field
   * inside a JSON object body; we serialize it here so axios sends
   * `Content-Type: application/json` (a raw string would be sent as
   * `text/plain` and rejected with 422).
   *
   * Robustness: try TWO paths:
   *   1. Direct axios POST to VITE_API_BASE_URL/api/deepagents/import
   *      (works if backend is reachable + CORS allows)
   *   2. Native fetch POST to window.location.origin/api/deepagents/import
   *      (same-origin; works through Vite dev proxy or Tauri webview
   *      bundled origin, no CORS check)
   *
   * Path 2 is the one that ACTUALLY works in the Tauri webview, where
   * cross-origin XHR is blocked. We use native fetch for path 2 because
   * mutating axios's baseURL after construction has no effect on the
   * already-created AxiosInstance.
   */
  async importDeepAgent(langconfig: object) {
    const body = { langconfig_content: JSON.stringify(langconfig) };
    const directUrl = `${this.baseURL || ''}/api/deepagents/import`;
    const fallbackUrl = `${window.location.origin}/api/deepagents/import`;

    // Path 1: direct axios call
    try {
      console.log(`[apiClient] POST ${directUrl}`);
      return await this.client.post('/api/deepagents/import', body);
    } catch (err: any) {
      const isNetwork = !err?.response;
      console.warn(
        `[apiClient] direct ${directUrl} failed ` +
        `(${err?.message || 'network'}${err?.response?.status ? ' HTTP ' + err.response.status : ''}); ` +
        `retrying ${fallbackUrl}`
      );
      if (!isNetwork && err?.response?.status) {
        // Server responded with a non-2xx — surface it, don't retry.
        throw err;
      }
    }

    // Path 2: native fetch same-origin (bypasses axios & CORS)
    try {
      console.log(`[apiClient] POST ${fallbackUrl} (native fetch)`);
      const res = await fetch(fallbackUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(
          `HTTP ${res.status} from ${fallbackUrl}: ${text.slice(0, 300)}`
        );
      }
      const data = await res.json();
      return { data, status: res.status, statusText: res.statusText, headers: res.headers, config: {} as any };
    } catch (err: any) {
      console.error(`[apiClient] fallback to ${fallbackUrl} also failed:`, err);
      throw err;
    }
  }

  // Custom Tools
  async listCustomTools(config?: { project_id?: number; template_type?: string; tool_type?: string; signal?: AbortSignal }) {
    const { signal, ...params } = config || {};
    return this.client.get('/api/custom-tools', { params: Object.keys(params).length ? params : undefined, signal });
  }

  // Native Tool Registry (single source of truth for UI tool pickers)
  async listToolRegistry(config?: { signal?: AbortSignal }) {
    return this.client.get('/api/tools/registry', config);
  }

  // Native tool details — returns full LLM-facing description and args schema
  async getToolDetails(toolId: string, config?: { signal?: AbortSignal }) {
    return this.client.get(`/api/tools/registry/${toolId}/details`, config);
  }

  async getCustomTool(toolId: string, config?: { signal?: AbortSignal }) {
    return this.client.get(`/api/custom-tools/${toolId}`, config);
  }

  async createCustomTool(data: any) {
    return this.client.post('/api/custom-tools', data);
  }

  async updateCustomTool(toolId: string, data: any) {
    return this.client.put(`/api/custom-tools/${toolId}`, data);
  }

  async deleteCustomTool(toolId: string) {
    return this.client.delete(`/api/custom-tools/${toolId}`);
  }

  async testCustomTool(toolId: string, testInput: any) {
    return this.client.post(`/api/custom-tools/${toolId}/test`, { test_input: testInput });
  }

  async duplicateCustomTool(toolId: string, newToolId: string) {
    return this.client.post(`/api/custom-tools/${toolId}/duplicate`, { new_tool_id: newToolId });
  }

  async exportCustomTool(toolId: string) {
    return this.client.post(`/api/custom-tools/${toolId}/export`, {}, { responseType: 'blob' });
  }

  async importCustomTool(file: File) {
    const formData = new FormData();
    formData.append('file', file);
    return this.client.post('/api/custom-tools/import', formData);
  }

  async verifyCustomToolCode(data: { code: string; function_name: string; description?: string; auto_fix?: boolean }) {
    return this.client.post('/api/custom-tools/verify-code', data);
  }

  async generateCustomToolCode(data: { prompt: string; function_name: string; description?: string }) {
    return this.client.post('/api/custom-tools/generate-code', data);
  }

  async listToolTemplates() {
    return this.client.get('/api/custom-tools/templates/list');
  }

  async getToolTemplate(templateId: string) {
    return this.client.get(`/api/custom-tools/templates/${templateId}`);
  }

  // Background Tasks
  async getBackgroundTask(taskId: number) {
    return this.client.get(`/api/background-tasks/${taskId}`);
  }

  async listBackgroundTasks(params?: { status?: string; limit?: number; skip?: number }) {
    return this.client.get('/api/background-tasks', { params });
  }

  async retryBackgroundTask(taskId: number) {
    return this.client.post(`/api/background-tasks/${taskId}/retry`);
  }

  async cancelBackgroundTask(taskId: number) {
    return this.client.post(`/api/background-tasks/${taskId}/cancel`);
  }

  // Chat
  async startChatSession(agentId: number) {
    return this.client.post('/api/chat/start', { agent_id: agentId });
  }

  async endChatSession(sessionId: string) {
    return this.client.post(`/api/chat/${sessionId}/end`);
  }

  async getChatSessions() {
    return this.client.get('/api/chat/sessions');
  }

  async getChatHistory(sessionId: string) {
    return this.client.get(`/api/chat/${sessionId}/history`);
  }

  async getChatMetrics(sessionId: string) {
    return this.client.get(`/api/chat/${sessionId}/metrics`);
  }

  // Action Presets
  async listActionPresets(params?: {
    category?: string;
    action_type?: string;
    risk_level?: string;
    requires_runtime?: boolean;
  }) {
    return this.client.get('/api/action-presets/', { params });
  }

  async getActionPreset(presetId: string) {
    return this.client.get(`/api/action-presets/${presetId}`);
  }

  async listActionCategories() {
    return this.client.get('/api/action-presets/categories/list');
  }

  async getRecommendedActions(agentType: string) {
    return this.client.get(`/api/action-presets/recommended/${agentType}`);
  }

  // Directory Browser
  async browseDirectories(path?: string) {
    return this.client.get('/api/settings/browse-directories', {
      params: { path: path || '.' }
    });
  }

  // Workflow Output Path
  async validateOutputPath(workflowId: number, path: string) {
    return this.client.post(`/api/workflows/${workflowId}/validate-output-path`, { path });
  }

  // =============================================================================
  // File Viewer - Tree, Versions, and Diff APIs
  // =============================================================================

  /**
   * Get hierarchical file tree for folder navigation
   */
  async getFileTree(workflowId?: number) {
    const params = workflowId ? { workflow_id: workflowId } : undefined;
    return this.client.get('/api/workspace/files/tree', { params });
  }

  /**
   * Get files grouped by task for a workflow
   */
  async getWorkflowFilesGrouped(workflowId: number) {
    return this.client.get(`/api/workspace/workflows/${workflowId}/files/grouped`);
  }

  /**
   * Get version history for a file
   */
  async getFileVersions(fileId: number) {
    return this.client.get(`/api/workspace/files/${fileId}/versions`);
  }

  /**
   * Get diff between two file versions
   */
  async getFileDiff(fileId: number, v1: number, v2: number) {
    return this.client.get(`/api/workspace/files/${fileId}/diff`, {
      params: { v1, v2 }
    });
  }

  /**
   * Get content of a specific file version
   */
  async getFileVersionContent(fileId: number, versionNumber: number) {
    return this.client.get(`/api/workspace/files/${fileId}/version/${versionNumber}/content`);
  }

  /**
   * Get full file metadata including version count
   */
  async getFullFileMetadata(fileId: number) {
    return this.client.get(`/api/workspace/files/${fileId}/metadata/full`);
  }

  /**
   * Get file metadata by path
   */
  async getFileMetadataByPath(filePath: string) {
    return this.client.get('/api/workspace/files/by-path', {
      params: { file_path: filePath }
    });
  }

  /**
   * Update file metadata (tags, description, etc.)
   */
  async updateFileMetadata(fileId: number, data: {
    description?: string;
    content_type?: string;
    tags?: string[];
  }) {
    return this.client.patch(`/api/workspace/files/metadata/${fileId}`, data);
  }

  // =============================================================================
  // Workflow Schedules
  // =============================================================================

  /**
   * List schedules for a workflow
   */
  async listSchedules(workflowId: number) {
    return this.client.get(`/api/schedules/workflow/${workflowId}`);
  }

  /**
   * Get a specific schedule
   */
  async getSchedule(scheduleId: number) {
    return this.client.get(`/api/schedules/${scheduleId}`);
  }

  /**
   * Create a new schedule
   */
  async createSchedule(data: {
    workflow_id: number;
    name?: string;
    cron_expression: string;
    timezone?: string;
    enabled?: boolean;
    default_input_data?: Record<string, unknown>;
    max_concurrent_runs?: number;
    timeout_minutes?: number;
    idempotency_key_template?: string;
  }) {
    return this.client.post('/api/schedules/', data);
  }

  /**
   * Update an existing schedule
   */
  async updateSchedule(scheduleId: number, data: {
    name?: string;
    cron_expression?: string;
    timezone?: string;
    enabled?: boolean;
    default_input_data?: Record<string, unknown>;
    max_concurrent_runs?: number;
    timeout_minutes?: number;
    idempotency_key_template?: string;
  }) {
    return this.client.patch(`/api/schedules/${scheduleId}`, data);
  }

  /**
   * Delete a schedule
   */
  async deleteSchedule(scheduleId: number) {
    return this.client.delete(`/api/schedules/${scheduleId}`);
  }

  /**
   * Manually trigger a schedule
   */
  async triggerScheduleNow(scheduleId: number) {
    return this.client.post(`/api/schedules/${scheduleId}/trigger`);
  }

  /**
   * Get execution history for a schedule
   */
  async getScheduleHistory(scheduleId: number, params?: { limit?: number; skip?: number }) {
    return this.client.get(`/api/schedules/${scheduleId}/history`, { params });
  }

  /**
   * Validate a cron expression
   */
  async validateCronExpression(cronExpression: string, timezone?: string) {
    return this.client.post('/api/schedules/validate-cron', {
      cron_expression: cronExpression,
      timezone: timezone || 'UTC'
    });
  }

  // =============================================================================
  // Workflow Triggers (Webhooks, File Watch)
  // =============================================================================

  /**
   * List triggers for a workflow
   */
  async listTriggers(workflowId: number) {
    return this.client.get(`/api/triggers/workflow/${workflowId}`);
  }

  /**
   * Get a specific trigger
   */
  async getTrigger(triggerId: number) {
    return this.client.get(`/api/triggers/${triggerId}`);
  }

  /**
   * Create a new trigger
   */
  async createTrigger(data: {
    workflow_id: number;
    trigger_type: 'webhook' | 'file_watch';
    name?: string;
    enabled?: boolean;
    config: Record<string, unknown>;
  }) {
    return this.client.post('/api/triggers/', data);
  }

  /**
   * Update an existing trigger
   */
  async updateTrigger(triggerId: number, data: {
    name?: string;
    enabled?: boolean;
    config?: Record<string, unknown>;
  }) {
    return this.client.patch(`/api/triggers/${triggerId}`, data);
  }

  /**
   * Delete a trigger
   */
  async deleteTrigger(triggerId: number) {
    return this.client.delete(`/api/triggers/${triggerId}`);
  }

  /**
   * Test-fire a trigger
   */
  async testTrigger(triggerId: number, testPayload?: Record<string, unknown>) {
    return this.client.post(`/api/triggers/${triggerId}/test`, {
      test_payload: testPayload || {}
    });
  }

  /**
   * Regenerate webhook secret
   */
  async regenerateWebhookSecret(triggerId: number) {
    return this.client.post(`/api/triggers/${triggerId}/regenerate-secret`);
  }

  /**
   * Get trigger execution history
   */
  async getTriggerHistory(triggerId: number, params?: { limit?: number; skip?: number }) {
    return this.client.get(`/api/triggers/${triggerId}/history`, { params });
  }

  /**
   * Validate a file watch path
   */
  async validateWatchPath(path: string) {
    return this.client.post('/api/triggers/validate-path', null, {
      params: { path }
    });
  }

  // =============================================================================
  // Skills API
  // =============================================================================

  /**
   * List all available skills with optional filtering.
   */
  async listSkills(config?: { source_type?: string; tag?: string; search?: string; signal?: AbortSignal }) {
    const { signal, ...params } = config || {};
    const cleanParams = Object.fromEntries(Object.entries(params).filter(([_, v]) => v !== undefined));
    return this.client.get('/api/skills', { params: Object.keys(cleanParams).length ? cleanParams : undefined, signal });
  }

  /**
   * Get detailed information for a specific skill.
   */
  async getSkill(skillId: string) {
    return this.client.get(`/api/skills/${skillId}`);
  }

  /**
   * Create a new personal skill.
   */
  async createSkill(data: {
    name: string;
    description?: string;
    tags?: string[];
    triggers?: string[];
    instructions?: string;
    examples?: string;
    author?: string;
    version?: string;
    required_context?: string[];
    allowed_tools?: string[];
  }) {
    return this.client.post('/api/skills', data);
  }

  /**
   * Update an existing skill (all fields optional).
   */
  async updateSkill(
    skillId: string,
    data: {
      name?: string;
      description?: string;
      tags?: string[];
      triggers?: string[];
      instructions?: string;
      examples?: string;
      author?: string;
      version?: string;
      required_context?: string[];
      allowed_tools?: string[];
    }
  ) {
    return this.client.put(`/api/skills/${skillId}`, data);
  }

  /**
   * List files in a skill's source directory.
   */
  async getSkillFiles(skillId: string) {
    return this.client.get(`/api/skills/${skillId}/files`);
  }

  /**
   * Read a single file's content from a skill's source directory.
   */
  async readSkillFile(skillId: string, filePath: string) {
    return this.client.get(`/api/skills/${skillId}/files/${filePath}`);
  }
}

// Export singleton instance
export const apiClient = new APIClient();
export default apiClient;
