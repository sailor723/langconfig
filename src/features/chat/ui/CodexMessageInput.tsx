/**
 * CodexMessageInput — Codex-style multi-line composer with action row.
 *
 * Layout (inside the rounded composer card):
 *   ┌──────────────────────────────────────────┐
 *   │    Multi-line textarea                   │
 *   ├──────────────────────────────────────────┤
 *   │   (+) [agent]                 [Send ↑]   │
 *   └──────────────────────────────────────────┘
 *
 * Two rows, not three: the workspace label has no row of its own any more, so
 * the card's height is the textarea plus a single control row. That row names
 * the AGENT, not the workspace, and carries no "Work locally" text — it was a
 * hardcoded string describing nothing.
 */
import { useState, useRef, KeyboardEvent, useEffect } from 'react';
import { Send } from 'lucide-react';
import FileUploadButton from './FileUploadButton';
import ContextMeter from './ContextMeter';
import type { ContextOccupancy, SessionDocument } from '../types/chat';

interface CodexMessageInputProps {
  onSendMessage: (message: string) => void;
  disabled?: boolean;
  isStreaming?: boolean;
  placeholder?: string;
  sessionId?: string | null;
  projectId?: number | null;
  onFileUploaded?: (file: SessionDocument) => void;
  /**
   * Agent label for the composer's control row — which agent this composer
   * sends to. It carried the WORKSPACE (project) name before; the workspace is
   * already named in the empty-state heading and in the sidebar, so the row
   * names the agent instead. That does repeat the name in the chat header: the
   * header identifies the conversation, this row identifies where your next
   * message goes.
   */
  agentName?: string;
  /**
   * Context occupancy for the meter beside send. Absent until the metrics
   * endpoint answers, and on a backend that does not report it yet — the meter
   * then renders nothing rather than an empty ring.
   */
  context?: ContextOccupancy | null;
}

/**
 * Empty-composer floor and the ceiling the box grows to before it scrolls.
 *
 * Module-level on purpose: the resize effect below lists both as dependencies.
 * The effect writes an explicit `height`, which outranks `min-height`, so a
 * change to the floor has to re-run it. Without that, editing this number while
 * the dev server was running left the previous height on screen until the next
 * keystroke (Fast Refresh keeps state, and with it the stale inline height), so
 * the edit looked like it had done nothing — or, when the floor went up, like
 * the box had got taller for no reason.
 *
 * 42px is close to the hard floor: the textarea's own padding (pt-3 + pb-2 =
 * 20px) plus one 14px line at 1.5 line-height (21px) needs 41px, so anything
 * smaller starts clipping the first line. The card is then 42 + 48 = 90px.
 */
const MIN_TEXTAREA_HEIGHT = 42;
const MAX_TEXTAREA_HEIGHT = 240;

/**
 * Widest the composer gets — a proportion of its container, not a fixed cap.
 *
 * A fixed width (700px, and before that 780 / 672 / 640 / 600) reads well at the
 * one window size it was chosen at and ignores every other: widen the window and
 * the box stays put. A proportion grows and shrinks with the window instead.
 *
 * 71.3% is the first proportional value — 62% — raised by the 15% asked for:
 * 62 × 1.15 = 71.3. In a 1400px window that is 779px of the panel's 1092px
 * content box, against 677px at 62%. For reference, assistant messages are
 * capped at max-w-[80%] in MessagesPanel, so the composer sits just inside the
 * widest message column above it.
 *
 * The 560px floor keeps it usable in a narrow window, and `min(100%, …)` keeps
 * it inside the panel when even that floor is too wide (a phone-width window
 * gets 100% of what there is). There is deliberately NO ceiling, since a
 * percentage has none — add one with clamp(), e.g.
 * `min(100%, clamp(560px, 71.3%, 1200px))`, if a very wide screen makes the box
 * uncomfortably long.
 *
 * Exported because the stats line under the composer (MessagesPanel) is a
 * SIBLING of this card and has to line up with it: same containing block, same
 * max width, same centring. The empty-state column, by contrast, deliberately
 * carries no cap of its own — applying the rule at two nested levels would
 * compound (71.3% of 71.3%) and pin that box to its floor.
 */
export const COMPOSER_MAX_WIDTH = 'min(100%, max(560px, 71.3%))';

