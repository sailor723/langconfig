/**
 * TruncatedLabel — a label that ellipsizes, with a hover popup of the full text.
 *
 * Why not just `title`: these rows already carried one, but only on the name
 * span itself, so hovering the row around it (icon, padding, size, gap) showed
 * nothing at all — and in the Tauri/WKWebView shell a native `title` tooltip is
 * not dependable. This renders the same text as an app-styled popup, portalled
 * to <body> so the file list's own scroll container cannot clip it.
 *
 * The popup appears only when the text is ACTUALLY clipped (scrollWidth beyond
 * clientWidth at hover time), so a short name stays silent instead of popping a
 * tooltip that repeats what is already on screen.
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

/** Delay before the popup appears — long enough not to flash while the pointer crosses rows. */
const SHOW_DELAY_MS = 250;
/** Gap between the label and the popup above it. */
const GAP = 6;

interface TruncatedLabelProps {
  /** What the row shows (and what gets measured for clipping). */
  text: string;
  /**
   * Second line, muted — the full workspace path for a file row, where the path
   * is what tells two same-named uploads apart.
   */
  sublabel?: string;
  className?: string;
  style?: React.CSSProperties;
}

export default function TruncatedLabel({ text, sublabel, className = '', style }: TruncatedLabelProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);
  const timer = useRef<number | null>(null);
  const [pos, setPos] = useState<{ left: number; bottom: number } | null>(null);

  const clearTimer = () => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  };

  const hide = () => {
    clearTimer();
    setPos(null);
  };

  const show = () => {
    const el = ref.current;
    if (!el) return;
    // Nothing is hidden: a tooltip repeating the visible text is noise.
    if (el.scrollWidth <= el.clientWidth) return;
    const r = el.getBoundingClientRect();
    setPos({ left: r.left, bottom: window.innerHeight - r.top + GAP });
  };

  const handleEnter = () => {
    clearTimer();
    timer.current = window.setTimeout(show, SHOW_DELAY_MS);
  };

  // Hide as soon as anything moves the row out from under the popup.
  useEffect(() => {
    if (!pos) return;
    const onScrollOrResize = () => hide();
    window.addEventListener('scroll', onScrollOrResize, true);
    window.addEventListener('resize', onScrollOrResize);
    return () => {
      window.removeEventListener('scroll', onScrollOrResize, true);
      window.removeEventListener('resize', onScrollOrResize);
    };
  }, [pos]);

  useEffect(() => clearTimer, []);

  // Keep the popup on screen once its width is known (the first paint is
  // measured, then corrected — one extra render, no visible jump because the
  // correction happens before the browser paints).
  useLayoutEffect(() => {
    if (!pos || !popupRef.current) return;
    const w = popupRef.current.getBoundingClientRect().width;
    const maxLeft = window.innerWidth - w - 8;
    const clamped = Math.max(8, Math.min(pos.left, maxLeft));
    if (clamped !== pos.left) setPos({ ...pos, left: clamped });
  }, [pos]);

  return (
    <>
      <span
        ref={ref}
        className={`truncate ${className}`}
        style={style}
        onMouseEnter={handleEnter}
        onMouseLeave={hide}
        onMouseDown={hide}
      >
        {text}
      </span>
      {pos && createPortal(
        <div
          ref={popupRef}
          role="tooltip"
          className="chat-composer-menu fixed border rounded-lg shadow-lg z-[70] pointer-events-none"
          style={{
            left: pos.left,
            bottom: pos.bottom,
            maxWidth: 'min(460px, 80vw)',
            width: 'max-content',
            padding: '6px 8px',
            borderColor: 'var(--color-border-dark, #3c3c3c)',
            fontSize: 11,
            lineHeight: '16px',
            wordBreak: 'break-all',
            color: 'var(--color-text-primary)',
          }}
        >
          {text}
          {sublabel && (
            <div style={{ color: 'var(--color-text-muted)', marginTop: 2 }}>{sublabel}</div>
          )}
        </div>,
        document.body,
      )}
    </>
  );
}
