/**
 * OfficeViewer — paginated inline preview for .docx and .pptx.
 *
 *   .docx → docx-preview renders the full document once (hidden), then each
 *           page is shown one at a time in the center and cloned into the
 *           thumbnail rail on the right.
 *   .pptx → pptxviewjs renders the current slide to a canvas; each slide is
 *           also rendered to a small thumbnail canvas in the right rail.
 *
 * Layout: [ center: one large page/slide + prev/next + zoom ] [ right: page list ]
 *
 * Both run entirely in the browser — no server conversion, no upload.
 * The render targets (docx stage, pptx canvas, thumbnails) are managed
 * imperatively via refs because the libraries own the DOM they produce.
 */
import { useEffect, useRef, useState, useCallback } from 'react';
// MUST be imported before pptxviewjs: captures the native FileReader before
// pptxviewjs overwrites the global (see office-compat.ts).
import { restoreNativeFileReader } from './office-compat';
import { renderAsync } from 'docx-preview';
import PptxViewJS from 'pptxviewjs';
import { useLayoutTokens } from './tokens';
import {
  Loader, AlertCircle, ChevronLeft, ChevronRight, Download,
  ZoomIn, ZoomOut, Maximize,
} from 'lucide-react';

// pptxviewjs replaces window.FileReader at module load with its async shim
// (static-only methods); restore the native one so docx-preview's jszip can
// read blobs. Runs after every import above has been evaluated.
restoreNativeFileReader();

interface OfficeViewerProps {
  url: string;         // raw file URL (/api/kv/documents/{id}/file)
  fileName: string;
  ext: 'docx' | 'pptx';
}

type ViewStatus = 'loading' | 'loaded' | 'error';

const THUMB_WIDTH = 120; // CSS px for thumbnail rail boxes

/* ── docx pagination ─────────────────────────────────────
 * docx-preview only breaks pages at explicit page-break/section markers, so
 * a long flowing document renders as ONE <section class="docx"> whose height
 * is the whole document. We paginate it ourselves with a fill-then-trim
 * approach: append block clones to a fresh page section and measure the REAL
 * laid-out height, rolling the last block back when the page overflows.
 * Blocks taller than a full page are kept whole on their own page.
 */
function paginateDocxSections(sections: HTMLElement[], host: HTMLElement): HTMLElement[] {
  const out: HTMLElement[] = [];
  const PT_TO_PX = 96 / 72;
  for (const section of sections) {
    const pageH = (parseFloat(section.style.minHeight) || 792) * PT_TO_PX;
    const articles = Array.from(section.children).filter(
      (c) => c.tagName === 'ARTICLE' || c.tagName === 'DIV',
    ) as HTMLElement[];
    if (articles.length === 0) { out.push(section); continue; }

    // If the whole section fits in ~1 page, keep it as-is.
    if (section.offsetHeight <= pageH * 1.2) { out.push(section); continue; }

    // Flatten article children into a block stream.
    const blocks: HTMLElement[] = [];
    for (const article of articles) {
      const kids = Array.from(article.children) as HTMLElement[];
      if (kids.length === 0) { blocks.push(article); continue; }
      for (const k of kids) blocks.push(k);
    }
    if (blocks.length === 0) { out.push(section); continue; }

    const baseStyle = section.getAttribute('style') || '';
    const makePage = (): HTMLElement => {
      const p = document.createElement('section');
      p.className = 'docx';
      if (baseStyle) p.setAttribute('style', baseStyle);
      return p;
    };

    // Pages must be attached to the DOM (host) while filling so scrollHeight
    // reflects real layout; detach when finalized.
    let page = makePage();
    host.appendChild(page);

    const finalize = () => {
      host.removeChild(page);
      out.push(page);
    };

    for (const block of blocks) {
      const clone = block.cloneNode(true) as HTMLElement;
      page.appendChild(clone);
      // scrollHeight ≥ minHeight; anything beyond pageH is real content overflow.
      if (page.scrollHeight > pageH + 4) {
        page.removeChild(clone);
        if (page.children.length === 0) {
          // Block taller than a page: keep it alone (clipped, but preserved).
          page.appendChild(clone);
          finalize();
          page = makePage();
          host.appendChild(page);
          continue;
        }
        finalize();
        page = makePage();
        host.appendChild(page);
        page.appendChild(clone);
      }
    }
    if (page.children.length > 0) finalize();
    else host.removeChild(page);
  }
  return out;
}

