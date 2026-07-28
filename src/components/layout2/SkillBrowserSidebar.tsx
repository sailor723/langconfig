/**
 * SkillBrowserSidebar — left-sidebar browser for all available skills.
 *
 * Lists skills grouped by source type (builtin, personal) from the
 * /api/skills endpoint. Clicking a skill opens it in the workspace
 * as a tab with the 'skill' view type showing full skill details.
 */
import { useEffect, useState, useCallback } from 'react';
import { useLayoutTokens } from './tokens';
import { useLayoutState, type Tab } from './useLayout';
import apiClient from '../../lib/api-client';
import {
  Folder, Award, ChevronRight, ChevronDown, Loader, RefreshCw, FileText,
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
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set(['builtin']));

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

  const toggleCategory = (cat: string) => {
    setExpandedCategories(prev => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat); else next.add(cat);
      return next;
    });
  };

  // Group skills by source_type
  const grouped = skills.reduce<Record<string, SkillSummary[]>>((acc, s) => {
    const key = s.source_type || 'other';
    if (!acc[key]) acc[key] = [];
    acc[key].push(s);
    return acc;
  }, {});
  const categoryOrder = ['builtin', 'personal', 'project', 'other'];

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Toolbar */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '6px 12px', borderBottom: `1px solid ${t.border}`,
      }}>
        <span style={{ fontSize: 11, color: t.textMuted }}>
          {skills.length} skill{skills.length !== 1 ? 's' : ''}
        </span>
        <button
          onClick={loadSkills}
          title="Refresh"
          style={{
            display: 'flex', alignItems: 'center', gap: 4, height: 22,
            padding: '0 6px', background: 'transparent', border: 'none',
            color: t.textMuted, fontSize: 11, cursor: 'pointer',
            borderRadius: 3,
          }}
          onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
        >
          <RefreshCw size={12} />
          Refresh
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
          categoryOrder.map(cat => {
            const items = grouped[cat];
            if (!items || items.length === 0) return null;
            const isOpen = expandedCategories.has(cat);
            return (
              <div key={cat}>
                {/* Category header */}
                <div
                  onClick={() => toggleCategory(cat)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 4,
                    padding: '6px 12px', cursor: 'pointer', userSelect: 'none',
                    fontSize: 11, fontWeight: 600, color: t.textMuted,
                    textTransform: 'uppercase', letterSpacing: 0.3,
                  }}
                >
                  {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  <Folder size={12} />
                  <span>{cat}</span>
                  <span style={{ marginLeft: 4, fontWeight: 400, color: t.textMuted }}>
                    ({items.length})
                  </span>
                </div>

                {/* Skills under this category */}
                {isOpen && items.map(skill => (
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
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
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
                  </div>
                ))}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
