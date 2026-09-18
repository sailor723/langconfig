/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useEffect, useState, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Loader, Table2, Code2 } from 'lucide-react';
import apiClient from '../../../lib/api-client';
import TwoPagePdfViewer from './TwoPagePdfViewer';

type DocKind = 'markdown' | 'csv' | 'html' | 'code' | 'plain';

interface DocumentContent {
  kind: DocKind;
  content: string;
  rows?: string[][];
  sheet_names?: string[];
  sheet_rows?: string[][][];
  truncated: boolean;
}

interface DocumentViewerProps {
  documentId: number;
  documentName: string;
  documentType: string;
  /** When set, the viewer routes file/content fetches through the
      Neo4j-backed endpoints at /api/graphindex/{file,content} instead
      of the id-based /api/rag/documents/{id}/* endpoints. Used for
      docs that exist in Neo4j but not in Postgres context_documents
      (so the id-based endpoints would 404). */
  projectId?: number | null;
}

/**
 * Inline document viewer for the Knowledge panel.
 *
 * Picks a renderer based on file extension:
 *   - PDF  → TwoPagePdfViewer (canvas-based, 1/2/4 pages, zoom, pan)
 *   - MD / DOCX / PPTX  → markdown renderer (react-markdown + GFM)
 *   - CSV / XLSX  → table renderer (multi-sheet for xlsx)
 *   - HTML  → sandboxed iframe
 *   - TXT / JSON / YAML / code  → monospace <pre> with simple syntax tint
 *   - PNG / JPG / SVG / GIF / WEBP / BMP  → <img>
 *
 * For binary / Office formats, content is fetched from the backend
 * `/api/rag/documents/{id}/content` endpoint which extracts the text
 * (python-docx, python-pptx, openpyxl).
 */
