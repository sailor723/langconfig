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

// ── Resource modules ──────────────────────────────────────────────────
// The former god-class's ~160 endpoint methods now live in src/lib/api/,
// one module per domain. Each module exports an interface (declaring the
// method surface) + a plain object of implementations that call the base
// `this.get/post/...` helpers. They are attached to the APIClient
// prototype below via Object.assign, and exposed to type-checkers via
// the `interface APIClient extends ...` declaration merge.
import { workflowsApi, type WorkflowsApi } from './api/workflows';
import { projectsApi, type ProjectsApi } from './api/projects';
import { documentsApi, type DocumentsApi } from './api/documents';
import { settingsApi, type SettingsApi } from './api/settings';
import { agentsApi, type AgentsApi } from './api/agents';
import { toolsApi, type ToolsApi } from './api/tools';
import { filesApi, type FilesApi } from './api/files';
import { backgroundTasksApi, type BackgroundTasksApi } from './api/backgroundTasks';
import { chatApi, type ChatApi } from './api/chat';
import { skillsApi, type SkillsApi } from './api/skills';
import { schedulesApi, type SchedulesApi } from './api/schedules';
import { triggersApi, type TriggersApi } from './api/triggers';

/**
 * API Client for LangConfig backend
 * Enhanced features:
 * - Optimistic locking (409 handling)
 * - Rate limiting (429 handling)
 * - Automatic toast notifications
 */
export class APIClient {
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
}

/**
 * Resource method surface — declared via interface merging so that
 * `apiClient.<resourceMethod>()` type-checks, then attached at runtime
 * with Object.assign below.
 */
export interface APIClient extends
  WorkflowsApi,
  ProjectsApi,
  DocumentsApi,
  SettingsApi,
  AgentsApi,
  ToolsApi,
  FilesApi,
  BackgroundTasksApi,
  ChatApi,
  SkillsApi,
  SchedulesApi,
  TriggersApi {}

// Attach the extracted resource methods to the class prototype.
Object.assign(
  APIClient.prototype,
  workflowsApi,
  projectsApi,
  documentsApi,
  settingsApi,
  agentsApi,
  toolsApi,
  filesApi,
  backgroundTasksApi,
  chatApi,
  skillsApi,
  schedulesApi,
  triggersApi,
);

export const apiClient = new APIClient();
export default apiClient;
