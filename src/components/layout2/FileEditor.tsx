/**
 * FileEditor — a simple text/code editor for workspace tabs.
 *
 * Click a file in the sidebar → opens as a tab with a textarea editor.
 * Changes persist in contentStore so reopen retains content.
 */
import { useState, useCallback, useEffect, useRef } from 'react';
import { useLayoutTokens } from './tokens';
import { useLayoutState, type Tab } from './useLayout';
import { ToolbarButton } from './ui-system';
import { getContent, setContent } from './contentStore';
import { Save, Copy, Check } from 'lucide-react';

interface Props {
  tab: Tab;
}

export default function FileEditor({ tab }: Props) {
  const t = useLayoutTokens();
  const { setTabDirty } = useLayoutState();
  const [content, setContentState] = useState(() => getContent(tab.id) ?? tab.data?.content ?? '');
  const [originalContent] = useState(() => getContent(tab.id) ?? tab.data?.content ?? '');
  const [saved, setSaved] = useState(false);
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

  const handleSave = useCallback(() => {
    // Persist to content store for session persistence
    setContent(tab.id, content);
    // Call API save if the tab data provides a save function
    if (tab.data?.onSave) {
      tab.data.onSave(tab.id, content);
    }
    // Clear dirty flag after save
    setTabDirty(tab.id, false);
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  }, [content, tab.id, tab.data, setTabDirty]);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(content);
  }, [content]);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

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
        </span>

        <ToolbarButton onClick={handleCopy} title="Copy content" t={t}>
          <Copy size={14} /> Copy
        </ToolbarButton>

        <ToolbarButton
          onClick={handleSave}
          title="Save"
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
          placeholder="Start typing..."
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

