/**
 * TwoPagePdfViewer — cross-browser PDF viewer (Safari/Chrome/Firefox)
 *
 * Renders ALL pages stacked vertically inside a scrollable container,
 * just like the MD/text viewer. The user scrolls down to read through
 * the entire document top-to-bottom, regardless of page count or zoom
 * level. Each page is sized to its natural rendered size at the
 * current zoom, so zooming in makes pages taller (more scroll needed)
 * and zooming out makes them shorter (less scroll).
 *
 * Features:
 *   - Continuous scroll through the whole document (MD-like)
 *   - Zoom in/out + reset (each page renders at its natural size at
 *     the chosen zoom, container scrolls)
 *   - Page indicator + Prev/Next (scrolls by one viewport at a time)
 *   - Auto-fit to viewport width at default zoom
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

const ZOOM_STEPS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0];
// Default zoom = "fit to viewport width" (index 2 → 1.0).
const FIT_ZOOM_INDEX = 2;

interface TwoPagePdfViewerProps {
  url: string;
  title: string;
}

export default function TwoPagePdfViewer({ url, title }: TwoPagePdfViewerProps) {
  const [pdf, setPdf] = useState<pdfjsLib.PDFDocumentProxy | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [zoomIndex, setZoomIndex] = useState(FIT_ZOOM_INDEX); // 1.0 = fit to container height
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // Page currently in view (used for the toolbar page indicator).
  // Tracked separately from scroll so the indicator updates as the
  // user scrolls through the document.
  const [visiblePage, setVisiblePage] = useState(1);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  // One slot per page (page 1 → slot 0). Filled as pages render.
  const pageSlotRefs = useRef<(HTMLDivElement | null)[]>([]);
  // Render-task cancellation — only the latest render matters; older
  // ones are cancelled to avoid wasted CPU.
  const renderTaskRefs = useRef<{ cancel: () => void }[]>([]);

  // 1. Load PDF whenever URL changes
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPdf(null);
    setNumPages(0);
    setVisiblePage(1);
    setZoomIndex(FIT_ZOOM_INDEX);
    // Reset slot refs for the new doc
    pageSlotRefs.current = [];
    renderTaskRefs.current = [];

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
      // Cancel any in-flight renders
      renderTaskRefs.current.forEach((t) => t?.cancel());
    };
  }, [url]);

  // 2. Render pages whenever pdf / zoom changes.
  //
  // Approach (continuous scroll, MD-like):
  //   - Each page gets its own slot <div> in the vertical stack.
  //   - The slot is sized to the page's natural width × height at the
  //     current zoom (NOT to a fixed viewport size). At fit zoom, each
  //     page fits the viewport height exactly; at zoom > fit, pages
  //     are taller and the user scrolls.
  //   - All pages render in parallel via pdfjs's getPage/render API.
  //   - We cancel any in-flight render tasks on re-render (zoom/page
  //     change) so the GPU doesn't waste cycles on stale frames.
  useEffect(() => {
    if (!pdf) return;

    // Cancel any in-flight renders from the previous render pass
    renderTaskRefs.current.forEach((t) => t?.cancel());
    renderTaskRefs.current = new Array(numPages).fill(null);

    (async () => {
      try {
        // We size pages relative to the SCROLL container's width (so
        // horizontal scroll never happens at fit zoom — the page
        // width is exactly the available width). Use a conservative
        // width estimate since clientWidth may be 0 if the container
        // hasn't laid out yet; in that case we fall back to 800px and
        // the next render pass picks up the real width.
        const containerWidth = scrollRef.current?.clientWidth ?? 800;
        const dpr = window.devicePixelRatio || 1;

        // Probe page 1 to compute the fit scale. We use page 1's
        // aspect ratio for the "fit" calculation so a wide landscape
        // page doesn't get squished against the height (the user can
        // always zoom out further if they want a full overview).
        const firstPage = await pdf.getPage(1);
        const firstViewport = firstPage.getViewport({ scale: 1 });
        // Fit: scale so the page width matches container width
        const fitScale = containerWidth / firstViewport.width;
        const scale = fitScale * ZOOM_STEPS[zoomIndex];

        // Render each page into its slot
        for (let pageNum = 1; pageNum <= numPages; pageNum++) {
          const slot = pageSlotRefs.current[pageNum - 1];
          if (!slot) continue;

          const page = await pdf.getPage(pageNum);
          const viewport = page.getViewport({ scale });

          // Create / resize the canvas inside the slot
          let canvas = slot.querySelector('canvas') as HTMLCanvasElement | null;
          if (!canvas) {
            canvas = document.createElement('canvas');
            canvas.className = 'shadow bg-white';
            canvas.style.display = 'block';
            slot.appendChild(canvas);
          }
          canvas.width = viewport.width * dpr;
          canvas.height = viewport.height * dpr;
          canvas.style.width = `${viewport.width}px`;
          canvas.style.height = `${viewport.height}px`;

          const ctx = canvas.getContext('2d');
          if (!ctx) continue;
          ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
          ctx.clearRect(0, 0, viewport.width, viewport.height);

          const task = page.render({
            canvas,
            canvasContext: ctx,
            viewport,
            transform: [1, 0, 0, 1, 0, 0],
          });
          renderTaskRefs.current[pageNum - 1] = task;
          try {
            await task.promise;
          } catch (e: any) {
            if (e?.name !== 'RenderingCancelledException') {
              console.error(`[PdfViewer] render page ${pageNum} failed:`, e);
            }
          }
        }
      } catch (e: any) {
        if (e?.name === 'RenderingCancelledException') return;
        console.error('[PdfViewer] render error:', e);
        setError(e?.message || 'Failed to render PDF');
      }
    })();

    return () => {
      renderTaskRefs.current.forEach((t) => t?.cancel());
    };
  }, [pdf, numPages, zoomIndex]);

  // 3. Track which page is most-visible (for the page indicator).
  // We use IntersectionObserver to update `visiblePage` whenever a
  // page crosses the threshold of being in view. The page whose top
  // is closest to the viewport top wins.
  useEffect(() => {
    if (!scrollRef.current || numPages === 0) return;
    const scrollEl = scrollRef.current;

    const observer = new IntersectionObserver(
      (entries) => {
        // Pick the entry with the largest intersection ratio that's
        // currently visible. Stable across rapid scroll events because
        // IntersectionObserver debounces internally.
        let best: { page: number; ratio: number } | null = null;
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const pageNum = parseInt(
            (entry.target as HTMLElement).dataset.pageNum || '0',
            10,
          );
          if (!pageNum) continue;
          if (!best || entry.intersectionRatio > best.ratio) {
            best = { page: pageNum, ratio: entry.intersectionRatio };
          }
        }
        if (best) setVisiblePage(best.page);
      },
      {
        root: scrollEl,
        // Trigger when the page is 30%+ visible — avoids the indicator
        // flickering as the user scrolls between two pages.
        threshold: [0.3, 0.6, 0.9],
      },
    );

    for (const slot of pageSlotRefs.current) {
      if (slot) observer.observe(slot);
    }

    return () => observer.disconnect();
  }, [numPages, pdf]);

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

  const zoomLabel = `${Math.round(ZOOM_STEPS[zoomIndex] * 100)}%`;

  // Scroll to a specific page (used by Prev/Next). Pages are stacked
  // vertically, so we just scroll to the page's top offset within the
  // scroll container.
  const scrollToPage = (pageNum: number) => {
    const slot = pageSlotRefs.current[pageNum - 1];
    if (!slot || !scrollRef.current) return;
    const scrollEl = scrollRef.current;
    const slotTop = slot.offsetTop;
    // Scroll so the page's top aligns with the scroll container's top.
    // Subtract a small offset so the page label isn't cut off.
    scrollEl.scrollTo({ top: slotTop - 8, behavior: 'smooth' });
  };

  // Scroll by one viewport (used by prev/next "page" navigation).
  // We use scrollBy with clientHeight so the user moves roughly one
  // screenful per click — same affordance as turning a page.
  const scrollByViewport = (direction: -1 | 1) => {
    if (!scrollRef.current) return;
    const scrollEl = scrollRef.current;
    scrollEl.scrollBy({ top: direction * scrollEl.clientHeight * 0.9, behavior: 'smooth' });
  };

  const canPrev = visiblePage > 1;
  const canNext = visiblePage < numPages;

  return (
    <div className="w-full h-full flex flex-col">
      {/* Toolbar: page nav · zoom
          Always visible at the top so the user can jump to a specific
          page or change zoom regardless of how far they've scrolled. */}
      <div
        className="flex items-center justify-between gap-2 px-2 py-1 text-[10px] border-b border-gray-200 dark:border-border-dark bg-white dark:bg-panel-dark flex-shrink-0"
        style={{ color: 'var(--color-text-muted)' }}
      >
        {/* Page nav */}
        <div className="flex items-center gap-1">
          <button
            disabled={!canPrev}
            onClick={() => scrollByViewport(-1)}
            className="px-2 py-0.5 rounded bg-gray-100 dark:bg-white/10 hover:opacity-80 disabled:opacity-30 disabled:cursor-not-allowed"
            style={{ color: 'var(--color-text-primary)' }}
            title="Scroll up one screen (Prev)"
          >
            ← Prev
          </button>
          <span style={{ color: 'var(--color-text-primary)' }} className="font-medium">
            {visiblePage}
            {' '}<span style={{ color: 'var(--color-text-muted)' }}>of {numPages}</span>
          </span>
          <button
            disabled={!canNext}
            onClick={() => scrollByViewport(1)}
            className="px-2 py-0.5 rounded bg-gray-100 dark:bg-white/10 hover:opacity-80 disabled:opacity-30 disabled:cursor-not-allowed"
            style={{ color: 'var(--color-text-primary)' }}
            title="Scroll down one screen (Next)"
          >
            Next →
          </button>
        </div>

        {/* Page jump — typing a number and Enter scrolls to that page.
            Provides the same "go to page X" affordance as a traditional
            PDF reader, but uses the same continuous scroll under the hood. */}
        <div className="flex items-center gap-1">
          <span style={{ color: 'var(--color-text-muted)' }} className="hidden sm:inline">Go to:</span>
          <input
            type="number"
            min={1}
            max={numPages}
            defaultValue=""
            placeholder="#"
            onKeyDown={(e) => {
              if (e.key !== 'Enter') return;
              const v = parseInt((e.target as HTMLInputElement).value, 10);
              if (v >= 1 && v <= numPages) {
                scrollToPage(v);
                (e.target as HTMLInputElement).value = '';
              }
            }}
            className="w-10 px-1 py-0.5 text-center border border-gray-200 dark:border-border-dark rounded bg-white dark:bg-panel-dark focus:outline-none focus:ring-1 focus:ring-primary"
            style={{ color: 'var(--color-text-primary)' }}
            title="Type a page number and press Enter"
          />
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
            onClick={() => {
              setZoomIndex(FIT_ZOOM_INDEX);
              // Scroll back to the top so the user starts at page 1
              if (scrollRef.current) scrollRef.current.scrollTo({ top: 0, behavior: 'smooth' });
            }}
            className="px-2 py-0.5 rounded bg-gray-100 dark:bg-white/10 hover:opacity-80"
            style={{ color: 'var(--color-text-primary)' }}
            title="Reset to fit width (scroll to top)"
          >
            ⟳
          </button>
        </div>
      </div>

      {/* Continuous-scroll page stack. All pages are rendered in a
          vertical column. The user scrolls down to read through the
          entire document — same affordance as the MD viewer. */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-auto bg-gray-100 dark:bg-black/20"
        style={{ scrollBehavior: 'auto' }}
      >
        <div className="flex flex-col items-center gap-4 p-3 min-w-min">
          {Array.from({ length: numPages }).map((_, idx) => {
            const pageNum = idx + 1;
            return (
              <div
                key={pageNum}
                ref={(el) => { pageSlotRefs.current[idx] = el; }}
                data-page-num={pageNum}
                className="flex flex-col items-center"
              >
                {/* Page label — small caption above each page so the
                    user can see where one page ends and the next begins
                    (helpful when zooming in and pages are tall). */}
                <div
                  className="text-[10px] mb-1 px-2 py-0.5 rounded-full"
                  style={{
                    color: 'var(--color-text-muted)',
                    backgroundColor: 'rgba(255,255,255,0.7)',
                  }}
                >
                  Page {pageNum}
                </div>
                {/* Canvas is appended imperatively in the render effect
                    (so we can size it precisely to the rendered viewport
                    and re-render without React thrash). */}
              </div>
            );
          })}
        </div>
      </div>
      <span className="sr-only">{title}</span>
    </div>
  );
}
