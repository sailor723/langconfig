/**
 * ContextMeter — how full the conversation's context is, as a ring beside the
 * send button, with a click-open panel of the figures.
 *
 * Ported from DeepSeek Harness' composer meter
 * (ui-conversation/src/client/skeleton/ContextMeter.tsx): a 14px SVG ring
 * (2px stroke, round cap, rotated -90° so it fills from the top) inside a 28px
 * circular hit target — the same control family as this card's "+" button —
 * and a panel on click. Renders nothing at all until there is a figure to show,
 * which is what DSH does when a provider has not reported pressure yet.
 *
 * One deliberate difference from DSH: the denominator. DSH measures against the
 * model route's advertised context window. Here it is the AGENT's
 * `summarization_threshold`, the token size at which that agent is already told
 * to compact its history, so the ring and the behaviour it describes cannot
 * disagree. The panel shows the wider ceiling (max_total_tokens) alongside, and
 * the threshold it is measured against, so the percentage is never ambiguous.
 */
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { ContextOccupancy } from '../types/chat';
import HoverTooltip from './HoverTooltip';

/** Ring geometry, matching DSH: 14px viewBox, 2px stroke. */
const RADIUS = 5.5;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/** Panel width in px — needed to keep it on screen, so not just layout. */
const PANEL_WIDTH = 248;
const PANEL_GAP = 6;

interface ContextMeterProps {
  /** Absent until the metrics endpoint has answered; nothing renders without it. */
  context?: ContextOccupancy | null;
  /** Ring colour: the meter turns warning-coloured as the context fills. */
  accentColor?: string;
}

/** 32_000 -> "32K", 1_048_576 -> "1.0M" — the figures DSH shows in its panel. */
export function formatTokens(tokens: number): string {
  if (!Number.isFinite(tokens)) return '0';
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
  if (tokens >= 1_000) return `${Math.round(tokens / 1_000)}K`;
  return String(tokens);
}

