/**
 * Projects + Tasks API — resource module extracted from the api-client
 * god-class. Methods are attached to the APIClient prototype via
 * Object.assign in api-client.ts.
 */
import type { APIClient } from '../api-client';

export interface ProjectsApi {
  listProjects(config?: { skip?: number; limit?: number; status?: string; signal?: AbortSignal }): Promise<any>;
  getProject(id: number): Promise<any>;
  createProject(data: { name: string; description?: string; configuration?: object }): Promise<any>;
  updateProject(id: number, data: Partial<any>): Promise<any>;
  deleteProject(id: number): Promise<any>;
  indexProject(id: number): Promise<any>;
  getAgentsMd(projectId: number): Promise<any>;
  updateAgentsMd(projectId: number, content: string): Promise<any>;
  deleteAgentsMd(projectId: number): Promise<any>;
  listTasks(params?: { skip?: number; limit?: number; project_id?: number; status?: string }): Promise<any>;
  getTask(id: number): Promise<any>;
  getRecentProjectTasks(projectId: number, limit?: number): Promise<any>;
  getTaskStats(projectId?: number): Promise<any>;
  deleteTask(id: number): Promise<any>;
}

export const projectsApi: ProjectsApi = {
  // Projects
  async listProjects(this: APIClient, config?: { skip?: number; limit?: number; status?: string; signal?: AbortSignal }) {
    const { signal, ...params } = config || {};
    return this.get('/api/projects/', { params: Object.keys(params).length ? params : undefined, signal });
  },

  async getProject(this: APIClient, id: number) {
    return this.get(`/api/projects/${id}`);
  },

  async createProject(this: APIClient, data: {
    name: string;
    description?: string;
    configuration?: object;
  }) {
    return this.post('/api/projects/', data);
  },

  async updateProject(this: APIClient, id: number, data: Partial<any>) {
    return this.patch(`/api/projects/${id}`, data);
  },

  async deleteProject(this: APIClient, id: number) {
    return this.delete(`/api/projects/${id}`);
  },

  async indexProject(this: APIClient, id: number) {
    return this.post(`/api/projects/${id}/index`);
  },

  // AGENTS.md (MemoryMiddleware for DeepAgent)
  async getAgentsMd(this: APIClient, projectId: number) {
    return this.get(`/api/projects/${projectId}/agents-md`);
  },

  async updateAgentsMd(this: APIClient, projectId: number, content: string) {
    return this.put(`/api/projects/${projectId}/agents-md`, { content });
  },

  async deleteAgentsMd(this: APIClient, projectId: number) {
    return this.delete(`/api/projects/${projectId}/agents-md`);
  },

  // Tasks
  async listTasks(this: APIClient, params?: {
    skip?: number;
    limit?: number;
    project_id?: number;
    status?: string;
  }) {
    return this.get('/api/tasks/', { params });
  },

  async getTask(this: APIClient, id: number) {
    return this.get(`/api/tasks/${id}`);
  },

  async getRecentProjectTasks(this: APIClient, projectId: number, limit: number = 10) {
    return this.get(`/api/tasks/project/${projectId}/recent`, {
      params: { limit },
    });
  },

  async getTaskStats(this: APIClient, projectId?: number) {
    return this.get('/api/tasks/stats/summary', {
      params: { project_id: projectId },
    });
  },

  async deleteTask(this: APIClient, id: number) {
    return this.delete(`/api/tasks/${id}`);
  },
};
