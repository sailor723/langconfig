/**
 * SkillEditorTab — create / edit a skill.
 *
 * Compact editor with the core SKILL.md fields: name, description, tags,
 * triggers, instructions. New skills POST to /api/skills; existing ones
 * PUT to /api/skills/{id}. Editing builtin skills is disabled (system-defined).
 */
import { useState, useCallback, useEffect, useRef } from 'react';
import { useLayoutTokens } from './tokens';
import { Award, Save, Loader, FileText, Tag, Zap } from 'lucide-react';
import type { Tab } from './useLayout';
import apiClient from '../../lib/api-client';

interface SkillEditorTabProps {
  tab: Tab;
}

interface SkillPayload {
  skill_id?: string;
  name: string;
  description?: string;
  tags?: string[];
  triggers?: string[];
  instructions?: string;
  source_type?: string;
}

export default function SkillEditorTab({ tab }: SkillEditorTabProps) {
  const t = useLayoutTokens();
  const skill = (tab.data?.skill ?? tab.data ?? {}) as SkillPayload;
  // Track the persisted skill_id locally so a freshly created skill flips
  // from create-mode to update-mode without needing to mutate tab data.
  const [skillId, setSkillId] = useState<string | undefined>(skill.skill_id);
  const isNew = !skillId;
  const isBuiltin = skill.source_type === 'builtin' && !isNew;

  const [name, setName] = useState(skill.name || '');
  const [description, setDescription] = useState(skill.description || '');
  const [tags, setTags] = useState((skill.tags || []).join(', '));
  const [triggers, setTriggers] = useState((skill.triggers || []).join(', '));
  const [instructions, setInstructions] = useState(skill.instructions || '');
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // True when this tab was opened for a brand-new skill (nothing to fetch).
  const isNewRef = useRef(!skill.skill_id);

  // The sidebar passes only a SkillSummary (no instructions/examples), so
  // fetch the full detail when editing an existing skill. Skipped for new
  // skills and when full detail was already provided.
  useEffect(() => {
    if (isNewRef.current || !skillId || skill.instructions !== undefined) return;
    let cancelled = false;
    apiClient.getSkill(skillId)
      .then(res => {
        if (cancelled || !res?.data) return;
        const d = res.data as SkillPayload;
        setName(d.name || '');
        setDescription(d.description || '');
        setTags((d.tags || []).join(', '));
        setTriggers((d.triggers || []).join(', '));
        setInstructions(d.instructions || '');
      })
      .catch(() => { /* keep sidebar summary values */ });
    return () => { cancelled = true; };
  }, [skillId]);

  const handleSave = useCallback(async () => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setSaveMsg({ ok: false, text: 'Name is required' });
      return;
    }
    if (isBuiltin) {
      setSaveMsg({ ok: false, text: 'Builtin skills cannot be edited' });
      return;
    }

    setSaving(true);
    setSaveMsg(null);
    const payload = {
      name: trimmedName,
      description: description.trim() || undefined,
      tags: tags.split(',').map(s => s.trim()).filter(Boolean),
      triggers: triggers.split(',').map(s => s.trim()).filter(Boolean),
      instructions: instructions.trim(),
    };
    try {
      if (isNew) {
        const res = await apiClient.createSkill(payload);
        const createdId = res?.data?.skill_id ?? res?.data?.id;
        if (createdId) setSkillId(createdId); // flip to update-mode after create
      } else {
        await apiClient.updateSkill(skillId as string, payload);
      }
      setSaveMsg({ ok: true, text: isNew ? 'Skill created' : 'Saved successfully' });
      setTimeout(() => setSaveMsg(null), 3000);
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? err?.message ?? 'unknown error';
      setSaveMsg({ ok: false, text: `Save failed: ${detail}` });
    } finally {
      setSaving(false);
    }
  }, [name, description, tags, triggers, instructions, isNew, isBuiltin, skillId]);

  const labelStyle: React.CSSProperties = {
    fontSize: 11, color: t.textMuted, textTransform: 'uppercase',
    letterSpacing: 0.4, marginBottom: 4,
  };
  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '7px 10px', boxSizing: 'border-box',
    borderRadius: 6, border: `1px solid ${t.border}`,
    background: t.bgInput, color: t.textPrimary, fontSize: 12,
    outline: 'none',
  };
  const textareaStyle: React.CSSProperties = {
    ...inputStyle,
    // Cap height so the parent flex container (flex:1; overflowY:auto) handles
    // scrolling instead of the textarea growing past the viewport and hiding
    // content below. `resize: none` keeps it predictable.
    minHeight: 240,
    maxHeight: '60vh',
    lineHeight: 1.6,
    fontFamily: '"SF Mono", "Fira Code", monospace',
    resize: 'none',
    whiteSpace: 'pre-wrap',
    overflowY: 'auto',
  };

  return (
    <div style={{ height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Header bar */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 24px', height: 44, flexShrink: 0,
        borderBottom: `1px solid ${t.border}`, background: t.bgContent,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Award size={16} style={{ color: t.accent }} />
          <span style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary }}>
            {isNew ? 'New Skill' : `Edit: ${skill.name}`}
          </span>
          {isBuiltin && (
            <span style={{
              fontSize: 10, padding: '2px 8px', borderRadius: 4,
              background: '#f59e0b18', color: '#f59e0b', fontWeight: 600,
            }}>
              Builtin — read only
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {saveMsg && (
            <span style={{ fontSize: 12, color: saveMsg.ok ? '#22c55e' : '#e5484d' }}>{saveMsg.text}</span>
          )}
          <button
            onClick={handleSave}
            disabled={saving || isBuiltin}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '6px 14px', borderRadius: 6,
              background: isBuiltin ? t.bgHover : t.accent,
              color: isBuiltin ? t.textMuted : '#fff',
              fontSize: 12, fontWeight: 600, border: 'none', cursor: isBuiltin ? 'not-allowed' : 'pointer',
            }}
          >
            {saving ? <Loader size={13} style={{ animation: 'spin 1s linear infinite' }} /> : <Save size={13} />}
            Save
          </button>
        </div>
      </div>

      {/* Editor body — uses the same scroll pattern as PromptDetailTab */}
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '24px 24px 32px', maxWidth: 760, width: '100%', boxSizing: 'border-box', margin: '0 auto' }}>
        <div style={{ marginBottom: 14 }}>
          <div style={labelStyle}>Name *</div>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. api-rate-limiter" style={inputStyle} />
        </div>

        <div style={{ marginBottom: 14 }}>
          <div style={labelStyle}>Description</div>
          <textarea
            value={description}
            onChange={e => setDescription(e.target.value)}
            placeholder="Brief description — the agent matches skills by this."
            style={{ ...textareaStyle, minHeight: 56, maxHeight: 120 }}
          />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
          <div>
            <div style={{ ...labelStyle, display: 'flex', alignItems: 'center', gap: 4 }}>
              <Tag size={11} /> Tags
            </div>
            <input
              value={tags}
              onChange={e => setTags(e.target.value)}
              placeholder="research, python, api (comma separated)"
              style={inputStyle}
            />
          </div>
          <div>
            <div style={{ ...labelStyle, display: 'flex', alignItems: 'center', gap: 4 }}>
              <Zap size={11} /> Triggers
            </div>
            <input
              value={triggers}
              onChange={e => setTriggers(e.target.value)}
              placeholder="retry failed API calls (comma separated)"
              style={inputStyle}
            />
          </div>
        </div>

        <div>
          <div style={{ ...labelStyle, display: 'flex', alignItems: 'center', gap: 4 }}>
            <FileText size={11} /> Instructions
          </div>
          <textarea
            value={instructions}
            onChange={e => setInstructions(e.target.value)}
            placeholder={'Detailed step-by-step instructions for the agent...'}
            style={textareaStyle}
          />
        </div>
      </div>
    </div>
  );
}
