/**
 * Workflows API — resource module extracted from the api-client god-class.
 * Methods are attached to the APIClient prototype via Object.assign in
 * api-client.ts, so call sites keep using `apiClient.<method>()`.
 */
import type { APIClient } from '../api-client';

export interface WorkflowsApi {
  listWorkflows(config?: { project_id?: number; skip?: number; limit?: number; signal?: AbortSignal }): Promise<any>;
  getWorkflow(id: number): Promise<any>;
  createWorkflow(data: {
    name: string;
    project_id?: number;
    strategy_type?: string;
    configuration: object;
    schema_output_config?: object;
    output_schema?: string;
    blueprint?: object;
  }): Promise<any>;
  updateWorkflow(id: number, data: Partial<any>): Promise<any>;
  deleteWorkflow(id: number): Promise<any>;
  getWorkflowCode(id: number): Promise<any>;
  debugWorkflow(id: number): Promise<any>;
  getWorkflowVersions(id: number): Promise<any>;
  createWorkflowVersion(id: number, data: any): Promise<any>;
  getWorkflowVersion(id: number, versionId: number): Promise<any>;
  compareWorkflowVersions(id: number, v1: number, v2: number): Promise<any>;
  continueWorkflow(id: number, data: any): Promise<any>;
  exportWorkflowExecutionDocx(executionId: number): Promise<any>;
  getWorkflowCostMetrics(id: number, days?: number): Promise<any>;
  getWorkflowMemory(workflowId: number): Promise<any>;
  addWorkflowMemoryItem(workflowId: number, data: { namespace: string[]; key: string; value: any }): Promise<any>;
  deleteWorkflowMemoryItem(workflowId: number, key: string): Promise<any>;
  clearWorkflowMemory(workflowId: number): Promise<any>;
  batchUpdateWorkflowMemory(workflowId: number, items: any[]): Promise<any>;
  executeWorkflow(data: {
    workflow_id: number;
    project_id: number;
    input_data: object;
    context_documents?: number[];
    attachments?: Array<{ type: string; name: string; mime_type: string; data?: string; size?: number }>;
    continue_from_task_id?: number;
  }): Promise<any>;
  getTaskStatus(taskId: number): Promise<any>;
  cancelTask(taskId: number): Promise<any>;
  listTaskFiles(taskId: number): Promise<any>;
  downloadTaskFile(taskId: number, filename: string): Promise<any>;
  getWorkflowHistory(workflowId: number, limit?: number, offset?: number): Promise<any>;
  validateOutputPath(workflowId: number, path: string): Promise<any>;
}

export const workflowsApi: WorkflowsApi = {
  // Workflows
  async listWorkflows(this: APIClient, config?: { project_id?: number; skip?: number; limit?: number; signal?: AbortSignal }) {
    const { signal, ...params } = config || {};
    return this.get('/api/workflows/', { params: Object.keys(params).length ? params : undefined, signal });
  },

  async getWorkflow(this: APIClient, id: number) {
    return this.get(`/api/workflows/${id}`);
  },

  async createWorkflow(this: APIClient, data: {
    name: string;
    project_id?: number;  // Optional - project association
    strategy_type?: string;  // Optional - only needed for predefined strategy workflows
    configuration: object;
    schema_output_config?: object;
    output_schema?: string;
    blueprint?: object;
  }) {
    return this.post('/api/workflows/', data);
  },

  async updateWorkflow(this: APIClient, id: number, data: Partial<any>) {
    return this.patch(`/api/workflows/${id}`, data);
  },

  async deleteWorkflow(this: APIClient, id: number) {
    return this.delete(`/api/workflows/${id}`);
  },

  async getWorkflowCode(this: APIClient, id: number) {
    return this.get(`/api/workflows/${id}/code`, {
      responseType: 'text'
    });
  },

  async debugWorkflow(this: APIClient, id: number) {
    return this.get(`/api/debug/workflow/${id}`);
  },

  async getWorkflowVersions(this: APIClient, id: number) {
    return this.get(`/api/workflows/${id}/versions`);
  },

  async createWorkflowVersion(this: APIClient, id: number, data: any) {
    return this.post(`/api/workflows/${id}/versions`, data);
  },

  async getWorkflowVersion(this: APIClient, id: number, versionId: number) {
    return this.get(`/api/workflows/${id}/versions/${versionId}`);
  },

  async compareWorkflowVersions(this: APIClient, id: number, v1: number, v2: number) {
    return this.get(`/api/workflows/${id}/versions/${v1}/compare/${v2}`);
  },

  async continueWorkflow(this: APIClient, id: number, data: any) {
    return this.post(`/api/workflows/${id}/continue`, data);
  },

  async exportWorkflowExecutionDocx(this: APIClient, executionId: number) {
    return this.get(`/api/workflows/executions/${executionId}/export/docx`, {
      responseType: 'blob'
    });
  },

  async getWorkflowCostMetrics(this: APIClient, id: number, days: number = 30) {
    return this.get(`/api/workflows/${id}/metrics/cost`, {
      params: { days }
    });
  },

  // Workflow Memory
  async getWorkflowMemory(this: APIClient, workflowId: number) {
    return this.get(`/api/workflows/${workflowId}/memory`);
  },

  async addWorkflowMemoryItem(this: APIClient, workflowId: number, data: {
    namespace: string[];
    key: string;
    value: any;
  }) {
    return this.post(`/api/workflows/${workflowId}/memory`, data);
  },

  async deleteWorkflowMemoryItem(this: APIClient, workflowId: number, key: string) {
    return this.delete(`/api/workflows/${workflowId}/memory/${key}`);
  },

  async clearWorkflowMemory(this: APIClient, workflowId: number) {
    return this.delete(`/api/workflows/${workflowId}/memory`);
  },

  async batchUpdateWorkflowMemory(this: APIClient, workflowId: number, items: any[]) {
    return this.post(`/api/workflows/${workflowId}/memory/batch`, { items });
  },

  // Orchestration
  async executeWorkflow(this: APIClient, data: {
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
    return this.post('/api/orchestration/execute', data);
  },

  async getTaskStatus(this: APIClient, taskId: number) {
    return this.get(`/api/orchestration/tasks/${taskId}`);
  },

  async cancelTask(this: APIClient, taskId: number) {
    return this.post(`/api/orchestration/tasks/${taskId}/cancel`);
  },

  async listTaskFiles(this: APIClient, taskId: number) {
    return this.get(`/api/orchestration/tasks/${taskId}/files`);
  },

  async downloadTaskFile(this: APIClient, taskId: number, filename: string) {
    return this.get(`/api/orchestration/tasks/${taskId}/files/${filename}`, {
      responseType: 'blob', // Important for file downloads
    });
  },

  // Workflow History
  async getWorkflowHistory(this: APIClient, workflowId: number, limit: number = 50, offset: number = 0) {
    return this.get(`/api/orchestration/workflows/${workflowId}/history`, {
      params: { limit, offset }
    });
  },

  // Workflow Output Path
  async validateOutputPath(this: APIClient, workflowId: number, path: string) {
    return this.post(`/api/workflows/${workflowId}/validate-output-path`, { path });
  },
};
