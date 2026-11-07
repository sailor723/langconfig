/**
 * RunningLight — the one visible answer to "is it doing anything?".
 *
 * A turn or a build can run for a minute or more, and a spinner that never changes is
 * indistinguishable from a frozen panel: that is exactly how "I approved and nothing happened" felt.
 * So the light says three things at once — that work is in flight (a breathing dot), for how long
 * (a live counter), and what it is doing (the label the caller passes).
 *
 * `tone="idle"` renders a quiet dot, so the same component can sit in a header permanently and the
 * state reads at a glance instead of needing a tooltip.
 */
import { useEffect, useState } from 'react';
import { useLayoutTokens } from '../../components/layout2/tokens';

function useElapsed(since: number | null): string {
  const [, tick] = useState(0);
  useEffect(() => {
    if (since === null) return;
    const id = window.setInterval(() => tick(n => n + 1), 1000);
    return () => window.clearInterval(id);
  }, [since]);
  if (since === null) return '';
  const s = Math.max(0, Math.round((Date.now() - since) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${String(s % 60).padStart(2, '0')}s`;
}

export default function RunningLight({
  running, label = '运行中', startedAt, tone = 'live', compact = false,
}: {
  running: boolean;
  label?: string;
  /** ms epoch; omit to hide the counter */
  startedAt?: number | null;
  tone?: 'live' | 'idle';
  compact?: boolean;
}) {
  const t = useLayoutTokens();
  const elapsed = useElapsed(running ? (startedAt ?? Date.now()) : null);

  if (!running) {
    if (compact) {
      return <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 999, background: t.border }} />;
    }
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 10.5, color: t.textDim }}>
        <span style={{ width: 8, height: 8, borderRadius: 999, background: t.border }} />
        {label === '运行中' ? '空闲' : label}
      </span>
    );
  }

  return (
    <span
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 10.5, fontWeight: 600,
        color: tone === 'live' ? '#fab840' : t.textDim,
      }}
      title={`${label}${elapsed ? ` · 已运行 ${elapsed}` : ''}`}
    >
      <span className="lc-live" />
      {!compact && label}
      {elapsed ? <span style={{ fontWeight: 400, fontVariantNumeric: 'tabular-nums' }}>{elapsed}</span> : null}
    </span>
  );
}

/** A thin bar that sweeps while something long is running — for a job or a streamed turn. */
export function RunningBar({ running }: { running: boolean }) {
  if (!running) return null;
  return <div className="lc-sweep" style={{ width: '100%' }} />;
}
