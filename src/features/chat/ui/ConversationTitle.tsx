/**
 * ConversationTitle — the open chat's name and pin control.
 *
 * Lives in the chat header rather than on every history row: pinning is a
 * decision you make while reading a conversation, and a star per row turns the
 * list into a management surface. Renaming follows the same rule — the title is
 * only stored once the user types one; until then the row falls back to the
 * first user message, so every conversation is readable without a naming step.
 */
import { useEffect, useRef, useState } from 'react';
import { Archive } from 'lucide-react';

interface ConversationTitleProps {
  /** Stored title, or null when the conversation has never been named. */
  title: string | null;
  /** Shown when there is no stored title (first user message, trimmed). */
  fallback: string;
  isFavorite: boolean;
  onRename: (title: string) => void | Promise<void>;
  onToggleFavorite: () => void | Promise<void>;
}

export default function ConversationTitle({
  title, fallback, isFavorite, onRename, onToggleFavorite,
}: ConversationTitleProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title ?? '');
  const inputRef = useRef<HTMLInputElement>(null);

  // Keep the draft in sync when the active conversation (or its title) changes
  // underneath us — switching chats must never carry the previous name over.
  useEffect(() => {
    setEditing(false);
    setDraft(title ?? '');
  }, [title]);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  const commit = async () => {
    setEditing(false);
    if ((title ?? '') === draft.trim()) return;   // nothing changed
    await onRename(draft);
  };

  const cancel = () => {
    setEditing(false);
    setDraft(title ?? '');
  };

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); void commit(); }
          if (e.key === 'Escape') { e.preventDefault(); cancel(); }
        }}
        maxLength={120}
        placeholder={fallback}
        title="Name this conversation (Enter to save, Esc to cancel, blank to clear)"
        className="text-sm font-semibold px-2 py-1 rounded-lg min-w-0 text-center"
        style={{
          width: '320px',
          maxWidth: '40vw',
          color: 'var(--color-text-primary)',
          backgroundColor: 'var(--color-layer-1, transparent)',
          border: '1px solid var(--color-border)',
          outline: 'none',
        }}
      />
    );
  }

  return (
    <div className="flex items-center gap-1.5 min-w-0">
      <button
        onClick={() => setEditing(true)}
        className="text-sm font-semibold truncate px-1 py-0.5 rounded hover:bg-black/5 transition-colors"
        style={{
          color: title ? 'var(--color-text-primary)' : 'var(--color-text-muted)',
          // Bounded so a long name truncates instead of shoving the metadata
          // (date/time/length) and the header buttons out of the row.
          maxWidth: '280px',
        }}
        title={title ? `${title} — click to rename` : 'Click to name this conversation'}
      >
        {title || fallback}
      </button>
      <button
        onClick={() => void onToggleFavorite()}
        className="p-1 rounded-lg hover:bg-black/5 transition-colors flex-shrink-0"
        title={isFavorite ? 'Remove from favourites' : 'Add to favourites'}
        aria-pressed={isFavorite}
      >
        {/* A storage box rather than a star. The state affordance is carried by
            colour + opacity alone: the icon is stroke-drawn, so filling it the way
            the star was filled would read as a solid blob instead of a box. */}
        <Archive
          className="w-4 h-4"
          style={{ color: isFavorite ? 'var(--color-primary)' : 'var(--color-text-muted)', opacity: isFavorite ? 1 : 0.5 }}
        />
      </button>
    </div>
  );
}
