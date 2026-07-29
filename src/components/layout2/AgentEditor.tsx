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
import { Info, FileText, Wrench, Code, Play, Square, Loader, Save, Award } from 'lucide-react';
import { useLayoutState, type Tab } from './useLayout';
import { chatStore } from './chatStore';
import { useAvailableModels } from '../../hooks/useAvailableModels';
import { useAvailableTools } from '../../hooks/useAvailableTools';
import apiClient from '../../lib/api-client';

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
  const { closeRightPanel, setRightPanelOpen } = useLayoutState();
  const agent = tab.data?.agent ?? tab.data ?? {};
  const config = agent.config || {};
  const isNew = agent.new === true;
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
  const [selectedNativeTools, setSelectedNativeTools] = useState<string[]>(config.native_tools || []);
  const [selectedCustomTools, setSelectedCustomTools] = useState<string[]>(config.custom_tools || []);
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
    setLocalAgentId(agent.id || null);
    setSelectedNativeTools(config.native_tools || []);
    setSelectedCustomTools(config.custom_tools || []);
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
    if (!isNew) return;
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
  const [localAgentId, setLocalAgentId] = useState<number | null>(agent.id || null);

  const handleRun = async () => {
    if (!localAgentId || running) return;
    setRunning(true);
    // Ensure the right-panel Chat tab is open, so the user sees responses as they stream in
    closeRightPanel();   // clear any node-config content → Chat tab becomes the active tab
    setRightPanelOpen(true);
    try {
      await chatStore.sendStreamMessage(localAgentId, testPrompt, editableName || 'Agent');
    } catch (err: any) {
      chatStore.add({
        role: 'system',
        text: `// Test failed: ${err?.message ?? 'unknown error'}`,
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

  // ── Tools section (interactive picker) ──
  const renderTools = () => {
    const nativeCount = selectedNativeTools.length;
    const customCount = selectedCustomTools.length;
    const totalCount = nativeCount + customCount;
    const allNativeLoaded = Object.values(groupedByCategory).flat();
    // Reusable tool card (matches ModelCardsGridTab style)
    const toolCard = (
      tool: { id: string; name: string; description: string },
      checked: boolean,
      onToggle: () => void,
    ) => (
      <label
        key={tool.id}
        style={{
          display: 'flex', flexDirection: 'column', gap: 6,
          padding: 10, borderRadius: 6, cursor: 'pointer',
          border: `1px solid ${t.border}`,
          background: t.bgSidebar,
          minHeight: 80,
          boxSizing: 'border-box',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
          <input
            type="checkbox"
            checked={checked}
            onChange={onToggle}
            style={{ accentColor: t.accent, flexShrink: 0, marginTop: 2 }}
          />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{
              color: t.textPrimary, fontWeight: 600, fontSize: 12,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {tool.name}
            </div>
            <div style={{
              fontSize: 10, color: t.textMuted, fontFamily: 'monospace',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {tool.id}
            </div>
          </div>
        </div>
        <div style={{
          fontSize: 11, color: t.textMuted, lineHeight: 1.4,
          display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
        }}>
          {tool.description}
        </div>
      </label>
    );
    const toggleBtn = (label: string, active: boolean, onClick: () => void) => (
      <button
        onClick={onClick}
        style={{
          padding: '2px 10px',
          fontSize: 11,
          border: `1px solid ${active ? t.accent : t.border}`,
          background: active ? t.accent + '20' : 'transparent',
          color: active ? t.accent : t.textMuted,
          borderRadius: 10,
          cursor: 'pointer',
          fontWeight: active ? 600 : 400,
        }}
      >
        {label}
      </button>
    );

    // Filter helper: when showAllTools=false, only include checked tools
    const filterTools = <T extends { id: string }>(tools: T[]): T[] =>
      showAllTools ? tools : tools.filter(t => selectedNativeTools.includes(t.id));

    return (
      <div style={{ padding: 4 }}>
        {/* Native tools grouped by category */}
        <div style={cardStyle}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <div style={labelStyle}>
              Native Tools ({nativeCount}/{allNativeLoaded.length} selected)
            </div>
            <div style={{ flex: 1 }} />
            {toggleBtn('All', showAllTools, () => setShowAllTools(true))}
            {toggleBtn('Selected', !showAllTools, () => setShowAllTools(false))}
          </div>
          {toolsLoading ? (
            <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic' }}>Loading tools...</div>
          ) : allNativeLoaded.length === 0 ? (
            <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic' }}>(none available)</div>
          ) : (
            Object.entries(groupedByCategory).map(([cat, tools]) => {
              const catTools = filterTools(tools);
              if (catTools.length === 0) return null;
              return (
                <div key={cat} style={{ marginBottom: 10 }}>
                  <div style={{
                    fontSize: 10, color: t.textMuted, textTransform: 'uppercase',
                    letterSpacing: 0.3, marginBottom: 6, fontWeight: 600,
                  }}>
                    {cat}
                  </div>
                  <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(4, 1fr)',
                    gap: 8,
                  }}>
                    {catTools.map(tool => toolCard(
                      tool,
                      selectedNativeTools.includes(tool.id),
                      () => toggleNativeTool(tool.id),
                    ))}
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Custom tools */}
        <div style={cardStyle}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <div style={labelStyle}>
              Custom Tools ({customCount}/{availableCustomTools.length} selected)
            </div>
            <div style={{ flex: 1 }} />
            {toggleBtn('All', showAllTools, () => setShowAllTools(true))}
            {toggleBtn('Selected', !showAllTools, () => setShowAllTools(false))}
          </div>
          {availableCustomTools.length === 0 ? (
            <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic' }}>
              (no custom tools — create one in the Tools activity)
            </div>
          ) : (
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(4, 1fr)',
              gap: 8,
            }}>
              {(showAllTools
                ? availableCustomTools
                : availableCustomTools.filter(t => selectedCustomTools.includes(t.tool_id))
              ).map(tool => toolCard(
                { id: tool.tool_id, name: tool.name, description: tool.description },
                selectedCustomTools.includes(tool.tool_id),
                () => toggleCustomTool(tool.tool_id),
              ))}
            </div>
          )}
        </div>

        {/* Quick summary of selected tools as chips */}
        {totalCount > 0 && (
          <div style={cardStyle}>
            <div style={labelStyle}>Selected ({totalCount})</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {selectedNativeTools.map(id => (
                <span key={`n-${id}`} style={{
                  fontSize: 11, padding: '2px 6px', background: t.bgHover,
                  border: `1px solid ${t.border}`, borderRadius: 3,
                  color: t.textPrimary, fontFamily: 'monospace',
                }}>{id}</span>
              ))}
              {selectedCustomTools.map(id => (
                <span key={`c-${id}`} style={{
                  fontSize: 11, padding: '2px 6px', background: t.bgHover,
                  border: `1px solid ${t.accent}40`, borderRadius: 3,
                  color: t.textPrimary, fontFamily: 'monospace',
                }}>{id}</span>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  };

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

  // ── JSON section (editable textarea) ──
  const renderJson = () => (
    <div style={{ padding: 4 }}>
      <textarea
        value={jsonEdit}
        onChange={e => setJsonEdit(e.target.value)}
        spellCheck={false}
        style={{
          width: '100%',
          background: t.bgContent,
          border: `1px solid ${t.border}`,
          borderRadius: 4,
          padding: 12,
          fontFamily: '"SF Mono", "Fira Code", monospace',
          fontSize: 12,
          color: t.textPrimary,
          overflow: 'auto',
          minHeight: 300,
          resize: 'vertical',
          outline: 'none',
          lineHeight: 1.5,
        }}
      />
    </div>
  );

  const sections: Record<SectionId, () => React.ReactNode> = {
    overview: renderOverview,
    prompt:   renderPrompt,
    tools:    renderTools,
    skills:   renderSkills,
    json:     renderJson,
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: t.bgContent }}>
      {/* ── Top action bar (VS Code run-toolbar style) ── */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        height: 35,
        minHeight: 35,
        padding: '0 12px',
        background: t.bgTabBar,
        borderBottom: `1px solid ${t.border}`,
        flexShrink: 0,
      }}>
        <span style={{ fontSize: 12, color: t.textMuted }}>Test:</span>
        <input
          value={testPrompt}
          onChange={e => setTestPrompt(e.target.value)}
          disabled={running}
          placeholder="Type a test message..."
          style={{
            flex: 1,
            maxWidth: 360,
            height: 22,
            padding: '0 8px',
            background: t.bgContent,
            border: `1px solid ${t.border}`,
            borderRadius: 3,
            color: t.textPrimary,
            fontSize: 12,
            outline: 'none',
            opacity: running ? 0.5 : 1,
          }}
        />
        <button
          onClick={handleRun}
          disabled={running || !localAgentId}
          title="Run test"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            height: 24,
            padding: '0 10px',
            background: running ? t.bgHover : t.accent,
            color: '#fff',
            border: 'none',
            borderRadius: 3,
            fontSize: 12,
            fontWeight: 500,
            cursor: running || !localAgentId ? 'not-allowed' : 'pointer',
            opacity: running || !localAgentId ? 0.6 : 1,
          }}
        >
          {running ? <Loader size={12} style={{ animation: 'spin 1s linear infinite' }} /> : <Play size={12} />}
          {running ? 'Running…' : 'Run'}
        </button>
        {running && (
          <button
            onClick={handleStop}
            title="Cancel stream"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              height: 24,
              padding: '0 10px',
              background: 'transparent',
              color: t.textPrimary,
              border: `1px solid ${t.border}`,
              borderRadius: 3,
              fontSize: 12,
              cursor: 'pointer',
            }}
          >
            <Square size={10} />
            Stop
          </button>
        )}
        <button
          onClick={handleSave}
          disabled={saving}
          title="Save changes"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            height: 24,
            padding: '0 10px',
            background: saving ? t.bgHover : '#2d7d46',
            color: '#fff',
            border: 'none',
            borderRadius: 3,
            fontSize: 12,
            cursor: saving ? 'not-allowed' : 'pointer',
            opacity: saving ? 0.6 : 1,
          }}
        >
          <Save size={12} />
          {saving ? 'Saving…' : 'Save'}
        </button>
        {saveMsg && (
          <span style={{
            fontSize: 11,
            color: saveMsg.ok ? '#4caf50' : '#ef5350',
            marginLeft: 4,
          }}>
            {saveMsg.text}
          </span>
        )}
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 11, color: t.textDim }}>
          ID: {agent.id ?? '—'} · v{agent.version ?? '?'} · {agent.category ?? ''}
        </span>
      </div>

      {/* ── Body: section nav + section content ── */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        <div style={{
          width: 130,
          minWidth: 130,
          background: t.bgSidebar,
          borderRight: `1px solid ${t.border}`,
          padding: '8px 0',
          overflowY: 'auto',
          flexShrink: 0,
        }}>
          {SECTIONS.map(s => {
            const isActive = s.id === activeSection;
            return (
              <button
                key={s.id}
                onClick={() => setActiveSection(s.id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  width: '100%',
                  padding: '8px 14px',
                  fontSize: 12,
                  color: isActive ? t.textPrimary : t.textMuted,
                  background: isActive ? t.bgHover : 'transparent',
                  border: 'none',
                  borderLeft: isActive ? `2px solid ${t.accent}` : '2px solid transparent',
                  cursor: 'pointer',
                  textAlign: 'left',
                }}
              >
                {s.icon}
                {s.label}
              </button>
            );
          })}
        </div>

        {/* Section content */}
        <div style={{
          flex: 1,
          padding: 16,
          overflowY: 'auto',
          minHeight: 0,
        }}>
          {sections[activeSection]()}
        </div>
      </div>
    </div>
  );
}
