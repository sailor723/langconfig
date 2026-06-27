/**
 * TwoPagePdfViewer — cross-browser PDF viewer (Safari/Chrome/Firefox)
 *
 * Renders N pages (1, 2, or 4) side-by-side using <canvas>, with:
 *   - Zoom in/out + reset
 *   - Page count selector (1 / 2 / 4 pages)
 *   - Prev / Next navigation
 *   - Auto-fit to viewport height by default
 *
 * Built on pdfjs-dist so it works in Safari (whose built-in PDF
 * viewer doesn't honor view=TwoPageView URL params).
 */
import { useEffect, useRef, useState } from 'react';
import * as pdfjsLib from 'pdfjs-dist';
// Vite-friendly worker import — uses ?url to get the asset path.
// pdfjs-dist ships the worker in the build output, so this resolves
// to a hashed asset at runtime.
// @ts-ignore
import workerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

pdfjsLib.GlobalWorkerOptions.workerSrc = workerSrc;

const PAGE_OPTIONS = [1, 2, 4] as const;
type PageCount = typeof PAGE_OPTIONS[number];
const ZOOM_STEPS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0];

interface TwoPagePdfViewerProps {
  url: string;
  title: string;
}

export default function TwoPagePdfViewer({ url, title }: TwoPagePdfViewerProps) {
  const [pdf, setPdf] = useState<pdfjsLib.PDFDocumentProxy | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [currentPage, setCurrentPage] = useState(1); // 1-indexed, the leftmost visible page
  const [pageCount, setPageCount] = useState<PageCount>(2);
  const [zoomIndex, setZoomIndex] = useState(2); // index into ZOOM_STEPS → 1.0
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // NEW: pan offset (in CSS pixels) — when zoomed in, the user can drag
  // the page to see different parts. We store one offset that applies
  // to all visible pages (so panning feels coherent across the spread).
  const [pan, setPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRefs = useRef<(HTMLCanvasElement | null)[]>([]);
  const renderTaskRef = useRef<{ cancel: () => void } | null>(null);
  // Pan drag state (ref to avoid re-render on every pointer move)
  const dragRef = useRef<{
    active: boolean;
    startX: number;
    startY: number;
    origX: number;
    origY: number;
  }>({ active: false, startX: 0, startY: 0, origX: 0, origY: 0 });

  // 1. Load PDF whenever URL changes
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPdf(null);
    setCurrentPage(1);

    (async () => {
      try {
        const doc = await pdfjsLib.getDocument({ url }).promise;
        if (cancelled) return;
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

  // 2. Render pages whenever pdf / currentPage / pageCount / zoom changes
  useEffect(() => {
    if (!pdf) return;
    const container = containerRef.current;
    if (!container) return;

    // Cancel any in-flight render
    renderTaskRef.current?.cancel();

    (async () => {
      try {
        // BUG FIX: previously the canvas was sized to the PAGE width/height,
        // which made centering and zoom-in fail (content could be drawn
        // outside the canvas bounds). Now canvas is sized to the SLOT, and
        // the page is rendered with a transform to center it inside.
        const containerHeight = container.clientHeight - 12;
        const totalWidth = container.clientWidth - 12;
        const slotWidth = totalWidth / pageCount;
        const slotHeight = containerHeight;
        const dpr = window.devicePixelRatio || 1;

        // Compute pages to render
        const pages: number[] = [];
        for (let i = 0; i < pageCount; i++) {
          const p = currentPage + i;
          if (p <= numPages) pages.push(p);
        }

        for (let i = 0; i < pages.length; i++) {
          const pageNum = pages[i];
          const canvas = canvasRefs.current[i];
          if (!canvas) continue;
          const page = await pdf.getPage(pageNum);

          // 1. Size canvas to SLOT (not page) — so we have room to center
          //    and so the user can scroll when zoomed in beyond fit.
          canvas.width = slotWidth * dpr;
          canvas.height = slotHeight * dpr;
          canvas.style.width = `${slotWidth}px`;
          canvas.style.height = `${slotHeight}px`;

          // 2. Compute page scale: fit to slot height × zoom multiplier
          //    (so zoom 200% gives a page 2x the fit size, even if it
          //    overflows the slot — overflow is then scrollable).
          const unscaledViewport = page.getViewport({ scale: 1 });
          const fitScale = slotHeight / unscaledViewport.height;
          const scale = fitScale * ZOOM_STEPS[zoomIndex];
          const viewport = page.getViewport({ scale });

          // 3. Clear and apply DPR transform
          const ctx = canvas.getContext('2d');
          if (!ctx) continue;
          ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
          ctx.clearRect(0, 0, slotWidth, slotHeight);

          // 4. Center the page in the slot, then add the user's pan offset.
          //    (offset can be negative when zoomed in beyond fit — that's
          //    fine, content extends beyond the canvas and the user can
          //    drag the page around.)
          const offsetX = (slotWidth - viewport.width) / 2 + pan.x;
          const offsetY = (slotHeight - viewport.height) / 2 + pan.y;

          const task = page.render({
            canvas,
            canvasContext: ctx,
            viewport,
            transform: [1, 0, 0, 1, offsetX, offsetY],
          });
          renderTaskRef.current = task;
          await task.promise;
        }

        // Clear any unused canvas slots
        for (let i = pages.length; i < pageCount; i++) {
          const canvas = canvasRefs.current[i];
          if (canvas) {
            const ctx = canvas.getContext('2d');
            if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
            canvas.width = 0;
            canvas.height = 0;
          }
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
  }, [pdf, currentPage, pageCount, zoomIndex, numPages, pan]);

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
  const canNext = currentPage + pageCount - 1 < numPages;
  const lastVisible = Math.min(currentPage + pageCount - 1, numPages);
  const zoomLabel = `${Math.round(ZOOM_STEPS[zoomIndex] * 100)}%`;

  // Pan drag handlers — bound to the container so dragging on any
  // canvas slot moves all pages together. Uses pointer events for
  // cross-input compatibility (mouse, touch, pen).
  const onPointerDown = (e: React.PointerEvent) => {
    dragRef.current = {
      active: true,
      startX: e.clientX,
      startY: e.clientY,
      origX: pan.x,
      origY: pan.y,
    };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragRef.current.active) return;
    const dx = e.clientX - dragRef.current.startX;
    const dy = e.clientY - dragRef.current.startY;
    setPan({ x: dragRef.current.origX + dx, y: dragRef.current.origY + dy });
  };
  const onPointerUp = (e: React.PointerEvent) => {
    dragRef.current.active = false;
    try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId); } catch {}
  };
  const onDoubleClick = () => {
    // Double-click to re-center / reset pan
    setPan({ x: 0, y: 0 });
  };

  return (
    <div className="w-full h-full flex flex-col">
      <div
        ref={containerRef}
        className="flex-1 flex items-stretch justify-center gap-2 overflow-auto p-1 bg-gray-100 dark:bg-black/20 select-none"
        style={{ cursor: dragRef.current.active ? 'grabbing' : 'grab', touchAction: 'none' }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={onDoubleClick}
        title="Click and drag to pan. Double-click to reset."
      >
        {Array.from({ length: pageCount }).map((_, i) => (
          <canvas
            key={i}
            ref={(el) => { canvasRefs.current[i] = el; }}
            className="shadow bg-white"
            style={{ pointerEvents: 'none' }}  // let the parent container get the events
          />
        ))}
      </div>

      {/* Toolbar: page nav | page count | zoom */}
      <div
        className="flex items-center justify-between gap-2 px-2 py-1 text-[10px] border-t border-gray-200 dark:border-border-dark bg-white dark:bg-panel-dark flex-shrink-0"
        style={{ color: 'var(--color-text-muted)' }}
      >
        {/* Page nav */}
        <div className="flex items-center gap-1">
          <button
            disabled={!canPrev}
            onClick={() => { setCurrentPage(Math.max(1, currentPage - pageCount)); setPan({ x: 0, y: 0 }); }}
            className="px-2 py-0.5 rounded bg-gray-100 dark:bg-white/10 hover:opacity-80 disabled:opacity-30 disabled:cursor-not-allowed"
            style={{ color: 'var(--color-text-primary)' }}
            title="Previous pages"
          >
            ← Prev
          </button>
          <span style={{ color: 'var(--color-text-primary)' }} className="font-medium">
            {currentPage}{pageCount > 1 && lastVisible > currentPage ? `–${lastVisible}` : ''}
            {' '}<span style={{ color: 'var(--color-text-muted)' }}>of {numPages}</span>
          </span>
          <button
            disabled={!canNext}
            onClick={() => { setCurrentPage(Math.min(numPages, currentPage + pageCount)); setPan({ x: 0, y: 0 }); }}
            className="px-2 py-0.5 rounded bg-gray-100 dark:bg-white/10 hover:opacity-80 disabled:opacity-30 disabled:cursor-not-allowed"
            style={{ color: 'var(--color-text-primary)' }}
            title="Next pages"
          >
            Next →
          </button>
        </div>

        {/* Page count selector */}
        <div className="flex items-center gap-1">
          {PAGE_OPTIONS.map((n) => (
            <button
              key={n}
              onClick={() => {
                setPageCount(n);
                // Snap currentPage to a valid start (1, 3, 5, ...)
                const snapped = Math.floor((currentPage - 1) / n) * n + 1;
                setCurrentPage(Math.max(1, Math.min(snapped, numPages)));
                setPan({ x: 0, y: 0 });
              }}
              className={`px-2 py-0.5 rounded text-[10px] font-medium transition-all ${pageCount === n
                ? 'bg-primary text-white'
                : 'bg-gray-100 dark:bg-white/10 hover:opacity-80'
                }`}
              style={pageCount === n ? {} : { color: 'var(--color-text-primary)' }}
              title={`${n} page${n > 1 ? 's' : ''} per view`}
            >
              {n}P
            </button>
          ))}
        </div>

        {/* Zoom controls */}
        <div className="flex items-center gap-1">
          <button
            disabled={zoomIndex <= 0}
            onClick={() => setZoomIndex(Math.max(0, zoomIndex - 1))}
            className="px-2 py-0.5 rounded bg-gray-100 dark:bg-white/10 hover:opacity-80 disabled:opacity-30 disabled:cursor-not-allowed"
            style={{ color: 'var(--color-text-primary)' }}
            title="Zoom out"
          >
            −
          </button>
          <span style={{ color: 'var(--color-text-primary)' }} className="font-medium w-10 text-center">
            {zoomLabel}
          </span>
          <button
            disabled={zoomIndex >= ZOOM_STEPS.length - 1}
            onClick={() => setZoomIndex(Math.min(ZOOM_STEPS.length - 1, zoomIndex + 1))}
            className="px-2 py-0.5 rounded bg-gray-100 dark:bg-white/10 hover:opacity-80 disabled:opacity-30 disabled:cursor-not-allowed"
            style={{ color: 'var(--color-text-primary)' }}
            title="Zoom in"
          >
            +
          </button>
          <button
            onClick={() => { setZoomIndex(2); setPan({ x: 0, y: 0 }); }}  // reset to 1.0
            className="px-2 py-0.5 rounded bg-gray-100 dark:bg-white/10 hover:opacity-80"
            style={{ color: 'var(--color-text-primary)' }}
            title="Reset zoom and pan"
          >
            ⟳
          </button>
        </div>
      </div>
      <span className="sr-only">{title}</span>
    </div>
  );
}