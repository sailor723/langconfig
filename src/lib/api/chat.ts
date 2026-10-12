/**
 * Chat + Action Presets API — resource module extracted from the
 * api-client god-class. Methods are attached to the APIClient prototype
 * via Object.assign in api-client.ts.
 */
import type { APIClient } from '../api-client';

export interface ChatApi {
  startChatSession(agentId: number, projectId?: number | null): Promise<any>;
  endChatSession(sessionId: string): Promise<any>;
  getChatSessions(): Promise<any>;
  /** Pin/unpin a conversation (chat history quick select). */
  setChatFavorite(sessionId: string, favorite: boolean): Promise<any>;
  /** Rename a conversation; empty string clears it back to the fallback. */
  setChatTitle(sessionId: string, title: string): Promise<any>;
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
  async startChatSession(this: APIClient, agentId: number, projectId?: number | null) {
    return this.post('/api/chat/start', {
      agent_id: agentId,
      project_id: projectId ?? undefined, // active vault scopes the agent workspace
    });
  },

  async endChatSession(this: APIClient, sessionId: string) {
    return this.post(`/api/chat/${sessionId}/end`);
  },

  async getChatSessions(this: APIClient) {
    return this.get('/api/chat/sessions');
  },

  /** Pin/unpin a conversation. Purely a bookmark: never touches the messages. */
  async setChatFavorite(this: APIClient, sessionId: string, favorite: boolean) {
    return this.post(`/api/chat/${sessionId}/favorite`, { favorite });
  },

  /** Rename a conversation. Blank clears it, returning the UI to its fallback. */
  async setChatTitle(this: APIClient, sessionId: string, title: string) {
    return this.post(`/api/chat/${sessionId}/title`, { title });
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
