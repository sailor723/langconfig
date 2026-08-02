/**
 * AgentEditor — structured editor for a normal Agent (use_deepagents=false).
 *
 * Simpler than DeepAgentEditor — no subagents, middleware, or guardrails.
 * Sections:
 *   - Overview   name, description, category, model, temperature, max_tokens
 *   - Prompt     system_prompt (large textarea)
 *   - Tools      native_tools / cli_tools / custom_tools
 *   - JSON       raw config
 */
import { useState, useCallback, useEffect } from 'react';
import { useLayoutTokens } from './tokens';
import { Award, Loader, Info, FileText, Wrench, Code } from 'lucide-react';
import type { Tab } from './useLayout';
import { useLayoutState } from './useLayout';
import { chatStore } from './chatStore';
import { useAvailableModels } from '../../hooks/useAvailableModels';
import { useAvailableTools } from '../../hooks/useAvailableTools';
import apiClient from '../../lib/api-client';
import ChatTestToolbar from './editorChatToolbar';
import JsonEditorSection from './editorJsonSection';
import ToolsPicker, { toToolIdList } from './editorToolsPicker';
import EditorSectionNav from './editorSectionNav';

interface AgentEditorProps {
  tab: Tab;
}

type SectionId = 'overview' | 'prompt' | 'tools' | 'skills' | 'json';

const SECTIONS: { id: SectionId; label: string; icon: React.ReactNode }[] = [
  { id: 'overview', label: 'Overview', icon: <Info size={13} /> },
  { id: 'prompt',   label: 'Prompt',   icon: <FileText size={13} /> },
  { id: 'tools',    label: 'Tools',    icon: <Wrench size={13} /> },
  { id: 'skills',   label: 'Skills',   icon: <Award size={13} /> },
  { id: 'json',     label: 'JSON',     icon: <Code size={13} /> },
];

