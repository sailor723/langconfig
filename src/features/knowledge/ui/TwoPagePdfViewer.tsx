/**
 * TwoPagePdfViewer — cross-browser 2-page side-by-side PDF viewer
 *
 * Built on pdfjs-dist so it works in Safari (whose built-in PDF
 * viewer doesn't honor view=TwoPageView URL params) and any other
 * browser that doesn't support the Chrome PDF viewer's URL knobs.
 *
 * Renders 2 pages of the PDF side-by-side using <canvas>, with
 * prev/next controls to navigate the document. Pages are auto-fitted
 * to the available height.
 */
import { useEffect, useRef, useState } from 'react';
import * as pdfjsLib from 'pdfjs-dist';
// Vite-friendly worker import — uses ?url to get the asset path.
// pdfjs-dist ships the worker in the build output, so this resolves
// to a hashed asset at runtime.
// @ts-ignore
import workerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

// Tell pdfjs where to find its worker
pdfjsLib.GlobalWorkerOptions.workerSrc = workerSrc;

interface TwoPagePdfViewerProps {
  url: string;
  /** Title for accessibility */
  title: string;
}

export default function TwoPagePdfViewer({ url, title }: TwoPagePdfViewerProps) {
  const [pdf, setPdf] = useState<pdfjsLib.PDFDocumentProxy | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [currentPage, setCurrentPage] = useState(1); // 1-indexed, the left page
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const leftCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const rightCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const renderTaskRef = useRef<{ cancel: () => void } | null>(null);

  // 1. Load the PDF whenever the URL changes
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPdf(null);
    setCurrentPage(1);

    (async () => {
      try {
        const loadingTask = pdfjsLib.getDocument({ url });
        const doc = await loadingTask.promise;
        if (cancelled) {
          // v6: no public destroy() — leaked docs are GC'd when refs drop.
          return;
        }
        setNumPages(doc.numPages);
        setPdf(doc);
        setLoading(false);
      } catch (e: any) {
        if (cancelled) return;
        setError(e?.message || 'Failed to load PDF');
        setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [url]);

  // 2. Render the current pair of pages whenever pdf/currentPage changes
  useEffect(() => {
    if (!pdf) return;
    const leftCanvas = leftCanvasRef.current;
    const rightCanvas = rightCanvasRef.current;
    const container = containerRef.current;
    if (!leftCanvas || !rightCanvas || !container) return;

    // Cancel any in-flight render before starting a new one
    renderTaskRef.current?.cancel();

    (async () => {
      try {
        // Compute available height
        const containerHeight = container.clientHeight - 8; // small padding
        const pages = [currentPage, currentPage + 1].filter((p) => p <= numPages);

        for (let i = 0; i < pages.length; i++) {
          const pageNum = pages[i];
          const canvas = i === 0 ? leftCanvas : rightCanvas;
          const page = await pdf.getPage(pageNum);

          // Fit-to-height (we want the doc to fill the viewport vertically)
          const unscaledViewport = page.getViewport({ scale: 1 });
          const scale = containerHeight / unscaledViewport.height;
          const viewport = page.getViewport({ scale });

          // Set canvas pixel size for crisp rendering
          const dpr = window.devicePixelRatio || 1;
          canvas.width = viewport.width * dpr;
          canvas.height = viewport.height * dpr;
          canvas.style.width = `${viewport.width}px`;
          canvas.style.height = `${viewport.height}px`;

          const ctx = canvas.getContext('2d');
          if (!ctx) continue;
          ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
          ctx.clearRect(0, 0, canvas.width, canvas.height);

          const task = page.render({ canvas, canvasContext: ctx!, viewport });
          renderTaskRef.current = task;
          await task.promise;
        }

        // Clear the right canvas if there are no more pages
        if (pages.length < 2 && rightCanvas) {
          const ctx = rightCanvas.getContext('2d');
          if (ctx) ctx.clearRect(0, 0, rightCanvas.width, rightCanvas.height);
        }
      } catch (e: any) {
        if (e?.name === 'RenderingCancelledException') return;
        console.error('[TwoPagePdfViewer] render error:', e);
        setError(e?.message || 'Failed to render PDF');
      }
    })();

    return () => {
      renderTaskRef.current?.cancel();
    };
  }, [pdf, currentPage, numPages]);

  if (loading) {
    return (
      <div className="w-full h-full flex items-center justify-center text-xs" style={{ color: 'var(--color-text-muted)' }}>
        Loading PDF…
      </div>
    );
  }
  if (error) {
    return (
      <div className="w-full h-full flex items-center justify-center text-xs px-3 text-center" style={{ color: '#ef4444' }}>
        {error}
      </div>
    );
  }

  const canPrev = currentPage > 1;
  const canNext = currentPage + 1 < numPages;
  // Show page numbers
  const pages = [currentPage, currentPage + 1].filter((p) => p <= numPages);

  return (
    <div className="w-full h-full flex flex-col">
      <div ref={containerRef} className="flex-1 flex items-center justify-center gap-2 overflow-auto p-1 bg-gray-100 dark:bg-black/20">
        <canvas ref={leftCanvasRef} className="shadow bg-white" />
        <canvas ref={rightCanvasRef} className="shadow bg-white" />
      </div>
      <div className="flex items-center justify-between gap-2 px-2 py-1 text-[10px] border-t border-gray-200 dark:border-border-dark bg-white dark:bg-panel-dark flex-shrink-0" style={{ color: 'var(--color-text-muted)' }}>
        <button
          disabled={!canPrev}
          onClick={() => setCurrentPage(Math.max(1, currentPage - 2))}
          className="px-2 py-0.5 rounded bg-gray-100 dark:bg-white/10 hover:opacity-80 disabled:opacity-30 disabled:cursor-not-allowed"
          style={{ color: 'var(--color-text-primary)' }}
        >
          ← Prev
        </button>
        <span>
          Page {pages[0]}{pages.length > 1 ? `–${pages[pages.length - 1]}` : ''} of {numPages}
        </span>
        <button
          disabled={!canNext}
          onClick={() => setCurrentPage(Math.min(numPages, currentPage + 2))}
          className="px-2 py-0.5 rounded bg-gray-100 dark:bg-white/10 hover:opacity-80 disabled:opacity-30 disabled:cursor-not-allowed"
          style={{ color: 'var(--color-text-primary)' }}
        >
          Next →
        </button>
      </div>
      <span className="sr-only">{title}</span>
    </div>
  );
}