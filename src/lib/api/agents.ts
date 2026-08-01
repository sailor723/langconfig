/**
 * DeepAgents API — resource module extracted from the api-client
 * god-class. Methods are attached to the APIClient prototype via
 * Object.assign in api-client.ts.
 */
import type { APIClient } from '../api-client';

export interface AgentsApi {
  createDeepAgent(data: {
    name: string;
    description?: string;
    category: string;
    config: any;
    base_template_id?: string;
  }): Promise<any>;
  listDeepAgents(config?: { category?: string; public_only?: boolean; signal?: AbortSignal }): Promise<any>;
  listDeepAgentTemplates(config?: { signal?: AbortSignal }): Promise<any>;
  getDeepAgent(id: number): Promise<any>;
  updateDeepAgent(id: number, data: Partial<any>): Promise<any>;
  deleteDeepAgent(id: number): Promise<any>;
  previewPromptAssembly(model: string, systemPrompt?: string, customPrompt?: string, customSuffix?: string): Promise<any>;
  saveAgentPrompt(agentId: number, customPrompt?: string, customSuffix?: string): Promise<any>;
  generateAgentConfig(data: { name: string; description: string; agent_type: string; category: string }): Promise<any>;
  exportDeepAgent(id: number, data: { export_type: string; include_chat_ui: boolean; include_docker: boolean }): Promise<any>;
  importDeepAgent(langconfig: object): Promise<any>;
}

export const agentsApi: AgentsApi = {
  // DeepAgents
  async createDeepAgent(this: APIClient, data: {
    name: string;
    description?: string;
    category: string;
    config: any;
    base_template_id?: string;
  }) {
    return this.post('/api/deepagents/', data);
  },

  async listDeepAgents(this: APIClient, config?: { category?: string; public_only?: boolean; signal?: AbortSignal }) {
    const { signal, ...params } = config || {};
    return this.get('/api/deepagents/', { params: Object.keys(params).length ? params : undefined, signal });
  },

  async listDeepAgentTemplates(this: APIClient, config?: { signal?: AbortSignal }) {
    const { signal } = config || {};
    return this.get('/api/deepagents/templates', { signal });
  },

  async getDeepAgent(this: APIClient, id: number) {
    return this.get(`/api/deepagents/${id}`);
  },

  async updateDeepAgent(this: APIClient, id: number, data: Partial<any>) {
    return this.put(`/api/deepagents/${id}`, data);
  },

  async deleteDeepAgent(this: APIClient, id: number) {
    return this.delete(`/api/deepagents/${id}`);
  },

  async previewPromptAssembly(this: APIClient, model: string, systemPrompt?: string, customPrompt?: string, customSuffix?: string) {
    return this.post('/api/deepagents/prompt-preview', { model, system_prompt: systemPrompt, custom_prompt: customPrompt, custom_suffix: customSuffix });
  },

  async saveAgentPrompt(this: APIClient, agentId: number, customPrompt?: string, customSuffix?: string) {
    return this.patch(`/api/deepagents/${agentId}/prompt`, { custom_prompt: customPrompt, custom_suffix: customSuffix });
  },

  // Generation
  async generateAgentConfig(this: APIClient, data: {
    name: string;
    description: string;
    agent_type: string;
    category: string;
  }) {
    return this.post('/api/generation/generate', data);
  },

  async exportDeepAgent(this: APIClient, id: number, data: {
    export_type: string;
    include_chat_ui: boolean;
    include_docker: boolean;
  }) {
    return this.post(`/api/deepagents/${id}/export`, data);
  },

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
  async importDeepAgent(this: APIClient, langconfig: object) {
    const body = { langconfig_content: JSON.stringify(langconfig) };
    const directUrl = `${this.baseURL || ''}/api/deepagents/import`;
    const fallbackUrl = `${window.location.origin}/api/deepagents/import`;

    // Path 1: direct axios call
    try {
      console.log(`[apiClient] POST ${directUrl}`);
      return await this.post('/api/deepagents/import', body);
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
  },
};