export default function AgentEditor({ tab }: AgentEditorProps) {
  const t = useLayoutTokens();
  const { setRightPanelTab, openRightPanel } = useLayoutState();
  const agent = tab.data?.agent ?? tab.data ?? {};
  const config = agent.config || {};
  const isNew = agent.new === true || typeof agent.id !== 'number';
  const { cloudModels, localModels, isLoading: modelsLoading } = useAvailableModels({ includeLocal: true });
  const [activeSection, setActiveSection] = useState<SectionId>('overview');
  const [testPrompt, setTestPrompt] = useState('Hello, please introduce yourself.');
  const [running, setRunning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [jsonEdit, setJsonEdit] = useState(() => JSON.stringify(agent, null, 2));
  // ── Editable fields (synced to jsonEdit for Save) ──
  // For new agents, provide sensible defaults — user can tweak later
  const [editableName, setEditableName] = useState(agent.name || '');
  const [editableDesc, setEditableDesc] = useState(agent.description || '');
  const [editableCategory, setEditableCategory] = useState(agent.category || 'general');
  const [editableModel, setEditableModel] = useState(config.model || '');
  const [editableTemp, setEditableTemp] = useState(config.temperature ?? 0.7);
  const [editableMaxTokens, setEditableMaxTokens] = useState(config.max_tokens ?? (isNew ? 4096 : ''));
  const [editablePrompt, setEditablePrompt] = useState(
    config.system_prompt || (isNew
      ? 'You are a helpful AI assistant. Be concise and accurate. When you are unsure, admit it rather than guessing.'
      : '')
  );

  // ── Skills state ──
  const [skillDetails, setSkillDetails] = useState<Record<string, any>>({});
  const [skillsLoading, setSkillsLoading] = useState(false);

  useEffect(() => {
    const skillNames = config.skills || [];
    if (skillNames.length === 0) return;
    let cancelled = false;
    setSkillsLoading(true);
    Promise.all(
      skillNames.map((s: string) =>
        apiClient.getSkill(s).then(res => ({ id: s, data: res.data })).catch(() => ({ id: s, data: null }))
      )
    ).then(results => {
      if (cancelled) return;
      const map: Record<string, any> = {};
      for (const r of results) if (r.data) map[r.id] = r.data;
      setSkillDetails(map);
      setSkillsLoading(false);
    });
    return () => { cancelled = true; };
  }, [config.skills]);

  // ── Tools state ──
  const { isLoading: toolsLoading, groupedByCategory } = useAvailableTools();
  const [availableCustomTools, setAvailableCustomTools] = useState<
    { id: number; tool_id: string; name: string; description: string }[]
  >([]);
  const [selectedNativeTools, setSelectedNativeTools] = useState<string[]>(toToolIdList(config.native_tools));
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
    setJsonEdit(JSON.stringify(agent, null, 2));
    setLocalAgentId(typeof agent.id === 'number' ? agent.id : null);
    setSelectedNativeTools(toToolIdList(config.native_tools));
    setSelectedCustomTools(toToolIdList(config.custom_tools));
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
    setSelectedNativeTools(prev =>
      prev.includes(toolId) ? prev.filter(t => t !== toolId) : [...prev, toolId]
    );
  }, []);
  const toggleCustomTool = useCallback((toolId: string) => {
    setSelectedCustomTools(prev =>
      prev.includes(toolId) ? prev.filter(t => t !== toolId) : [...prev, toolId]
    );
  }, []);

  // For new agents, fetch default model from DB settings
  useEffect(() => {
    if (!isNew || config.model) return;
    let cancelled = false;
    apiClient.getSettings().then((res: any) => {
      if (!cancelled && res?.data?.default_model) {
        setEditableModel(res.data.default_model);
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
      let payload: any;
      try {
        payload = JSON.parse(jsonEdit);
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
        skills: [],
        middleware: [],
        subagents: [],
        backend: { type: 'state' },
        guardrails: {},
        use_deepagents: false,
        // JSON-tab overrides
        ...jsonConfig,
        // Tool picker always wins over JSON tab for tool selection
        native_tools: selectedNativeTools,
        custom_tools: selectedCustomTools,
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
          config: fullConfig,
        });
      } else {
        const res = await apiClient.createDeepAgent({
          name: trimmedName,
          description: editableDesc.trim() || undefined,
          category: editableCategory,
          config: fullConfig,
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

  // ── Skills section ──
  const renderSkills = () => {
    const skillNames = config.skills || [];
    if (skillNames.length === 0) {
      return (
        <div style={{ padding: 4 }}>
          <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic' }}>(no skills configured)</div>
        </div>
      );
    }
    return (
      <div style={{ padding: 4 }}>
        {skillNames.map((skillId: string) => {
          const detail = skillDetails[skillId];
          return (
            <div key={skillId} style={cardStyle}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <Award size={16} style={{ color: t.accent, flexShrink: 0 }} />
                <div>
                  <div style={{ fontWeight: 600, fontSize: 13, color: t.textPrimary }}>
                    {detail?.name || skillId}
                  </div>
                  {detail && (
                    <div style={{ fontSize: 11, color: t.textMuted }}>
                      v{detail.version || '?'} · {detail.source_type}
                    </div>
                  )}
                </div>
                {skillsLoading && !detail && (
                  <Loader size={12} style={{ animation: 'spin 1s linear infinite', color: t.textMuted }} />
                )}
              </div>

              {detail?.description && (
                <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.5, marginBottom: 8 }}>
                  {detail.description}
                </div>
              )}

              {detail?.tags && detail.tags.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
                  {detail.tags.map((tag: string) => (
                    <span key={tag} style={{
                      fontSize: 10, padding: '1px 6px', borderRadius: 8,
                      background: t.bgHover, border: `1px solid ${t.border}`, color: t.textMuted,
                    }}>
                      {tag}
                    </span>
                  ))}
                </div>
              )}

              {detail?.allowed_tools && detail.allowed_tools.length > 0 && (
                <div>
                  <div style={{ fontSize: 10, color: t.textMuted, textTransform: 'uppercase', marginBottom: 4 }}>
                    Allowed Tools
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {detail.allowed_tools.map((tool: string) => (
                      <span key={tool} style={{
                        fontSize: 11, padding: '2px 6px', borderRadius: 3,
                        background: t.accent + '18', border: `1px solid ${t.accent}40`,
                        color: t.accent, fontFamily: 'monospace',
                      }}>
                        {tool}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {detail?.instructions && (
                <details style={{ marginTop: 8 }}>
                  <summary style={{ fontSize: 11, color: t.textMuted, cursor: 'pointer', userSelect: 'none' }}>
                    View Instructions ({detail.instructions.length} chars)
                  </summary>
                  <pre style={{
                    whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                    fontFamily: '"SF Mono", "Fira Code", monospace',
                    fontSize: 11, color: t.textPrimary, lineHeight: 1.5,
                    margin: '6px 0 0 0',
                  }}>
                    {detail.instructions}
                  </pre>
                </details>
              )}

              {/* Copy / Download row */}
              {detail && (
                <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                  <button onClick={async () => {
                    const text = `# ${detail.name || skillId}\n\n${detail.description || ''}\n\n## Instructions\n\n${detail.instructions || ''}`;
                    await navigator.clipboard.writeText(text);
                  }} style={{
                    fontSize: 11, height: 24, padding: '0 8px',
                    background: t.bgHover, border: `1px solid ${t.border}`,
                    borderRadius: 3, color: t.textPrimary, cursor: 'pointer',
                  }}>Copy</button>
                  <button onClick={() => {
                    const text = `# ${detail.name || skillId}\n\n${detail.description || ''}\n\n## Tags\n${(detail.tags || []).join(', ')}\n\n## Instructions\n\n${detail.instructions || ''}`;
                    const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a'); a.href = url;
                    a.download = `${skillId}.md`; a.click();
                    URL.revokeObjectURL(url);
                  }} style={{
                    fontSize: 11, height: 24, padding: '0 8px',
                    background: t.bgHover, border: `1px solid ${t.border}`,
                    borderRadius: 3, color: t.textPrimary, cursor: 'pointer',
                  }}>Download</button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  };

  const sections: Record<SectionId, () => React.ReactNode> = {
    overview: renderOverview,
    prompt:   renderPrompt,
    tools:    () => (
      <ToolsPicker
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
      />
    ),
    skills:   renderSkills,
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
        canRun={!!localAgentId}
        saveDisabled={false}
        saveMsg={saveMsg}
        statusLabel={`ID: ${agent.id ?? '—'} · v${agent.version ?? '?'} · ${agent.category ?? ''}`}
        t={t}
      />

      {/* ── Body: section nav + section content ── */}
      <EditorSectionNav
        sections={SECTIONS}
        activeSection={activeSection}
        onSectionChange={id => setActiveSection(id as SectionId)}
        renderSection={id => sections[id as SectionId]()}
        t={t}
      />
    </div>
  );
}
