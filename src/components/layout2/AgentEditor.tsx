/**
 * AgentEditor — structured editor for a normal Agent (use_deepagents=false).
 *
 * Simpler than DeepAgentEditor — no subagents. Middleware is a single
 * section (Human-in-the-loop today); guardrails come from Settings → Agents.
 * Sections:
 *   - Overview   name, description, category, model, temperature, max_tokens
 *   - Prompt     system_prompt (large textarea)
 *   - Tools      native_tools / cli_tools / custom_tools
 *   - JSON       raw config
 */
import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { useLayoutTokens } from './tokens';
import { Award, Info, FileText, Wrench, Code, Shield } from 'lucide-react';
import type { Tab } from './useLayout';
import { useLayoutState } from './useLayout';
import { chatStore } from './chatStore';
import { useAvailableModels } from '../../hooks/useAvailableModels';
import { useAvailableTools } from '../../hooks/useAvailableTools';
import { useAgentDefaults } from '../../hooks/useAgentDefaults';
import apiClient from '../../lib/api-client';
import CodeViewerModal from './CodeViewerModal';
import ChatTestToolbar from './editorChatToolbar';
import JsonEditorSection from './editorJsonSection';
import ToolsPicker, { toToolIdList } from './editorToolsPicker';
import HitlPolicyEditor from './HitlPolicyEditor';
import HandoffPolicyEditor from './HandoffPolicyEditor';
import ToolInspectModal from './ToolInspectModal';
import SkillsPicker from './editorSkillsPicker';
import EditorSectionNav from './editorSectionNav';
import { useProject } from '../../contexts/ProjectContext';

interface AgentEditorProps {
  tab: Tab;
}

type SectionId = 'overview' | 'prompt' | 'tools' | 'skills' | 'middleware' | 'json';

const SECTIONS: { id: SectionId; label: string; icon: React.ReactNode }[] = [
  { id: 'overview', label: 'Overview', icon: <Info size={13} /> },
  { id: 'prompt',   label: 'Prompt',   icon: <FileText size={13} /> },
  { id: 'tools',    label: 'Tools',    icon: <Wrench size={13} /> },
  { id: 'skills',   label: 'Skills',   icon: <Award size={13} /> },
  { id: 'middleware', label: 'Middleware', icon: <Shield size={13} /> },
  { id: 'json',     label: 'JSON',     icon: <Code size={13} /> },
];

