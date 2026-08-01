/**
 * Custom Tools / Tool Registry API — resource module extracted from the
 * api-client god-class. Methods are attached to the APIClient prototype
 * via Object.assign in api-client.ts.
 */
import type { APIClient } from '../api-client';

export interface ToolsApi {
  listCustomTools(config?: { project_id?: number; template_type?: string; tool_type?: string; signal?: AbortSignal }): Promise<any>;
  listToolRegistry(config?: { signal?: AbortSignal }): Promise<any>;
  getToolDetails(toolId: string, config?: { signal?: AbortSignal }): Promise<any>;
  getCustomTool(toolId: string, config?: { signal?: AbortSignal }): Promise<any>;
  createCustomTool(data: any): Promise<any>;
  updateCustomTool(toolId: string, data: any): Promise<any>;
  deleteCustomTool(toolId: string): Promise<any>;
  testCustomTool(toolId: string, testInput: any): Promise<any>;
  duplicateCustomTool(toolId: string, newToolId: string): Promise<any>;
  exportCustomTool(toolId: string): Promise<any>;
  importCustomTool(file: File): Promise<any>;
  verifyCustomToolCode(data: { code: string; function_name: string; description?: string; auto_fix?: boolean }): Promise<any>;
  generateCustomToolCode(data: { prompt: string; function_name: string; description?: string }): Promise<any>;
  listToolTemplates(): Promise<any>;
  getToolTemplate(templateId: string): Promise<any>;
}

export const toolsApi: ToolsApi = {
  // Custom Tools
  async listCustomTools(this: APIClient, config?: { project_id?: number; template_type?: string; tool_type?: string; signal?: AbortSignal }) {
    const { signal, ...params } = config || {};
    return this.get('/api/custom-tools', { params: Object.keys(params).length ? params : undefined, signal });
  },

  // Native Tool Registry (single source of truth for UI tool pickers)
  async listToolRegistry(this: APIClient, config?: { signal?: AbortSignal }) {
    return this.get('/api/tools/registry', config);
  },

  // Native tool details — returns full LLM-facing description and args schema
  async getToolDetails(this: APIClient, toolId: string, config?: { signal?: AbortSignal }) {
    return this.get(`/api/tools/registry/${toolId}/details`, config);
  },

  async getCustomTool(this: APIClient, toolId: string, config?: { signal?: AbortSignal }) {
    return this.get(`/api/custom-tools/${toolId}`, config);
  },

  async createCustomTool(this: APIClient, data: any) {
    return this.post('/api/custom-tools', data);
  },

  async updateCustomTool(this: APIClient, toolId: string, data: any) {
    return this.put(`/api/custom-tools/${toolId}`, data);
  },

  async deleteCustomTool(this: APIClient, toolId: string) {
    return this.delete(`/api/custom-tools/${toolId}`);
  },

  async testCustomTool(this: APIClient, toolId: string, testInput: any) {
    return this.post(`/api/custom-tools/${toolId}/test`, { test_input: testInput });
  },

  async duplicateCustomTool(this: APIClient, toolId: string, newToolId: string) {
    return this.post(`/api/custom-tools/${toolId}/duplicate`, { new_tool_id: newToolId });
  },

  async exportCustomTool(this: APIClient, toolId: string) {
    return this.post(`/api/custom-tools/${toolId}/export`, {}, { responseType: 'blob' });
  },

  async importCustomTool(this: APIClient, file: File) {
    const formData = new FormData();
    formData.append('file', file);
    return this.post('/api/custom-tools/import', formData);
  },

  async verifyCustomToolCode(this: APIClient, data: { code: string; function_name: string; description?: string; auto_fix?: boolean }) {
    return this.post('/api/custom-tools/verify-code', data);
  },

  async generateCustomToolCode(this: APIClient, data: { prompt: string; function_name: string; description?: string }) {
    return this.post('/api/custom-tools/generate-code', data);
  },

  async listToolTemplates(this: APIClient) {
    return this.get('/api/custom-tools/templates/list');
  },

  async getToolTemplate(this: APIClient, templateId: string) {
    return this.get(`/api/custom-tools/templates/${templateId}`);
  },
};
