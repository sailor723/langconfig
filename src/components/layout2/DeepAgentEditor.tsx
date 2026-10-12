/**
 * DeepAgentEditor — structured editor for a DeepAgent template.
 *
 * Sections (left-to-right tab nav):
 *   - Overview     name, description, category, model, version, stats
 *   - Prompt       system_prompt (large textarea)
 *   - Tools        native_tools / cli_tools / custom_tools
 *   - Subagents    list of subagent cards
 *   - Middleware   list with enabled toggles
 *   - Guardrails   token limits, eviction
 *   - JSON         raw config
 */
import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { useLayoutTokens } from './tokens';
import { ChevronDown, ChevronRight } from 'lucide-react';
import type { Tab } from './useLayout';
import { useLayoutState } from './useLayout';
import { chatStore } from './chatStore';
import { useAvailableModels } from '../../hooks/useAvailableModels';
import { useAvailableTools } from '../../hooks/useAvailableTools';
import apiClient from '../../lib/api-client';
import CodeViewerModal from './CodeViewerModal';
import { SectionId as _SectionId, SECTIONS } from './editorConstants';
import ChatTestToolbar from './editorChatToolbar';
import JsonEditorSection from './editorJsonSection';
import ToolsPicker, { toToolIdList } from './editorToolsPicker';
import ToolInspectModal from './ToolInspectModal';
import SkillsPicker from './editorSkillsPicker';
import EditorSectionNav from './editorSectionNav';
import { useProject } from '../../contexts/ProjectContext';

interface DeepAgentEditorProps {
  tab: Tab;
}

type SectionId = _SectionId;

