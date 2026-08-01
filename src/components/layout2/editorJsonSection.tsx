/**
 * JsonEditorSection — shared editable JSON textarea for agent editors.
 *
 * Verbatim extraction of the renderJson section that was duplicated in
 * AgentEditor and DeepAgentEditor.
 */
import type { LayoutTokens } from './tokens';

interface JsonEditorSectionProps {
  value: string;
  onChange: (v: string) => void;
  t: LayoutTokens;
}

export default function JsonEditorSection({ value, onChange, t }: JsonEditorSectionProps) {
  return (
    <div style={{ padding: 4 }}>
      <textarea
        value={value}
        onChange={e => onChange(e.target.value)}
        spellCheck={false}
        style={{
          width: '100%',
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
        }}
      />
    </div>
  );
}
