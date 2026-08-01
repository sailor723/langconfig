/**
 * Workflow Schedules API — resource module extracted from the api-client
 * god-class. Methods are attached to the APIClient prototype via
 * Object.assign in api-client.ts.
 */
import type { APIClient } from '../api-client';

export interface SchedulesApi {
  listSchedules(workflowId: number): Promise<any>;
  getSchedule(scheduleId: number): Promise<any>;
  createSchedule(data: {
    workflow_id: number;
    name?: string;
    cron_expression: string;
    timezone?: string;
    enabled?: boolean;
    default_input_data?: Record<string, unknown>;
    max_concurrent_runs?: number;
    timeout_minutes?: number;
    idempotency_key_template?: string;
  }): Promise<any>;
  updateSchedule(scheduleId: number, data: {
    name?: string;
    cron_expression?: string;
    timezone?: string;
    enabled?: boolean;
    default_input_data?: Record<string, unknown>;
    max_concurrent_runs?: number;
    timeout_minutes?: number;
    idempotency_key_template?: string;
  }): Promise<any>;
  deleteSchedule(scheduleId: number): Promise<any>;
  triggerScheduleNow(scheduleId: number): Promise<any>;
  getScheduleHistory(scheduleId: number, params?: { limit?: number; skip?: number }): Promise<any>;
  validateCronExpression(cronExpression: string, timezone?: string): Promise<any>;
}

export const schedulesApi: SchedulesApi = {
  /**
   * List schedules for a workflow
   */
  async listSchedules(this: APIClient, workflowId: number) {
    return this.get(`/api/schedules/workflow/${workflowId}`);
  },

  /**
   * Get a specific schedule
   */
  async getSchedule(this: APIClient, scheduleId: number) {
    return this.get(`/api/schedules/${scheduleId}`);
  },

  /**
   * Create a new schedule
   */
  async createSchedule(this: APIClient, data: {
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
    return this.post('/api/schedules/', data);
  },

  /**
   * Update an existing schedule
   */
  async updateSchedule(this: APIClient, scheduleId: number, data: {
    name?: string;
    cron_expression?: string;
    timezone?: string;
    enabled?: boolean;
    default_input_data?: Record<string, unknown>;
    max_concurrent_runs?: number;
    timeout_minutes?: number;
    idempotency_key_template?: string;
  }) {
    return this.patch(`/api/schedules/${scheduleId}`, data);
  },

  /**
   * Delete a schedule
   */
  async deleteSchedule(this: APIClient, scheduleId: number) {
    return this.delete(`/api/schedules/${scheduleId}`);
  },

  /**
   * Manually trigger a schedule
   */
  async triggerScheduleNow(this: APIClient, scheduleId: number) {
    return this.post(`/api/schedules/${scheduleId}/trigger`);
  },

  /**
   * Get execution history for a schedule
   */
  async getScheduleHistory(this: APIClient, scheduleId: number, params?: { limit?: number; skip?: number }) {
    return this.get(`/api/schedules/${scheduleId}/history`, { params });
  },

  /**
   * Validate a cron expression
   */
  async validateCronExpression(this: APIClient, cronExpression: string, timezone?: string) {
    return this.post('/api/schedules/validate-cron', {
      cron_expression: cronExpression,
      timezone: timezone || 'UTC'
    });
  },
};
