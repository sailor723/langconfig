/**
 * Shared chat timestamp formatting.
 *
 * One compact form for anything shown inline — history rows and the open
 * conversation's header — so the same conversation reads identically in both
 * places. The long, unambiguous form stays available for tooltips.
 */

/** Compact, locale-aware: "12 Oct 20:35" (year only when it isn't this year). */
export function formatCompactDateTime(iso?: string | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const day = date.getDate();
  const month = date.toLocaleString(undefined, { month: 'short' });
  const time = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  const year = date.getFullYear() === new Date().getFullYear() ? '' : ` ${date.getFullYear()}`;
  return `${day} ${month}${year} ${time}`;
}

/** Full timestamp for tooltips, so the compact form never hides anything. */
export function formatFullDateTime(iso?: string | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString();
}

/** Relative age for scanning ("now", "5m", "3h", "4d"). */
export function formatRelativeTime(iso?: string | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const diffMinutes = Math.floor((Date.now() - date.getTime()) / (1000 * 60));
  if (diffMinutes < 1) return 'now';
  if (diffMinutes < 60) return `${diffMinutes}m`;
  if (diffMinutes < 1440) return `${Math.floor(diffMinutes / 60)}h`;
  const diffDays = Math.floor(diffMinutes / 1440);
  if (diffDays < 7) return `${diffDays}d`;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/** Conversation length in messages, singular-aware. */
export function formatMessageCount(count?: number | null): string {
  const n = count || 0;
  return `${n} ${n === 1 ? 'msg' : 'msgs'}`;
}
