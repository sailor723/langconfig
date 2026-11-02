/**
 * Users API — accounts: who is asking, and (for admins) who exists.
 *
 * Two surfaces, mirroring the backend:
 *   - self-service: `getMe` / `updateMe` / `changeMyPassword`
 *   - administration: `listUsers` / `createUser` / `updateUser` / `adminSetPassword`
 *
 * There is no login endpoint and no token: the browser's Basic-auth prompt is the
 * login, handled by the LAN gate before any of this runs. "Sign out" is therefore
 * a browser action, not an API call.
 */
import type { APIClient } from '../api-client';

export interface UserSummary {
  id: number;
  username: string;
  /** Optional alias that also works at the sign-in prompt (case-insensitive). */
  nickname: string | null;
  display_name: string | null;
  role: 'admin' | 'member';
  is_active: boolean;
  created_at: string | null;
  last_login_at: string | null;
}

export interface UsersApi {
  getMe(): Promise<{ data: UserSummary }>;
  updateMe(data: { display_name?: string | null; nickname?: string | null }): Promise<{ data: UserSummary }>;
  changeMyPassword(data: { current_password: string; new_password: string }): Promise<any>;
  listUsers(): Promise<{ data: UserSummary[] }>;
  createUser(data: {
    username: string;
    password: string;
    nickname?: string | null;
    display_name?: string | null;
    role?: 'admin' | 'member';
  }): Promise<{ data: UserSummary }>;
  updateUser(
    id: number,
    data: {
      display_name?: string | null;
      /** "" clears the alias; omit to leave it alone. */
      nickname?: string | null;
      role?: 'admin' | 'member';
      is_active?: boolean;
    }
  ): Promise<{ data: UserSummary }>;
  adminSetPassword(id: number, data: { new_password: string }): Promise<any>;
  listRoles(): Promise<{ data: { roles: string[] } }>;
}

export const usersApi: UsersApi = {
  async getMe(this: APIClient) {
    return this.get('/api/users/me');
  },

  async updateMe(this: APIClient, data: { display_name?: string | null; nickname?: string | null }) {
    return this.patch('/api/users/me', data);
  },

  async changeMyPassword(this: APIClient, data: { current_password: string; new_password: string }) {
    return this.post('/api/users/me/password', data);
  },

  async listUsers(this: APIClient) {
    return this.get('/api/users');
  },

  async createUser(this: APIClient, data: {
    username: string;
    password: string;
    display_name?: string | null;
    role?: 'admin' | 'member';
  }) {
    return this.post('/api/users', data);
  },

  async updateUser(this: APIClient, id: number, data: {
    display_name?: string | null;
    role?: 'admin' | 'member';
    is_active?: boolean;
  }) {
    return this.patch(`/api/users/${id}`, data);
  },

  async adminSetPassword(this: APIClient, id: number, data: { new_password: string }) {
    return this.post(`/api/users/${id}/password`, data);
  },

  async listRoles(this: APIClient) {
    return this.get('/api/users/roles');
  },
};
