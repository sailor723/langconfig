/**
 * EditorSectionNav — section sidebar + content shell shared by the agent
 * editors. Renders the section-nav buttons (verbatim across both editors)
 * and the scrolling content area; optional heading/hint blocks are passed
 * by the DeepAgentEditor only.
 */
import type { ReactNode } from 'react';
import type { LayoutTokens } from './tokens';

interface EditorSectionDef {
  id: string;
  label: string;
  icon: ReactNode;
}

interface EditorSectionNavProps {
  sections: EditorSectionDef[];
  activeSection: string;
  onSectionChange: (id: string) => void;
  renderSection: (id: string) => ReactNode;
  heading?: ReactNode;
  hint?: ReactNode;
  t: LayoutTokens;
}

export default function EditorSectionNav({
  sections,
  activeSection,
  onSectionChange,
  renderSection,
  heading,
  hint,
  t,
}: EditorSectionNavProps) {
  return (
    <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
      <div style={{
        width: 130,
        minWidth: 130,
        background: t.bgSidebar,
        borderRight: `1px solid ${t.border}`,
        padding: '8px 0',
        overflowY: 'auto',
        flexShrink: 0,
      }}>
        {sections.map(s => {
          const isActive = s.id === activeSection;
          return (
            <button
              key={s.id}
              onClick={() => onSectionChange(s.id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                width: '100%',
                padding: '8px 14px',
                fontSize: 12,
                color: isActive ? t.textPrimary : t.textMuted,
                background: isActive ? t.bgHover : 'transparent',
                border: 'none',
                borderLeft: isActive ? `2px solid ${t.accent}` : '2px solid transparent',
                cursor: 'pointer',
                textAlign: 'left',
              }}
            >
              {s.icon}
              {s.label}
            </button>
          );
        })}
      </div>

      {/* Section content */}
      <div style={{
        flex: 1,
        padding: 16,
        overflowY: 'auto',
        minHeight: 0,
      }}>
        {heading}
        {renderSection(activeSection)}
        {hint}
      </div>
    </div>
  );
}
