/**
 * Skills API — resource module extracted from the api-client god-class.
 * Methods are attached to the APIClient prototype via Object.assign in
 * api-client.ts.
 */
import type { APIClient } from '../api-client';

export interface SkillsApi {
  listSkills(config?: { source_type?: string; tag?: string; search?: string; signal?: AbortSignal }): Promise<any>;
  getSkill(skillId: string): Promise<any>;
  createSkill(data: {
    name: string;
    description?: string;
    tags?: string[];
    triggers?: string[];
    instructions?: string;
    examples?: string;
    author?: string;
    version?: string;
    required_context?: string[];
    allowed_tools?: string[];
  }): Promise<any>;
  updateSkill(
    skillId: string,
    data: {
      name?: string;
      description?: string;
      tags?: string[];
      triggers?: string[];
      instructions?: string;
      examples?: string;
      author?: string;
      version?: string;
      required_context?: string[];
      allowed_tools?: string[];
    }
  ): Promise<any>;
  getSkillFiles(skillId: string): Promise<any>;
  readSkillFile(skillId: string, filePath: string): Promise<any>;
}

export const skillsApi: SkillsApi = {
  /**
   * List all available skills with optional filtering.
   */
  async listSkills(this: APIClient, config?: { source_type?: string; tag?: string; search?: string; signal?: AbortSignal }) {
    const { signal, ...params } = config || {};
    const cleanParams = Object.fromEntries(Object.entries(params).filter(([_, v]) => v !== undefined));
    return this.get('/api/skills', { params: Object.keys(cleanParams).length ? cleanParams : undefined, signal });
  },

  /**
   * Get detailed information for a specific skill.
   */
  async getSkill(this: APIClient, skillId: string) {
    return this.get(`/api/skills/${skillId}`);
  },

  /**
   * Create a new personal skill.
   */
  async createSkill(this: APIClient, data: {
    name: string;
    description?: string;
    tags?: string[];
    triggers?: string[];
    instructions?: string;
    examples?: string;
    author?: string;
    version?: string;
    required_context?: string[];
    allowed_tools?: string[];
  }) {
    return this.post('/api/skills', data);
  },

  /**
   * Update an existing skill (all fields optional).
   */
  async updateSkill(
    this: APIClient,
    skillId: string,
    data: {
      name?: string;
      description?: string;
      tags?: string[];
      triggers?: string[];
      instructions?: string;
      examples?: string;
      author?: string;
      version?: string;
      required_context?: string[];
      allowed_tools?: string[];
    }
  ) {
    return this.put(`/api/skills/${skillId}`, data);
  },

  /**
   * List files in a skill's source directory.
   */
  async getSkillFiles(this: APIClient, skillId: string) {
    return this.get(`/api/skills/${skillId}/files`);
  },

  /**
   * Read a single file's content from a skill's source directory.
   */
  async readSkillFile(this: APIClient, skillId: string, filePath: string) {
    return this.get(`/api/skills/${skillId}/files/${filePath}`);
  },
};
