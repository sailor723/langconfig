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
import { useTranslation } from 'react-i18next';
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
import SubagentsEditor from './editorSubagents';
import ChatTestToolbar from './editorChatToolbar';
import JsonEditorSection from './editorJsonSection';
import ToolsPicker, { toToolIdList } from './editorToolsPicker';
import HitlPolicyEditor from './HitlPolicyEditor';
import HandoffPolicyEditor from './HandoffPolicyEditor';
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
  const { t: tr } = useTranslation('chat');
  const { setRightPanelTab, openRightPanel, closeTab } = useLayoutState();
  const agent = tab.data?.agent ?? tab.data ?? {};
  const config = agent.config || {};
  const { cloudModels, localModels, isLoading: modelsLoading } = useAvailableModels({ includeLocal: true });
  // Models the reader graph can use for the vision step (catalog `capabilities.vision`).
  const visionCapableModels = (cloudModels || [])
    .filter((m: any) => m?.capabilities?.vision)
    .map((m: any) => ({ id: m.id, name: m.name || m.id }));
  const [activeSection, setActiveSection] = useState<SectionId>('overview');
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
  // Creating and editing share this component (the old DeepAgentCreator was a
  // second, divergent implementation of the same form). `data.new` marks a
  // draft; the first save POSTs it and the id lands in localAgentId.
  const _agentIdNum = Number(agent.id);
  const isNew = tab.data?.new === true || !(Number.isFinite(_agentIdNum) && _agentIdNum > 0);
  // An existing agent is read from the server before rendering; the tab's
  // snapshot is only a placeholder until then.
  const [configLoaded, setConfigLoaded] = useState(isNew);
  const [configLoadError, setConfigLoadError] = useState<string | null>(null);
  const [configRev, setConfigRev] = useState(0);
  // Same reason as AgentEditor: the tab carries a snapshot, the server is the
  // truth. Re-read it when the tab opens so two tabs cannot silently diverge.
  useEffect(() => {
    const id = isNew ? null : _agentIdNum;
    if (!id) return;
    let cancelled = false;
    apiClient.getDeepAgent(id)
      .then(res => {
        if (cancelled || !res?.data) return;
        setJsonEdit(JSON.stringify(res.data, null, 2));
        setConfigLoadError(null);
        setConfigLoaded(true);
        setConfigRev(v => v + 1);
      })
      .catch((err: any) => {
        if (cancelled) return;
        setConfigLoadError(err?.message || '载入失败');
        setConfigLoaded(true);
      });
    return () => { cancelled = true; };
  }, [isNew, _agentIdNum]); // eslint-disable-line react-hooks/exhaustive-deps

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

  // ── Human-in-the-loop (middleware) ──
  // Same shape the LangChain docs use: config.middleware gets a {"type":"hitl"}
  // entry whose interrupt_on maps tool → true | {allowed_decisions}.
  const _mwList = (((liveConfig as any).middleware ?? (liveConfig as any).config?.middleware) as any[] | undefined) ?? [];
  const handoffMw = _mwList.find(m => m && (m.type === 'handoff' || m.type === 'handoffs'));
  const handoffCfg = handoffMw?.config ?? {};
  const writeHandoff = (next: any) => {
    patchJson(p => {
      if (!Array.isArray(p.config.middleware)) p.config.middleware = [];
      const rest = p.config.middleware.filter(
        (m: any) => !(m && (m.type === 'handoff' || m.type === 'handoffs')),
      );
      if (next && next.steps && Object.keys(next.steps).length > 0) {
        rest.push({ type: 'handoff', enabled: true, config: next });
      }
      p.config.middleware = rest;
      p.middleware_config = JSON.parse(JSON.stringify(rest));
    });
  };

  const HitlSection = () => {
    const mwRaw = ((liveConfig as any).middleware ?? (liveConfig as any).config?.middleware) as any[] | undefined;
    const mw = Array.isArray(mwRaw) ? mwRaw : [];
    const hitl = mw.find(m => m && (m.type === 'hitl' || m.type === 'human_in_the_loop'));
    const interruptOn = (
      (hitl?.config?.interrupt_on ?? hitl?.interrupt_on) ?? {}
    ) as Record<string, any>;
    const write = (next: Record<string, any>) => {
      patchJson(p => {
        if (!Array.isArray(p.config.middleware)) p.config.middleware = [];
        const rest = p.config.middleware.filter(
          (m: any) => !(m && (m.type === 'hitl' || m.type === 'human_in_the_loop')),
        );
        if (Object.keys(next).length > 0) {
          rest.push({
            type: 'hitl',
            enabled: true,
            config: {
              interrupt_on: next,
              description_prefix:
                hitl?.config?.description_prefix || 'Tool execution pending approval',
            },
          });
        }
        p.config.middleware = rest;
      });
    };
    return (
      <>
        <HitlPolicyEditor
          value={interruptOn}
          onChange={write}
          candidateTools={[
            ...(Array.isArray(liveConfig.config?.native_tools) ? liveConfig.config.native_tools : []),
          ]}
          t={t}
        />
        <HandoffPolicyEditor
          value={handoffCfg}
          resetKey={`${agent.id ?? 'new'}:${configRev}`}
          onChange={writeHandoff}
          candidateTools={[
            ...(Array.isArray(liveConfig.config?.native_tools) ? liveConfig.config.native_tools : []),
          ]}
          t={t}
        />
      </>
    );
  };

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
      if (!localAgentId) {
        const draftName = String(payload.name || agent.name || '').trim();
        const draftPrompt = String(payload.config?.system_prompt || '').trim();
        if (!draftName || !draftPrompt) {
          setSaveMsg({
            ok: false,
            text: 'New DeepAgent needs a name and a system prompt before it can be created',
          });
          setSaving(false);
          return;
        }
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
        <div style={labelStyle}>{tr('ag_name')}</div>
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
        <div style={labelStyle}>{tr('ag_description')}</div>
        <textarea
          value={live.description || ''}
          onChange={e => handleFieldChange('description', e.target.value)}
          spellCheck={false}
          rows={2}
          style={{ ...editableInputStyle, height: 'auto', minHeight: 48, resize: 'vertical', fontFamily: 'inherit', fontSize: 12 }}
        />
      </div>
      <div style={compactCardStyle}>
        <div style={labelStyle}>{tr('ag_category')}</div>
        <input
          value={live.category || ''}
          onChange={e => handleFieldChange('category', e.target.value)}
          style={editableInputStyle}
        />
      </div>
      {/* Workspace path — user-defined per-agent directory (PostgreSQL) */}
      <div style={compactCardStyle}>
        <div style={labelStyle}>{tr('ag_workspace_path')}</div>
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
          <div style={labelStyle}>{tr('ag_category')}</div>
          <div style={valueStyle}>{agent.category || '—'}</div>
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>{tr('ag_model')}</div>
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
          <div style={labelStyle}>{tr('ag_temperature')}</div>
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
          <div style={labelStyle}>{tr('ag_max_tokens')}</div>
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
          <div style={labelStyle}>{tr('ag_version')}</div>
          <div style={{ ...valueStyle, fontSize: 12 }}>{agent.version || '—'}</div>
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>{tr('ag_public')}</div>
          <div style={{ ...valueStyle, fontSize: 12 }}>{agent.is_public ? 'Yes' : 'No'}</div>
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>{tr('ag_usage_count')}</div>
          <div style={{ ...valueStyle, fontSize: 12 }}>{agent.usage_count ?? 0}</div>
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>{tr('ag_chat_sessions')}</div>
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
          <div style={labelStyle}>{tr('ag_agent_docs_own')}</div>
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
          <div style={labelStyle}>{tr('ag_system_prompt_chars', { count: promptDraft.length })}</div>
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

  // ── Subagents ────────────────────────────────────────────────────────────
  //
  // Editing lives in the shared SubagentsEditor (layout2/editorSubagents.tsx),
  // which AgentEditor renders too — one form, no drift. Here it only reads and
  // writes the JSON draft the editor is already holding.
  const readSubagents = useCallback((): any[] => {
    try {
      const parsed = JSON.parse(jsonEdit);
      // Backend update endpoint persists request.config.subagents; the
      // top-level subagents_config in the GET response is derived from it.
      return Array.isArray(parsed.config?.subagents) ? parsed.config.subagents : [];
    } catch { return []; }
  }, [jsonEdit]);

  const writeSubagents = useCallback((next: any[]) => {
    patchJson(p => {
      if (!p.config) p.config = {};
      p.config.subagents = next;
    });
  }, [patchJson]);

  const renderSubagents = () => (
    <SubagentsEditor
      subagents={readSubagents()}
      onChange={writeSubagents}
      t={t}
      emptyHint="(no subagents — add one above)"
    />
  );

  // ── Middleware section ──
  const renderMiddleware = () => {
    const mw = agent.middleware_config || config.middleware || [];
    if (mw.length === 0) {
      return (
        <div style={{ padding: 4 }}>
          <HitlSection />
          <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic' }}>
            (no other middleware)
          </div>
        </div>
      );
    }
    return (
      <div style={{ padding: 4 }}>
        <HitlSection />
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
          <div style={labelStyle}>{tr('ag_auto_eviction')}</div>
          {toggle(Boolean(g.enable_auto_eviction),
            () => handleGuardrailChange(['enable_auto_eviction'], true),
            () => handleGuardrailChange(['enable_auto_eviction'], false))}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 6 }}>
          <div style={labelStyle}>{tr('ag_summarization')}</div>
          {toggle(Boolean(g.enable_summarization),
            () => handleGuardrailChange(['enable_summarization'], true),
            () => handleGuardrailChange(['enable_summarization'], false))}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 6 }}>
          <div style={labelStyle}>{tr('ag_long_term_memory')}</div>
          {toggle(Boolean(g.long_term_memory),
            () => handleGuardrailChange(['long_term_memory'], true),
            () => handleGuardrailChange(['long_term_memory'], false))}
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>{tr('ag_execution_limit')}</div>
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
          <div style={labelStyle}>{tr('ag_token_limits')}</div>
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
          <div style={labelStyle}>{tr('ag_backend')}</div>
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
        canRun={!!localAgentId && !isNew}
        saveDisabled={false}
        saveMsg={saveMsg}
        statusLabel={`ID: ${localAgentId ?? agent.id ?? '—'} · v${agent.version ?? '?'} · ${agent.category ?? ''}`}
        t={t}
      />

      {/* ── Body: section nav + section content ── */}
      {(!configLoaded || configLoadError) && (
        <div
          style={{
            padding: '6px 12px',
            fontSize: 11,
            background: configLoadError ? 'rgba(239,68,68,0.12)' : t.bgSidebar,
            color: configLoadError ? '#e5484d' : t.textMuted,
            borderBottom: `1px solid ${t.border}`,
          }}
        >
          {configLoadError
            ? `配置载入失败：${configLoadError} —— 下面显示的是草稿，别保存`
            : '正在从服务器载入配置…'}
        </div>
      )}

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
