/**
 * KnowledgeView — workspace tab for viewing knowledge documents.
 *
 * Pure document viewer: renders Markdown, PDF, images, plain text, or
 * shows a download button for unsupported formats. Fetches content
 * directly from the KV store endpoint.
 *
 * Chat is handled by the bottom panel, not embedded in this view.
 */
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useTranslation } from 'react-i18next';
import { useLayoutTokens } from './tokens';
import PdfViewer from './PdfViewer';
import type { Tab } from './useLayout';
// OfficeViewer pulls in docx-preview + pptxviewjs (~1MB) — lazy-load it so
// the initial bundle stays lean; it only loads when a .docx/.pptx is opened.
const OfficeViewer = lazy(() => import('./OfficeViewer'));
import { Database, FileText, Loader, Download, AlertCircle, List } from 'lucide-react';

/* ── In-page anchor support ─────────────────────────────
 * The app shell runs inside a HashRouter, so a plain
 * `<a href="#section">` click would change the URL hash and
 * be interpreted as a route change — unmounting this view.
 * We render headings with GitHub-style slug ids and intercept
 * `#...` links to scroll in place instead of navigating.
 */
function slugify(text: string): string {
  return text
    .toLowerCase()
    // Keep unicode letters/numbers/underscores/spaces/hyphens; strip the rest
    // (matches GitHub-slugger so common TOC anchors resolve)
    .replace(/[^\p{L}\p{N}\s_-]/gu, '')
    .trim()
    .replace(/[\s]+/g, '-')
    .replace(/-+/g, '-');
}

/** Flatten React children (headings may contain inline code etc.) to text. */
function nodeToText(node: React.ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(nodeToText).join('');
  if (node && typeof node === 'object' && 'props' in node) {
    const props = (node as { props?: { children?: React.ReactNode } }).props;
    return nodeToText(props?.children);
  }
  return '';
}

/* ── Table of contents ─────────────────────────────────
 * Headings are parsed from the raw markdown (ATX `#` form,
 * skipping fenced code blocks). The id is the same
 * GitHub-style slug used for the rendered heading element,
 * so clicking a TOC entry scrolls to the right section.
 * Duplicate heading text maps to the same id (both scroll to
 * the first occurrence) — simple and always aligned with the
 * rendered headings, which use the same slug derivation.
 */
interface TocEntry {
  level: number;
  text: string;
  id: string;
}

