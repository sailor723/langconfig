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
import { useState, useCallback, useEffect } from 'react';
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
import SkillsPicker from './editorSkillsPicker';
import EditorSectionNav from './editorSectionNav';

interface DeepAgentEditorProps {
  tab: Tab;
}

type SectionId = _SectionId;

export default function DeepAgentEditor({ tab }: DeepAgentEditorProps) {
  const t = useLayoutTokens();
  const { setRightPanelTab, openRightPanel } = useLayoutState();
  const agent = tab.data?.agent ?? tab.data ?? {};
  const config = agent.config || {};
  const { cloudModels, localModels, isLoading: modelsLoading } = useAvailableModels({ includeLocal: true });
  const [activeSection, setActiveSection] = useState<SectionId>('overview');
  const [expandedSubs, setExpandedSubs] = useState<Record<number, boolean>>({});
  const [testPrompt, setTestPrompt] = useState('Hello, please introduce yourself.');
  const [running, setRunning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);
  // Editable JSON text for the JSON tab
  const [jsonEdit, setJsonEdit] = useState(() => JSON.stringify(agent, null, 2));
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

  // Editable model — synced from config, falls back to stored default
  const [editableModel, setEditableModel] = useState(config.model || localStorage.getItem('langconfig.defaultModel') || '');

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
  const { isLoading: toolsLoading, groupedByCategory } = useAvailableTools();
  const [availableCustomTools, setAvailableCustomTools] = useState<
    { id: number; tool_id: string; name: string; description: string }[]
  >([]);
  const [selectedNativeTools, setSelectedNativeTools] = useState<string[]>(toToolIdList(config.native_tools));
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
    // Sync tool + skill pickers with the imported config.
    const c = imported.config || {};
    setSelectedNativeTools(toToolIdList(c.native_tools));
    setSelectedCustomTools(toToolIdList(c.custom_tools));
    setSelectedSkills(Array.isArray(c.skills) ? c.skills : []);
    setActiveSection('json');
    setSaveMsg({ ok: true, text: `Imported as "${imported.name}"` });
    setTimeout(() => setSaveMsg(null), 4000);
  }, [setLocalAgentId, setJsonEdit, setSelectedNativeTools, setSelectedCustomTools, setSelectedSkills, setActiveSection, setSaveMsg]);

  /** Parse the JSON textarea and PUT the updated agent back to the backend */
  const handleSave = async () => {
    if (saving) return;
    setSaving(true);
    setSaveMsg(null);
    try {
      let payload: any;
      try {
        payload = JSON.parse(jsonEdit);
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

  // ── Overview section ──
  const renderOverview = () => (
    <div style={{ padding: 4 }}>
      <div style={compactCardStyle}>
        <div style={labelStyle}>Name</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ ...valueStyle, fontSize: 18, fontWeight: 600 }}>{agent.name || '—'}</span>
          {localAgentId && (
            <span style={{
              fontSize: 11, color: t.textMuted, fontFamily: 'monospace',
              background: t.bgHover, padding: '1px 6px', borderRadius: 3,
              border: `1px solid ${t.border}`,
            }}>
              #{agent.id}
            </span>
          )}
        </div>
      </div>
      <div style={compactCardStyle}>
        <div style={labelStyle}>Description</div>
        <div style={valueStyle}>{agent.description || '—'}</div>
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
          <div style={{ ...valueStyle, fontSize: 12 }}>{config.temperature ?? '—'}</div>
        </div>
        <div style={compactCardStyle}>
          <div style={labelStyle}>Max Tokens</div>
          <div style={{ ...valueStyle, fontSize: 12 }}>{config.max_tokens ?? '—'}</div>
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

  // ── System prompt section ──
  const renderPrompt = () => (
    <div style={{ padding: 4 }}>
      <div style={cardStyle}>
        <div style={labelStyle}>System Prompt ({config.system_prompt?.length ?? 0} chars)</div>
        <pre style={{
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          fontFamily: '"SF Mono", "Fira Code", monospace',
          fontSize: 12,
          color: t.textPrimary,
          lineHeight: 1.5,
          margin: 0,
        }}>
          {config.system_prompt || '(empty)'}
        </pre>
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

  // ── Subagents section ──
  const renderSubagents = () => {
    // Try multiple data locations (DB-level, normalized config, etc.)
    const subs =
      agent.subagents ||
      agent.subagents_config ||
      agent.config?.subagents ||
      [];
    if (subs.length === 0) {
      return (
        <div style={{ padding: 4 }}>
          <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic' }}>(no subagents / skills)</div>
        </div>
      );
    }
    return (
      <div style={{ padding: 4 }}>
        {subs.map((sa: any, i: number) => {
          // Normalize: if it's a string (skill name), wrap it
          const sa_obj = typeof sa === 'string' ? { name: sa } : sa;
          const open = expandedSubs[i];
          return (
            <div key={i} style={cardStyle}>
              <div
                onClick={() => setExpandedSubs(prev => ({ ...prev, [i]: !prev[i] }))}
                style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', userSelect: 'none' }}
              >
                {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                <div style={{ ...valueStyle, fontWeight: 600 }}>{sa_obj.name || sa_obj.prompt || `Subagent #${i + 1}`}</div>
                <div style={{ ...valueStyle, color: t.textMuted, fontSize: 11, marginLeft: 8 }}>
                  {sa_obj.description?.slice(0, 60)}
                </div>
              </div>
              {open && (
                <div style={{ marginTop: 10, paddingLeft: 20 }}>
                  <div style={labelStyle}>Description</div>
                  <div style={{ ...valueStyle, marginBottom: 8 }}>{sa_obj.description || '—'}</div>
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

  // ── Guardrails section ──
  const renderGuardrails = () => {
    const g = agent.guardrails_config || config.guardrails || {};
    const tl = g.token_limits || {};
    return (
      <div style={{ padding: 4 }}>
        <div style={cardStyle}>
          <div style={labelStyle}>Auto Eviction</div>
          <div style={valueStyle}>{g.enable_auto_eviction ? 'Enabled' : 'Disabled'}</div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Summarization</div>
          <div style={valueStyle}>{g.enable_summarization ? 'Enabled' : 'Disabled'}</div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Long-Term Memory</div>
          <div style={valueStyle}>{g.long_term_memory ? 'Enabled' : 'Disabled'}</div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Token Limits</div>
          <div style={{ fontFamily: 'monospace', fontSize: 12, color: t.textPrimary }}>
            <div>max_total: {tl.max_total_tokens?.toLocaleString() ?? '—'}</div>
            <div>eviction_threshold: {tl.eviction_threshold?.toLocaleString() ?? '—'}</div>
            <div>summarization_threshold: {tl.summarization_threshold?.toLocaleString() ?? '—'}</div>
          </div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Backend</div>
          <div style={valueStyle}>{agent.backend_config?.type ?? '—'}</div>
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
    </div>
  );
}