export default function ContextMeter({ context, accentColor = 'var(--color-primary)' }: ContextMeterProps) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ left: number; bottom: number } | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // A session switch can remove the figure while this stays mounted; close the
  // now-empty panel rather than leaving stale numbers on screen (DSH's rule).
  useEffect(() => {
    if (!context && open) setOpen(false);
  }, [context, open]);

  // Outside click / Escape close, one listener while open.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (buttonRef.current?.contains(t) || panelRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const placePanel = () => {
    const r = buttonRef.current?.getBoundingClientRect();
    if (!r) return;
    setPos({
      left: Math.max(8, Math.min(r.right - PANEL_WIDTH, window.innerWidth - PANEL_WIDTH - 8)),
      bottom: window.innerHeight - r.top + PANEL_GAP,
    });
  };

  useEffect(() => {
    if (!open) return;
    const update = () => placePanel();
    window.addEventListener('resize', update);
    window.addEventListener('scroll', update, true);
    return () => {
      window.removeEventListener('resize', update);
      window.removeEventListener('scroll', update, true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!context || !context.summarization_threshold) return null;

  const percent = context.percent;
  const stroke = percent >= 90 ? '#ef4444' : percent >= 70 ? '#f59e0b' : accentColor;
  const reading = `${percent}%`;

  return (
    <span className="relative inline-flex flex-shrink-0">
      {/* Hover label, DSH's `context.aria` sentence ("45% of context used"),
          with the figures the panel spells out. Suppressed while the panel is
          open, exactly as DSH disables its tooltip then. */}
      <HoverTooltip
        label={`${reading} of context used`}
        sublabel={`~${formatTokens(context.used_tokens)} / ${formatTokens(context.summarization_threshold)} · summarizes at ${formatTokens(context.summarization_threshold)}`}
        disabled={open}
      >
      <button
        ref={buttonRef}
        type="button"
        aria-label={`Context ${reading} used — ${formatTokens(context.used_tokens)} of ${formatTokens(context.summarization_threshold)}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => {
          if (open) { setOpen(false); return; }
          placePanel();
          setOpen(true);
        }}
        className="w-7 h-7 rounded-full grid place-items-center transition-colors
                   hover:bg-black/10 dark:hover:bg-white/10"
        style={{ background: 'transparent', border: 'none', cursor: 'pointer' }}
      >
        <svg viewBox="0 0 14 14" width="14" height="14" aria-hidden>
          {/* track */}
          <circle cx="7" cy="7" r={RADIUS} fill="none" strokeWidth="2"
                  stroke="var(--color-border-dark, #3c3c3c)" opacity="0.55" />
          {/* fill: dash length is the percentage of the circumference */}
          <circle cx="7" cy="7" r={RADIUS} fill="none" strokeWidth="2" strokeLinecap="round"
                  stroke={stroke}
                  strokeDasharray={`${CIRCUMFERENCE * percent / 100} ${CIRCUMFERENCE}`}
                  transform="rotate(-90 7 7)"
                  style={{ transition: 'stroke-dasharray 200ms ease' }} />
        </svg>
      </button>
      </HoverTooltip>

      {/* Portalled to <body>: the composer card clips its overflow to keep its
          rounded corners, and this panel opens above the card's top edge. */}
      {open && pos && createPortal(
        <div
          ref={panelRef}
          role="dialog"
          aria-label="Context usage"
          className="chat-composer-menu fixed border rounded-lg shadow-lg z-[60]"
          style={{
            left: pos.left,
            bottom: pos.bottom,
            width: PANEL_WIDTH,
            borderColor: 'var(--color-border-dark, #3c3c3c)',
            padding: 12,
            fontSize: 12,
            lineHeight: '20px',
            color: 'var(--color-text-muted)',
          }}
        >
          <div className="flex items-center gap-1.5">
            <span style={{ color: 'var(--color-text-muted)' }}>of context used</span>
            <span style={{ color: 'var(--color-text-primary)', fontWeight: 500 }}>{reading}</span>
          </div>
          <div className="mt-1" style={{ color: 'var(--color-text-primary)', fontWeight: 500, fontVariantNumeric: 'tabular-nums' }}>
            ~{formatTokens(context.used_tokens)} / {formatTokens(context.summarization_threshold)}
          </div>

          {/* The bar's length is the percentage; the threshold it is measured
              against is the agent's own setting. */}
          <div className="mt-2 rounded-full overflow-hidden" style={{ height: 6, backgroundColor: 'rgba(128,128,128,0.25)' }}>
            <div style={{ width: `${percent}%`, height: '100%', backgroundColor: stroke, transition: 'width 200ms ease' }} />
          </div>

          <dl className="mt-2 space-y-0.5">
            <div className="flex items-center justify-between gap-2">
              <dt>Summarize at</dt>
              <dd style={{ color: 'var(--color-text-primary)' }}>{context.summarization_threshold.toLocaleString()}</dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt>Evict at</dt>
              <dd style={{ color: 'var(--color-text-primary)' }}>{context.eviction_threshold.toLocaleString()}</dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt>Max context</dt>
              <dd style={{ color: 'var(--color-text-primary)' }}>
                {context.max_total_tokens.toLocaleString()} ({context.percent_of_max}%)
              </dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt>Keep verbatim</dt>
              <dd style={{ color: 'var(--color-text-primary)' }}>{context.keep_last_messages} messages</dd>
            </div>
            {!context.enable_summarization && (
              <div className="pt-1" style={{ color: '#f59e0b' }}>
                Summarization is off for this agent — the context will not compact.
              </div>
            )}
          </dl>

          <div className="mt-2 pt-2 border-t" style={{ borderColor: 'var(--color-border-dark, #3c3c3c)', fontSize: 11, color: 'var(--color-text-muted)' }}>
            Estimated over the system prompt and messages, not a provider's count.
          </div>
        </div>,
        document.body
      )}
    </span>
  );
}
