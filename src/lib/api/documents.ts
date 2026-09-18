/**
 * Documents / RAG API — resource module extracted from the api-client
 * god-class. Methods are attached to the APIClient prototype via
 * Object.assign in api-client.ts.
 */
import type { APIClient } from '../api-client';

export interface DocumentsApi {
  uploadDocument(
    projectId: number,
    file: File,
    metadata?: {
      description?: string;
      tags?: string[];
      industry?: string;
      player?: string;
      sub_category?: string;
      sub_department?: string;
    },
    onUploadProgress?: (percent: number) => void
  ): Promise<any>;
  uploadDocumentsBulk(
    projectId: number,
    files: File[],
    extractArchives?: boolean,
    metadata?: { description?: string; tags?: string[]; name?: string },
    onUploadProgress?: (percent: number) => void,
    fileMetadata?: Array<{
      description?: string;
      tags?: string[];
      name?: string;
      industry?: string;
      player?: string;
      sub_category?: string;
      sub_department?: string;
    }>
  ): Promise<any>;
  listDocuments(config: {
    project_id: number;
    skip?: number;
    limit?: number;
    status?: string;
    signal?: AbortSignal;
  }): Promise<any>;
  ingestFolderFromPath(params: { project_id: number; folder_path: string; industry?: string; player?: string }): Promise<any>;
  listNeo4jDocuments(config: { project_id: number; signal?: AbortSignal }): Promise<any>;
  getDocument(id: number): Promise<any>;
  getNeo4jDocumentContent(config: { project_id: number; name: string; max_chars?: number }): Promise<any>;
  deleteDocument(id: number): Promise<any>;
  listKVDocuments(config: { project_id: number }): Promise<any>;
  uploadKVDocumentsBulk(
    projectId: number,
    files: File[],
    fileMetadata?: Array<{ industry?: string; player?: string; sub_category?: string; sub_department?: string }>
  ): Promise<any>;
  ingestKVDocumentFolder(params: { project_id: number; folder_path: string }): Promise<any>;
  deleteKVDocument(docId: string, projectId: number): Promise<any>;
  searchDocuments(data: {
    query: string;
    project_id: number;
    top_k?: number;
    use_hyde?: boolean;
    search_mode?: string;
  }): Promise<any>;
  getSearchHistory(params: { project_id: number; limit?: number; skip?: number }): Promise<any>;
  getProjectStorageStats(projectId: number): Promise<any>;
  getDocumentContent(documentId: number): Promise<any>;
}