export default function DocumentViewer({
  documentId,
  documentName,
  documentType,
  projectId,
}: DocumentViewerProps) {
  // Derive the file extension once (memoized)
  const ext = useMemo(() => {
    const name = documentName || '';
    return name.split('.').pop()?.toLowerCase() || '';
  }, [documentName]);

  // The on-disk `documentName` is prefixed with the content hash
  // (e.g. "ffedf1e_02_tesla_product_lineup_2025.md"). The Neo4j
  // node's `name` is the ORIGINAL filename (no hash prefix). The
  // content API queries Neo4j by name, so we need to strip the
  // hash here. Pattern: 8 hex chars + "_" + original_name.
  //
  // Without this, the content API returns
  //   {"detail":"doc not found: ffedf1e_02_tesla_product_lineup_2025.md"}
  // and the viewer shows "content size failed: 'foreign' object has
  // no attribute '__call__'" (the error gets passed to a non-callable
  // by the response-normalization code).
  const neo4jName = useMemo(() => {
    const m = (documentName || '').match(/^[0-9a-f]{8}_(.+)$/);
    return m ? m[1] : documentName;
  }, [documentName]);

  // For binary/Office formats we lazy-load content
  const [content, setContent] = useState<DocumentContent | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeSheet, setActiveSheet] = useState(0);

  // Determine if we need to fetch extracted content
  const isPdf = ext === 'pdf' || documentType === 'pdf';
  const isImage = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'].includes(ext);
  const needsFetch = !isPdf && !isImage;

  useEffect(() => {
    if (!needsFetch) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setContent(null);
    setActiveSheet(0);

    // Pick the right fetch path: Neo4j-by-name for orphan docs,
    // id-based for normal docs. The two endpoints return slightly
    // different shapes — we normalize the Neo4j response to match
    // the id-based DocumentContent shape.
    //
    // NOTE: the Neo4j node's `name` is the ORIGINAL filename
    // (no hash prefix), so we use `neo4jName` (the hash-stripped
    // version of documentName) for the content API. The file
    // endpoint (line 136) keeps the original `documentName`
    // because it serves the actual on-disk file (which has the
    // hash prefix).
    const fetcher = projectId
      ? apiClient.getNeo4jDocumentContent({ project_id: projectId, name: neo4jName })
      : apiClient.getDocumentContent(documentId);
    fetcher
      .then((raw: any) => {
        if (cancelled) return;
        // Normalize: id-based returns DocumentContent; Neo4j returns
        // { doc_name, content, char_count, source, file_path }.
        let data: DocumentContent;
        if (raw && 'kind' in raw) {
          data = raw as DocumentContent;
        } else if (raw && 'content' in raw) {
          // The Neo4j response — infer `kind` from the extension.
          const ext = (neo4jName || '').split('.').pop()?.toLowerCase() || '';
          const kind: DocKind =
            ext === 'md'   ? 'markdown' :
            ext === 'html' ? 'html'     :
            ext === 'csv'  ? 'csv'      :
            ext === 'json' || ext === 'yaml' || ext === 'yml' || ext === 'txt' || ext === 'xml' ? 'plain' :
            'code';  // any other text-like doc
          data = { kind, content: raw.content, truncated: raw.char_count >= 100_000 };
        } else {
          data = { kind: 'plain', content: String(raw ?? ''), truncated: false };
        }
        setContent(data);
      })
      .catch((err: any) => {
        if (cancelled) return;
        const detail =
          err?.response?.data?.detail ||
          err?.message ||
          'Failed to load document content';
        setError(typeof detail === 'string' ? detail : JSON.stringify(detail));
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [documentId, projectId, neo4jName, needsFetch]);

  // ----- URL helpers -----
  // For Neo4j-only docs, the file lives behind /api/graphindex/file.
  // For everything else, the standard /api/rag/documents/{id}/file.
  const fileUrl = projectId
    ? `/api/graphindex/file?project_id=${projectId}&name=${encodeURIComponent(documentName)}`
    : `/api/rag/documents/${documentId}/file`;

  // ----- PDF -----
  if (isPdf) {
    return (
      <TwoPagePdfViewer
        key={documentId}
        url={fileUrl}
        title={documentName}
      />
    );
  }

  // ----- Image -----
  if (isImage) {
    return (
      <div className="w-full flex-1 overflow-auto flex items-center justify-center bg-gray-50 dark:bg-black/20 p-4">
        <img
          src={fileUrl}
          alt={documentName}
          className="max-w-full max-h-full object-contain"
        />
      </div>
    );
  }

  // ----- Loading state -----
  if (loading) {
    return (
      <div className="w-full h-full flex items-center justify-center text-xs gap-2" style={{ color: 'var(--color-text-muted)' }}>
        <Loader className="w-3.5 h-3.5 animate-spin" />
        Extracting {ext.toUpperCase()} content…
      </div>
    );
  }

  // ----- Error state -----
  if (error) {
    return (
      <div className="w-full h-full flex items-center justify-center text-xs p-4 text-center" style={{ color: 'var(--color-text-muted)' }}>
        <div>
          <p className="text-red-500 mb-2">{error}</p>
          <a
            href={fileUrl}
            target="_blank"
            rel="noreferrer"
            className="text-primary underline"
          >
            Open {documentName} in new tab →
          </a>
        </div>
      </div>
    );
  }

  if (!content) return null;

  // ----- Markdown (also used for .md, .docx, .pptx) -----
  if (content.kind === 'markdown') {
    return (
      <div className="w-full h-full overflow-auto bg-white dark:bg-[#0d1117] text-gray-900 dark:text-gray-100">
        <div className="max-w-3xl mx-auto px-6 py-5 text-sm leading-relaxed [&_h1]:text-2xl [&_h1]:font-bold [&_h1]:mt-5 [&_h1]:mb-3 [&_h1]:pb-2 [&_h1]:border-b [&_h1]:border-gray-200 dark:[&_h1]:border-gray-700 [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:mt-4 [&_h2]:mb-2 [&_h3]:text-lg [&_h3]:font-semibold [&_h3]:mt-3 [&_h3]:mb-1.5 [&_p]:my-2 [&_ul]:list-disc [&_ul]:pl-6 [&_ul]:my-2 [&_ol]:list-decimal [&_ol]:pl-6 [&_ol]:my-2 [&_li]:my-0.5 [&_a]:text-blue-600 dark:[&_a]:text-blue-400 [&_a]:underline [&_strong]:font-semibold [&_em]:italic [&_code]:bg-gray-100 dark:[&_code]:bg-gray-800 [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-xs [&_code]:font-mono [&_pre]:bg-gray-50 dark:[&_pre]:bg-[#161b22] [&_pre]:p-3 [&_pre]:rounded [&_pre]:overflow-x-auto [&_pre]:my-3 [&_pre]:text-xs [&_blockquote]:border-l-4 [&_blockquote]:border-gray-300 dark:[&_blockquote]:border-gray-600 [&_blockquote]:pl-4 [&_blockquote]:italic [&_blockquote]:text-gray-600 dark:[&_blockquote]:text-gray-400 [&_table]:w-full [&_table]:my-3 [&_table]:border-collapse [&_th]:bg-gray-100 dark:[&_th]:bg-gray-800 [&_th]:px-2 [&_th]:py-1.5 [&_th]:border [&_th]:border-gray-300 dark:[&_th]:border-gray-600 [&_th]:text-left [&_th]:font-semibold [&_td]:px-2 [&_td]:py-1 [&_td]:border [&_td]:border-gray-200 dark:[&_td]:border-gray-700 [&_hr]:my-4 [&_hr]:border-gray-200 dark:[&_hr]:border-gray-700">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {content.content}
          </ReactMarkdown>
          {content.truncated && (
            <p className="mt-6 text-xs italic text-gray-500">
              …content truncated. Use “Open in new tab” to view the full file.
            </p>
          )}
        </div>
      </div>
    );
  }

  // ----- CSV / XLSX -----
  if (content.kind === 'csv') {
    const sheetNames = content.sheet_names;
    const isMultiSheet = Array.isArray(sheetNames) && sheetNames.length > 1;
    const sheetRows = content.sheet_rows ?? (content.rows ? [content.rows] : []);

    // Pick the active sheet's rows
    const rows = sheetRows[activeSheet] ?? [];
    if (rows.length === 0) {
      return (
        <div className="w-full h-full flex items-center justify-center text-xs" style={{ color: 'var(--color-text-muted)' }}>
          (empty sheet)
        </div>
      );
    }
    const header = rows[0];
    const body = rows.slice(1);

    return (
      <div className="w-full h-full flex flex-col overflow-hidden">
        {isMultiSheet && (
          <div className="flex items-center gap-1 overflow-x-auto border-b border-gray-200 dark:border-border-dark px-2 py-1.5 flex-shrink-0" style={{ backgroundColor: 'var(--color-panel-light)' }}>
            <Table2 className="w-3 h-3 mr-1" style={{ color: 'var(--color-text-muted)' }} />
            {sheetNames!.map((name, i) => (
              <button
                key={name}
                onClick={() => setActiveSheet(i)}
                className={`px-2 py-0.5 text-[10px] font-medium rounded whitespace-nowrap ${
                  i === activeSheet
                    ? 'bg-primary text-white'
                    : 'bg-gray-100 dark:bg-white/10 hover:bg-gray-200 dark:hover:bg-white/20'
                }`}
              >
                {name}
              </button>
            ))}
          </div>
        )}
        <div className="flex-1 overflow-auto">
          <table className="w-full text-xs border-collapse">
            <thead className="sticky top-0 z-10" style={{ backgroundColor: 'var(--color-panel-light)' }}>
              <tr>
                {header.map((cell, i) => (
                  <th key={i} className="text-left px-2 py-1 font-semibold border-b border-gray-200 dark:border-border-dark whitespace-nowrap">
                    {cell}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {body.map((row, ri) => (
                <tr key={ri} className="hover:bg-gray-50 dark:hover:bg-white/5">
                  {row.map((cell, ci) => (
                    <td key={ci} className="px-2 py-1 border-b border-gray-100 dark:border-border-dark/50 align-top">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {content.truncated && (
            <p className="text-[10px] italic px-3 py-2" style={{ color: 'var(--color-text-muted)' }}>
              …showing first {body.length} rows. Use “Open in new tab” to see the full file.
            </p>
          )}
        </div>
      </div>
    );
  }

  // ----- HTML — sandboxed iframe -----
  if (content.kind === 'html') {
    // Use srcDoc so the HTML renders without leaving the viewer; sandbox
    // blocks scripts and same-origin access.
    return (
      <iframe
        title={documentName}
        srcDoc={content.content}
        sandbox=""
        className="w-full h-full bg-white"
      />
    );
  }

  // ----- Code (json, yaml, txt, .py, .js, …) -----
  if (content.kind === 'code') {
    return (
      <div className="w-full h-full overflow-auto" style={{ backgroundColor: '#0d1117' }}>
        <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-gray-800 sticky top-0 z-10" style={{ backgroundColor: '#161b22' }}>
          <Code2 className="w-3 h-3" style={{ color: '#8b949e' }} />
          <span className="text-[10px] font-mono" style={{ color: '#8b949e' }}>{ext}</span>
        </div>
        <pre className="text-xs font-mono p-3 leading-relaxed" style={{ color: '#c9d1d9' }}>
          <code>{content.content}</code>
        </pre>
        {content.truncated && (
          <p className="text-[10px] italic px-3 pb-2" style={{ color: '#8b949e' }}>
            …content truncated. Use “Open in new tab” to view the full file.
          </p>
        )}
      </div>
    );
  }

  // ----- Plain text fallback -----
  return (
    <div className="w-full h-full overflow-auto px-4 py-3 bg-white dark:bg-[#0d1117]">
      <pre className="text-xs whitespace-pre-wrap font-mono leading-relaxed text-gray-900 dark:text-gray-100">
        {content.content}
      </pre>
    </div>
  );
}