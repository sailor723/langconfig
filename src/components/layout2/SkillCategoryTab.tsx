/**
 * SkillCategoryTab — every skill in one category, as cards.
 *
 * The Tools activity has exactly this tab for a tool category (`ToolCategoryTab`), opened from the sidebar's
 * category rows; the Skills activity only had a flat list by `source_type`. This is the same surface for
 * skills, so a category row in the sidebar leads somewhere.
 *
 * Clicking a card opens the skill (builtin → detail view, personal → editor) — the same rule the picker and
 * the home page follow. "Clone" copies it into a new skill, as in the picker.
 */
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Award, ChevronRight } from 'lucide-react';
import { useLayoutTokens } from './tokens';
import { useLayoutState, type Tab } from './useLayout';
import { categoryLabel } from './skillCategories';

interface SkillItem {
  skill_id: string;
  name: string;
  description: string;
  source_type?: string | null;
  tags?: string[] | null;
  category?: string | null;
}

interface Props {
  tab: Tab;
}

export default function SkillCategoryTab({ tab }: Props) {
  const t = useLayoutTokens();
  const { t: tr } = useTranslation('chat');
  const { openTab, closeTab } = useLayoutState();
  const category = String(tab.data?.category ?? '');
  const skills = useMemo(() => (tab.data?.skills ?? []) as SkillItem[], [tab.data]);

  const open = (skill: SkillItem, clone = false) => {
    const builtin = (skill.source_type ?? '') === 'builtin';
    if (!clone) {
      openTab(builtin
        ? { id: `skill-${skill.skill_id}`, label: skill.name || skill.skill_id, viewType: 'skill',
            data: { skillId: skill.skill_id, skill } }
        : { id: `skill-edit-${skill.skill_id}`, label: `Edit: ${skill.name || skill.skill_id}`,
            viewType: 'skill-editor', data: { skill } });
      return;
    }
    openTab({
      id: `skill-clone-${skill.skill_id}-${Date.now()}`,
      label: `Clone: ${skill.name || skill.skill_id}`,
      viewType: 'skill-editor',
      data: { skill: { ...skill, name: '', skill_id: undefined, source_type: 'personal' } },
    });
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, padding: '0 20px', height: 44,
        borderBottom: `1px solid ${t.border}`, background: t.bgContent, flexShrink: 0,
      }}>
        <Award size={15} color={t.accent} />
        <span style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary }}>
          {categoryLabel(category) || category}
        </span>
        <span style={{ fontSize: 11, color: t.textMuted }}>{skills.length} skills</span>
        <button
          onClick={() => { closeTab(tab.id); }}
          title="close"
          style={{ marginLeft: 'auto', background: 'none', border: 'none', color: t.textMuted,
                   cursor: 'pointer', fontSize: 11.5 }}
        >
          {tr('c_close') ?? 'close'}
        </button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        {skills.length === 0 ? (
          <div style={{ fontSize: 12.5, color: t.textMuted }}>nothing in this category</div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 10 }}>
            {skills.map(skill => (
              <div
                key={skill.skill_id}
                onClick={() => open(skill)}
                role="button"
                tabIndex={0}
                style={{
                  padding: 14, borderRadius: 10, cursor: 'pointer',
                  background: t.bgContent, border: `1px solid ${t.border}`,
                  display: 'flex', flexDirection: 'column', gap: 6,
                }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = t.accent; }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Award size={13} color={t.accent} />
                  <span style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, flex: 1,
                                 overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {skill.name || skill.skill_id}
                  </span>
                  <ChevronRight size={12} style={{ color: t.textDim }} />
                </div>
                <div style={{ fontSize: 11.5, color: t.textMuted, lineHeight: 1.5,
                              display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical',
                              overflow: 'hidden' }}>
                  {skill.description}
                </div>
                <span
                  onClick={e => { e.stopPropagation(); open(skill, true); }}
                  title="copy this skill into a new one"
                  style={{ alignSelf: 'flex-start', fontSize: 10.5, color: t.textMuted,
                           border: `1px solid ${t.border}`, padding: '1px 7px', borderRadius: 999,
                           cursor: 'pointer' }}
                >
                  {tr('tp_clone_skill') ?? 'Clone'}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