export const documentsApi: DocumentsApi = {
  // RAG / Documents
  async uploadDocument(
    this: APIClient,
    projectId: number,
    file: File,
    metadata?: {
    description?: string;
    tags?: string[];
    industry?: string;
    player?: string;
    sub_category?: string;
    sub_department?: string;
  },
    onUploadProgress?: (percent: number) => void
  ) {
    const formData = new FormData();
    formData.append('file', file);
    if (metadata) {
      formData.append('metadata', JSON.stringify(metadata));
    }

    return this.post('/api/rag/upload', formData, {
      params: { project_id: projectId },
      onUploadProgress: onUploadProgress
        ? (event: any) => {
            // axios progress event for multipart uploads
            if (event.total) {
              onUploadProgress(Math.round((event.loaded * 100) / event.total));
            }
          }
        : undefined,
    });
  },

  async uploadDocumentsBulk(
    this: APIClient,
    projectId: number,
    files: File[],
    extractArchives: boolean = true,
    metadata?: { description?: string; tags?: string[]; name?: string },
    onUploadProgress?: (percent: number) => void,
    /**
     * Step N+1: per-file metadata for folder uploads. When the user
     * picks a folder via the browser-native file picker (webkitdirectory),
     * each File has a `webkitRelativePath` like
     * "electric_vehicle_industry/tesla/marketing/01-product-lineup.md".
     * The frontend parses the path into industry/player/sub_category/
     * sub_department and sends ONE metadata dict per file in this array.
     * The backend applies them in order to the corresponding file.
     * If omitted, all files share `metadata`.
     */
    fileMetadata?: Array<{
      description?: string;
      tags?: string[];
      name?: string;
      industry?: string;
      player?: string;
      sub_category?: string;
      sub_department?: string;
    }>
  ) {
    const formData = new FormData();

    // Append all files
    files.forEach((file) => {
      formData.append('files', file);
    });

    // Add form fields (not query params)
    formData.append('project_id', projectId.toString());
    formData.append('extract_archives', extractArchives.toString());

    // Add shared metadata if provided
    if (metadata) {
      formData.append('metadata', JSON.stringify(metadata));
    }

    // Add per-file metadata if provided (folder upload). JSON-encoded
    // list, one entry per file index. Empty list = no per-file metadata.
    if (fileMetadata && fileMetadata.length > 0) {
      formData.append('file_metadata', JSON.stringify(fileMetadata));
    }

    return this.post('/api/rag/upload-bulk', formData, {
      onUploadProgress: onUploadProgress
        ? (event: any) => {
            if (event.total) {
              onUploadProgress(Math.round((event.loaded * 100) / event.total));
            }
          }
        : undefined,
    });
  },

  async listDocuments(this: APIClient, config: {
    project_id: number;
    skip?: number;
    limit?: number;
    status?: string;
    signal?: AbortSignal;
  }) {
    const { signal, ...params } = config;
    return this.get('/api/rag/documents', { params, signal });
  },

  /**
   * Step N+1: server-side folder ingest (Safari / Firefox fallback).
   * The user pastes an absolute folder path; the server walks it
   * and ingests every supported file, deriving industry/player/
   * sub_category metadata from the path.
   */
  async ingestFolderFromPath(this: APIClient, params: {
    project_id: number;
    folder_path: string;
    industry?: string;
    player?: string;
  }) {
    return this.post('/api/rag/ingest-folder', params);
  },

  /**
   * List documents from the Neo4j graphindex catalog (the chat's view
   * of the project's docs). Complements /api/rag/documents (Postgres
   * context_documents) — the UI merges the two so the sidebar stays
   * in sync with what the chat can actually find. See Step M of the
   * Phase 9 README.
   */
  async listNeo4jDocuments(this: APIClient, config: { project_id: number; signal?: AbortSignal }) {
    return this.get('/api/graphindex/neo4j-documents', { params: config, signal: config.signal });
  },

  async getDocument(this: APIClient, id: number) {
    return this.get(`/api/rag/documents/${id}`);
  },

  /**
   * Fetch the text content of a doc by Neo4j catalog name (not
   * by Postgres id). For docs that exist in Neo4j but not in the
   * context_documents table. See Phase 9 / Step M.
   */
  async getNeo4jDocumentContent(this: APIClient, config: { project_id: number; name: string; max_chars?: number }) {
    const response = await this.get('/api/graphindex/content', { params: config });
    return response.data as {
      doc_id: number;
      doc_name: string;
      content: string;
      char_count: number;
      source: string;
      file_path: string;
    };
  },

  async deleteDocument(this: APIClient, id: number) {
    return this.delete(`/api/rag/documents/${id}`);
  },

  // ── KV Document Store (simple file-based, no DB) ─────────────

  /**
   * List documents from the KV store (file-based, no PostgreSQL/Neo4j).
   */
  async listKVDocuments(this: APIClient, config: { project_id: number }) {
    return this.get('/api/kv/documents', { params: config });
  },

  /**
   * Upload files to the KV store.
   */
  async uploadKVDocumentsBulk(
    this: APIClient,
    projectId: number,
    files: File[],
    fileMetadata?: Array<{
      industry?: string;
      player?: string;
      sub_category?: string;
      sub_department?: string;
    }>
  ) {
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));
    formData.append('project_id', projectId.toString());
    if (fileMetadata && fileMetadata.length > 0) {
      formData.append('file_metadata', JSON.stringify(fileMetadata));
    }
    return this.post('/api/kv/upload-bulk', formData);
  },

  /**
   * Ingest a folder from the server's disk into the KV store.
   */
  async ingestKVDocumentFolder(this: APIClient, params: { project_id: number; folder_path: string }) {
    return this.post('/api/kv/ingest-folder', params);
  },

  /**
   * Delete a document from the KV store.
   */
  async deleteKVDocument(this: APIClient, docId: string, projectId: number) {
    return this.delete(`/api/kv/documents/${docId}?project_id=${projectId}`);
  },

  async searchDocuments(this: APIClient, data: {
    query: string;
    project_id: number;
    top_k?: number;
    use_hyde?: boolean;
    search_mode?: string; // "vector" or "graphindex"
  }) {
    const response = await this.post('/api/rag/search', data);
    return response.data;
  },

  async getSearchHistory(this: APIClient, params: {
    project_id: number;
    limit?: number;
    skip?: number;
  }) {
    return this.get('/api/rag/search-history', { params });
  },

  async getProjectStorageStats(this: APIClient, projectId: number) {
    return this.get(`/api/rag/projects/${projectId}/storage-stats`);
  },

  // Get extracted text/structured content for inline rendering in the
  // Knowledge panel. Supports MD, TXT, CSV, JSON, YAML, HTML, XML, code,
  // DOCX, PPTX, XLSX. Returns `{ kind, content, rows?, sheet_names?,
  // sheet_rows?, truncated }`.
  async getDocumentContent(this: APIClient, documentId: number) {
    const response = await this.get(`/api/rag/documents/${documentId}/content`);
    return response.data as {
      kind: 'markdown' | 'csv' | 'html' | 'code' | 'plain';
      content: string;
      rows?: string[][];
      sheet_names?: string[];
      sheet_rows?: string[][][];
      truncated: boolean;
    };
  },
};
