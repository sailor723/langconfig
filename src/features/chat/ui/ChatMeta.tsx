/**
 * ChatMeta — the open conversation's key facts, shown to the right of its title.
 *
 * Start date + time and length in messages: enough to tell two similarly named
 * conversations apart at a glance, which is the reason the history rows carry
 * the same pair. Last activity and the exact figures live in the tooltip so the
 * header stays a single quiet line.
 */
import { formatCompactDateTime, formatFullDateTime, formatMessageCount } from '../utils/formatChatTime';

interface ChatMetaProps {
  /** When the conversation started (ISO). */
  createdAt?: string | null;
  /** Last activity (ISO); tooltip only. */
  updatedAt?: string | null;
  messageCount: number;
  /** Rendered in the active row/header colour scheme. */
  inverted?: boolean;
}

export default function ChatMeta({ createdAt, updatedAt, messageCount, inverted = false }: ChatMetaProps) {
  const started = formatCompactDateTime(createdAt);
  const lastActive = formatFullDateTime(updatedAt);
  const count = messageCount || 0;

  if (!started && !count) return null;

  const tooltip = [
    started ? `started ${formatFullDateTime(createdAt)}` : null,
    lastActive && lastActive !== formatFullDateTime(createdAt) ? `last activity ${lastActive}` : null,
    `${count} ${count === 1 ? 'message' : 'messages'}`,
  ].filter(Boolean).join(' · ');

  return (
    <span
      className="flex items-center gap-1.5 text-[11px] flex-shrink-0 whitespace-nowrap"
      style={{ color: inverted ? 'rgba(255,255,255,0.65)' : 'var(--color-text-muted)' }}
      title={tooltip}
    >
      {started && <span>{started}</span>}
      {started && count > 0 && <span>·</span>}
      {count > 0 && <span>{formatMessageCount(count)}</span>}
    </span>
  );
}