/** Strip inline markdown from a heading line for TOC display. */
function cleanHeadingText(raw: string): string {
  return raw
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1') // ![alt](url) -> alt
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')   // [text](url) -> text
    .replace(/`([^`]*)`/g, '$1')               // `code` -> code
    .replace(/\*\*([^*]+)\*\*/g, '$1')         // **bold**
    .replace(/__([^_]+)__/g, '$1')             // __bold__
    .replace(/\*([^*]+)\*/g, '$1')             // *italic*
    .replace(/_([^_]+)_/g, '$1')               // _italic_
    .replace(/~~([^~]+)~~/g, '$1')             // ~~strike~~
    .replace(/<[^>]*>/g, '')                   // inline HTML
    .replace(/\s+/g, ' ')
    .trim();
}

function extractToc(markdown: string): TocEntry[] {
  const entries: TocEntry[] = [];
  let inFence = false;

  for (const line of markdown.split('\n')) {
    // Fenced code blocks: `#` inside them is not a heading.
    if (/^\s*(```|~~~)/.test(line)) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;

    const m = /^(#{1,6})\s+(.+)$/.exec(line);
    if (!m) continue;

    let text = cleanHeadingText(m[2]);
    // CommonMark: trailing hashes are only stripped when preceded by a space.
    text = text.replace(/\s+#+$/, '');
    if (!text) continue;

    entries.push({ level: m[1].length, text, id: slugify(text) });
  }

  return entries;
}

interface KnowledgeViewProps {
  tab: Tab;
}

/* ── Supported formats ──────────────────────────────── */
const TEXT_EXTENSIONS = new Set(['md', 'txt', 'json', 'csv', 'yaml', 'yml', 'xml', 'css', 'sql', 'sh', 'bash', 'py', 'js', 'ts', 'tsx', 'jsx', 'rb', 'go', 'rs', 'java', 'kt', 'swift', 'c', 'cpp', 'h', 'hpp']);
const PDF_EXTENSIONS = new Set(['pdf']);
const HTML_EXTENSIONS = new Set(['html', 'htm']);
const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg']);
// Office formats: the browser can't render the binary directly, so the
// backend extracts text (`GET /api/kv/documents/{id}/content`) and we
// render the returned markdown/rows inline.
const OFFICE_EXTENSIONS = new Set(['docx', 'pptx']);

type DocStatus = 'loading' | 'loaded' | 'error';

export default function KnowledgeView({ tab }: KnowledgeViewProps) {
  const t = useLayoutTokens();
  const { t: tr } = useTranslation('chat');

  // Derive everything from tab.data reactively so switching tabs updates the view
  const folderPath = tab.data?.folderPath ?? null;
  // The knowledge base this document is in — its folder name. No project fallback: the tab
  // carries the name, and guessing one would open a different knowledge base's document.
  const knowledge: string = tab.data?.knowledge ?? '';
  const docId: string | undefined = tab.data?.docId;
  const docName: string = tab.data?.docName ?? '';
  // A file opened from the folder tree, named by its path rather than by a catalog id. The tree
  // is the filesystem, so it lists files nothing has indexed — a folder copied in by hand, a
  // report written straight to disk — and those have no id to open. Serving them by path is what
  // makes browsing the filesystem actually work.
  const filePath: string | undefined = tab.data?.filePath;

  // How to reach this file's bytes: by path when the tree named one, otherwise by catalog id.
  const rawFileUrl = knowledge
    ? filePath
      ? `/api/kv/file?knowledge=${encodeURIComponent(knowledge)}&path=${encodeURIComponent(filePath)}`
      : docId
        ? `/api/kv/documents/${docId}/file?knowledge=${encodeURIComponent(knowledge)}`
        : null
    : null;

  // Content state — resets when docId changes
  const [content, setContent] = useState<string | null>(null);
  const [status, setStatus] = useState<DocStatus>('loading');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Reset state when the viewed document changes
  useEffect(() => {
    setContent(null);
    setStatus('loading');
    setErrorMsg(null);
    setActiveId(null);
  }, [docId, filePath]);

  // Fetch document content
  useEffect(() => {
    if (!rawFileUrl) {
      setContent(null);
      setStatus('loading');
      return;
    }

    let cancelled = false;
    setStatus('loading');
    setErrorMsg(null);
    setContent(null);

    const ext = docName.split('.').pop()?.toLowerCase() || '';
    const isOffice = OFFICE_EXTENSIONS.has(ext);
    const isBinary = !TEXT_EXTENSIONS.has(ext) && !PDF_EXTENSIONS.has(ext) && !IMAGE_EXTENSIONS.has(ext) && !isOffice;

    if (isBinary) {
      setStatus('loaded');
      return;
    }
    // PDF / HTML / image / office render natively from the raw file URL —
    // no content fetch needed here (OfficeViewer fetches the binary itself).
    if (PDF_EXTENSIONS.has(ext) || HTML_EXTENSIONS.has(ext) || IMAGE_EXTENSIONS.has(ext) || isOffice) {
      setStatus('loaded');
      return;
    }

    // Text-based formats — fetch content from KV store
    fetch(rawFileUrl)
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
        setErrorMsg(err.message || tr('kb_err_load_document'));
        setStatus('error');
      });

    return () => { cancelled = true; };
  }, [rawFileUrl, docName]);

  // File URL for PDF/images/download
  const fileUrl = rawFileUrl;

  const ext = docName.split('.').pop()?.toLowerCase() || '';
  const isPdf = PDF_EXTENSIONS.has(ext);
  const isHtml = HTML_EXTENSIONS.has(ext);
  const isImage = IMAGE_EXTENSIONS.has(ext);
  const isText = TEXT_EXTENSIONS.has(ext);
  const isOffice = OFFICE_EXTENSIONS.has(ext);
  const isMarkdown = ext === 'md';

  // ── Table of contents (markdown only) ────────────────
  const toc = useMemo(() => (isMarkdown && content ? extractToc(content) : []), [isMarkdown, content]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  /** Scroll a heading into view (used by TOC clicks and in-page anchors). */
  const scrollToHeading = useCallback((id: string) => {
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      setActiveId(id);
    }
  }, []);

  /** Scroll-spy: mark the section currently at the top of the viewer. */
  const updateActive = useCallback(() => {
    const container = scrollRef.current;
    if (!container) return;
    // Near the top: highlight the first section by default.
    if (container.scrollTop < 24 && toc.length > 0) {
      setActiveId(toc[0].id);
      return;
    }
    const containerTop = container.getBoundingClientRect().top + 12;
    let current: string | null = null;
    for (const entry of toc) {
      const el = document.getElementById(entry.id);
      if (!el) continue;
      if (el.getBoundingClientRect().top <= containerTop) current = entry.id;
      else break;
    }
    setActiveId(current);
  }, [toc]);

  // Re-run scroll-spy after content renders (ids exist only then).
  useEffect(() => {
    if (status === 'loaded' && isMarkdown) {
      const raf = requestAnimationFrame(updateActive);
      return () => cancelAnimationFrame(raf);
    }
  }, [status, isMarkdown, updateActive]);

  /**
   * react-markdown components: headings get the SAME slug id as the parsed
   * TOC entry (looked up by rendered text so ids stay stable across
   * re-renders), and in-page `#...` links scroll instead of navigating
   * (the shell uses HashRouter — a hash change would unmount this view).
   */
  const mdComponents = useMemo(() => {
    const idByText = new Map<string, string>();
    for (const entry of toc) {
      if (!idByText.has(entry.text)) idByText.set(entry.text, entry.id);
    }
    const makeHeading = (level: 1 | 2 | 3 | 4 | 5 | 6) => {
      const Tag = `h${level}` as const;
      return ({ children }: { children?: React.ReactNode }) => {
        const text = nodeToText(children);
        // Fall back to slugifying the rendered text for headings the parser
        // didn't see (e.g. setext `===` headings).
        const id = idByText.get(text) ?? slugify(text);
        return <Tag id={id}>{children}</Tag>;
      };
    };
    return {
      h1: makeHeading(1),
      h2: makeHeading(2),
      h3: makeHeading(3),
      h4: makeHeading(4),
      h5: makeHeading(5),
      h6: makeHeading(6),
      a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
        <a
          href={href}
          onClick={(e) => {
            if (href && href.startsWith('#')) {
              e.preventDefault();
              scrollToHeading(href.slice(1));
            }
          }}
        >
          {children}
        </a>
      ),
    };
  }, [toc, scrollToHeading]);

  const cardStyle: React.CSSProperties = {
    background: t.bgContent,
    border: `1px solid ${t.border}`,
    borderRadius: 6,
  };

  const showToc = isMarkdown && !!content && toc.length > 0;

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
          {tr('nav_knowledge')}
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

      {/* ── Document viewer + TOC ─────────────────────── */}
      <div style={{ flex: 1, minHeight: 0, display: 'flex', gap: 10 }}>
        <div
          style={{
            flex: 1,
            minWidth: 0,
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            position: 'relative', // anchor for the absolutely-filled PDF embed
            ...cardStyle,
          }}
        >
        {!rawFileUrl ? (
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
              {tr('kb_view_select_doc')}
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
        ) : isPdf ? (
          /* PDF: render with pdf.js (PdfViewer) so Safari's PDFKit can't
           * garble subsetted fonts — output is identical in every browser. */
          <PdfViewer url={fileUrl!} />
        ) : isOffice ? (
          /* Office: native client-side render of the real binary
           * (docx-preview / pptxviewjs) — no server conversion. */
          <Suspense fallback={
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, color: t.textMuted, fontSize: 13 }}>
              <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
              {tr('kb_loading_office')}
            </div>
          }>
            <OfficeViewer url={fileUrl!} fileName={docName} ext={ext as 'docx' | 'pptx'} />
          </Suspense>
        ) : isHtml ? (
          /* HTML: keep iframe so it renders as a document */
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
          <div
            ref={scrollRef}
            onScroll={updateActive}
            style={{
              flex: 1,
              overflow: 'auto',
              padding: '16px 24px',
              fontSize: 14,
              lineHeight: 1.6,
              color: t.textPrimary,
            }}
          >
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
                .markdown-body h1, .markdown-body h2, .markdown-body h3,
                .markdown-body h4, .markdown-body h5, .markdown-body h6 {
                  scroll-margin-top: 12px;
                }
              `}</style>
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
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
            <p>{tr('kb_preview_unavailable')} <strong>.{ext}</strong></p>
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

        {/* ── TOC panel (right of the viewer) ─────────── */}
        {showToc && (
          <aside
            style={{
              width: 220,
              flexShrink: 0,
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
              ...cardStyle,
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '8px 12px',
                borderBottom: `1px solid ${t.border}`,
                flexShrink: 0,
              }}
            >
              <List size={13} style={{ color: '#a855f7' }} />
              <span style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', color: t.textMuted }}>
                {tr('kb_contents')}
              </span>
              <span style={{ fontSize: 11, color: t.textMuted, marginLeft: 'auto' }}>
                {toc.length}
              </span>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', padding: '6px 4px' }}>
              {toc.map((entry) => {
                const isActive = entry.id === activeId;
                return (
                  <button
                    key={entry.id}
                    title={entry.text}
                    onClick={() => scrollToHeading(entry.id)}
                    style={{
                      display: 'block',
                      width: '100%',
                      textAlign: 'left',
                      border: 'none',
                      background: isActive ? t.bgHover : 'transparent',
                      color: isActive ? '#a855f7' : t.textMuted,
                      fontSize: 12,
                      fontWeight: isActive ? 600 : 400,
                      cursor: 'pointer',
                      borderRadius: 3,
                      padding: '3px 8px',
                      paddingLeft: 8 + (entry.level - 1) * 12,
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      lineHeight: 1.4,
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = t.bgHover; }}
                    onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
                  >
                    {entry.text}
                  </button>
                );
              })}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
