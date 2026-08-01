/**
 * Chat + Action Presets API — resource module extracted from the
 * api-client god-class. Methods are attached to the APIClient prototype
 * via Object.assign in api-client.ts.
 */
import type { APIClient } from '../api-client';

export interface ChatApi {
  startChatSession(agentId: number): Promise<any>;
  endChatSession(sessionId: string): Promise<any>;
  getChatSessions(): Promise<any>;
  getChatHistory(sessionId: string): Promise<any>;
  getChatMetrics(sessionId: string): Promise<any>;
  listActionPresets(params?: {
    category?: string;
    action_type?: string;
    risk_level?: string;
    requires_runtime?: boolean;
  }): Promise<any>;
  getActionPreset(presetId: string): Promise<any>;
  listActionCategories(): Promise<any>;
  getRecommendedActions(agentType: string): Promise<any>;
}

export const chatApi: ChatApi = {
  // Chat
  async startChatSession(this: APIClient, agentId: number) {
    return this.post('/api/chat/start', { agent_id: agentId });
  },

  async endChatSession(this: APIClient, sessionId: string) {
    return this.post(`/api/chat/${sessionId}/end`);
  },

  async getChatSessions(this: APIClient) {
    return this.get('/api/chat/sessions');
  },

  async getChatHistory(this: APIClient, sessionId: string) {
    return this.get(`/api/chat/${sessionId}/history`);
  },

  async getChatMetrics(this: APIClient, sessionId: string) {
    return this.get(`/api/chat/${sessionId}/metrics`);
  },

  // Action Presets
  async listActionPresets(this: APIClient, params?: {
    category?: string;
    action_type?: string;
    risk_level?: string;
    requires_runtime?: boolean;
  }) {
    return this.get('/api/action-presets/', { params });
  },

  async getActionPreset(this: APIClient, presetId: string) {
    return this.get(`/api/action-presets/${presetId}`);
  },

  async listActionCategories(this: APIClient) {
    return this.get('/api/action-presets/categories/list');
  },

  async getRecommendedActions(this: APIClient, agentType: string) {
    return this.get(`/api/action-presets/recommended/${agentType}`);
  },
};
