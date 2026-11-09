/**
 * FileEditor — a simple text/code editor for workspace tabs.
 *
 * Click a file in the sidebar → opens as a tab with a textarea editor.
 * Changes persist in contentStore so reopen retains content.
 *
 * A tab may ask to open **at a line**: `tab.data.highlightLine` (1-based). The sidebar's search sets it
 * from a match, and until this existed nothing consumed it — clicking a search result opened the file at
 * the top, which is the half of "search" that makes the other half useless.
 */
import { useState, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useLayoutTokens } from './tokens';
import { useLayoutState, type Tab } from './useLayout';
import { ToolbarButton } from './ui-system';
import { getContent, setContent } from './contentStore';
import { Save, Copy, Check } from 'lucide-react';

interface Props {
  tab: Tab;
}

/**
 * Character range of `line` (1-based) in `content`, clamped to what exists.
 *
 * Pure so its arithmetic can be read and argued with: the editor is a textarea, and a textarea can be
 * given a selection but not a line number, so the line has to be turned back into offsets.
 */
export function lineSelection(content: string, line: number): { start: number; end: number } | null {
  if (!Number.isFinite(line) || line < 1) return null;
  const lines = content.split('\n');
  if (line > lines.length) return null;
  let start = 0;
  for (let i = 0; i < line - 1; i += 1) start += lines[i].length + 1;
  return { start, end: start + lines[line - 1].length };
}

export default function FileEditor({ tab }: Props) {
  const t = useLayoutTokens();
  const { t: tr } = useTranslation('chat');
  const { setTabDirty } = useLayoutState();
  const [content, setContentState] = useState(() => getContent(tab.id) ?? tab.data?.content ?? '');
  const [originalContent] = useState(() => getContent(tab.id) ?? tab.data?.content ?? '');
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const isDirty = content !== originalContent;

  // Sync dirty state to the tab bar indicator so the dirty dot shows in Workspace
  useEffect(() => {
    setTabDirty(tab.id, isDirty);
  }, [tab.id, isDirty, setTabDirty]);

  // Persist content to store on every change
  const handleChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    setContentState(val);
    setContent(tab.id, val);
  }, [tab.id]);

  const handleSave = useCallback(async () => {
    // Persist to content store for session persistence
    setContent(tab.id, content);
    setSaveError(null);
    // Call API save if the tab data provides a save function
    try {
      if (tab.data?.onSave) {
        await tab.data.onSave(tab.id, content);
      }
      // Clear dirty flag after save
      setTabDirty(tab.id, false);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (err: any) {
      setSaveError(err?.message ?? tr('fe_save_failed'));
    }
  }, [content, tab.id, tab.data, setTabDirty]);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(content);
  }, [content]);

  // Position the caret on the line the tab asked for, and scroll it into view. Selecting the whole line
  // (not just placing the caret) is what makes the browser scroll to it in a textarea, and it puts the
  // match under the pointer instead of one screen away.
  const wantedLine = typeof tab.data?.highlightLine === 'number' ? tab.data.highlightLine : null;
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    if (wantedLine === null) { el.focus(); return; }
    const range = lineSelection(content, wantedLine);
    if (!range) { el.focus(); return; }
    el.focus();
    el.setSelectionRange(range.start, range.end);
    // Approximate scroll: the textarea's line height is fixed in the style below (1.6 × 14px).
    const lineHeight = 14 * 1.6;
    el.scrollTop = Math.max(0, (wantedLine - 1) * lineHeight - el.clientHeight / 2);
  }, [tab.id, wantedLine, content]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, color: t.textPrimary }}>
      {/* ── Toolbar ────────────────────────────────────── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 4,
        padding: '6px 12px',
        borderBottom: `1px solid ${t.border}`,
        background: t.bgBase,
        minHeight: 36,
      }}>
        <span style={{ fontSize: 13, fontWeight: 600, marginRight: 'auto' }}>
          {tab.label}
          {isDirty && <span style={{ color: t.accent, marginLeft: 6 }}>●</span>}
          {wantedLine !== null && (
            <span
              title="opened from a search match"
              style={{
                marginLeft: 8, fontSize: 10.5, padding: '1px 6px', borderRadius: 9,
                border: `1px solid ${t.border}`, color: t.textMuted, fontWeight: 400,
              }}
            >
              line {wantedLine}
            </span>
          )}
        </span>

        <ToolbarButton onClick={handleCopy} title={tr('fe_copy_content')} t={t}>
          <Copy size={14} /> Copy
        </ToolbarButton>

        {saveError && (
          <span style={{ fontSize: 12, color: '#e5484d', marginRight: 4 }}>{saveError}</span>
        )}

        <ToolbarButton
          onClick={handleSave}
          title={tr('c_save')}
          t={t}
          style={{
            color: saved ? '#22c55e' : (isDirty ? t.accent : t.textMuted),
          }}
        >
          {saved ? <Check size={14} /> : <Save size={14} />}
          {saved ? ' Saved' : ' Save'}
        </ToolbarButton>
      </div>

      {/* ── Editor ─────────────────────────────────────── */}
      <div style={{ flex: 1, minHeight: 0, display: 'flex', background: t.bgContent }}>
        <textarea
          ref={textareaRef}
          value={content}
          onChange={handleChange}
          placeholder={tr('fe_type_ph')}
          spellCheck={false}
          style={{
            flex: 1,
            minHeight: 0,
            padding: '16px 20px',
            background: 'transparent',
            border: 'none',
            color: t.textPrimary,
            fontSize: 14,
            fontFamily: '"SF Mono", "Fira Code", "Cascadia Code", monospace',
            lineHeight: 1.6,
            resize: 'none',
            outline: 'none',
            tabSize: 2,
          }}
        />
      </div>
    </div>
  );
}

