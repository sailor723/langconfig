/**
 * Workflow Triggers API — resource module extracted from the api-client
 * god-class. Methods are attached to the APIClient prototype via
 * Object.assign in api-client.ts.
 */
import type { APIClient } from '../api-client';

export interface TriggersApi {
  listTriggers(workflowId: number): Promise<any>;
  getTrigger(triggerId: number): Promise<any>;
  createTrigger(data: {
    workflow_id: number;
    trigger_type: 'webhook' | 'file_watch';
    name?: string;
    enabled?: boolean;
    config: Record<string, unknown>;
  }): Promise<any>;
  updateTrigger(triggerId: number, data: { name?: string; enabled?: boolean; config?: Record<string, unknown> }): Promise<any>;
  deleteTrigger(triggerId: number): Promise<any>;
  testTrigger(triggerId: number, testPayload?: Record<string, unknown>): Promise<any>;
  regenerateWebhookSecret(triggerId: number): Promise<any>;
  getTriggerHistory(triggerId: number, params?: { limit?: number; skip?: number }): Promise<any>;
  validateWatchPath(path: string): Promise<any>;
}

export const triggersApi: TriggersApi = {
  /**
   * List triggers for a workflow
   */
  async listTriggers(this: APIClient, workflowId: number) {
    return this.get(`/api/triggers/workflow/${workflowId}`);
  },

  /**
   * Get a specific trigger
   */
  async getTrigger(this: APIClient, triggerId: number) {
    return this.get(`/api/triggers/${triggerId}`);
  },

  /**
   * Create a new trigger
   */
  async createTrigger(this: APIClient, data: {
    workflow_id: number;
    trigger_type: 'webhook' | 'file_watch';
    name?: string;
    enabled?: boolean;
    config: Record<string, unknown>;
  }) {
    return this.post('/api/triggers/', data);
  },

  /**
   * Update an existing trigger
   */
  async updateTrigger(this: APIClient, triggerId: number, data: {
    name?: string;
    enabled?: boolean;
    config?: Record<string, unknown>;
  }) {
    return this.patch(`/api/triggers/${triggerId}`, data);
  },

  /**
   * Delete a trigger
   */
  async deleteTrigger(this: APIClient, triggerId: number) {
    return this.delete(`/api/triggers/${triggerId}`);
  },

  /**
   * Test-fire a trigger
   */
  async testTrigger(this: APIClient, triggerId: number, testPayload?: Record<string, unknown>) {
    return this.post(`/api/triggers/${triggerId}/test`, {
      test_payload: testPayload || {}
    });
  },

  /**
   * Regenerate webhook secret
   */
  async regenerateWebhookSecret(this: APIClient, triggerId: number) {
    return this.post(`/api/triggers/${triggerId}/regenerate-secret`);
  },

  /**
   * Get trigger execution history
   */
  async getTriggerHistory(this: APIClient, triggerId: number, params?: { limit?: number; skip?: number }) {
    return this.get(`/api/triggers/${triggerId}/history`, { params });
  },

  /**
   * Validate a file watch path
   */
  async validateWatchPath(this: APIClient, path: string) {
    return this.post('/api/triggers/validate-path', null, {
      params: { path }
    });
  },
};
