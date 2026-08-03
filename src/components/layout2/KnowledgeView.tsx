/**
 * KnowledgeView — workspace tab for viewing knowledge documents.
 *
 * Pure document viewer: renders Markdown, PDF, images, plain text, or
 * shows a download button for unsupported formats. Fetches content
 * directly from the KV store endpoint.
 *
 * Chat is handled by the bottom panel, not embedded in this view.
 */
import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useLayoutTokens } from './tokens';
import type { Tab } from './useLayout';
import { Database, FileText, Loader, Download, AlertCircle } from 'lucide-react';

interface KnowledgeViewProps {
  tab: Tab;
}

/* ── Supported formats ──────────────────────────────── */
const TEXT_EXTENSIONS = new Set(['md', 'txt', 'json', 'csv', 'yaml', 'yml', 'xml', 'css', 'sql', 'sh', 'bash', 'py', 'js', 'ts', 'tsx', 'jsx', 'rb', 'go', 'rs', 'java', 'kt', 'swift', 'c', 'cpp', 'h', 'hpp']);
const PDF_EXTENSIONS = new Set(['pdf']);
const HTML_EXTENSIONS = new Set(['html', 'htm']);
const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg']);

type DocStatus = 'loading' | 'loaded' | 'error';

export default function KnowledgeView({ tab }: KnowledgeViewProps) {
  const t = useLayoutTokens();

  // Derive everything from tab.data reactively so switching tabs updates the view
  const folderPath = tab.data?.folderPath ?? null;
  const projectId = tab.data?.projectId ?? 1;
  const docId: string | undefined = tab.data?.docId;
  const docName: string = tab.data?.docName ?? '';

  // Content state — resets when docId changes
  const [content, setContent] = useState<string | null>(null);
  const [status, setStatus] = useState<DocStatus>('loading');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Reset state when the viewed document changes
  useEffect(() => {
    setContent(null);
    setStatus('loading');
    setErrorMsg(null);
  }, [docId]);

  // Fetch document content
  useEffect(() => {
    if (!docId) {
      setContent(null);
      setStatus('loading');
      return;
    }

    let cancelled = false;
    setStatus('loading');
    setErrorMsg(null);
    setContent(null);

    const ext = docName.split('.').pop()?.toLowerCase() || '';
    const isBinary = !TEXT_EXTENSIONS.has(ext) && !PDF_EXTENSIONS.has(ext) && !IMAGE_EXTENSIONS.has(ext);

    if (isBinary) {
      setStatus('loaded');
      return;
    }
    if (PDF_EXTENSIONS.has(ext) || HTML_EXTENSIONS.has(ext) || IMAGE_EXTENSIONS.has(ext)) {
      setStatus('loaded');
      return;
    }

    // Text-based formats — fetch content from KV store
    fetch(`/api/kv/documents/${docId}/file?project_id=${projectId}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        return res.text();
      })
      .then((text) => {
        if (cancelled) return;
        setContent(text);
        setStatus('loaded');
      })
      .catch((err) => {
        if (cancelled) return;
        setErrorMsg(err.message || 'Failed to load document');
        setStatus('error');
      });

    return () => { cancelled = true; };
  }, [docId, projectId, docName]);

  // File URL for PDF/images/download
  const fileUrl = docId ? `/api/kv/documents/${docId}/file?project_id=${projectId}` : null;

  const ext = docName.split('.').pop()?.toLowerCase() || '';
  const isPdf = PDF_EXTENSIONS.has(ext);
  const isHtml = HTML_EXTENSIONS.has(ext);
  const isImage = IMAGE_EXTENSIONS.has(ext);
  const isText = TEXT_EXTENSIONS.has(ext);
  const isMarkdown = ext === 'md';

  const cardStyle: React.CSSProperties = {
    background: t.bgContent,
    border: `1px solid ${t.border}`,
    borderRadius: 6,
  };

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflow: 'hidden',
        padding: 16,
        gap: 10,
      }}
    >
      {/* ── Breadcrumb ───────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
        <Database size={16} style={{ color: '#a855f7' }} />
        <span style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', color: t.textMuted }}>
          Knowledge
        </span>
        {folderPath && (
          <>
            <span style={{ color: t.textMuted }}>/</span>
            <span style={{ fontSize: 13, color: t.textPrimary }}>
              {folderPath.replace(/_/g, ' ').replace(/\//g, ' / ')}
            </span>
          </>
        )}
        {docName && (
          <>
            <span style={{ color: t.textMuted }}>/</span>
            <span style={{ fontSize: 12, color: '#a855f7', fontWeight: 500 }}>
              {docName}
            </span>
          </>
        )}
      </div>

      {/* ── Document viewer ──────────────────────────── */}
      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          ...cardStyle,
        }}
      >
        {!docId ? (
          /* Empty state */
          <div style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 12,
            color: t.textMuted,
          }}>
            <FileText size={32} style={{ opacity: 0.3 }} />
            <p style={{ fontSize: 14, textAlign: 'center' }}>
              Select a document from the Knowledge sidebar<br />
              to view its content here.
            </p>
          </div>
        ) : status === 'loading' && isText ? (
          /* Loading state */
          <div style={{
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
            color: t.textMuted,
            fontSize: 13,
          }}>
            <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
            Loading {docName}...
          </div>
        ) : status === 'error' ? (
          /* Error state */
          <div style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 12,
            padding: 24,
            color: t.textMuted,
            fontSize: 13,
            textAlign: 'center',
          }}>
            <AlertCircle size={24} style={{ color: '#e5484d' }} />
            <p style={{ color: '#e5484d' }}>{errorMsg}</p>
            {fileUrl && (
              <a
                href={fileUrl}
                target="_blank"
                rel="noreferrer"
                style={{ color: '#a855f7', textDecoration: 'underline', fontSize: 12 }}
              >
                Open {docName} in new tab &rarr;
              </a>
            )}
          </div>
        ) : isPdf || isHtml ? (
          /* PDF/HTML: render via iframe (browser-native viewer) */
          <iframe
            src={fileUrl!}
            title={docName}
            style={{ width: '100%', height: '100%', border: 'none' }}
          />
        ) : isImage ? (
          /* Image: render inline */
          <div style={{
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            overflow: 'auto',
            padding: 16,
          }}>
            <img
              src={fileUrl!}
              alt={docName}
              style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
            />
          </div>
        ) : isMarkdown && content ? (
          /* Markdown: render with react-markdown */
          <div style={{
            flex: 1,
            overflow: 'auto',
            padding: '16px 24px',
            fontSize: 14,
            lineHeight: 1.6,
            color: t.textPrimary,
          }}>
            <div className="markdown-body" style={{ maxWidth: 800 }}>
              <style>{`
                .markdown-body h1 { font-size: 1.6em; font-weight: 700; margin: 0.8em 0 0.4em; padding-bottom: 0.3em; border-bottom: 1px solid ${t.border}; }
                .markdown-body h2 { font-size: 1.35em; font-weight: 600; margin: 0.7em 0 0.3em; }
                .markdown-body h3 { font-size: 1.15em; font-weight: 600; margin: 0.6em 0 0.25em; }
                .markdown-body p { margin: 0.5em 0; }
                .markdown-body ul, .markdown-body ol { padding-left: 1.5em; margin: 0.4em 0; }
                .markdown-body li { margin: 0.2em 0; }
                .markdown-body a { color: #a855f7; text-decoration: underline; }
                .markdown-body pre { background: ${t.bgBase}; padding: 12px; border-radius: 6px; overflow-x: auto; margin: 0.6em 0; font-size: 0.875em; }
                .markdown-body code { background: ${t.bgHover}; padding: 1px 4px; border-radius: 3px; font-size: 0.875em; }
                .markdown-body pre code { background: transparent; padding: 0; }
                .markdown-body blockquote { border-left: 3px solid #a855f7; padding-left: 12px; color: ${t.textMuted}; margin: 0.5em 0; }
                .markdown-body table { border-collapse: collapse; width: 100%; margin: 0.6em 0; }
                .markdown-body th, .markdown-body td { border: 1px solid ${t.border}; padding: 6px 10px; text-align: left; }
                .markdown-body th { background: ${t.bgBase}; font-weight: 600; }
                .markdown-body hr { border: none; border-top: 1px solid ${t.border}; margin: 1em 0; }
                .markdown-body img { max-width: 100%; }
              `}</style>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {content}
              </ReactMarkdown>
            </div>
          </div>
        ) : isText && content ? (
          /* Plain text / code: render in pre */
          <pre style={{
            flex: 1,
            overflow: 'auto',
            padding: '12px 16px',
            margin: 0,
            fontSize: 13,
            fontFamily: 'ui-monospace, SFMono-Regular, monospace',
            lineHeight: 1.5,
            color: t.textPrimary,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}>
            {content}
          </pre>
        ) : (
          /* Unsupported format: download button */
          <div style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 12,
            color: t.textMuted,
            fontSize: 13,
            textAlign: 'center',
          }}>
            <FileText size={28} style={{ opacity: 0.3 }} />
            <p>Preview not available for <strong>.{ext}</strong> files.</p>
            {fileUrl && (
              <a
                href={fileUrl}
                download={docName}
                target="_blank"
                rel="noreferrer"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '6px 14px',
                  background: '#a855f7',
                  color: '#fff',
                  borderRadius: 6,
                  textDecoration: 'none',
                  fontSize: 12,
                  fontWeight: 500,
                }}
              >
                <Download size={12} />
                Download {docName}
              </a>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
