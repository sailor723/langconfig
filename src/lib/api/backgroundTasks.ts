/**
 * BackgroundTasks API methods — extracted from src/lib/api-client.ts (Phase 2 god-class split).
 */
import type { APIClient } from '../api-client';

export interface BackgroundTasksApi {
  getBackgroundTask(taskId: number): Promise<any>;
  listBackgroundTasks(params?: { status?: string; limit?: number; skip?: number }): Promise<any>;
  retryBackgroundTask(taskId: number): Promise<any>;
  cancelBackgroundTask(taskId: number): Promise<any>;
}

export const backgroundTasksApi: BackgroundTasksApi = {
  async getBackgroundTask(this: APIClient, taskId: number) {
    return this.get(`/api/background-tasks/${taskId}`);
  },

  async listBackgroundTasks(this: APIClient, params?: { status?: string; limit?: number; skip?: number }) {
    return this.get('/api/background-tasks', { params });
  },

  async retryBackgroundTask(this: APIClient, taskId: number) {
    return this.post(`/api/background-tasks/${taskId}/retry`);
  },

  async cancelBackgroundTask(this: APIClient, taskId: number) {
    return this.post(`/api/background-tasks/${taskId}/cancel`);
  },
};
