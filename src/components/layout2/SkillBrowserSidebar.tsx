/**
 * SkillBrowserSidebar — left-sidebar browser for all available skills.
 *
 * Matches the ToolBrowserSidebar arrangement:
 *   - top toolbar: title + search + refresh (search covers all skills)
 *   - Builtin section: system skills, view only (click opens details)
 *   - My Skills section: editable — "+" in the header, pencil per row
 *     (both open the skill editor tab)
 */
import { useEffect, useState, useCallback } from 'react';
import { useLayoutTokens } from './tokens';
import { useLayoutState, type Tab } from './useLayout';
import apiClient from '../../lib/api-client';
import {
  Folder, Award, ChevronRight, ChevronDown, Loader, RefreshCw,
  Search, Plus, Pencil,
} from 'lucide-react';

/* ── Types ────────────────────────────────────────────── */

interface SkillSummary {
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

/* ── Sidebar component ────────────────────────────────── */

export default function SkillBrowserSidebar() {
  const t = useLayoutTokens();
  const { openTab } = useLayoutState();

  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Category keys are the display labels used by renderCategory (e.g. 'Builtin')
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set(['Builtin']));
  const [searchQuery, setSearchQuery] = useState('');

  const loadSkills = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.listSkills();
      const list: SkillSummary[] = Array.isArray(res.data) ? res.data : [];
      setSkills(list);
    } catch (err: any) {
      const msg = err?.response?.status === 0 || err?.code === 'ERR_NETWORK'
        ? 'Backend not reachable. Is the server running?'
        : err?.message || 'Failed to load skills';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadSkills(); }, [loadSkills]);

  const handleSkillClick = useCallback((skill: SkillSummary) => {
    const tab: Tab = {
      id: `skill-${skill.skill_id}`,
      label: skill.name || skill.skill_id,
      viewType: 'skill',
      data: { skillId: skill.skill_id, skill },
    };
    openTab(tab);
  }, [openTab]);

  /** Open the skill editor for an existing skill */
  const handleEditSkill = useCallback((skill: SkillSummary) => {
    const tab: Tab = {
      id: `skill-edit-${skill.skill_id}`,
      label: `Edit: ${skill.name || skill.skill_id}`,
      viewType: 'skill-editor',
      data: { skill },
    };
    openTab(tab);
  }, [openTab]);

  /** Open the skill editor for a new (blank) skill */
  const handleNewSkill = useCallback(() => {
    const tab: Tab = {
      id: `skill-new-${Date.now()}`,
      label: 'New Skill',
      viewType: 'skill-editor',
      data: { skill: {} },
    };
    openTab(tab);
  }, [openTab]);

  const toggleCategory = (cat: string) => {
    setExpandedCategories(prev => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat); else next.add(cat);
      return next;
    });
  };

  // Search filter — matches name, description and tags of every skill
  const q = searchQuery.trim().toLowerCase();
  const matches = (s: SkillSummary) =>
    !q ||
    (s.name || '').toLowerCase().includes(q) ||
    (s.description || '').toLowerCase().includes(q) ||
    (s.tags || []).some(tag => tag.toLowerCase().includes(q));

  // Split: builtin (view only) vs the rest (editable "My Skills")
  const builtinSkills = skills.filter(s => s.source_type === 'builtin' && matches(s));
  const mySkills = skills.filter(s => s.source_type !== 'builtin' && matches(s));

  const renderSkillRow = (skill: SkillSummary, editable: boolean) => (
    <div
      key={skill.skill_id}
      onClick={() => handleSkillClick(skill)}
      title={skill.description || skill.skill_id}
      style={{
        display: 'flex', alignItems: 'center', gap: 6,
        padding: '5px 12px 5px 28px', cursor: 'pointer',
        fontSize: 12, color: t.textPrimary,
      }}
      onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
      onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
    >
      <Award size={13} style={{ flexShrink: 0, color: t.accent }} />
      <span style={{
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1,
      }}>
        {skill.name || skill.skill_id}
      </span>
      {/* Tag chips */}
      {(skill.tags || []).slice(0, 2).map(tag => (
        <span key={tag} style={{
          fontSize: 9, padding: '1px 4px', borderRadius: 3,
          background: t.bgHover, color: t.textMuted,
          fontFamily: 'monospace', flexShrink: 0,
        }}>
          {tag}
        </span>
      ))}
      {editable && (
        <button
          onClick={e => { e.stopPropagation(); handleEditSkill(skill); }}
          title="Edit skill"
          style={{
            background: 'none', border: 'none', color: t.textMuted,
            cursor: 'pointer', display: 'flex', alignItems: 'center', padding: 2,
            flexShrink: 0,
          }}
          onMouseEnter={e => { e.currentTarget.style.color = t.textPrimary; }}
          onMouseLeave={e => { e.currentTarget.style.color = t.textMuted; }}
        >
          <Pencil size={12} />
        </button>
      )}
    </div>
  );

  const renderCategory = (label: string, items: SkillSummary[], editable: boolean, headerExtra?: React.ReactNode) => {
    if (items.length === 0 && !headerExtra) return null;
    const isOpen = expandedCategories.has(label);
    return (
      <div key={label}>
        {/* Category header */}
        <div
          onClick={() => toggleCategory(label)}
          style={{
            display: 'flex', alignItems: 'center', gap: 4,
            padding: '6px 12px', cursor: 'pointer', userSelect: 'none',
            fontSize: 11, fontWeight: 600, color: t.textMuted,
            textTransform: 'uppercase', letterSpacing: 0.3,
          }}
        >
          {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          <Folder size={12} />
          <span style={{ flex: 1 }}>{label}</span>
          {headerExtra}
        </div>

        {/* Skill rows under this category */}
        {isOpen && (items.length === 0 ? (
          <div style={{ padding: '4px 12px 6px 28px', fontSize: 11, color: t.textMuted, fontStyle: 'italic' }}>
            {q ? '(no matching skills)' : '(none yet)'}
          </div>
        ) : (
          items.map(skill => renderSkillRow(skill, editable))
        ))}
      </div>
    );
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Header toolbar — title + search + refresh, all on one line */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '10px 12px 8px' }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: t.textPrimary, flexShrink: 0 }}>
          Skills
        </span>
        <div style={{ position: 'relative', flex: 1, minWidth: 0 }}>
          <Search size={12} style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', color: t.textMuted }} />
          <input
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search..."
            style={{
              width: '100%',
              padding: '5px 8px 5px 24px',
              borderRadius: 6,
              border: `1px solid ${t.border}`,
              background: t.bgInput,
              color: t.textPrimary,
              fontSize: 11,
              outline: 'none',
              boxSizing: 'border-box',
            }}
          />
        </div>
        <button
          onClick={loadSkills}
          disabled={loading}
          title="Refresh"
          style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            width: 24, height: 24, borderRadius: 4, flexShrink: 0,
            background: 'transparent', color: t.textMuted,
            border: 'none', cursor: 'pointer',
            opacity: loading ? 0.5 : 1,
          }}
          onMouseEnter={e => { if (!loading) e.currentTarget.style.background = t.bgHover; }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
        >
          {loading
            ? <Loader size={13} style={{ animation: 'spin 1s linear infinite' }} />
            : <RefreshCw size={13} />}
        </button>
      </div>

      {/* List area */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }}>
        {loading ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '16px 20px', fontSize: 13, color: t.textMuted }}>
            <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
            Loading skills...
          </div>
        ) : error ? (
          <div style={{ padding: '16px 20px', fontSize: 13, color: '#e5484d' }}>{error}</div>
        ) : skills.length === 0 ? (
          <div style={{ padding: '16px 20px', fontSize: 13, color: t.textMuted, fontStyle: 'italic' }}>
            (no skills found)
          </div>
        ) : (
          <>
            {/* Builtin — system skills, view only */}
            {renderCategory('Builtin', builtinSkills, false)}

            {/* My Skills — editable, "+" creates a new skill */}
            {renderCategory('My Skills', mySkills, true, (
              <button
                onClick={e => { e.stopPropagation(); handleNewSkill(); }}
                title="New Skill"
                style={{
                  background: 'none', border: 'none', color: t.textMuted,
                  cursor: 'pointer', display: 'flex', alignItems: 'center', padding: 2,
                }}
                onMouseEnter={e => { e.currentTarget.style.color = t.textPrimary; }}
                onMouseLeave={e => { e.currentTarget.style.color = t.textMuted; }}
              >
                <Plus size={14} />
              </button>
            ))}
          </>
        )}
      </div>
    </div>
  );
}