export default function AgentEditor({ tab }: AgentEditorProps) {
  const t = useLayoutTokens();
  const { setRightPanelTab, openRightPanel, closeTab } = useLayoutState();
  const agent = tab.data?.agent ?? tab.data ?? {};
  const config = agent.config || {};
  const isNew = agent.new === true || typeof agent.id !== 'number';
  // Active vault (project) — forwarded to createDeepAgent so the agent's
  // identity is baked with the right workspace at creation time.
  const { activeProjectId } = useProject();
  // Also sync it into the chat store so the Run button's chat session
  // (POST /api/chat/start) carries the project binding. Without this, the
  // session is created with project_id=NULL and the workspace resolver
  // falls back to the legacy default even though the agent's identity
  // block is correct.
  useEffect(() => {
    chatStore.setCurrentProjectId(activeProjectId ?? null);
  }, [activeProjectId]);
  const { cloudModels, localModels, isLoading: modelsLoading } = useAvailableModels({ includeLocal: true });
  // Create-time limits from Settings → Agents (PostgreSQL): a new standard agent
  // starts from the team's numbers rather than an empty guardrails object.
  const { agent: agentDefaults } = useAgentDefaults();
  const agentGuardrails = useMemo(() => (agentDefaults ? {
    enable_auto_eviction: agentDefaults.enable_auto_eviction,
    enable_summarization: agentDefaults.enable_summarization,
    token_limits: {
      max_total_tokens: agentDefaults.max_total_tokens,
      eviction_threshold: agentDefaults.eviction_threshold,
      summarization_threshold: agentDefaults.summarization_threshold,
      keep_last_messages: agentDefaults.keep_last_messages,
    },
  } : {}), [agentDefaults]);
  const defaultRecursionLimit = agentDefaults?.recursion_limit ?? null;
  // Models the reader can use for the vision step (catalog `capabilities.vision`).
  const visionCapableModels = (cloudModels || [])
    .filter((m: any) => m?.capabilities?.vision)
    .map((m: any) => ({ id: m.id, name: m.name || m.id }));
  const [activeSection, setActiveSection] = useState<SectionId>('overview');
  const [testPrompt, setTestPrompt] = useState('Hello, please introduce yourself.');
  const [running, setRunning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);
  // An existing agent is loaded from the server before anything is rendered:
  // the tab's snapshot is whatever the tab was created with, and editing it
  // silently wrote stale config back (the handoff steps came out as step_1
  // while the server held sales/support). A new agent has no server copy yet, so
  // it starts from the draft.
  // Ids arrive as numbers from most openers but as strings from a few (quick
  // picker, older tabs), and `typeof === 'number'` silently treated those as a
  // brand-new agent — no fetch, no banner, edits saved over the server copy.
  const _agentIdNum = Number(agent.id);
  const _hasId = Number.isFinite(_agentIdNum) && _agentIdNum > 0;
  const [jsonEdit, setJsonEdit] = useState(() =>
    _hasId ? '{}' : JSON.stringify(agent, null, 2),
  );
  const [configLoaded, setConfigLoaded] = useState(!_hasId);
  const [configLoadError, setConfigLoadError] = useState<string | null>(null);
  // Bumped on every successful load; the handoff editor resets its draft on change.
  const [configRev, setConfigRev] = useState(0);
  // Live view of jsonEdit — the tool-inspect modal reads tool_params from
  // here (the immutable `agent` prop would show the stale pre-save value
  // until a reload). Mirrors DeepAgentEditor's live/liveConfig.
  const live = useMemo(() => {
    try { return JSON.parse(jsonEdit) || {}; } catch { return agent || {}; }
  }, [jsonEdit]); // eslint-disable-line react-hooks/exhaustive-deps
  const liveConfig = live.config || {};
  // Tabs persist their `data.agent` snapshot (Workspace restores them), so a
  // reopened tab can show the config as it was when the tab was created — edits
  // made elsewhere (another tab, the API, a restore) are invisible, and saving
  // then writes the stale copy back. Pull the agent fresh on open.
  useEffect(() => {
    const id = _hasId ? _agentIdNum : null;
    if (!id) return;
    let cancelled = false;
    apiClient.getDeepAgent(id)
      .then(res => {
        if (cancelled) return;
        if (!res?.data) {
          setConfigLoadError('服务器没有返回配置');
          return;
        }
        const loaded = res.data;
        setJsonEdit(JSON.stringify(loaded, null, 2));
        const cfg = loaded.config || {};
        setEditableName(loaded.name || '');
        setEditableDesc(loaded.description || '');
        setEditableCategory(loaded.category || 'general');
        setEditableModel(cfg.model || '');
        setEditableTemp(cfg.temperature ?? 0.7);
        setEditableMaxTokens(cfg.max_tokens ?? '');
        setEditablePrompt(cfg.system_prompt || '');
        setSelectedNativeTools(toToolIdList(cfg.native_tools));
        setSelectedCustomTools(toToolIdList(cfg.custom_tools));
        setSelectedSkills(cfg.skills || []);
        setConfigLoadError(null);
        setConfigLoaded(true);
        setConfigRev(v => v + 1);
      })
      .catch((err: any) => {
        if (cancelled) return;
        setConfigLoadError(err?.message || '载入失败');
        setConfigLoaded(true); // let the editor open, but say it is a draft
      });
    return () => { cancelled = true; };
  }, [_hasId, _agentIdNum]); // eslint-disable-line react-hooks/exhaustive-deps

  // Always-current mirror of jsonEdit — lets async handlers (e.g. the tool
  // inspect modal's Save -> main save) read the latest JSON after a state
  // flush instead of a stale render closure.
  const jsonEditRef = useRef(jsonEdit);
  useEffect(() => { jsonEditRef.current = jsonEdit; }, [jsonEdit]);
  // Tool card click -> inspect/edit panel (per-agent tool_params, e.g. database)
  const [inspectTool, setInspectTool] = useState<{ id: string; name: string; description: string } | null>(null);
  // ── Middleware → Human-in-the-loop ──
  // LangChain configures review with
  //   middleware=[HumanInTheLoopMiddleware(interrupt_on={...},
  //                                        description_prefix="...")]
  // so that is exactly what this editor writes: config.middleware carries a
  // {"type": "hitl"} entry whose interrupt_on is the documented mapping.
  // (guardrails.interrupts still exists in old agent configs; the backend
  // reads it as a fallback, it is no longer written here.)
  const middlewareList = useMemo<Record<string, any>[]>(() => {
    const raw = (liveConfig as any).middleware ?? (liveConfig as any).config?.middleware;
    return Array.isArray(raw) ? raw : [];
  }, [liveConfig]); // eslint-disable-line react-hooks/exhaustive-deps

  const hitlMiddleware = useMemo(() => {
    const mw = middlewareList;
    if (!Array.isArray(mw)) return undefined;
    return mw.find((m: any) => m && (m.type === 'hitl' || m.type === 'human_in_the_loop'));
  }, [middlewareList]);
  // The API model keeps only `type` / `enabled` / `config`, so the policy lives
  // under config.* — top-level interrupt_on would be dropped on save.
  const hitlConfig = (hitlMiddleware?.config ?? {}) as Record<string, any>;
  const interruptOn = (hitlConfig.interrupt_on
    ?? hitlMiddleware?.interrupt_on) as Record<string, any> | undefined;
  const descriptionPrefix: string =
    hitlConfig.description_prefix || hitlMiddleware?.description_prefix
    || 'Tool execution pending approval';

  // Handoff middleware: step graph + transfer edges, written as one more
  // `{"type": "handoff"}` entry in the same middleware list.
  const handoffMiddleware = useMemo(
    () => middlewareList.find((m: any) => m && (m.type === 'handoff' || m.type === 'handoffs')),
    [middlewareList],
  );
  const handoffConfig = (handoffMiddleware?.config ?? {}) as any;

  const writeHandoff = (next: any) => {
    let parsed: any;
    try { parsed = JSON.parse(jsonEditRef.current); } catch { parsed = { ...agent }; }
    if (!parsed.config) parsed.config = {};
    const mw: any[] = Array.isArray(parsed.config.middleware) ? parsed.config.middleware : [];
    const rest = mw.filter(m => !(m && (m.type === 'handoff' || m.type === 'handoffs')));
    const hasSteps = next && next.steps && Object.keys(next.steps).length > 0;
    if (hasSteps) {
      rest.push({ type: 'handoff', enabled: true, config: next });
    }
    parsed.config.middleware = rest;
    // The API also returns `middleware_config` (a mirror of config.middleware).
    // Patching only the config made the JSON tab show two disagreeing copies.
    parsed.middleware_config = JSON.parse(JSON.stringify(rest));
    setJsonEdit(JSON.stringify(parsed, null, 2));
  };

  const writeHitl = (
    next: Record<string, any>,
    prefix: string = descriptionPrefix,
  ) => {
    let parsed: any;
    try { parsed = JSON.parse(jsonEditRef.current); } catch { parsed = { ...agent }; }
    if (!parsed.config) parsed.config = {};
    const mw: any[] = Array.isArray(parsed.config.middleware) ? parsed.config.middleware : [];
    const rest = mw.filter(m => !(m && (m.type === 'hitl' || m.type === 'human_in_the_loop')));
    if (Object.keys(next).length > 0) {
      rest.push({ type: 'hitl', enabled: true, config: { interrupt_on: next, description_prefix: prefix } });
    }
    parsed.config.middleware = rest;
    // The API also returns `middleware_config` (a mirror of config.middleware).
    // Patching only the config made the JSON tab show two disagreeing copies.
    parsed.middleware_config = JSON.parse(JSON.stringify(rest));
    setJsonEdit(JSON.stringify(parsed, null, 2));
  };

  // ── Editable fields (synced to jsonEdit for Save) ──
  // For new agents, provide sensible defaults — user can tweak later
  const [editableName, setEditableName] = useState(agent.name || '');
  const [editableDesc, setEditableDesc] = useState(agent.description || '');
  const [editableCategory, setEditableCategory] = useState(agent.category || 'general');
  const [editableModel, setEditableModel] = useState(config.model || '');
  const [editableTemp, setEditableTemp] = useState(config.temperature ?? 0.7);
  // User-defined workspace path (persisted in PostgreSQL; empty → default)
  const [workspacePath, setWorkspacePath] = useState<string>(agent.workspace_path || '');
  // Agent instruction docs (AGENTS.md / CLAUDE.md …)
  const [docsDraft, setDocsDraft] = useState<Record<string, string>>(() => ({
    ...((agent.agent_docs as Record<string, string>) || {}),
  }));
  const [docsSaving, setDocsSaving] = useState(false);
  const [docsMsg, setDocsMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [editableMaxTokens, setEditableMaxTokens] = useState(config.max_tokens ?? (isNew ? 4096 : ''));
  const [editablePrompt, setEditablePrompt] = useState(
    config.system_prompt || (isNew
      ? 'You are a helpful AI assistant. Be concise and accurate. When you are unsure, admit it rather than guessing.'
      : '')
  );

  // ── Skills state ──
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

  const toggleSkill = useCallback((skillId: string) => {
    setSelectedSkills(prev =>
      prev.includes(skillId) ? prev.filter(s => s !== skillId) : [...prev, skillId]
    );
  }, []);

  // ── Tools state ──
  const { isLoading: toolsLoading, groupedByCategory, defaultToolIds } = useAvailableTools();
  const [availableCustomTools, setAvailableCustomTools] = useState<
    { id: number; tool_id: string; name: string; description: string }[]
  >([]);
  // The selection IS the tool set. `native_tools: []` means no tools — the backend
  // stores exactly this list, so the panel and the row can no longer disagree.
  //
  // A new agent pre-ticks the universal base: that is a convenience of the editor
  // (untick anything you do not want), not a rule the server applies afterwards.
  const [selectedNativeTools, setSelectedNativeTools] = useState<string[]>(
    () => toToolIdList(config.native_tools));
  // True once the user has ticked, unticked, cleared or filled the list by hand.
  // Without it the pre-tick effect keeps restoring the template after a deliberate
  // "clear all" (it re-runs whenever defaultToolIds arrive).
  const [toolsTouched, setToolsTouched] = useState(false);
  useEffect(() => {
    // NEW agent only: offer the universal base pre-ticked so the user can untick
    // what they do not want. An EXISTING agent shows exactly what is stored — an
    // agent saved with no tools must open with nothing ticked, or the next save
    // would quietly hand it the base back.
    //
    // Only fills an untouched draft: once the user has clicked anything (even to
    // clear the list) `toolsTouched` stops this effect from re-adding everything.
    if (isNew && !toolsTouched && defaultToolIds.length && selectedNativeTools.length === 0) {
      setSelectedNativeTools(defaultToolIds);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaultToolIds, isNew, toolsTouched]);
  const [selectedCustomTools, setSelectedCustomTools] = useState<string[]>(toToolIdList(config.custom_tools));
  const [showAllTools, setShowAllTools] = useState(true);

  // Reset all editable state when tab changes to a different agent
  // (React reuses the component instance, so useState init values are stale)
  useEffect(() => {
    setEditableName(agent.name || '');
    setEditableDesc(agent.description || '');
    setEditableCategory(agent.category || 'general');
    setEditableModel(config.model || '');
    setEditableTemp(config.temperature ?? 0.7);
    setEditableMaxTokens(config.max_tokens ?? (isNew ? 4096 : ''));
    setEditablePrompt(
      config.system_prompt || (isNew
        ? 'You are a helpful AI assistant. Be concise and accurate. When you are unsure, admit it rather than guessing.'
        : '')
    );
    // jsonEdit belongs to the server fetch for an existing agent. Writing the tab
    // snapshot here raced with that fetch and won, so the editor showed (and
    // would save) the snapshot while the server held the real config.
    if (isNew) setJsonEdit(JSON.stringify(agent, null, 2));
    setLocalAgentId(typeof agent.id === 'number' ? agent.id : Number(agent.id) || null);
    // Stored list only — an existing agent with [] stays []. (The default base is
    // offered only for a brand-new agent, in the effect above.)
    setSelectedNativeTools(toToolIdList(config.native_tools));
    setToolsTouched(false);       // switching agents resets the draft
    setSelectedCustomTools(toToolIdList(config.custom_tools));
    setSelectedSkills(config.skills || []);
    setActiveSection('overview');
    setSaveMsg(null);
  }, [tab.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch custom tools list for the tool picker
  useEffect(() => {
    let cancelled = false;
    apiClient.listCustomTools().then((res: any) => {
      if (!cancelled && res?.data) setAvailableCustomTools(res.data);
    }).catch(() => {/* custom tools are optional */});
    return () => { cancelled = true; };
  }, []);

  // Toggle helpers
  const toggleNativeTool = useCallback((toolId: string) => {
    setToolsTouched(true);          // a click beats the pre-ticked template
    setSelectedNativeTools(prev =>
      prev.includes(toolId) ? prev.filter(t => t !== toolId) : [...prev, toolId]
    );
  }, []);
  // One click to build a tool-less agent, instead of unticking 28 boxes.
  const clearNativeTools = useCallback(() => {
    setToolsTouched(true);
    setSelectedNativeTools([]);
  }, []);
  const selectAllNativeTools = useCallback(() => {
    setToolsTouched(true);
    setSelectedNativeTools(defaultToolIds);
  }, [defaultToolIds]);
  const toggleCustomTool = useCallback((toolId: string) => {
    setSelectedCustomTools(prev =>
      prev.includes(toolId) ? prev.filter(t => t !== toolId) : [...prev, toolId]
    );
  }, []);

  // For new agents, fetch default model from settings (describe → models ns)
  useEffect(() => {
    if (!isNew || config.model) return;
    let cancelled = false;
    apiClient.describeSettings().then((res: any) => {
      const ns = (res?.data?.namespaces || []).find((n: any) => n.ns === 'models');
      const model = ns?.value?.default_model;
      if (!cancelled && model) {
        setEditableModel(model);
      }
    }).catch(() => {
      // Fallback: try localStorage cache
      const cached = localStorage.getItem('langconfig.defaultModel');
      if (!cancelled && cached) setEditableModel(cached);
    });
    return () => { cancelled = true; };
  }, [isNew]);

  /** Update a top-level field in jsonEdit */
  const updateTopField = useCallback((key: string, value: string) => {
    setJsonEdit(prev => {
      try {
        const parsed = JSON.parse(prev);
        parsed[key] = value || null;
        if (!parsed[key]) delete parsed[key];
        return JSON.stringify(parsed, null, 2);
      } catch { return prev; }
    });
  }, []);

  /** Update a config-level field in jsonEdit */
  const updateConfigField = useCallback((key: string, value: any) => {
    setJsonEdit(prev => {
      try {
        const parsed = JSON.parse(prev);
        if (!parsed.config) parsed.config = {};
        parsed.config[key] = value;
        if (parsed.config[key] === null || parsed.config[key] === '' || parsed.config[key] === undefined) {
          delete parsed.config[key];
        }
        return JSON.stringify(parsed, null, 2);
      } catch { return prev; }
    });
  }, []);

  // Track the persisted agent id locally — updated after first save for new agents
  const [localAgentId, setLocalAgentId] = useState<number | null>(
    typeof agent.id === 'number' ? agent.id : null
  );

  const handleRun = async () => {
    if (!localAgentId || running) return;
    setRunning(true);

    // Open the right-sidebar chat panel
    setRightPanelTab('chat');
    openRightPanel('');

    // Start a chat session and send the test prompt
    const prompt = testPrompt || 'Hello, please introduce yourself.';
    try {
      const msgId = await chatStore.sendStreamMessage(localAgentId, prompt, agent.name);
      if (!msgId) {
        console.error('[AgentEditor] sendStreamMessage failed');
      }
    } catch (err: any) {
      console.error('[AgentEditor] Run error:', err);
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
      console.error('[AgentEditor] View code error:', err);
      setSaveMsg({ ok: false, text: 'Failed to load code' });
    }
  };

  // After a .langconfig import, point the editor at the imported agent.
  const handleImported = useCallback((imported: any) => {
    if (!imported?.id) return;
    setLocalAgentId(typeof imported.id === 'number' ? imported.id : null);
    setJsonEdit(JSON.stringify(imported, null, 2));
    // Sync ALL editable fields with the imported config — not just the
    // JSON view. The Overview + Prompt tabs read editableName / editableDesc
    // / editablePrompt / editableModel / editableTemp / editableMaxTokens,
    // so without this they keep whatever the editor was initialized with
    // (often the one-sentence default) while the JSON tab shows the real
    // imported values.
    const c = imported.config || {};
    setEditableName(imported.name || '');
    setEditableDesc(imported.description || '');
    setEditableCategory(imported.category || 'general');
    setEditableModel(c.model || '');
    setEditableTemp(typeof c.temperature === 'number' ? c.temperature : 0.7);
    setEditableMaxTokens(c.max_tokens ?? (isNew ? 4096 : ''));
    setEditablePrompt(c.system_prompt || '');
    setSelectedNativeTools(toToolIdList(c.native_tools));
    setSelectedCustomTools(toToolIdList(c.custom_tools));
    setSelectedSkills(Array.isArray(c.skills) ? c.skills : []);
    setActiveSection('json');
    setSaveMsg({ ok: true, text: `Imported as "${imported.name}"` });
    setTimeout(() => setSaveMsg(null), 4000);
  }, [setLocalAgentId, setJsonEdit, setEditableName, setEditableDesc, setEditableCategory, setEditableModel, setEditableTemp, setEditableMaxTokens, setEditablePrompt, setSelectedNativeTools, setSelectedCustomTools, setSelectedSkills, setActiveSection, setSaveMsg, isNew]);

  /** Two-step destructive delete: first confirm irreversibility, then a
   *  second hard confirm before the API call. On success, close the tab.
   *  The editor is an Agent (use_deepagents=false) but shares the same
   *  deep_agent_templates table, so the same DELETE endpoint applies. */
  const handleDelete = async () => {
    const id = localAgentId;
    const name = agent.name || `Agent ${id ?? '?'}`;
    if (!id) return;
    const step1 = window.confirm(
      `Delete agent "${name}" (id=${id})? Its chat sessions and workspace ` +
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
      // Close the editor tab after a short delay so the message is visible.
      window.setTimeout(() => closeTab(tab.id), 400);
    } catch (err: any) {
      console.error('[AgentEditor] Delete error:', err);
      setSaveMsg({
        ok: false,
        text: `Delete failed: ${err?.response?.data?.detail ?? err?.message ?? 'unknown error'}`,
      });
    } finally {
      setSaving(false);
    }
  };

  const handleSave = async () => {
    if (saving) return;

    // ── Validate required fields ──
    const trimmedName = editableName.trim();
    const trimmedPrompt = editablePrompt.trim();
    if (!trimmedName) {
      setSaveMsg({ ok: false, text: 'Name is required' });
      return;
    }
    if (!trimmedPrompt) {
      setSaveMsg({ ok: false, text: 'System prompt is required' });
      return;
    }

    setSaving(true);
    setSaveMsg(null);
    try {
      if (!configLoaded) {
        setSaveMsg({ ok: false, text: '正在从服务器载入配置，稍后再保存' });
        setSaving(false);
        return;
      }
      let payload: any;
      try {
        payload = JSON.parse(jsonEditRef.current);
      } catch {
        setSaveMsg({ ok: false, text: 'Invalid JSON — fix errors and try again' });
        setSaving(false);
        return;
      }

      // Build a complete config from editable fields, merged with any JSON-tab overrides
      const jsonConfig = payload.config || {};
      const fullConfig = {
        // Defaults for normal agents
        cli_tools: [],
        tools: [],
        subagents: [],
        backend: { type: 'state' },
        // Guardrails + step budget come from Settings → Agents for a new agent;
        // the JSON tab still wins (spread below) if the user edited them there.
        recursion_limit: defaultRecursionLimit,
        use_deepagents: false,
        // JSON-tab overrides
        ...jsonConfig,
        middleware: Array.isArray((jsonConfig as any).middleware)
          ? (jsonConfig as any).middleware
          : [],
        // Guardrails merge instead of replace: the JSON tab writes only what it
        // shows, and a bare `{"guardrails": {"interrupts": ...}}` used to wipe
        // the team's token limits and summarization flags on save.
        guardrails: {
          ...agentGuardrails,
          ...(jsonConfig.guardrails || {}),
          token_limits: {
            ...(agentGuardrails.token_limits || {}),
            ...((jsonConfig.guardrails || {}).token_limits || {}),
          },
        },
        // Tool picker always wins over JSON tab for tool selection
        native_tools: selectedNativeTools,
        custom_tools: selectedCustomTools,
        // Skill picker always wins over JSON tab for skill selection
        skills: selectedSkills,
        // Form fields always win — the UI is the source of truth
        system_prompt: trimmedPrompt,
        model: editableModel || null,
        temperature: editableTemp,
        max_tokens: editableMaxTokens ? parseInt(String(editableMaxTokens), 10) : null,
      };

      if (localAgentId) {
        await apiClient.updateDeepAgent(localAgentId, {
          name: trimmedName,
          description: editableDesc.trim() || null,
          category: editableCategory,
          config: fullConfig,
          workspace_path: workspacePath.trim() || null,
          agent_docs: docsDraft,
        });
      } else {
        const res = await apiClient.createDeepAgent({
          name: trimmedName,
          description: editableDesc.trim() || undefined,
          category: editableCategory,
          config: fullConfig,
          workspace_path: workspacePath.trim() || undefined,
          agent_docs: docsDraft,
          project_id: activeProjectId ?? undefined,
        });
        const newAgent = res.data;
        setLocalAgentId(newAgent.id);
        setJsonEdit(JSON.stringify(newAgent, null, 2));
      }

      setSaveMsg({ ok: true, text: 'Saved successfully' });
      setTimeout(() => setSaveMsg(null), 3000);
    } catch (err: any) {
      const raw = err?.response?.data?.detail ?? err?.message ?? 'unknown error';
      const detail = typeof raw === 'string' ? raw : JSON.stringify(raw);
      setSaveMsg({ ok: false, text: `Save failed: ${detail}` });
    } finally {
      setSaving(false);
    }
  };

  // Reusable compact card style
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
  const inputStyle: React.CSSProperties = {
    width: '100%',
    height: 28,
    padding: '0 6px',
    background: t.bgContent,
    border: `1px solid ${t.border}`,
    borderRadius: 3,
    color: t.textPrimary,
    fontSize: 12,
    outline: 'none',
    boxSizing: 'border-box',
  };

  // ── Overview section (all fields editable) ──
  const renderOverview = () => (
    <div style={{ padding: 4 }}>
      <div style={compactCardStyle}>
        <div style={labelStyle}>Name</div>
        <input
          value={editableName}
          onChange={e => { setEditableName(e.target.value); updateTopField('name', e.target.value); }}
          style={inputStyle}
        />
      </div>
      <div style={compactCardStyle}>
        <div style={labelStyle}>Description</div>
        <input
          value={editableDesc}
          onChange={e => { setEditableDesc(e.target.value); updateTopField('description', e.target.value); }}
          style={inputStyle}
        />
      </div>
      {/* Workspace path — user-defined per-agent directory (PostgreSQL) */}
      <div style={compactCardStyle}>
        <div style={labelStyle}>Workspace Path (optional)</div>
        <input
          value={workspacePath}
          onChange={e => setWorkspacePath(e.target.value)}
          placeholder="e.g. outputs/projects/my-vault/agents/my-agent (empty = default)"
          style={inputStyle}
        />
        <div style={{ fontSize: 10, color: t.textMuted, marginTop: 3 }}>
          Uploads + generated files live here (absolute, or relative to the active vault).
        </div>
      </div>
      {/* Agent docs (AGENTS.md / CLAUDE.md — this agent only) */}
      <div style={compactCardStyle}>
        <div style={labelStyle}>Agent Docs (AGENTS.md / CLAUDE.md)</div>
        {['AGENTS.md', 'CLAUDE.md'].map(name => (
          <div key={name} style={{ marginBottom: 6 }}>
            <div style={{ fontSize: 10, color: t.textMuted, marginBottom: 2 }}>{name}</div>
            <textarea
              value={docsDraft[name] ?? ''}
              onChange={e => setDocsDraft(prev => ({ ...prev, [name]: e.target.value }))}
              placeholder={`Instructions specific to ${editableName || 'this agent'}…`}
              spellCheck={false}
              style={{ ...inputStyle, minHeight: 90, fontFamily: 'ui-monospace, Menlo, monospace', resize: 'vertical' }}
            />
          </div>
        ))}
        <div style={{ fontSize: 10, color: t.textMuted }}>
          Saved with the agent (PostgreSQL); written to the workspace on each chat run.
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
        <div style={compactCardStyle}>
          <div style={labelStyle}>Category</div>
          <select
            value={editableCategory}
            onChange={e => { setEditableCategory(e.target.value); updateTopField('category', e.target.value); }}
            style={inputStyle}
          >
            {['research', 'coding', 'analysis', 'general', 'custom'].map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>Model</div>
          <select
            value={editableModel}
            onChange={e => { setEditableModel(e.target.value); updateConfigField('model', e.target.value || null); }}
            disabled={modelsLoading}
            style={{ ...inputStyle, fontFamily: 'monospace' }}
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
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <input
              type="range"
              min={0}
              max={2}
              step={0.1}
              value={editableTemp}
              onChange={e => { const v = parseFloat(e.target.value); setEditableTemp(v); updateConfigField('temperature', v); }}
              style={{ flex: 1, accentColor: t.accent }}
            />
            <span style={{ ...valueStyle, fontFamily: 'monospace', minWidth: 24, fontSize: 11 }}>{editableTemp.toFixed(1)}</span>
          </div>
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>Max Tokens</div>
          <input
            type="number"
            value={editableMaxTokens}
            onChange={e => { const v = e.target.value; setEditableMaxTokens(v); updateConfigField('max_tokens', v ? parseInt(v, 10) : null); }}
            placeholder="Unlimited"
            style={{ ...inputStyle, fontFamily: 'monospace' }}
            min={0}
          />
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>Recursion Limit</div>
          <input
            type="number"
            value={config.recursion_limit ?? ''}
            onChange={e => updateConfigField(
              'recursion_limit', e.target.value === '' ? null : parseInt(e.target.value, 10))}
            placeholder="Team default (1000)"
            style={{ ...inputStyle, fontFamily: 'monospace' }}
            min={1}
          />
          {/* Steps, not turns: measured ~30 LangGraph steps per tool turn for a
              standard agent, so 1000 is roughly 30 tool calls. */}
          <div style={{ fontSize: 10, color: t.textMuted, marginTop: 4, lineHeight: '14px' }}>
            Maximum LangGraph steps in one run — a standard agent spends ~30 of
            them per tool turn, so the 1000 default is about 30 tool calls. Leave
            empty to use the team-wide setting.
          </div>
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>Version</div>
          <div style={valueStyle}>{agent.version || '—'}</div>
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>Public</div>
          <div style={valueStyle}>{agent.is_public ? 'Yes' : 'No'}</div>
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>Usage Count</div>
          <div style={valueStyle}>{agent.usage_count ?? 0}</div>
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>Chat Sessions</div>
          <div style={valueStyle}>{agent.chat_sessions_count ?? 0}</div>
        </div>
      </div>
    </div>
  );

  // ── System prompt section (editable textarea) ──
  const renderPrompt = () => (
    <div style={{ padding: 4, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ ...cardStyle, flex: 1, display: 'flex', flexDirection: 'column' }}>
        <div style={labelStyle}>System Prompt ({editablePrompt.length} chars)</div>
        <textarea
          value={editablePrompt}
          onChange={e => { setEditablePrompt(e.target.value); updateConfigField('system_prompt', e.target.value); }}
          spellCheck={false}
          placeholder="Instructions that define the agent's behavior..."
          style={{
            flex: 1,
            width: '100%',
            background: t.bgContent,
            border: `1px solid ${t.border}`,
            borderRadius: 4,
            padding: 10,
            fontFamily: '"SF Mono", "Fira Code", monospace',
            fontSize: 12,
            color: t.textPrimary,
            lineHeight: 1.5,
            resize: 'vertical',
            outline: 'none',
            minHeight: 120,
            boxSizing: 'border-box',
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

  const sections: Record<SectionId, () => React.ReactNode> = {
    overview: renderOverview,
    prompt:   renderPrompt,
    tools:    () => (
      <ToolsPicker
        selectedNativeTools={selectedNativeTools}
        selectedCustomTools={selectedCustomTools}
        onToggleNative={toggleNativeTool}
        onClearNative={clearNativeTools}
        onSelectAllNative={selectAllNativeTools}
        onToggleCustom={toggleCustomTool}
        showAllTools={showAllTools}
        onShowAllChange={setShowAllTools}
        toolsLoading={toolsLoading}
        groupedByCategory={groupedByCategory}
        availableCustomTools={availableCustomTools}
        onInspect={setInspectTool}
        toolParams={liveConfig.tool_params}
        onToolParamsChange={(toolId, params) => {
          // Persist per-agent tool params (hard-pinned at build time).
          const next = { ...(liveConfig.tool_params || {}) };
          if (params && Object.keys(params).length > 0) next[toolId] = params;
          else delete next[toolId];
          updateConfigField('tool_params', Object.keys(next).length > 0 ? next : null);
        }}
        visionModels={visionCapableModels}
        t={t}
      />
    ),
    skills:   renderSkills,
    middleware: () => (
      <div style={{ padding: 4 }}>
        <HitlPolicyEditor
          value={interruptOn}
          onChange={next => writeHitl(next)}
          candidateTools={[...selectedNativeTools, ...selectedCustomTools]}
          t={t}
        />
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4 }}>description_prefix</div>
          <input
            value={descriptionPrefix}
            onChange={e => writeHitl(interruptOn || {}, e.target.value)}
            style={{
              width: '100%', boxSizing: 'border-box', padding: '6px 8px', fontSize: 11,
              fontFamily: 'monospace', background: t.bgContent, color: t.textPrimary,
              border: `1px solid ${t.border}`, borderRadius: 4, outline: 'none',
            }}
          />
          <div style={{ fontSize: 10, color: t.textMuted, marginTop: 4, lineHeight: '15px' }}>
            打断信息的前缀，和工具名、参数一起组成提示。保存后开新聊天生效。
          </div>
        </div>
        <HandoffPolicyEditor
          value={handoffConfig}
          resetKey={`${agent.id ?? 'new'}:${configRev}`}
          onChange={writeHandoff}
          candidateTools={[...selectedNativeTools, ...selectedCustomTools]}
          t={t}
        />
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 6 }}>
          {handoffMiddleware && (
            <button
              onClick={() => writeHandoff({})}
              style={{
                padding: '2px 8px', borderRadius: 10, cursor: 'pointer',
                border: `1px solid ${t.border}`, background: 'transparent',
                color: t.textMuted, fontSize: 10,
              }}
            >
              移除转交配置
            </button>
          )}
        </div>
      </div>
    ),
    json:     () => <JsonEditorSection value={jsonEdit} onChange={setJsonEdit} t={t} />,
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
        canRun={!!localAgentId}
        saveDisabled={false}
        saveMsg={saveMsg}
        statusLabel={`ID: ${agent.id ?? '—'} · v${agent.version ?? '?'} · ${agent.category ?? ''}`}
        agentId={localAgentId}
        agentName={agent.name}
        onImported={handleImported}
        onDelete={handleDelete}
        t={t}
      />

      {/* ── Body: section nav + section content ── */}
      {(!configLoaded || configLoadError) && (
        <div
          style={{
            padding: '6px 12px',
            fontSize: 11,
            background: configLoadError ? 'rgba(239,68,68,0.12)' : 'var(--color-background-light)',
            color: configLoadError ? '#e5484d' : 'var(--color-text-muted)',
            borderBottom: '1px solid var(--color-border-dark)',
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
            // Build the updated payload synchronously from the CURRENT jsonEdit
            // and write BOTH state and ref — handleSave below must not read a
            // stale ref (the useEffect that syncs the ref runs after commit,
            // racing the setTimeout below).
            let updated: any = null;
            try {
              updated = JSON.parse(jsonEdit);
              if (!updated.config) updated.config = {};
              if (!updated.config.tool_params) updated.config.tool_params = {};
              updated.config.tool_params[toolId] = params;
            } catch { /* invalid JSON — leave updated null */ }
            if (updated) {
              const json = JSON.stringify(updated, null, 2);
              setJsonEdit(json);
              jsonEditRef.current = json;
              if (localAgentId) {
                setTimeout(() => { handleSave(); }, 0);
              } else {
                setSaveMsg({ ok: true, text: `Tool params saved for ${toolId} (draft — click Save to create the agent)` });
                setTimeout(() => setSaveMsg(null), 3000);
              }
            } else {
              setSaveMsg({ ok: false, text: 'Invalid JSON — tool params not saved' });
              setTimeout(() => setSaveMsg(null), 3000);
            }
            setInspectTool(null);
          }}
          t={t}
        />
      )}
    </div>
  );
}