export default function DeepAgentEditor({ tab }: DeepAgentEditorProps) {
  const t = useLayoutTokens();
  const { setRightPanelTab, openRightPanel, closeTab } = useLayoutState();
  const agent = tab.data?.agent ?? tab.data ?? {};
  const config = agent.config || {};
  const { cloudModels, localModels, isLoading: modelsLoading } = useAvailableModels({ includeLocal: true });
  // Models the reader graph can use for the vision step (catalog `capabilities.vision`).
  const visionCapableModels = (cloudModels || [])
    .filter((m: any) => m?.capabilities?.vision)
    .map((m: any) => ({ id: m.id, name: m.name || m.id }));
  const [activeSection, setActiveSection] = useState<SectionId>('overview');
  const [expandedSubs, setExpandedSubs] = useState<Record<number, boolean>>({});
  const [testPrompt, setTestPrompt] = useState('Hello, please introduce yourself.');
  const [running, setRunning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);
  // Tool card click -> inspect/edit panel (per-agent tool_params, e.g. database)
  const [inspectTool, setInspectTool] = useState<{ id: string; name: string; description: string } | null>(null);
  // Editable JSON text for the JSON tab
  const [jsonEdit, setJsonEdit] = useState(() => JSON.stringify(agent, null, 2));

  // Always-current mirror of jsonEdit — lets async handlers (e.g. the tool
  // inspect modal's Save -> main save) read the latest JSON after a state
  // flush instead of a stale render closure.
  const jsonEditRef = useRef(jsonEdit);
  useEffect(() => { jsonEditRef.current = jsonEdit; }, [jsonEdit]);

  // Live view of jsonEdit — the form fields read from here so edits reflect
  // immediately (and Save persists exactly what's shown).
  const live = useMemo(() => {
    try { return JSON.parse(jsonEdit) || {}; } catch { return agent || {}; }
  }, [jsonEdit]); // eslint-disable-line react-hooks/exhaustive-deps
  const liveConfig = live.config || {};
  const liveGuardrails = liveConfig.guardrails || agent.guardrails_config || {};
  // User-defined workspace path (persisted in PostgreSQL; empty → default
  // outputs/agents/agent_{id}/)
  const [workspacePath, setWorkspacePath] = useState<string>(agent.workspace_path || '');
  // Agent instruction docs (AGENTS.md / CLAUDE.md …) — edited in the Docs tab
  const [docsDraft, setDocsDraft] = useState<Record<string, string>>(() => ({
    ...((agent.agent_docs as Record<string, string>) || {}),
  }));
  const [docsSaving, setDocsSaving] = useState(false);
  const [docsMsg, setDocsMsg] = useState<{ ok: boolean; text: string } | null>(null);
  // Track the persisted agent id locally — template ids are strings until saved
  const [localAgentId, setLocalAgentId] = useState<number | null>(
    typeof agent.id === 'number' ? agent.id : null
  );

  // Keep the persisted id in sync when switching tabs
  useEffect(() => {
    setLocalAgentId(typeof agent.id === 'number' ? agent.id : null);
  }, [tab.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Sync the active project (vault) into the chat store so the next chat
  // sends project_id in both /api/chat/start and /api/chat/message/stream.
  // Without this, the chat session is created with project_id=NULL and the
  // workspace resolver falls back to the legacy default path.
  const { activeProjectId: _activeProjectId } = useProject();
  useEffect(() => {
    chatStore.setCurrentProjectId(_activeProjectId ?? null);
  }, [_activeProjectId]);

  // Editable model — synced from config, falls back to stored default
  const [editableModel, setEditableModel] = useState(config.model || localStorage.getItem('langconfig.defaultModel') || '');

  // Editable system prompt — synced from config, updated in the Prompt tab and
  // written into jsonEdit so the Save button persists it (the Prompt tab used
  // to be a read-only <pre>; now it's a real textarea).
  const [promptDraft, setPromptDraft] = useState(config.system_prompt || '');

  // ── Skills state (interactive picker) ──
  const [availableSkills, setAvailableSkills] = useState<any[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(true);
  const [selectedSkills, setSelectedSkills] = useState<string[]>(config.skills || []);
  const [showAllSkills, setShowAllSkills] = useState(true);

  // Fetch the full skill catalog for the picker
  useEffect(() => {
    let cancelled = false;
    apiClient.listSkills()
      .then(res => {
        if (!cancelled) setAvailableSkills(Array.isArray(res.data) ? res.data : []);
      })
      .catch(() => { /* skills are optional */ })
      .finally(() => { if (!cancelled) setSkillsLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // ── Tools state (interactive picker) ──
  const { isLoading: toolsLoading, groupedByCategory, defaultToolIds } = useAvailableTools();
  const [availableCustomTools, setAvailableCustomTools] = useState<
    { id: number; tool_id: string; name: string; description: string }[]
  >([]);
  const [selectedNativeTools, setSelectedNativeTools] = useState<string[]>(
    toToolIdList(config.native_tools).length ? toToolIdList(config.native_tools) : defaultToolIds);
  // Apply the default tool set once loaded (async hook) when the agent has no
  // configured tools yet — new agents start with the universal base pre-checked.
  useEffect(() => {
    if (defaultToolIds.length && selectedNativeTools.length === 0) {
      setSelectedNativeTools(defaultToolIds);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaultToolIds]);
  const [selectedCustomTools, setSelectedCustomTools] = useState<string[]>(toToolIdList(config.custom_tools));
  const [showAllTools, setShowAllTools] = useState(true);

  // Seed tool + skill state from jsonEdit on mount (since payload may change after load)
  useEffect(() => {
    try {
      const p = JSON.parse(jsonEdit);
      const c = p.config || {};
      setSelectedNativeTools(toToolIdList(c.native_tools));
      setSelectedCustomTools(toToolIdList(c.custom_tools));
      setSelectedSkills(Array.isArray(c.skills) ? c.skills : []);
    } catch { /* ignore malformed json */ }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch custom tools list
  useEffect(() => {
    let cancelled = false;
    apiClient.listCustomTools().then((res: any) => {
      if (!cancelled && res?.data) setAvailableCustomTools(res.data);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const handleModelChange = useCallback((newModel: string) => {
    setEditableModel(newModel);
    // Sync into jsonEdit so the Save button persists the change
    setJsonEdit(prev => {
      try {
        const parsed = JSON.parse(prev);
        if (!parsed.config) parsed.config = {};
        parsed.config.model = newModel || null;
        // Clean up null values
        if (!parsed.config.model) delete parsed.config.model;
        return JSON.stringify(parsed, null, 2);
      } catch {
        return prev;
      }
    });
  }, []);

  /** Edit the system prompt in the Prompt tab; sync into jsonEdit so Save persists it. */
  const handlePromptChange = useCallback((value: string) => {
    setPromptDraft(value);
    setJsonEdit(prev => {
      try {
        const parsed = JSON.parse(prev);
        if (!parsed.config) parsed.config = {};
        parsed.config.system_prompt = value;
        return JSON.stringify(parsed, null, 2);
      } catch {
        return prev;
      }
    });
  }, []);

  /** Generic: mutate the parsed jsonEdit object, then re-serialize (used by the
   * editable Overview/Guardrails fields so every change survives Save). */
  const patchJson = useCallback((mutate: (parsed: any) => void) => {
    setJsonEdit(prev => {
      try {
        const parsed = JSON.parse(prev);
        if (!parsed.config) parsed.config = {};
        mutate(parsed);
        return JSON.stringify(parsed, null, 2);
      } catch {
        return prev;
      }
    });
  }, []);

  /** Edit a top-level field (name/description/category) in the agent JSON. */
  const handleFieldChange = useCallback((field: string, value: string) => {
    patchJson(p => { p[field] = value; });
  }, [patchJson]);

  /** Edit a config-level field (temperature/max_tokens/…) in the agent JSON. */
  const handleConfigFieldChange = useCallback((field: string, value: any) => {
    patchJson(p => { p.config[field] = value; });
  }, [patchJson]);

  /** Edit a guardrails field (enable_auto_eviction / enable_summarization /
   * long_term_memory / token_limits.*) — synced into config.guardrails so the
   * backend PUT persists it via request.config.guardrails. */
  const handleGuardrailChange = useCallback((path: string[], value: any) => {
    patchJson(p => {
      if (!p.config.guardrails) p.config.guardrails = {};
      let cur: any = p.config.guardrails;
      for (const key of path.slice(0, -1)) {
        if (typeof cur[key] !== 'object' || cur[key] === null) cur[key] = {};
        cur = cur[key];
      }
      cur[path[path.length - 1]] = value;
    });
  }, [patchJson]);

  const handleRun = async () => {
    if (!localAgentId || running) return;
    setRunning(true);

    // Open the right-sidebar chat panel
    setRightPanelTab('chat');
    openRightPanel('');

    // Start a chat session and send the test prompt
    const prompt = testPrompt || 'Hello, please introduce yourself.';
    try {
      // sendStreamMessage auto-starts a session if none exists
      const msgId = await chatStore.sendStreamMessage(localAgentId, prompt, agent.name);
      if (!msgId) {
        // Session start failed — error is already in chatStore
        console.error('[DeepAgentEditor] sendStreamMessage failed');
      }
    } catch (err: any) {
      console.error('[DeepAgentEditor] Run error:', err);
      chatStore.add({
        role: 'system',
        text: `// Failed to run agent: ${err.message}`,
      });
    } finally {
      setRunning(false);
    }
  };

  const handleStop = () => {
    chatStore.cancelStream();
    setRunning(false);
  };

  /** Update jsonEdit with the current tool selections */
  const syncToolsToJson = useCallback((native: string[], custom: string[]) => {
    setJsonEdit(prev => {
      try {
        const p = JSON.parse(prev);
        if (!p.config) p.config = {};
        p.config.native_tools = native;
        p.config.custom_tools = custom;
        return JSON.stringify(p, null, 2);
      } catch { return prev; }
    });
  }, []);

  /**
   * The single writer of `config.tool_params` in this editor.
   *
   * Both the inline tool-box controls (ToolsPicker -> ToolParamsControls, e.g.
   * read_any_file's "Image reading" / "Vision model") and the inspect modal call
   * it, so the JSON tab, the in-memory draft and the saved row cannot disagree.
   * The ref write is synchronous on purpose: handleSave reads
   * jsonEditRef.current, and the effect that mirrors jsonEdit runs after commit.
   */
  const applyToolParams = (toolId: string, params: Record<string, any> | null) => {
    let updated: any = null;
    try {
      updated = JSON.parse(jsonEditRef.current);
      if (!updated.config) updated.config = {};
      const current = { ...(updated.config.tool_params || {}) };
      // No params left => unpin the tool for this agent instead of storing {}.
      if (params && Object.keys(params).length > 0) current[toolId] = params;
      else delete current[toolId];
      updated.config.tool_params = Object.keys(current).length > 0 ? current : null;
    } catch { /* invalid JSON — reported below */ }

    if (!updated) {
      setSaveMsg({ ok: false, text: 'Invalid JSON — tool options not saved' });
      setTimeout(() => setSaveMsg(null), 3000);
      return;
    }

    const json = JSON.stringify(updated, null, 2);
    setJsonEdit(json);
    jsonEditRef.current = json;
    if (localAgentId) {
      setTimeout(() => { handleSave(); }, 0);
    } else {
      setSaveMsg({ ok: true, text: `Tool options saved for ${toolId} (draft — click Save to create the agent)` });
      setTimeout(() => setSaveMsg(null), 3000);
    }
  };

  const toggleNativeTool = useCallback((toolId: string) => {
    setSelectedNativeTools(prev => {
      const next = prev.includes(toolId) ? prev.filter(t => t !== toolId) : [...prev, toolId];
      syncToolsToJson(next, selectedCustomTools);
      return next;
    });
  }, [syncToolsToJson, selectedCustomTools]);

  const toggleCustomTool = useCallback((toolId: string) => {
    setSelectedCustomTools(prev => {
      const next = prev.includes(toolId) ? prev.filter(t => t !== toolId) : [...prev, toolId];
      syncToolsToJson(selectedNativeTools, next);
      return next;
    });
  }, [syncToolsToJson, selectedNativeTools]);

  /** Update jsonEdit with the current skill selections */
  const syncSkillsToJson = useCallback((skills: string[]) => {
    setJsonEdit(prev => {
      try {
        const p = JSON.parse(prev);
        if (!p.config) p.config = {};
        p.config.skills = skills;
        return JSON.stringify(p, null, 2);
      } catch { return prev; }
    });
  }, []);

  const toggleSkill = useCallback((skillId: string) => {
    setSelectedSkills(prev => {
      const next = prev.includes(skillId) ? prev.filter(s => s !== skillId) : [...prev, skillId];
      syncSkillsToJson(next);
      return next;
    });
  }, [syncSkillsToJson]);

  // Fetch the generated runnable Python CLI (`agent.py`) and show it in a code popup
  const [codeModal, setCodeModal] = useState<{ filename: string; code: string } | null>(null);
  const handleViewCode = async () => {
    if (!localAgentId) return;
    try {
      const res = await apiClient.getAgentCode(localAgentId);
      const code = typeof res.data === 'string' ? res.data : String(res.data ?? '');
      const safeName = (agent.name || 'agent').replace(/[^\w\-]+/g, '_');
      setCodeModal({ filename: `${safeName}.py`, code });
    } catch (err: any) {
      console.error('[DeepAgentEditor] View code error:', err);
      setSaveMsg({ ok: false, text: 'Failed to load code' });
    }
  };

  // After a .langconfig import, point the editor at the imported agent.
  const handleImported = useCallback((imported: any) => {
    if (!imported?.id) return;
    setLocalAgentId(typeof imported.id === 'number' ? imported.id : null);
    setJsonEdit(JSON.stringify(imported, null, 2));
    // Sync ALL editable fields with the imported config — not just the
    // JSON view. The Prompt tab reads `promptDraft`, so without this the
    // textarea keeps whatever the editor was initialized with (often the
    // one-sentence default) while the JSON tab shows the real prompt.
    const c = imported.config || {};
    setEditableModel(c.model || '');
    setPromptDraft(c.system_prompt || '');
    setSelectedNativeTools(toToolIdList(c.native_tools));
    setSelectedCustomTools(toToolIdList(c.custom_tools));
    setSelectedSkills(Array.isArray(c.skills) ? c.skills : []);
    setActiveSection('json');
    setSaveMsg({ ok: true, text: `Imported as "${imported.name}"` });
    setTimeout(() => setSaveMsg(null), 4000);
  }, [setLocalAgentId, setJsonEdit, setEditableModel, setPromptDraft, setSelectedNativeTools, setSelectedCustomTools, setSelectedSkills, setActiveSection, setSaveMsg]);

  /** Two-step destructive delete: first confirm irreversibility, then a
   *  second hard confirm before the API call. On success, close the tab. */
  const handleDelete = async () => {
    const id = localAgentId;
    const name = agent.name || `DeepAgent ${id ?? '?'}`;
    if (!id) return;
    const step1 = window.confirm(
      `Delete DeepAgent "${name}" (id=${id})? Its chat sessions and workspace ` +
      `directory will be removed. This action cannot be undone.`,
    );
    if (!step1) return;
    const step2 = window.confirm(
      `Last warning — permanently delete "${name}" (id=${id})? ` +
      `There is no undo for this action.`,
    );
    if (!step2) return;
    try {
      setSaving(true);
      await apiClient.deleteDeepAgent(id);
      setSaveMsg({ ok: true, text: `Deleted "${name}"` });
      window.setTimeout(() => closeTab(tab.id), 400);
    } catch (err: any) {
      console.error('[DeepAgentEditor] Delete error:', err);
      setSaveMsg({
        ok: false,
        text: `Delete failed: ${err?.response?.data?.detail ?? err?.message ?? 'unknown error'}`,
      });
    } finally {
      setSaving(false);
    }
  };

  /** Parse the JSON textarea and PUT the updated agent back to the backend */
  const handleSave = async () => {
    if (saving) return;
    setSaving(true);
    setSaveMsg(null);
    try {
      let payload: any;
      try {
        payload = JSON.parse(jsonEditRef.current);
      } catch {
        setSaveMsg({ ok: false, text: 'Invalid JSON — fix errors and try again' });
        setSaving(false);
        return;
      }
      if (localAgentId) {
        payload.workspace_path = workspacePath.trim() || null;
        await apiClient.updateDeepAgent(localAgentId, payload);
        setSaveMsg({ ok: true, text: 'Saved successfully' });
      } else {
        const res = await apiClient.createDeepAgent({
          name: payload.name || agent.name || 'Untitled Deep Agent',
          description: payload.description || agent.description || undefined,
          category: payload.category || agent.category || 'Custom',
          config: payload.config || {},
          workspace_path: workspacePath.trim() || undefined,
          // Forward the active project so the agent's identity is baked
          // with the right vault at creation time (AGENTS.md/CLAUDE.md
          // system_prompt mentions the correct workspace path from the
          // start). The chat path also re-bakes per-turn, but this means
          // even the first message's identity block is correct.
          project_id: _activeProjectId ?? undefined,
        });
        const newAgent = res.data;
        setLocalAgentId(newAgent.id);
        setJsonEdit(JSON.stringify(newAgent, null, 2));
        setSaveMsg({ ok: true, text: 'Saved successfully' });
      }
      // Clear message after 3s
      setTimeout(() => setSaveMsg(null), 3000);
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? err?.message ?? 'unknown error';
      setSaveMsg({ ok: false, text: `Save failed: ${detail}` });
    } finally {
      setSaving(false);
    }
  };

  // ── Reusable styles ──
  const compactCardStyle: React.CSSProperties = {
    background: t.bgContent,
    border: `1px solid ${t.border}`,
    borderRadius: 4,
    padding: '6px 10px',
    marginBottom: 8,
  };
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
  const editableInputStyle: React.CSSProperties = {
    width: '100%',
    height: 26,
    padding: '0 6px',
    background: t.bgContent,
    border: `1px solid ${t.border}`,
    borderRadius: 3,
    color: t.textPrimary,
    fontSize: 12,
    fontFamily: 'inherit',
    outline: 'none',
    boxSizing: 'border-box',
  };
  const inputStyle: React.CSSProperties = { ...editableInputStyle };
  const textareaStyle: React.CSSProperties = {
    ...editableInputStyle,
    height: 'auto',
    minHeight: 56,
    padding: '6px',
    resize: 'vertical',
    lineHeight: 1.4,
  };
  const smallBtnStyle: React.CSSProperties = {
    fontSize: 11,
    padding: '3px 8px',
    background: t.bgHover,
    border: `1px solid ${t.border}`,
    borderRadius: 3,
    color: t.textPrimary,
    cursor: 'pointer',
    fontFamily: 'inherit',
  };

  // ── Overview section — editable fields ──
  const renderOverview = () => (
    <div style={{ padding: 4 }}>
      <div style={compactCardStyle}>
        <div style={labelStyle}>Name</div>
        <input
          value={live.name || ''}
          onChange={e => handleFieldChange('name', e.target.value)}
          style={editableInputStyle}
        />
        {localAgentId && (
          <span style={{
            fontSize: 11, color: t.textMuted, fontFamily: 'monospace',
            background: t.bgHover, padding: '1px 6px', borderRadius: 3,
            border: `1px solid ${t.border}`, marginLeft: 6,
          }}>
            #{agent.id}
          </span>
        )}
      </div>
      <div style={compactCardStyle}>
        <div style={labelStyle}>Description</div>
        <textarea
          value={live.description || ''}
          onChange={e => handleFieldChange('description', e.target.value)}
          spellCheck={false}
          rows={2}
          style={{ ...editableInputStyle, height: 'auto', minHeight: 48, resize: 'vertical', fontFamily: 'inherit', fontSize: 12 }}
        />
      </div>
      <div style={compactCardStyle}>
        <div style={labelStyle}>Category</div>
        <input
          value={live.category || ''}
          onChange={e => handleFieldChange('category', e.target.value)}
          style={editableInputStyle}
        />
      </div>
      {/* Workspace path — user-defined per-agent directory (PostgreSQL) */}
      <div style={compactCardStyle}>
        <div style={labelStyle}>Workspace Path (optional)</div>
        <input
          value={workspacePath}
          onChange={e => setWorkspacePath(e.target.value)}
          placeholder="e.g. outputs/agents/my-analysis  (empty = default agent workspace)"
          style={{
            width: '100%',
            height: 26,
            padding: '0 6px',
            background: t.bgContent,
            border: `1px solid ${t.border}`,
            borderRadius: 3,
            color: t.textPrimary,
            fontSize: 11,
            fontFamily: 'monospace',
            outline: 'none',
          }}
        />
        <div style={{ fontSize: 10, color: t.textMuted, marginTop: 3 }}>
          Uploads + generated files for this agent live here (absolute, or relative to outputs/).
          Saved on the next <b>Save</b>.
        </div>
      </div>
      {/* Skills */}
      {config.skills && config.skills.length > 0 && (
        <div style={compactCardStyle}>
          <div style={labelStyle}>Skills ({config.skills.length})</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {config.skills.map((skill: string, i: number) => (
              <span
                key={i}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  padding: '3px 10px',
                  background: t.accent + '18',
                  border: `1px solid ${t.accent}40`,
                  borderRadius: 12,
                  fontSize: 12,
                  fontWeight: 500,
                  color: t.accent,
                  fontFamily: 'monospace',
                }}
              >
                {skill}
              </span>
            ))}
          </div>
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
        <div style={compactCardStyle}>
          <div style={labelStyle}>Category</div>
          <div style={valueStyle}>{agent.category || '—'}</div>
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>Model</div>
          <select
            value={editableModel}
            onChange={e => handleModelChange(e.target.value)}
            disabled={modelsLoading}
            style={{
              width: '100%',
              height: 26,
              padding: '0 6px',
              background: t.bgContent,
              border: `1px solid ${t.border}`,
              borderRadius: 3,
              color: t.textPrimary,
              fontSize: 11,
              fontFamily: 'monospace',
              outline: 'none',
            }}
          >
            <option value="">
              {modelsLoading ? 'Loading...' : '(Backend default)'}
            </option>
            {cloudModels.length > 0 && (
              <optgroup label="Cloud Models">
                {cloudModels.map(m => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </optgroup>
            )}
            {localModels.length > 0 && (
              <optgroup label="Local Models">
                {localModels.map(m => (
                  <option key={m.id} value={m.id}>
                    {m.name}{m.is_validated === false ? ' [Not Validated]' : ''}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>Temperature</div>
          <input
            type="number"
            step="0.1"
            min={0}
            max={2}
            value={liveConfig.temperature ?? ''}
            onChange={e => handleConfigFieldChange('temperature', e.target.value === '' ? undefined : parseFloat(e.target.value))}
            style={editableInputStyle}
          />
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>Max Tokens</div>
          <input
            type="number"
            step={1}
            min={1}
            value={liveConfig.max_tokens ?? ''}
            onChange={e => handleConfigFieldChange('max_tokens', e.target.value === '' ? null : parseInt(e.target.value, 10))}
            style={editableInputStyle}
          />
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>Version</div>
          <div style={{ ...valueStyle, fontSize: 12 }}>{agent.version || '—'}</div>
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>Public</div>
          <div style={{ ...valueStyle, fontSize: 12 }}>{agent.is_public ? 'Yes' : 'No'}</div>
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>Usage Count</div>
          <div style={{ ...valueStyle, fontSize: 12 }}>{agent.usage_count ?? 0}</div>
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>Chat Sessions</div>
          <div style={{ ...valueStyle, fontSize: 12 }}>{agent.chat_sessions_count ?? 0}</div>
        </div>
      </div>
    </div>
  );

  // ── Agent Docs section (AGENTS.md / CLAUDE.md — per specific agent) ──
  const renderDocs = () => {
    const docKeys = ['AGENTS.md', 'CLAUDE.md'];
    const handleDocSave = async () => {
      if (!localAgentId) {
        setDocsMsg({ ok: false, text: 'Save the agent first, then edit its docs' });
        return;
      }
      setDocsSaving(true);
      setDocsMsg(null);
      try {
        await apiClient.updateAgentDocs(localAgentId, docsDraft);
        setDocsMsg({ ok: true, text: 'Docs saved (PostgreSQL). Applied on the next chat run.' });
      } catch (err: any) {
        const detail = err?.response?.data?.detail ?? err?.message ?? 'unknown error';
        setDocsMsg({ ok: false, text: `Save failed: ${detail}` });
      } finally {
        setDocsSaving(false);
      }
    };
    return (
      <div style={{ padding: 4 }}>
        <div style={cardStyle}>
          <div style={labelStyle}>Agent Docs — this agent only</div>
          <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 8 }}>
            Stored in PostgreSQL on this agent&apos;s row; written into the agent workspace
            (AGENTS.md is loaded by MemoryMiddleware) on each chat run.
          </div>
          {docKeys.map(name => (
            <div key={name} style={{ marginBottom: 10 }}>
              <div style={{ ...labelStyle, textTransform: 'none', fontSize: 12 }}>{name}</div>
              <textarea
                value={docsDraft[name] ?? ''}
                onChange={e => setDocsDraft(prev => ({ ...prev, [name]: e.target.value }))}
                placeholder={`# ${name} — instructions specific to ${agent.name || 'this agent'}…`}
                spellCheck={false}
                style={{
                  width: '100%',
                  minHeight: 140,
                  padding: 8,
                  background: t.bgContent,
                  border: `1px solid ${t.border}`,
                  borderRadius: 4,
                  color: t.textPrimary,
                  fontSize: 12,
                  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                  lineHeight: 1.5,
                  outline: 'none',
                  resize: 'vertical',
                }}
              />
            </div>
          ))}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <button
              onClick={handleDocSave}
              disabled={docsSaving || !localAgentId}
              style={{
                padding: '5px 14px',
                border: 'none',
                borderRadius: 4,
                background: t.accent,
                color: '#fff',
                fontSize: 12,
                fontWeight: 600,
                cursor: docsSaving || !localAgentId ? 'not-allowed' : 'pointer',
                opacity: docsSaving || !localAgentId ? 0.6 : 1,
              }}
            >
              {docsSaving ? 'Saving…' : 'Save Docs'}
            </button>
            {docsMsg && (
              <span style={{ fontSize: 11, color: docsMsg.ok ? '#22c55e' : '#ef4444' }}>
                {docsMsg.text}
              </span>
            )}
          </div>
        </div>
      </div>
    );
  };

  // ── System prompt section — editable textarea ──
  const renderPrompt = () => (
    <div style={{ padding: 4 }}>
      <div style={cardStyle}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
          <div style={labelStyle}>System Prompt ({promptDraft.length} chars)</div>
          <span style={{ fontSize: 10, color: t.textMuted }}>
            Saved with the Save button
          </span>
        </div>
        <textarea
          value={promptDraft}
          onChange={e => handlePromptChange(e.target.value)}
          spellCheck={false}
          placeholder="Enter the agent's system prompt…"
          style={{
            width: '100%',
            height: 'calc(100vh - 210px)', // fill the editor panel height
            minHeight: 280,
            padding: 10,
            boxSizing: 'border-box',
            background: t.bgInput,
            border: `1px solid ${t.border}`,
            borderRadius: 4,
            color: t.textPrimary,
            fontFamily: '"SF Mono", "Fira Code", monospace',
            fontSize: 12,
            lineHeight: 1.5,
            outline: 'none',
            resize: 'vertical',
          }}
        />
      </div>
    </div>
  );

  // ── Skills section — searchable, card-grid picker over all skills ──
  const renderSkills = () => (
    <SkillsPicker
      selectedSkills={selectedSkills}
      onToggle={toggleSkill}
      showAll={showAllSkills}
      onShowAllChange={setShowAllSkills}
      skillsLoading={skillsLoading}
      availableSkills={availableSkills}
      t={t}
    />
  );

  // ── Subagents section — editable: add / edit / remove subagent cards ──
  const [subagentDraft, setSubagentDraft] = useState<{
    name: string; description: string; model: string; system_prompt: string; tools: string;
    type: string; graph_id: string; database: string; workflow_id: string;
  }>({ name: '', description: '', model: '', system_prompt: '', tools: '',
       type: 'dictionary', graph_id: '', database: '', workflow_id: '' });
  const [subagentEditIdx, setSubagentEditIdx] = useState<number | null>(null);

  const readSubagents = useCallback((): any[] => {
    try {
      const parsed = JSON.parse(jsonEdit);
      // Backend update endpoint persists request.config.subagents; the
      // top-level subagents_config in the GET response is derived from it.
      return Array.isArray(parsed.config?.subagents) ? parsed.config.subagents : [];
    } catch { return []; }
  }, [jsonEdit]);

  const startAddSubagent = () => {
    setSubagentDraft({ name: '', description: '', model: '', system_prompt: '', tools: '',
      type: 'dictionary', graph_id: '', database: '', workflow_id: '' });
    setSubagentEditIdx(null);
  };

  const startEditSubagent = (idx: number) => {
    const subs = readSubagents();
    const sa = subs[idx] || {};
    setSubagentDraft({
      name: sa.name || '',
      description: sa.description || '',
      model: sa.model || '',
      system_prompt: sa.system_prompt || '',
      tools: Array.isArray(sa.tools) ? sa.tools.join(', ') : '',
      type: sa.type || 'dictionary',
      graph_id: sa.graph_id || '',
      database: sa.database || '',
      workflow_id: sa.workflow_id != null ? String(sa.workflow_id) : '',
    });
    setSubagentEditIdx(idx);
  };

  const saveSubagentDraft = () => {
    if (!subagentDraft.name.trim()) {
      setSaveMsg({ ok: false, text: 'Subagent needs a name' });
      return;
    }
    if (subagentDraft.type === 'langgraph' && !subagentDraft.graph_id.trim()) {
      setSaveMsg({ ok: false, text: 'LangGraph subagent needs a graph_id (e.g. neo4j_agent)' });
      return;
    }
    const sa: any = {
      name: subagentDraft.name.trim(),
      description: subagentDraft.description.trim(),
      system_prompt: subagentDraft.system_prompt,
    };
    if (subagentDraft.type !== 'dictionary') sa.type = subagentDraft.type;
    if (subagentDraft.type === 'langgraph') {
      sa.graph_id = subagentDraft.graph_id.trim();
      if (subagentDraft.database.trim()) sa.database = subagentDraft.database.trim();
    } else if (subagentDraft.type === 'compiled' && subagentDraft.workflow_id.trim()) {
      const wid = Number(subagentDraft.workflow_id.trim());
      if (Number.isInteger(wid) && wid > 0) sa.workflow_id = wid;
    }
    if (subagentDraft.model.trim()) sa.model = subagentDraft.model.trim();
    if (subagentDraft.tools.trim()) {
      sa.tools = subagentDraft.tools.split(',').map(s => s.trim()).filter(Boolean);
    }
    patchJson(p => {
      if (!p.config) p.config = {};
      if (!Array.isArray(p.config.subagents)) p.config.subagents = [];
      if (subagentEditIdx !== null && subagentEditIdx < p.config.subagents.length) {
        p.config.subagents[subagentEditIdx] = sa;
      } else {
        p.config.subagents.push(sa);
      }
    });
    startAddSubagent();
    setSaveMsg({ ok: true, text: subagentEditIdx !== null ? 'Subagent updated' : 'Subagent added' });
    setTimeout(() => setSaveMsg(null), 2500);
  };

  const removeSubagent = (idx: number) => {
    patchJson(p => {
      if (p.config && Array.isArray(p.config.subagents)) {
        p.config.subagents = p.config.subagents.filter((_: any, i: number) => i !== idx);
      }
    });
    if (subagentEditIdx === idx) startAddSubagent();
    setSaveMsg({ ok: true, text: 'Subagent removed' });
    setTimeout(() => setSaveMsg(null), 2500);
  };

  const renderSubagents = () => {
    const subs = readSubagents();
    return (
      <div style={{ padding: 4 }}>
        <button onClick={startAddSubagent} style={{
          ...compactCardStyle, cursor: 'pointer', color: t.textPrimary, fontWeight: 600,
          display: 'flex', alignItems: 'center', gap: 6, border: `1px dashed ${t.accent}`,
        }}>
          <span style={{ fontSize: 15 }}>+</span> Add subagent
        </button>

        {subs.length === 0 && (
          <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic', marginTop: 8 }}>
            (no subagents — add one above)
          </div>
        )}

        {subs.map((sa: any, i: number) => {
          const sa_obj = typeof sa === 'string' ? { name: sa } : sa;
          const open = expandedSubs[i];
          const isEditing = subagentEditIdx === i;
          return (
            <div key={i} style={{ ...cardStyle, marginTop: 8 }}>
              {isEditing ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <input value={subagentDraft.name} onChange={e => setSubagentDraft(d => ({ ...d, name: e.target.value }))}
                    placeholder="Name (e.g. researcher)" style={inputStyle} />
                  <input value={subagentDraft.description} onChange={e => setSubagentDraft(d => ({ ...d, description: e.target.value }))}
                    placeholder="Description — what this subagent does" style={inputStyle} />
                  <select
                    value={subagentDraft.type}
                    onChange={e => setSubagentDraft(d => ({ ...d, type: e.target.value }))}
                    style={{
                      width: '100%', height: 26, padding: '0 6px',
                      background: t.bgContent, border: `1px solid ${t.border}`,
                      borderRadius: 3, color: t.textPrimary, fontSize: 11,
                      fontFamily: 'monospace', outline: 'none',
                    }}
                  >
                    <option value="dictionary">Dictionary (model + tools)</option>
                    <option value="compiled">Compiled (workflow)</option>
                    <option value="langgraph">LangGraph (code-defined agent)</option>
                  </select>
                  {subagentDraft.type === 'langgraph' && (
                    <>
                      <input value={subagentDraft.graph_id} onChange={e => setSubagentDraft(d => ({ ...d, graph_id: e.target.value }))}
                        placeholder="Graph agent id (neo4j_agent or sql_agent)" style={inputStyle} />
                      <input value={subagentDraft.database} onChange={e => setSubagentDraft(d => ({ ...d, database: e.target.value }))}
                        placeholder="Neo4j database (e.g. neo4j; empty = default)" style={inputStyle} />
                    </>
                  )}
                  {subagentDraft.type === 'compiled' && (
                    <input value={subagentDraft.workflow_id} onChange={e => setSubagentDraft(d => ({ ...d, workflow_id: e.target.value }))}
                      placeholder="Workflow ID (number)" style={inputStyle} />
                  )}
                  <input value={subagentDraft.model} onChange={e => setSubagentDraft(d => ({ ...d, model: e.target.value }))}
                    placeholder="Model override (optional, e.g. deepseek-chat)" style={inputStyle} />
                  <textarea value={subagentDraft.system_prompt} onChange={e => setSubagentDraft(d => ({ ...d, system_prompt: e.target.value }))}
                    placeholder="System prompt for this subagent" rows={3} style={textareaStyle} />
                  <input value={subagentDraft.tools} onChange={e => setSubagentDraft(d => ({ ...d, tools: e.target.value }))}
                    placeholder="Tools (comma-separated, optional)" style={inputStyle} />
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button onClick={saveSubagentDraft} style={{ ...smallBtnStyle, background: t.accent, color: '#fff' }}>
                      {subagentEditIdx !== null ? 'Update' : 'Add'}
                    </button>
                    <button onClick={startAddSubagent} style={smallBtnStyle}>Cancel</button>
                  </div>
                </div>
              ) : (
                <>
                  <div
                    onClick={() => setExpandedSubs(prev => ({ ...prev, [i]: !prev[i] }))}
                    style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', userSelect: 'none' }}
                  >
                    {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                    <div style={{ ...valueStyle, fontWeight: 600 }}>{sa_obj.name || sa_obj.prompt || `Subagent #${i + 1}`}</div>
                    <div style={{ ...valueStyle, color: t.textMuted, fontSize: 11, marginLeft: 8, flex: 1 }}>
                      {sa_obj.description?.slice(0, 60)}
                    </div>
                    <button onClick={(e) => { e.stopPropagation(); startEditSubagent(i); }}
                      style={smallBtnStyle}>Edit</button>
                    <button onClick={(e) => { e.stopPropagation(); removeSubagent(i); }}
                      style={{ ...smallBtnStyle, color: '#e5484d' }}>Remove</button>
                  </div>
                  {open && (
                    <div style={{ marginTop: 10, paddingLeft: 20 }}>
                      <div style={labelStyle}>Description</div>
                      <div style={{ ...valueStyle, marginBottom: 8 }}>{sa_obj.description || '—'}</div>
                      {sa_obj.type && sa_obj.type !== 'dictionary' && (
                        <>
                          <div style={labelStyle}>Type</div>
                          <div style={{ ...valueStyle, fontFamily: 'monospace', marginBottom: 8 }}>{sa_obj.type}</div>
                        </>
                      )}
                      {sa_obj.graph_id && (
                        <>
                          <div style={labelStyle}>Graph Agent</div>
                          <div style={{ ...valueStyle, fontFamily: 'monospace', marginBottom: 8 }}>{sa_obj.graph_id}</div>
                        </>
                      )}
                      {sa_obj.database && (
                        <>
                          <div style={labelStyle}>Database</div>
                          <div style={{ ...valueStyle, fontFamily: 'monospace', marginBottom: 8 }}>{sa_obj.database}</div>
                        </>
                      )}
                      {sa_obj.workflow_id && (
                        <>
                          <div style={labelStyle}>Workflow ID</div>
                          <div style={{ ...valueStyle, fontFamily: 'monospace', marginBottom: 8 }}>{sa_obj.workflow_id}</div>
                        </>
                      )}
                      {sa_obj.model && (
                        <>
                          <div style={labelStyle}>Model</div>
                          <div style={{ ...valueStyle, fontFamily: 'monospace', marginBottom: 8 }}>{sa_obj.model}</div>
                        </>
                      )}
                      {sa_obj.tools && sa_obj.tools.length > 0 && (
                        <>
                          <div style={labelStyle}>Tools ({sa_obj.tools.length})</div>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
                            {sa_obj.tools.map((tool: string, j: number) => (
                              <span key={j} style={{
                                fontSize: 11, padding: '2px 6px',
                                background: t.bgHover, borderRadius: 3,
                                color: t.textPrimary, fontFamily: 'monospace',
                              }}>{tool}</span>
                            ))}
                          </div>
                        </>
                      )}
                      {sa_obj.system_prompt && (
                        <>
                          <div style={labelStyle}>System Prompt</div>
                          <pre style={{
                            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                            fontFamily: '"SF Mono", monospace', fontSize: 11,
                            color: t.textMuted, lineHeight: 1.5, margin: 0,
                            maxHeight: 200, overflow: 'auto',
                          }}>{sa_obj.system_prompt}</pre>
                        </>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          );
        })}
      </div>
    );
  };

  // ── Middleware section ──
  const renderMiddleware = () => {
    const mw = agent.middleware_config || config.middleware || [];
    if (mw.length === 0) {
      return (
        <div style={{ padding: 4 }}>
          <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic' }}>(no middleware)</div>
        </div>
      );
    }
    return (
      <div style={{ padding: 4 }}>
        {mw.map((m: any, i: number) => (
          <div key={i} style={cardStyle}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{
                fontSize: 11, padding: '2px 6px',
                background: m.enabled ? t.accent : t.bgHover,
                color: m.enabled ? '#fff' : t.textMuted,
                borderRadius: 3, fontWeight: 600,
              }}>{m.enabled ? 'ON' : 'OFF'}</span>
              <span style={{ ...valueStyle, fontWeight: 600 }}>{m.type}</span>
            </div>
            {m.config && Object.keys(m.config).length > 0 && (
              <div style={{ marginTop: 8, fontFamily: 'monospace', fontSize: 11, color: t.textMuted }}>
                {JSON.stringify(m.config, null, 2)}
              </div>
            )}
          </div>
        ))}
      </div>
    );
  };

  // ── Guardrails section — editable toggles + token inputs ──
  const renderGuardrails = () => {
    const g = liveGuardrails;
    const tl = g.token_limits || {};
    const toggle = (checked: boolean, on: () => void, off: () => void) => (
      <button
        onClick={() => (checked ? off() : on())}
        style={{
          padding: '3px 10px', borderRadius: 12, cursor: 'pointer',
          border: `1px solid ${checked ? t.accent : t.border}`,
          background: checked ? `${t.accent}18` : 'transparent',
          color: checked ? t.accent : t.textMuted,
          fontSize: 11, fontWeight: 500,
        }}
      >
        {checked ? 'Enabled' : 'Disabled'}
      </button>
    );
    const numInput = (path: string[], value: any) => (
      <input
        type="number"
        step={1}
        min={0}
        value={value ?? ''}
        onChange={e => handleGuardrailChange(path, e.target.value === '' ? undefined : parseInt(e.target.value, 10))}
        style={{ ...editableInputStyle, width: 120, fontFamily: 'monospace' }}
      />
    );
    return (
      <div style={{ padding: 4 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={labelStyle}>Auto Eviction</div>
          {toggle(Boolean(g.enable_auto_eviction),
            () => handleGuardrailChange(['enable_auto_eviction'], true),
            () => handleGuardrailChange(['enable_auto_eviction'], false))}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 6 }}>
          <div style={labelStyle}>Summarization</div>
          {toggle(Boolean(g.enable_summarization),
            () => handleGuardrailChange(['enable_summarization'], true),
            () => handleGuardrailChange(['enable_summarization'], false))}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 6 }}>
          <div style={labelStyle}>Long-Term Memory</div>
          {toggle(Boolean(g.long_term_memory),
            () => handleGuardrailChange(['long_term_memory'], true),
            () => handleGuardrailChange(['long_term_memory'], false))}
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>Execution Limit</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 11, color: t.textMuted, width: 150 }}>recursion_limit</span>
            <input
              type="number"
              min={1}
              value={liveConfig.recursion_limit ?? ''}
              onChange={e => handleConfigFieldChange(
                'recursion_limit', e.target.value === '' ? null : parseInt(e.target.value, 10))}
              style={{ ...editableInputStyle, width: 120, fontFamily: 'monospace' }}
            />
            <span style={{ fontSize: 10, color: t.textMuted }}>
              turns per run — unset uses the team default (1000)
            </span>
          </div>
          <div style={{ fontSize: 10, color: t.textMuted, marginTop: 6, lineHeight: '14px' }}>
            Caps LangGraph steps in one run (model + tool turns), so a runaway
            tool loop stops with a clear error instead of spinning. Measured cost:
            a DeepAgent spends ~2–3 steps per tool turn, a standard agent ~30 — so
            the 1000 default is ~30 tool turns for a standard agent. It bounds
            steps, not context size — that is what summarization is for.
          </div>
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>Token Limits</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 11, color: t.textMuted, width: 150 }}>max_total_tokens</span>
              {numInput(['token_limits', 'max_total_tokens'], tl.max_total_tokens)}
              <span style={{ fontSize: 10, color: t.textMuted }}>workflow / export only</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 11, color: t.textMuted, width: 150 }}>eviction_threshold</span>
              {numInput(['token_limits', 'eviction_threshold'], tl.eviction_threshold)}
              <span style={{ fontSize: 10, color: t.textMuted }}>not read at runtime</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 11, color: t.textMuted, width: 150 }}>summarization_threshold</span>
              {numInput(['token_limits', 'summarization_threshold'], tl.summarization_threshold)}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 11, color: t.textMuted, width: 150 }}>keep_last_messages</span>
              {numInput(['token_limits', 'keep_last_messages'], tl.keep_last_messages)}
            </div>
          </div>
          {/* How compaction behaves, in one line — the numbers above are easy to
              misread: the threshold counts system prompt + tool schemas +
              conversation, so a value below the agent's own baseline compacts on
              every turn; and nothing is evicted until the history is longer than
              keep_last_messages. */}
          <div style={{ fontSize: 10, color: t.textMuted, marginTop: 6, lineHeight: '14px' }}>
            Older messages are folded into one summary that stays in context;
            the last <strong style={{ color: t.textPrimary }}>{tl.keep_last_messages ?? 20}</strong> messages
            are kept verbatim (default 20), and everything evicted is written
            verbatim to <code>conversation_history/&lt;thread&gt;.md</code> in the agent
            workspace. The threshold is compared against system prompt + tool
            schemas + conversation, so keep it comfortably above the agent's own
            baseline or it will compact on every turn.
          </div>
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>Backend</div>
          <div style={{ fontSize: 11, color: t.textMuted }}>
            {agent.backend_config?.type ?? 'state'} — set automatically at build time
          </div>
        </div>
      </div>
    );
  };

  const sections: Record<SectionId, () => React.ReactNode> = {
    overview:   renderOverview,
    prompt:     renderPrompt,
    tools:      () => <ToolsPicker
      selectedNativeTools={selectedNativeTools}
      selectedCustomTools={selectedCustomTools}
      onToggleNative={toggleNativeTool}
      onToggleCustom={toggleCustomTool}
      showAllTools={showAllTools}
      onShowAllChange={setShowAllTools}
      toolsLoading={toolsLoading}
      groupedByCategory={groupedByCategory}
      availableCustomTools={availableCustomTools}
      onInspect={setInspectTool}
      toolParams={liveConfig.tool_params}
      onToolParamsChange={applyToolParams}
      visionModels={visionCapableModels}
      t={t}
    />,
    skills:     renderSkills,
    subagents:  renderSubagents,
    middleware: renderMiddleware,
    guardrails: renderGuardrails,
    docs:       renderDocs,
    json:       () => <JsonEditorSection value={jsonEdit} onChange={setJsonEdit} t={t} />,
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: t.bgContent }}>
      {/* ── Top action bar (VS Code run-toolbar style) ── */}
      <ChatTestToolbar
        testPrompt={testPrompt}
        onTestPromptChange={setTestPrompt}
        running={running}
        onRun={handleRun}
        onStop={handleStop}
        saving={saving}
        onSave={handleSave}
        onViewCode={handleViewCode}
        agentId={localAgentId ?? (typeof agent.id === 'number' ? agent.id : null)}
        agentName={agent.name}
        onImported={handleImported}
        onDelete={handleDelete}
        canRun={!!localAgentId}
        saveDisabled={!localAgentId}
        saveMsg={saveMsg}
        statusLabel={`ID: ${localAgentId ?? agent.id ?? '—'} · v${agent.version ?? '?'} · ${agent.category ?? ''}`}
        t={t}
      />

      {/* ── Body: section nav + section content ── */}
      <EditorSectionNav
        sections={SECTIONS}
        activeSection={activeSection}
        onSectionChange={id => setActiveSection(id as SectionId)}
        renderSection={id => sections[id as SectionId]()}
        heading={
          <h2 style={{
            fontSize: 16,
            fontWeight: 600,
            color: t.textPrimary,
            margin: '0 0 12px 0',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}>
            {agent.name || 'DeepAgent'}
            {localAgentId && (
              <span style={{
                fontSize: 11, fontWeight: 400, color: t.textMuted, fontFamily: 'monospace',
              }}>
                #{agent.id}
              </span>
            )}
          </h2>
        }
        hint={
          <div style={{
            marginTop: 16,
            padding: 10,
            fontSize: 11,
            color: t.textMuted,
            fontStyle: 'italic',
          }}>
            💬 After clicking <strong style={{ color: t.textPrimary }}>▶ Run</strong>, the conversation appears in the <strong style={{ color: t.textPrimary }}>Chat</strong> panel on the right.
          </div>
        }
        t={t}
      />

      {codeModal && (
        <CodeViewerModal
          filename={codeModal.filename}
          code={codeModal.code}
          onClose={() => setCodeModal(null)}
        />
      )}

      {inspectTool && (
        <ToolInspectModal
          tool={inspectTool}
          toolParams={liveConfig.tool_params}
          onClose={() => setInspectTool(null)}
          onSave={(toolId, params) => {
            applyToolParams(toolId, params);
            setInspectTool(null);
          }}
          t={t}
        />
      )}
    </div>
  );
}
