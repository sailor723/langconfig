/**
 * JsonEditorSection — shared editable JSON textarea for agent editors.
 *
 * Verbatim extraction of the renderJson section that was duplicated in
 * AgentEditor and DeepAgentEditor.
 */
import { useState } from 'react';
import type { LayoutTokens } from './tokens';

interface JsonEditorSectionProps {
  value: string;
  onChange: (v: string) => void;
  t: LayoutTokens;
}

export default function JsonEditorSection({ value, onChange, t }: JsonEditorSectionProps) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard needs a secure context; fall back to selecting the text so the
      // user can copy it with the keyboard.
      const el = document.querySelector<HTMLTextAreaElement>('[data-json-editor]');
      el?.focus();
      el?.select();
    }
  };

  return (
    <div style={{ padding: 4 }} data-copied={copied}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 6 }}>
        <button
          type="button"
          onClick={copy}
          style={{
            padding: '3px 10px', borderRadius: 10, cursor: 'pointer',
            border: `1px solid ${t.border}`, background: 'transparent',
            color: t.textMuted, fontSize: 11,
          }}
        >
          {copied ? '已复制' : '复制 JSON'}
        </button>
      </div>
      <textarea
        data-json-editor
        value={value}
        onChange={e => onChange(e.target.value)}
        spellCheck={false}
        style={{
          width: '100%',
          height: 'calc(100vh - 210px)', // fill the editor panel height
          background: t.bgContent,
          border: `1px solid ${t.border}`,
          borderRadius: 4,
          padding: 12,
          fontFamily: '"SF Mono", "Fira Code", monospace',
          fontSize: 12,
          color: t.textPrimary,
          overflow: 'auto',
          minHeight: 300,
          resize: 'vertical',
          outline: 'none',
          lineHeight: 1.5,
          boxSizing: 'border-box',
        }}
      />
    </div>
  );
}