export default function CodexMessageInput({
  onSendMessage,
  disabled = false,
  isStreaming = false,
  placeholder = 'Do anything',
  sessionId = null,
  projectId = null,
  onFileUploaded = () => {},
  agentName,
  context,
}: CodexMessageInputProps) {
  const [inputValue, setInputValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea. The floor is a middle ground: the original 44px made
  // the composer look like a search field, while a full double (88px) pushed the
  // whole card to 171px once the action row and the workspace footer below it
  // are counted. 45px is that double trimmed by 30% — 64px minus 30% is 44.8, so
  // it lands a pixel above the original.
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    // Measure from `auto` so a shrink is measured rather than remembered.
    ta.style.height = 'auto';
    const needed = ta.scrollHeight;
    // Inside the floor, leave the inline height EMPTY and let the stylesheet's
    // min-height size the box. Writing a height here is what let the number go
    // stale: an inline height beats min-height, so a remembered 88px survived
    // every later change until something re-ran this effect.
    ta.style.height = needed > MIN_TEXTAREA_HEIGHT
      ? `${Math.min(needed, MAX_TEXTAREA_HEIGHT)}px`
      : '';
  }, [inputValue, MIN_TEXTAREA_HEIGHT, MAX_TEXTAREA_HEIGHT]);

  const handleSend = () => {
    const message = inputValue.trim();
    if (!message || disabled || isStreaming) return;
    onSendMessage(message);
    setInputValue('');
    setTimeout(() => textareaRef.current?.focus(), 50);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const canSend = inputValue.trim().length > 0 && !disabled && !isStreaming;

  return (
    <div
      // rounded-[28px] rather than a Tailwind step: the card is 90px tall
      // (42px textarea + one 48px control row), and the old rounded-2xl (16px)
      // read almost square on a box that size. 28px keeps a visibly curved
      // corner without the pill shape a larger radius would give.
      //
      // overflow-hidden is what actually makes the corner round, and it is not
      // cosmetic. `border-radius` only clips the element's OWN background; the
      // textarea is a full-bleed opaque child starting at the card's very corner
      // (both rects begin at the same x/y, card padding is 0), so its rectangle
      // painted over the curve and the corner rendered square. Raising the radius
      // changed nothing for exactly that reason.
      //
      // The textarea cannot simply be made transparent instead: themes.tsx
      // injects `[data-theme="X"] textarea { background-color: … !important }`,
      // which beats this component's inline `backgroundColor: 'transparent'`.
      // Clipping is therefore the fix that does not depend on out-ranking an
      // !important rule, and it holds for any future child of this card.
      // `chat-composer-card` pins this card's fill in index.css. The inline
      // background below cannot do the job on its own: lib/themes.tsx maps any
      // element whose inline style mentions --color-input-background to
      // panelDark !important, i.e. to exactly the colour of the panel behind the
      // card — which left the bottom corners (and the control row) invisible,
      // while the textarea's forced-opaque fill stopped at its own bottom edge
      // and so showed round top corners above square bottom ones.
      className="chat-composer-card mx-auto w-full rounded-[28px] overflow-hidden transition-colors"
      style={{
        backgroundColor: 'var(--color-input-background, #ffffff)',
        maxWidth: COMPOSER_MAX_WIDTH,
        // inline fallback — the corners stay round even if the Tailwind class is
        // purged or the app renders without the stylesheet
        borderRadius: 28,
      }}
    >
      {/* Textarea */}
      <textarea
        ref={textareaRef}
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={disabled || isStreaming}
        rows={1}
        // `block` is load-bearing for the height, not cosmetic: as an
        // inline-block the textarea sat on the text baseline, leaving a 6px
        // descender gap above the control row (45 + 6 + 48 = 99px). Block layout
        // removes the gap and the card is 42 + 48 = 90px.
        // pl-8 keeps the first character of the text over the "+" rather than
        // left of it: both this text and the "+" moved right by 16px (2
        // characters at this 14px font — the row's pl-6 is that same 16px, since
        // the row's own left padding was 8px). The right padding stays 16px.
        className="block w-full resize-none pl-8 pr-4 pt-3 pb-2 text-sm focus:outline-none disabled:opacity-50"
        style={{
          backgroundColor: 'transparent',
          color: 'var(--color-text-primary)',
          minHeight: `${MIN_TEXTAREA_HEIGHT}px`,
          maxHeight: `${MAX_TEXTAREA_HEIGHT}px`,
          lineHeight: '1.5',
        }}
      />

      {/* Action row — the attach button and the workspace label share the left
          side, send sits on the right. The workspace label used to have a row of
          its own below this one (35px of the card's 128px); folding it in here
          removes an entire row, which is the only way the box gets materially
          shorter — the textarea alone bottoms out around 41px before the text
          clips, so squeezing it can never save more than a few pixels. */}
      <div className="flex items-center justify-between gap-2 pl-6 pr-6 py-2">
        {/* The right padding matches the left (24px) so the send circle and the
            "+" sit equally far in from the card's edges. DSH keeps its send
            button at 8px, so this is a deliberate step away from it — it reads
            better now that the card is capped and centred. */}
        {/* py-2 rather than py-1.5 keeps this row 48px now that the attach
            control is a 28px circle (DSH's "+" geometry): the row is sized by
            its tallest child, so a 32px send button plus 16px of padding still
            comes to 48px and the card stays at 90px. */}
        <div className="flex items-center gap-2 min-w-0">
          <FileUploadButton
            sessionId={sessionId}
            projectId={projectId}
            onFileUploaded={onFileUploaded}
            disabled={disabled || isStreaming}
          />
          {agentName && (
            <div
              className="text-[11px] min-w-0 truncate"
              style={{ color: 'var(--color-text-primary)' }}
              title={`Sending to ${agentName}`}
            >
              {agentName}
            </div>
          )}
        </div>

        {/* Trailing controls: the context meter, then send — DSH's order. */}
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <ContextMeter context={context} />

          <button
            onClick={handleSend}
            disabled={!canSend}
            className="w-8 h-8 rounded-full flex items-center justify-center transition-all flex-shrink-0
                       disabled:opacity-40 disabled:cursor-not-allowed
                       hover:opacity-90 active:scale-95"
            style={{
              backgroundColor: 'var(--color-primary)',
              color: 'white',
            }}
            title={isStreaming ? 'Streaming...' : 'Send message'}
          >
            {isStreaming ? (
              <span className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : (
              <Send className="w-3.5 h-3.5" />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
