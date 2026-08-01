/**
 * Workspace Files API — resource module extracted from the api-client
 * god-class. Methods are attached to the APIClient prototype via
 * Object.assign in api-client.ts.
 */
import type { APIClient } from '../api-client';

export interface FilesApi {
  getFileTree(workflowId?: number): Promise<any>;
  getWorkflowFilesGrouped(workflowId: number): Promise<any>;
  getFileVersions(fileId: number): Promise<any>;
  getFileDiff(fileId: number, v1: number, v2: number): Promise<any>;
  getFileVersionContent(fileId: number, versionNumber: number): Promise<any>;
  getFullFileMetadata(fileId: number): Promise<any>;
  getFileMetadataByPath(filePath: string): Promise<any>;
  updateFileMetadata(fileId: number, data: { description?: string; content_type?: string; tags?: string[] }): Promise<any>;
}

export const filesApi: FilesApi = {
  /**
   * Get hierarchical file tree for folder navigation
   */
  async getFileTree(this: APIClient, workflowId?: number) {
    const params = workflowId ? { workflow_id: workflowId } : undefined;
    return this.get('/api/workspace/files/tree', { params });
  },

  /**
   * Get files grouped by task for a workflow
   */
  async getWorkflowFilesGrouped(this: APIClient, workflowId: number) {
    return this.get(`/api/workspace/workflows/${workflowId}/files/grouped`);
  },

  /**
   * Get version history for a file
   */
  async getFileVersions(this: APIClient, fileId: number) {
    return this.get(`/api/workspace/files/${fileId}/versions`);
  },

  /**
   * Get diff between two file versions
   */
  async getFileDiff(this: APIClient, fileId: number, v1: number, v2: number) {
    return this.get(`/api/workspace/files/${fileId}/diff`, {
      params: { v1, v2 }
    });
  },

  /**
   * Get content of a specific file version
   */
  async getFileVersionContent(this: APIClient, fileId: number, versionNumber: number) {
    return this.get(`/api/workspace/files/${fileId}/version/${versionNumber}/content`);
  },

  /**
   * Get full file metadata including version count
   */
  async getFullFileMetadata(this: APIClient, fileId: number) {
    return this.get(`/api/workspace/files/${fileId}/metadata/full`);
  },

  /**
   * Get file metadata by path
   */
  async getFileMetadataByPath(this: APIClient, filePath: string) {
    return this.get('/api/workspace/files/by-path', {
      params: { file_path: filePath }
    });
  },

  /**
   * Update file metadata (tags, description, etc.)
   */
  async updateFileMetadata(this: APIClient, fileId: number, data: {
    description?: string;
    content_type?: string;
    tags?: string[];
  }) {
    return this.patch(`/api/workspace/files/metadata/${fileId}`, data);
  },
};