export default function OfficeViewer({ url, fileName, ext }: OfficeViewerProps) {
  const t = useLayoutTokens();

  // docx: hidden full render + center stage + thumbnail rail
  const docxHiddenRef = useRef<HTMLDivElement>(null);
  const docxStageRef = useRef<HTMLDivElement>(null);
  const docxStageSizeRef = useRef<HTMLDivElement>(null); // sized wrapper for scale math
  const thumbRailRef = useRef<HTMLDivElement>(null);

  // pptx: main canvas + viewer instance
  const pptxCanvasRef = useRef<HTMLCanvasElement>(null);
  const pptxMainWrapRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<InstanceType<typeof PptxViewJS.PPTXViewer> | null>(null);

  const [status, setStatus] = useState<ViewStatus>('loading');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(0);
  const [pageCount, setPageCount] = useState(0);
  const [zoom, setZoom] = useState(1); // multiplier on top of fit-scale

  // docx pages extracted from the hidden render (element per page)
  const docxPagesRef = useRef<HTMLElement[]>([]);
  // pptx slide aspect ratio (from first main-canvas render)
  const pptxAspectRef = useRef(16 / 9);

  /* ── Load & first render ───────────────────────────── */
  useEffect(() => {
    let cancelled = false;
    setStatus('loading');
    setErrorMsg(null);
    setCurrentPage(0);
    setPageCount(0);
    setZoom(1);

    const run = async () => {
      try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);

        if (ext === 'docx') {
          const hidden = docxHiddenRef.current;
          if (!hidden) return;
          const blob = await res.blob();
          if (cancelled) return;
          hidden.innerHTML = '';
          await renderAsync(blob, hidden, hidden, {
            className: 'docx',
            breakPages: true,
            inWrapper: true,
          });
          if (cancelled) return;
          // Each <section class="docx"> is one page, but docx-preview only
          // splits at explicit page breaks — paginate long sections ourselves.
          const rawSections = Array.from(hidden.querySelectorAll('.docx')) as HTMLElement[];
          const pages = paginateDocxSections(rawSections, hidden);
          docxPagesRef.current = pages;
          setPageCount(pages.length);
          setCurrentPage(0);
          setStatus('loaded');
        } else {
          const mainWrap = pptxMainWrapRef.current;
          const canvas = pptxCanvasRef.current;
          if (!canvas) return;
          const buffer = await res.arrayBuffer();
          if (cancelled) return;
          // Seed a 16:9 canvas so the first render has a sane size; the
          // real aspect is read back from the rendered canvas afterwards.
          canvas.style.width = '960px';
          canvas.style.height = '540px';
          const viewer = new PptxViewJS.PPTXViewer({ canvas, slideSizeMode: 'fit' });
          viewerRef.current = viewer;
          await viewer.loadFile(buffer);
          await viewer.render(canvas);
          if (cancelled) { viewer.destroy(); return; }
          const n = viewer.getSlideCount();
          const aspect = (canvas.width && canvas.height) ? canvas.width / canvas.height : 16 / 9;
          pptxAspectRef.current = aspect;
          setPageCount(n);
          setCurrentPage(0);
          setStatus('loaded');
          // Re-fit canvas to the panel at the correct aspect now that we know it.
          fitPptxCanvas();
        }
      } catch (err: any) {
        if (cancelled) return;
        console.error('[OfficeViewer] render failed:', err, err?.stack);
        setErrorMsg(err?.message || 'Failed to render document');
        setStatus('error');
      }
    };

    run();

    return () => {
      cancelled = true;
      if (ext === 'pptx' && viewerRef.current) {
        try { viewerRef.current.destroy(); } catch { /* noop */ }
        viewerRef.current = null;
      }
      // NOTE: do NOT clear docxHiddenRef/docxStageRef/thumbRailRef here — those
      // are React-managed elements. React tears down the JSX subtree itself on
      // unmount/ext change; clearing innerHTML first would leave React's
      // reconciliation trying to remove a child that no longer exists
      // ("node to be removed is not a child of this node").
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, ext]);

  /* ── Fit the pptx main canvas into its panel ────────── */
  const fitPptxCanvas = useCallback(() => {
    const canvas = pptxCanvasRef.current;
    const wrap = pptxMainWrapRef.current;
    if (!canvas || !wrap) return;
    const availW = wrap.clientWidth - 48;
    const availH = wrap.clientHeight - 48;
    const aspect = pptxAspectRef.current;
    let w = availW;
    let h = w / aspect;
    if (h > availH) { h = availH; w = h * aspect; }
    canvas.style.width = `${Math.max(160, Math.floor(w))}px`;
    canvas.style.height = `${Math.max(90, Math.floor(h))}px`;
    if (viewerRef.current) {
      viewerRef.current.render(canvas, { slideIndex: viewerRef.current.getCurrentSlideIndex() }).catch(() => {});
    }
  }, []);

  /* ── pptx: re-fit on panel resize ───────────────────── */
  useEffect(() => {
    if (ext !== 'pptx' || status !== 'loaded') return;
    const wrap = pptxMainWrapRef.current;
    if (!wrap) return;
    const ro = new ResizeObserver(() => fitPptxCanvas());
    ro.observe(wrap);
    return () => ro.disconnect();
  }, [ext, status, fitPptxCanvas]);

  /* ── pptx: render main canvas when page changes ─────── */
  useEffect(() => {
    if (ext !== 'pptx' || status !== 'loaded') return;
    const canvas = pptxCanvasRef.current;
    const viewer = viewerRef.current;
    if (!canvas || !viewer) return;
    viewer.render(canvas, { slideIndex: currentPage }).catch(() => {});
  }, [ext, status, currentPage]);

  /* ── docx: draw center page into the stage ──────────── */
  useEffect(() => {
    if (ext !== 'docx' || status !== 'loaded') return;
    const stage = docxStageRef.current;
    const sizeWrap = docxStageSizeRef.current;
    const pages = docxPagesRef.current;
    if (!stage || !sizeWrap || !pages[currentPage]) return;

    // Fit scale: how much the page (natural px) must shrink to fit the panel.
    const pageEl = pages[currentPage];
    const pageW = pageEl.offsetWidth || 816;
    const pageH = pageEl.offsetHeight || 1056;
    const availW = stage.clientWidth - 48;
    const availH = stage.clientHeight - 48;
    const fit = Math.min(availW / pageW, availH / pageH, 1.6);
    const scale = Math.max(0.05, fit * zoom);

    // Clone the page so the hidden originals stay intact for thumbnails.
    const clone = pageEl.cloneNode(true) as HTMLElement;
    clone.style.transform = `scale(${scale})`;
    clone.style.transformOrigin = 'top left';
    sizeWrap.style.width = `${pageW * scale}px`;
    sizeWrap.style.height = `${pageH * scale}px`;
    // IMPORTANT: clear only sizeWrap. Clearing `stage` would detach sizeWrap
    // from the DOM, orphaning the clone below it.
    sizeWrap.innerHTML = '';
    sizeWrap.appendChild(clone);
  }, [ext, status, currentPage, zoom]);

  /* ── docx: rebuild thumbnail rail ───────────────────── */
  useEffect(() => {
    if (ext !== 'docx' || status !== 'loaded') return;
    const rail = thumbRailRef.current;
    const pages = docxPagesRef.current;
    if (!rail) return;
    rail.innerHTML = '';
    pages.forEach((pageEl, idx) => {
      const pageW = pageEl.offsetWidth || 816;
      const pageH = pageEl.offsetHeight || 1056;
      const s = THUMB_WIDTH / pageW;

      const box = document.createElement('div');
      box.dataset.page = String(idx);
      box.style.cssText = `width:${THUMB_WIDTH}px;height:${Math.max(60, pageH * s)}px;overflow:hidden;position:relative;border-radius:4px;cursor:pointer;border:1px solid ${t.border};flex-shrink:0;`;
      box.title = `Page ${idx + 1}`;
      box.addEventListener('click', () => setCurrentPage(idx));

      const clone = pageEl.cloneNode(true) as HTMLElement;
      clone.style.transform = `scale(${s})`;
      clone.style.transformOrigin = 'top left';
      clone.style.pointerEvents = 'none';
      box.appendChild(clone);

      const num = document.createElement('span');
      num.textContent = String(idx + 1);
      num.style.cssText = `position:absolute;bottom:2px;right:4px;font-size:10px;color:#fff;background:rgba(0,0,0,0.6);border-radius:3px;padding:0 4px;`;
      box.appendChild(num);

      rail.appendChild(box);
    });
    highlightThumb();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ext, status]);

  /* ── pptx: rebuild thumbnail rail (small canvases) ──── */
  useEffect(() => {
    if (ext !== 'pptx' || status !== 'loaded') return;
    const rail = thumbRailRef.current;
    const viewer = viewerRef.current;
    if (!rail || !viewer) return;
    let cancelled = false;
    (async () => {
      const n = viewer.getSlideCount();
      rail.innerHTML = '';
      const aspect = pptxAspectRef.current;
      const h = Math.max(60, THUMB_WIDTH / aspect);
      for (let i = 0; i < n; i++) {
        if (cancelled) return;
        const box = document.createElement('div');
        box.dataset.page = String(i);
        box.style.cssText = `width:${THUMB_WIDTH}px;height:${h}px;overflow:hidden;position:relative;border-radius:4px;cursor:pointer;border:1px solid ${t.border};flex-shrink:0;background:#fff;`;
        box.title = `Slide ${i + 1}`;
        box.addEventListener('click', () => setCurrentPage(i));

        const c = document.createElement('canvas');
        c.style.width = `${THUMB_WIDTH}px`;
        c.style.height = `${h}px`;
        box.appendChild(c);
        rail.appendChild(box);
        try {
          await viewer.renderSlide(i, c, { timeout: 8000 });
        } catch { /* keep blank thumb */ }
        highlightThumb();
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ext, status]);

  /* ── thumb highlight follows currentPage ────────────── */
  const highlightThumb = useCallback(() => {
    const rail = thumbRailRef.current;
    if (!rail) return;
    Array.from(rail.children).forEach((box) => {
      const active = box.getAttribute('data-page') === String(currentPage);
      (box as HTMLElement).style.borderColor = active ? '#a855f7' : t.border;
      (box as HTMLElement).style.boxShadow = active ? '0 0 0 2px rgba(168,85,247,0.4)' : 'none';
    });
  }, [currentPage, t.border]);

  useEffect(() => { highlightThumb(); }, [highlightThumb]);

  const goTo = (idx: number) => {
    const clamped = Math.max(0, Math.min(pageCount - 1, idx));
    setCurrentPage(clamped);
  };

  const cardStyle: React.CSSProperties = {
    background: t.bgContent,
    border: `1px solid ${t.border}`,
    borderRadius: 6,
  };

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', ...cardStyle, overflow: 'hidden', position: 'relative' }}>
      {/* Hidden docx render target — kept offscreen, pages cloned from here */}
      {ext === 'docx' && (
        <div ref={docxHiddenRef} style={{ position: 'absolute', left: -99999, top: 0, width: 900, pointerEvents: 'none', zIndex: -1 }} />
      )}

      {/* ── Center: one page / slide ───────────────────── */}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        {/* Toolbar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px', borderBottom: `1px solid ${t.border}`, flexShrink: 0 }}>
          <button onClick={() => goTo(currentPage - 1)} disabled={currentPage <= 0} title="Previous"
            style={toolBtn(t, currentPage <= 0)}>
            <ChevronLeft size={14} />
          </button>
          <span style={{ fontSize: 12, color: t.textMuted, minWidth: 70, textAlign: 'center' }}>
            {pageCount > 0 ? `${currentPage + 1} / ${pageCount}` : '—'}
          </span>
          <button onClick={() => goTo(currentPage + 1)} disabled={pageCount === 0 || currentPage >= pageCount - 1} title="Next"
            style={toolBtn(t, pageCount === 0 || currentPage >= pageCount - 1)}>
            <ChevronRight size={14} />
          </button>
          <span style={{ width: 1, height: 16, background: t.border, margin: '0 4px' }} />
          <button onClick={() => setZoom((z) => Math.max(0.25, +(z - 0.25).toFixed(2)))} title="Zoom out" style={toolBtn(t, false)}>
            <ZoomOut size={13} />
          </button>
          <span style={{ fontSize: 11, color: t.textMuted, minWidth: 38, textAlign: 'center' }}>{Math.round(zoom * 100)}%</span>
          <button onClick={() => setZoom((z) => Math.min(4, +(z + 0.25).toFixed(2)))} title="Zoom in" style={toolBtn(t, false)}>
            <ZoomIn size={13} />
          </button>
          <button onClick={() => setZoom(1)} title="Reset zoom" style={toolBtn(t, zoom === 1)}>
            <Maximize size={13} />
          </button>
          <span style={{ fontSize: 11, color: t.textMuted, marginLeft: 'auto', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {fileName}
          </span>
        </div>

        {/* Stage */}
        {ext === 'docx' ? (
          <div
            ref={docxStageRef}
            style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', alignItems: 'flex-start', justifyContent: 'center', padding: 24, background: t.bgBase }}
          >
            <div ref={docxStageSizeRef} style={{ flexShrink: 0 }} />
          </div>
        ) : (
          <div
            ref={pptxMainWrapRef}
            style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', alignItems: 'flex-start', justifyContent: 'center', padding: 24, background: t.bgBase }}
          >
            <canvas ref={pptxCanvasRef} style={{ boxShadow: '0 2px 16px rgba(0,0,0,0.35)', borderRadius: 4, flexShrink: 0 }} />
          </div>
        )}
      </div>

      {/* ── Right: page thumbnails ─────────────────────── */}
      {status === 'loaded' && pageCount > 0 && (
        <div style={{ width: THUMB_WIDTH + 24, flexShrink: 0, display: 'flex', flexDirection: 'column', borderLeft: `1px solid ${t.border}` }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 10px', borderBottom: `1px solid ${t.border}`, flexShrink: 0 }}>
            <span style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', color: t.textMuted }}>
              {ext === 'docx' ? 'Pages' : 'Slides'}
            </span>
            <span style={{ fontSize: 11, color: t.textMuted, marginLeft: 'auto' }}>{pageCount}</span>
          </div>
          <div ref={thumbRailRef} style={{ flex: 1, overflowY: 'auto', padding: 10, display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'center' }} />
        </div>
      )}

      {/* Loading overlay */}
      {status === 'loading' && (
        <div style={{ position: 'absolute', inset: 0, zIndex: 5, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 8, background: t.bgContent, color: t.textMuted, fontSize: 13 }}>
          <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
          Rendering {fileName}...
        </div>
      )}

      {/* Error overlay */}
      {status === 'error' && (
        <div style={{ position: 'absolute', inset: 0, zIndex: 5, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24, background: t.bgContent, color: t.textMuted, fontSize: 13, textAlign: 'center' }}>
          <AlertCircle size={24} style={{ color: '#e5484d' }} />
          <p style={{ color: '#e5484d', margin: 0 }}>{errorMsg}</p>
          <a href={url} download={fileName} target="_blank" rel="noreferrer"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 14px', background: '#a855f7', color: '#fff', borderRadius: 6, textDecoration: 'none', fontSize: 12, fontWeight: 500 }}>
            <Download size={12} />
            Download {fileName}
          </a>
        </div>
      )}
    </div>
  );
}

/** Small toolbar button style helper. */
function toolBtn(t: any, disabled: boolean): React.CSSProperties {
  return {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    width: 24, height: 24, border: `1px solid ${t.border}`, borderRadius: 4,
    background: 'transparent', color: t.textPrimary, cursor: disabled ? 'default' : 'pointer',
    opacity: disabled ? 0.4 : 1,
  };
}
