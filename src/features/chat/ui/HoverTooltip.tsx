/**
 * HoverTooltip — a small app-styled popup shown on hover.
 *
 * Ported from DSH's composer behaviour: its context ring carries a `Tooltip`
 * (`label`, side top, 200ms delay) that is suppressed while the click-open panel
 * is up. A native `title` cannot do this job here — it cannot be styled, it
 * cannot be disabled while a panel is open, and in the Tauri/WKWebView shell it
 * is not dependable at all. The popup is therefore a portalled element, which
 * also means the composer card and the side panels cannot clip it: both set
 * `overflow: hidden`.
 *
 * Positioning is measured rather than assumed: the popup is laid out, then
 * clamped horizontally into the viewport and flipped below the trigger when
 * there is not enough room above (the composer sits at the bottom of the
 * window, so "above" is the usual case and "below" the fallback).
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { ReactNode } from 'react';

/** DSH's tooltip delay, in ms. */
const DEFAULT_DELAY_MS = 200;
const GAP = 6;

interface HoverTooltipProps {
  /** Popup content — a string or nodes. */
  label: ReactNode;
  /** Optional muted second line (figures, paths). */
  sublabel?: ReactNode;
  /** Suppress while a click-open panel is showing, as DSH does. */
  disabled?: boolean;
  delayMs?: number;
  /** Passed through to the trigger wrapper. */
  className?: string;
  children: ReactNode;
}

export default function HoverTooltip({
  label,
  sublabel,
  disabled = false,
  delayMs = DEFAULT_DELAY_MS,
  className = '',
  children,
}: HoverTooltipProps) {
  const anchorRef = useRef<HTMLSpanElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);
  const timer = useRef<number | null>(null);
  const [place, setPlace] = useState<{ vertical: 'above' | 'below'; left: number; offset: number } | null>(null);

  const clearTimer = () => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  };

  const hide = () => {
    clearTimer();
    setPlace(null);
  };

  const show = () => {
    const el = anchorRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    // Provisional: assume the tooltip fits above; the layout effect corrects it.
    setPlace({ vertical: 'above', left: r.left + r.width / 2, offset: window.innerHeight - r.top + GAP });
  };

  const handleEnter = () => {
    if (disabled) return;
    clearTimer();
    timer.current = window.setTimeout(show, delayMs);
  };

  // A disabled tooltip must not linger when it becomes disabled mid-hover
  // (clicking the ring opens the panel).
  useEffect(() => {
    if (disabled) hide();
  }, [disabled]);

  useEffect(() => {
    if (!place) return;
    const onMove = () => hide();
    window.addEventListener('scroll', onMove, true);
    window.addEventListener('resize', onMove);
    return () => {
      window.removeEventListener('scroll', onMove, true);
      window.removeEventListener('resize', onMove);
    };
  }, [place]);

  useEffect(() => clearTimer, []);

  // Measure, then centre on the trigger and keep it on screen.
  useLayoutEffect(() => {
    if (!place || !popupRef.current || !anchorRef.current) return;
    const pop = popupRef.current.getBoundingClientRect();
    const r = anchorRef.current.getBoundingClientRect();
    const left = Math.max(8, Math.min(place.left - pop.width / 2, window.innerWidth - pop.width - 8));
    const fitsAbove = r.top >= pop.height + GAP + 8;

    if (fitsAbove !== (place.vertical === 'above') || Math.abs(left - (place.left - pop.width / 2)) > 0.5) {
      setPlace({
        vertical: fitsAbove ? 'above' : 'below',
        left: r.left + r.width / 2,
        offset: fitsAbove ? window.innerHeight - r.top + GAP : r.bottom + GAP,
      });
    }
  }, [place]);

  return (
    <>
      <span
        ref={anchorRef}
        className={`inline-flex ${className}`}
        onMouseEnter={handleEnter}
        onMouseLeave={hide}
        onMouseDown={hide}
      >
        {children}
      </span>
      {place && createPortal(
        <div
          ref={popupRef}
          role="tooltip"
          className="chat-composer-menu fixed border rounded-lg shadow-lg z-[70] pointer-events-none"
          style={{
            left: place.left,
            ...(place.vertical === 'above' ? { bottom: place.offset } : { top: place.offset }),
            transform: 'translateX(-50%)',
            maxWidth: 'min(320px, 80vw)',
            width: 'max-content',
            padding: '6px 8px',
            borderColor: 'var(--color-border-dark, #3c3c3c)',
            fontSize: 11,
            lineHeight: '16px',
            color: 'var(--color-text-primary)',
          }}
        >
          {label}
          {sublabel !== undefined && (
            <div style={{ color: 'var(--color-text-muted)', marginTop: 2 }}>{sublabel}</div>
          )}
        </div>,
        document.body,
      )}
    </>
  );
}
