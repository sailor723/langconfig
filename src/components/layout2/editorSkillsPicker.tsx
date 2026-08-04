/**
 * SkillsPicker — searchable, grid-style skill picker shared by the agent editors.
 *
 * Pure presentation: the toggle handler stays in each editor (AgentEditor
 * only updates React state, DeepAgentEditor also syncs jsonEdit). Search is
 * local to this component — it never touches config.
 */
import { useState } from 'react';
import type { LayoutTokens } from './tokens';
import { Award, Search } from 'lucide-react';

export interface SkillSummary {
  skill_id: string;
  name: string;
  description: string;
  version: string;
  source_type: string;
  tags: string[];
  triggers: string[];
  usage_count: number;
  avg_success_rate: number;
}

interface SkillsPickerProps {
  selectedSkills: string[];
  onToggle: (id: string) => void;
  showAll: boolean;
  onShowAllChange: (v: boolean) => void;
  skillsLoading: boolean;
  availableSkills: SkillSummary[];
  t: LayoutTokens;
}

export default function SkillsPicker({
  selectedSkills,
  onToggle,
  showAll,
  onShowAllChange,
  skillsLoading,
  availableSkills,
  t,
}: SkillsPickerProps) {
  const [searchQuery, setSearchQuery] = useState('');

  const cardStyle: React.CSSProperties = {
    background: t.bgContent,
    border: `1px solid ${t.border}`,
    borderRadius: 4,
    padding: 10,
    marginBottom: 10,
  };
  const labelStyle: React.CSSProperties = {
    fontSize: 11,
    color: t.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    marginBottom: 4,
  };
  const valueStyle: React.CSSProperties = {
    fontSize: 13,
    color: t.textPrimary,
  };

  // Search filter — matches name, skill_id, description and tags
  const q = searchQuery.trim().toLowerCase();
  const matches = (s: SkillSummary) =>
    !q ||
    (s.name || '').toLowerCase().includes(q) ||
    (s.skill_id || '').toLowerCase().includes(q) ||
    (s.description || '').toLowerCase().includes(q) ||
    (s.tags || []).some(tag => tag.toLowerCase().includes(q));

  // All/Selected toggle decides the base set, search further narrows it
  const visible = (showAll
    ? availableSkills
    : availableSkills.filter(s => selectedSkills.includes(s.skill_id))
  ).filter(matches);

  const toggleBtn = (label: string, active: boolean, onClick: () => void) => (
    <button
      onClick={onClick}
      style={{
        padding: '2px 10px',
        fontSize: 11,
        border: `1px solid ${active ? t.accent : t.border}`,
        background: active ? t.accent + '20' : 'transparent',
        color: active ? t.accent : t.textMuted,
        borderRadius: 10,
        cursor: 'pointer',
        fontWeight: active ? 600 : 400,
      }}
    >
      {label}
    </button>
  );

  return (
    <div style={{ padding: 4 }}>
      <div style={cardStyle}>
        {/* Header — count + All/Selected toggle */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <div style={labelStyle}>
            Skills ({selectedSkills.length}/{availableSkills.length} selected)
          </div>
          <div style={{ flex: 1 }} />
          {toggleBtn('All', showAll, () => onShowAllChange(true))}
          {toggleBtn('Selected', !showAll, () => onShowAllChange(false))}
        </div>

        {/* Search box */}
        <div style={{ position: 'relative', marginBottom: 10 }}>
          <Search size={12} style={{
            position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)',
            color: t.textMuted,
          }} />
          <input
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search skills..."
            style={{
              width: '100%',
              padding: '6px 8px 6px 24px',
              borderRadius: 6,
              border: `1px solid ${t.border}`,
              background: t.bgInput,
              color: t.textPrimary,
              fontSize: 12,
              outline: 'none',
              boxSizing: 'border-box',
            }}
          />
        </div>

        {skillsLoading ? (
          <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic' }}>Loading skills...</div>
        ) : visible.length === 0 ? (
          <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic' }}>
            {q ? '(no matching skills)' : '(no skills available — create one in the Skills activity)'}
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
            {visible.map(skill => {
              const id = skill.skill_id;
              const checked = selectedSkills.includes(id);
              return (
                <label
                  key={id}
                  style={{
                    display: 'flex', flexDirection: 'column', gap: 6,
                    padding: 10, borderRadius: 6, cursor: 'pointer',
                    border: `1px solid ${checked ? t.accent : t.border}`,
                    background: checked ? t.accent + '10' : t.bgSidebar,
                    minHeight: 84, boxSizing: 'border-box',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => onToggle(id)}
                      style={{ accentColor: t.accent, flexShrink: 0, marginTop: 2 }}
                    />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{
                        color: t.textPrimary, fontWeight: 600, fontSize: 12,
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      }}>
                        {skill.name || id}
                      </div>
                      <div style={{
                        fontSize: 10, color: t.textMuted, fontFamily: 'monospace',
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      }}>
                        {id}
                      </div>
                    </div>
                  </div>
                  <div style={{
                    fontSize: 11, color: t.textMuted, lineHeight: 1.4,
                    display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                    overflow: 'hidden',
                  }}>
                    {skill.description || '(no description)'}
                  </div>
                  {(skill.tags || []).length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 'auto' }}>
                      {skill.tags.slice(0, 2).map(tag => (
                        <span key={tag} style={{
                          fontSize: 9, padding: '1px 5px', borderRadius: 4,
                          background: t.bgHover, color: t.textMuted, fontFamily: 'monospace',
                        }}>
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                </label>
              );
            })}
          </div>
        )}
      </div>

      {/* Selected summary chips */}
      {selectedSkills.length > 0 && (
        <div style={cardStyle}>
          <div style={{ ...labelStyle, display: 'flex', alignItems: 'center', gap: 4 }}>
            <Award size={11} /> Selected ({selectedSkills.length})
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {selectedSkills.map(id => (
              <span key={id} style={{
                fontSize: 11, padding: '2px 6px', background: t.bgHover,
                border: `1px solid ${t.accent}40`, borderRadius: 3,
                color: t.textPrimary, fontFamily: 'monospace',
              }}>{id}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
