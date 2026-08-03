/**
 * PdfViewer — cross-browser PDF renderer built on pdf.js.
 *
 * Renders every page to a <canvas> instead of relying on the browser's
 * native PDF viewer, so output is identical in all browsers. Safari's
 * PDFKit mis-renders some subsetted fonts (garbled text) that Chrome's
 * PDFium draws correctly — pdf.js sidesteps the browser viewer entirely.
 *
 * The pdf.js worker is lazy-loaded as a static Vite asset (no bundling bloat
 * for non-PDF documents, and the main bundle stays small via code splitting).
 */
import { useEffect, useRef, useState } from 'react';
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist';
import { AlertCircle, Loader } from 'lucide-react';
import { useLayoutTokens } from './tokens';

interface PdfViewerProps {
  url: string; // KV file endpoint (same-origin)
}

/** Lazily import pdf.js and configure its worker exactly once. */
async function getPdfJs() {
  const pdfjs = await import('pdfjs-dist');
  if (!pdfjs.GlobalWorkerOptions.workerSrc) {
    const workerUrl = (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default;
    pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
  }
  return pdfjs;
}

/** Renders a single page into a canvas sized to the container width. */
function PdfPage({
  doc,
  pageNumber,
  width,
}: {
  doc: PDFDocumentProxy;
  pageNumber: number;
  width: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const t = useLayoutTokens();

  useEffect(() => {
    let cancelled = false;
    let renderTask: RenderTask | null = null;

    (async () => {
      try {
        const page = await doc.getPage(pageNumber);
        if (cancelled) return;
        // Scale for both the container width and the device's pixel density
        // so text stays crisp on retina displays.
        const dpr = window.devicePixelRatio || 1;
        const scale = (width * dpr) / page.getViewport({ scale: 1 }).width;
        const viewport = page.getViewport({ scale });
        const canvas = canvasRef.current;
        if (!canvas) return;
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        canvas.style.width = `${width}px`;
        renderTask = page.render({ canvas, viewport });
        await renderTask.promise;
      } catch (e) {
        // Renders cancelled on unmount/width-change are expected — ignore.
      }
    })();

    return () => {
      cancelled = true;
      renderTask?.cancel();
    };
  }, [doc, pageNumber, width]);

  return (
    <canvas
      ref={canvasRef}
      style={{
        display: 'block',
        width: '100%',
        background: '#fff',
        border: `1px solid ${t.border}`,
        borderRadius: 4,
      }}
    />
  );
}

export default function PdfViewer({ url }: PdfViewerProps) {
  const t = useLayoutTokens();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [width, setWidth] = useState(0);

  // Load the document (fully via fetch; a 206/range-aware backend is not
  // needed for canvas rendering).
  useEffect(() => {
    let cancelled = false;
    let loaded: PDFDocumentProxy | null = null;
    setDoc(null);
    setNumPages(0);
    setError(null);

    (async () => {
      try {
        const pdfjs = await getPdfJs();
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        loaded = await pdfjs.getDocument({ data: await res.arrayBuffer() }).promise;
        if (cancelled) return;
        setDoc(loaded);
        setNumPages(loaded.numPages);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();

    return () => {
      cancelled = true;
      // Release the worker/document if we unmounted mid-load.
      if (loaded) loaded.loadingTask.destroy();
    };
  }, [url]);

  // Track container width so pages render crisply and re-flow on resize.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const pages = Array.from({ length: numPages }, (_, i) => i + 1);

  return (
    <div style={{ position: 'absolute', inset: 0 }}>
      {/* Scroll area — always mounted so the ResizeObserver attaches at
       * mount time (loading/error states overlay on top). */}
      <div
        ref={scrollRef}
        style={{
          height: '100%',
          overflow: 'auto',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 12,
          padding: 16,
        }}
      >
        {doc &&
          width > 0 &&
          pages.map((n) => (
            <div key={n} style={{ width: '100%', maxWidth: 900 }}>
              <PdfPage doc={doc} pageNumber={n} width={Math.min(width - 32, 900)} />
            </div>
          ))}
      </div>

      {/* Overlay for loading / error states */}
      {error ? (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12, color: t.textMuted, fontSize: 13, textAlign: 'center' }}>
          <AlertCircle size={24} style={{ color: '#e5484d' }} />
          <p style={{ color: '#e5484d' }}>Failed to render PDF: {error}</p>
          <a href={url} target="_blank" rel="noreferrer" style={{ color: '#a855f7', textDecoration: 'underline', fontSize: 12 }}>
            Open {url.split('/').pop()?.split('?')[0] ?? 'file'} in new tab &rarr;
          </a>
        </div>
      ) : !doc ? (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, color: t.textMuted, fontSize: 13 }}>
          <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
          Rendering PDF...
        </div>
      ) : null}
    </div>
  );
}
