/**
 * TemplatePicker — a generic "pick a template or start from scratch" tab
 * shown in direct mode for the four catalog activities that have meaningful
 * template collections (DeepAgents, Agents, Skills, Prompt).
 *
 * Each activity feeds the picker with its own source of templates via the
 * `viewType` discriminator on the tab's `data` field. The picker fetches
 * the templates, renders a search-filtered card grid, and emits "use this"
 * events back to the activity via `openTab()` so the chosen template's
 * editor opens pre-filled.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Search, FileText } from 'lucide-react';
import type { Tab } from './useLayout';
import { useLayoutState } from './useLayout';
import { useLayoutTokens } from './tokens';
import apiClient from '../../lib/api-client';

// ---- Template shape (unified across activities) ----------------------------

interface Template {
  /** Unique id — string for registry-built templates, number for DB rows. */
  id: string | number;
  name: string;
  description: string;
  category?: string;
  tags?: string[];
  /** Free-form extras (system_prompt, model, temperature, native_tools). */
  config?: Record<string, any>;
}

type PickerActivity = 'deepagents' | 'agents' | 'skills' | 'prompt';

export default function TemplatePicker({ tab }: { tab: Tab }) {
  // The activity discriminator is carried in tab.data by directModeTabFor().
  // Fall back to 'deepagents' so a misconfigured tab still renders something
  // instead of a blank screen.
  const activity: PickerActivity = (tab.data?.activity as PickerActivity) ?? 'deepagents';
  const t = useLayoutTokens();
  const { t: tr } = useTranslation('chat');
  const { openTab, closeTab } = useLayoutState();
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  // ── Load templates for the activity ───────────────────────────────
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const list = await loadTemplatesFor(activity);
        if (!cancelled) setTemplates(list);
      } catch (err: any) {
        if (!cancelled) setError(err?.message ?? tr('tp_load_failed'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [activity]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return templates;
    return templates.filter((tmpl) =>
      tmpl.name.toLowerCase().includes(q) ||
      tmpl.description.toLowerCase().includes(q) ||
      (tmpl.category ?? '').toLowerCase().includes(q) ||
      (tmpl.tags ?? []).some((tag) => tag.toLowerCase().includes(q))
    );
  }, [templates, search]);

  // ── Handlers ────────────────────────────────────────────────────────
  //
  // For skills the picker is a LIST OF SKILLS, not a list of templates: the cards are the same skills
  // the left sidebar lists. Clicking one therefore has to open THAT skill — a builtin opens its detail
  // view, a personal one opens its editor — which is what the sidebar does. It used to run every click
  // through the clone path (`skill_id: undefined`), so selecting a skill opened a blank "new skill"
  // editor and the real definition was nowhere to be seen. Cloning is still available, as its own
  // action on the card.
  const openSkillCard = (tmpl: Template) => {
    const skill = (tmpl.config ?? {}) as { skill_id?: string; source_type?: string; name?: string };
    if (!skill.skill_id) {
      setError('this card has no skill id — refusing to open an editor for nothing');
      return;
    }
    closeTab(tab.id);
    openTab(skill.source_type === 'builtin'
      ? { id: `skill-${skill.skill_id}`, label: skill.name || skill.skill_id, viewType: 'skill',
          data: { skillId: skill.skill_id, skill } }
      : { id: `skill-edit-${skill.skill_id}`, label: `Edit: ${skill.name || skill.skill_id}`,
          viewType: 'skill-editor', data: { skill } });
  };

  const handlePick = (tmpl: Template) => {
    if (activity === 'skills') { openSkillCard(tmpl); return; }
    closeTab(tab.id);
    const next = openEditorTabFor(activity, tmpl, /* fromBlank */ false);
    if (next) openTab(next);
  };

  /** Clone a skill into a new one (the picker's old behaviour, kept as an explicit action). */
  const handleClone = (tmpl: Template) => {
    closeTab(tab.id);
    const next = openEditorTabFor(activity, tmpl, /* fromBlank */ false);
    if (next) openTab(next);
  };
  const handleBlank = () => {
    closeTab(tab.id);
    const next = openEditorTabFor(activity, null, /* fromBlank */ true);
    if (next) openTab(next);
  };

  const headerTitle = activityHeader(activity, tr);
  const headerSubtitle = activitySubtitle(activity);

  return (
    <div style={{
      height: '100%', display: 'flex', flexDirection: 'column',
      overflow: 'hidden', background: t.bgContent,
    }}>
      {/* ── Top action bar ──────────────────────────────────── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 16px', borderBottom: `1px solid ${t.border}`,
        background: t.bgSidebar, flexShrink: 0,
      }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary }}>
            {headerTitle}
          </div>
          <div style={{ fontSize: 11, color: t.textMuted, marginTop: 2 }}>
            {headerSubtitle}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {/* Search input */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '4px 10px', border: `1px solid ${t.border}`,
            borderRadius: 6, background: t.bgContent,
          }}>
            <Search size={12} color={t.textMuted} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={tr('tp_search_ph')}
              style={{
                border: 'none', outline: 'none', background: 'transparent',
                color: t.textPrimary, fontSize: 12, width: 200,
              }}
              autoFocus
            />
          </div>
          <button
            onClick={handleBlank}
            style={{
              height: 28, padding: '0 12px', fontSize: 12, fontWeight: 600,
              background: t.accent, color: '#fff', border: 'none',
              borderRadius: 4, cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 4,
            }}
            title={tr('tp_blank_hint')}
          >
            <Plus size={12} /> Blank
          </button>
        </div>
      </div>

      {/* ── Body ──────────────────────────────────────────────── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        {error && (
          <div style={{
            marginBottom: 12, padding: 12, borderRadius: 6,
            background: '#e5484d18', border: '1px solid #e5484d',
            color: '#e5484d', fontSize: 12,
          }}>{error}</div>
        )}
        {loading ? (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8,
            color: t.textMuted, fontSize: 12, padding: 24, justifyContent: 'center',
          }}>
            Loading templates...
          </div>
        ) : error ? (
          <div style={{ padding: 16, fontSize: 12, color: '#e5484d' }}>{error}</div>
        ) : filtered.length === 0 ? (
          <div style={{
            padding: 32, textAlign: 'center', borderRadius: 10,
            border: `1px dashed ${t.border}`, background: t.bgSidebar,
          }}>
            <FileText size={28} style={{ color: t.textMuted, opacity: 0.4, marginBottom: 8 }} />
            <div style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary }}>
              {templates.length === 0 ? tr('tp_none') : tr('tp_no_match')}
            </div>
            <div style={{ fontSize: 11, color: t.textMuted, marginTop: 6 }}>
              {templates.length === 0
                ? tr('tp_scratch_hint')
                : tr('tp_try_other')}
            </div>
            <button
              onClick={handleBlank}
              style={{
                marginTop: 14, padding: '8px 16px', fontSize: 12, fontWeight: 600,
                background: t.accent, color: '#fff', border: 'none',
                borderRadius: 6, cursor: 'pointer',
                display: 'inline-flex', alignItems: 'center', gap: 6,
              }}
            >
              <Plus size={12} /> Start from scratch
            </button>
          </div>
        ) : (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
            gap: 12,
          }}>
            {filtered.map((tmpl) => (
              <TemplateCard
                key={String(tmpl.id)}
                template={tmpl}
                onPick={() => handlePick(tmpl)}
                {...(activity === 'skills'
                  ? { onSecondary: () => handleClone(tmpl), secondaryLabel: tr('tp_clone_skill') }
                  : {})}
                t={t}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// Card
// ────────────────────────────────────────────────────────────────────────────

function TemplateCard({ template, onPick, onSecondary, secondaryLabel, t }: {
  template: Template;
  onPick: () => void;
  onSecondary?: () => void;
  secondaryLabel?: string;
  t: ReturnType<typeof useLayoutTokens>;
}) {
  return (
    <div
      onClick={onPick}
      role="button"
      tabIndex={0}
      style={{
        padding: 14, borderRadius: 10,
        background: t.bgContent, border: `1px solid ${t.border}`,
        textAlign: 'left', cursor: 'pointer',
        display: 'flex', flexDirection: 'column', gap: 6,
        transition: 'border-color 0.15s, box-shadow 0.15s',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = t.accent;
        e.currentTarget.style.boxShadow = '0 2px 10px rgba(0,0,0,0.08)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = t.border;
        e.currentTarget.style.boxShadow = 'none';
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary }}>
        {template.name}
      </div>
      <div style={{
        fontSize: 11, color: t.textMuted, lineHeight: 1.5,
        display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical',
        overflow: 'hidden', minHeight: 48,
      }}>
        {template.description}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4, flexWrap: 'wrap' }}>
        {template.category && (
          <span style={{
            fontSize: 10, padding: '1px 6px', borderRadius: 999,
            background: `${t.accent}15`, color: t.accent, fontWeight: 600,
            textTransform: 'uppercase', letterSpacing: 0.3,
          }}>{template.category}</span>
        )}
        {(template.tags ?? []).slice(0, 2).map((tag) => (
          <span key={tag} style={{
            fontSize: 10, color: t.textMuted,
            border: `1px solid ${t.border}`, padding: '1px 6px',
            borderRadius: 4,
          }}>{tag}</span>
        ))}
      </div>
      {onSecondary && secondaryLabel && (
        <span
          // Stop the card's own click: "clone" is a different intent from "open".
          onClick={(e) => { e.stopPropagation(); onSecondary(); }}
          style={{
            alignSelf: 'flex-start', marginTop: 2, fontSize: 10.5,
            color: t.textMuted, border: `1px solid ${t.border}`,
            padding: '1px 7px', borderRadius: 999, cursor: 'pointer',
          }}
          title="copy this skill into a new one"
        >{secondaryLabel}</span>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// Per-activity data + tab wiring
// ────────────────────────────────────────────────────────────────────────────

async function loadTemplatesFor(activity: PickerActivity): Promise<Template[]> {
  switch (activity) {
    case 'deepagents': {
      // Built-in registry templates (Deep Code Researcher / Architect /
      // Debugger / Document Writer / Test Engineer) + user-created agents
      // (which double as starting points the user can clone + customize).
      const [builtinRes, userRes] = await Promise.all([
        apiClient.listDeepAgentTemplates(),
        apiClient.listDeepAgents({ public_only: false }).catch(() => null),
      ]);
      const builtin = (builtinRes as any)?.data ?? builtinRes ?? [];
      const userList = (userRes as any)?.data ?? userRes ?? [];
      const builtinMapped: Template[] = builtin.map((t: any) => ({
        id: t.template_id ?? t.id,
        name: t.name,
        description: t.description || '',
        category: t.category ?? 'system',
        tags: t.capabilities || t.tags || [],
        config: {
          system_prompt: t.system_prompt,
          model: t.model,
          temperature: t.temperature,
          native_tools: t.native_tools || [],
        },
      }));
      const userMapped: Template[] = (Array.isArray(userList) ? userList : []).map((a: any) => ({
        id: a.id,
        name: a.name,
        description: a.description || '',
        category: a.category || 'custom',
        tags: ['user-built'],
        config: a.config,
      }));
      return [...builtinMapped, ...userMapped];
    }
    case 'agents': {
      // AgentHomePage shows built-in system templates + user-created regular
      // agents (use_deepagents=false). We mirror that here so the picker
      // matches the HomePage's "System Templates" + "Custom Builds" lists.
      const [tplRes, dbRes] = await Promise.all([
        apiClient.apiFetch(`${apiClient.baseURL}/api/agents/templates`).catch(() => null),
        apiClient.listDeepAgents({ public_only: false }).catch(() => null),
      ]);
      const tplData = (tplRes as any)?.data ?? tplRes ?? [];
      const tpl = Array.isArray(tplData) ? tplData : (tplData.templates ?? []);
      const builtin: Template[] = tpl.map((t: any) => ({
        id: `tpl-${t.id}`,
        name: t.name,
        description: t.description || '',
        category: 'system',
        tags: t.tags || [],
        config: {
          system_prompt: t.system_prompt,
          model: t.model,
          temperature: t.temperature,
          native_tools: t.native_tools || [],
        },
      }));
      const userList = (dbRes as any)?.data ?? dbRes ?? [];
      const userAgents: Template[] = (Array.isArray(userList) ? userList : [])
        .filter((a: any) => a.config?.use_deepagents === false)
        .map((a: any) => ({
          id: a.id,
          name: a.name,
          description: a.description || '',
          category: a.category || 'custom',
          tags: ['user-built'],
          config: a.config,
        }));
      return [...builtin, ...userAgents];
    }
    case 'skills': {
      const res = await apiClient.listSkills();
      const list: any[] = (res as any)?.data ?? res ?? [];
      return list.map((s: any) => ({
        id: s.skill_id,
        name: s.name || s.skill_id,
        description: s.description || '',
        category: s.source_type || 'builtin',
        tags: s.tags || [],
        config: s,
      }));
    }
    case 'prompt': {
      // Agent templates double as prompt templates (same registry used by
      // PromptHomePage's "Prompt Assembly" view).
      const res = await apiClient.apiFetch(`${apiClient.baseURL}/api/agents/templates`);
      const tplData = (res as any)?.data?.templates ?? (res as any)?.data ?? res ?? [];
      return (Array.isArray(tplData) ? tplData : []).map((t: any) => ({
        id: t.id,
        name: t.name,
        description: t.description || '',
        category: 'template',
        tags: t.tags || [],
        config: {
          system_prompt: t.system_prompt,
          model: t.model,
        },
      }));
    }
  }
}

// A plain function cannot use a hook, so the translator is passed in.
function activityHeader(activity: PickerActivity, tr: (k: string) => string): string {
  switch (activity) {
    case 'deepagents': return tr('tp_qa_deepagents');
    case 'agents':     return tr('tp_qa_agents');
    case 'skills':     return tr('tp_qa_skills');
    case 'prompt':     return tr('tp_qa_prompt');
  }
}
function activitySubtitle(activity: PickerActivity): string {
  switch (activity) {
    case 'deepagents': return 'Pick a starting template — the editor opens pre-filled. Or start from scratch.';
    case 'agents':     return 'Pick an agent template or one of your own agents to clone. Or start from scratch.';
    case 'skills':     return 'Click a skill to open it; Clone copies it into a new one. Or start from scratch.';
    case 'prompt':     return 'Pick an agent template as a starting point for the prompt. Or start from scratch.';
  }
}

/**
 * Build the editor tab to open after the picker resolves.
 *
 * - From a template: pass the template's config through to the editor so
 *   the form opens pre-filled (system prompt, model, native_tools, etc.).
 * - From "Blank": open the editor in fresh-mode (`new: true`, etc.).
 */
function openEditorTabFor(
  activity: PickerActivity,
  template: Template | null,
  fromBlank: boolean,
): Tab | null {
  if (fromBlank) {
    switch (activity) {
      case 'deepagents':
        return { id: `deepagent-new-${Date.now()}`, label: 'New DeepAgent', viewType: 'deepagent', data: { new: true } };
      case 'agents':
        return { id: `agent-new-${Date.now()}`, label: 'New Agent', viewType: 'agent', data: { new: true } };
      case 'skills':
        return { id: `skill-new-${Date.now()}`, label: 'New Skill', viewType: 'skill-editor', data: { skill: {} } };
      case 'prompt':
        return { id: `prompt-new-${Date.now()}`, label: 'New Prompt', viewType: 'prompt-detail', data: { newPrompt: true } };
    }
  }
  // From a template — pre-fill.
  if (!template) return null;
  const cfg = template.config ?? {};
  switch (activity) {
    case 'deepagents': {
      // Always open the CREATOR pre-filled — clicking a template should
      // produce a NEW agent. We avoid opening the editor on an existing
      // user-built agent because that would let the user accidentally
      // edit the source-of-truth for the picker itself.
      return {
        id: `deepagent-from-${template.id}-${Date.now()}`,
        label: `From: ${template.name}`,
        viewType: 'deepagent',
        data: {
          name: '',
          description: template.description ?? '',
          category: template.category ?? 'custom',
          tags: template.tags ?? [],
          config: {
            system_prompt: cfg.system_prompt ?? 'You are a helpful AI assistant. Be concise and accurate.',
            model: cfg.model,
            temperature: cfg.temperature ?? 0.7,
            native_tools: cfg.native_tools ?? [],
          },
        },
      };
    }
    case 'agents': {
      return {
        id: `agent-from-${template.id}-${Date.now()}`,
        label: `From: ${template.name}`,
        viewType: 'agent',
        data: {
          // Empty name so the user must type one — they are creating a
          // NEW agent, not editing the template's source-of-truth.
          name: '',
          description: template.description ?? '',
          category: template.category ?? 'custom',
          tags: template.tags ?? [],
          new: true,
          config: {
            system_prompt: cfg.system_prompt ?? 'You are a helpful AI assistant. Be concise and accurate.',
            model: cfg.model,
            temperature: cfg.temperature ?? 0.7,
            native_tools: cfg.native_tools ?? [],
          },
        },
      };
    }
    case 'skills': {
      return {
        id: `skill-clone-${template.id}-${Date.now()}`,
        label: `Clone: ${template.name}`,
        viewType: 'skill-editor',
        data: { skill: { ...(template.config ?? {}), name: '', skill_id: undefined, source_type: 'personal' } },
      };
    }
    case 'prompt': {
      return {
        id: `prompt-tpl-${template.id}`,
        label: template.name,
        viewType: 'prompt-detail',
        data: {
          templateId: template.id,
          template: template.config,
          name: template.name,
          description: template.description,
        },
      };
    }
  }
}