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
import { Info, FileText, Wrench, Code, Play, Square, Loader, Save } from 'lucide-react';
import type { Tab } from './useLayout';
import { chatStore } from './chatStore';
import { useAvailableModels } from '../../hooks/useAvailableModels';
import apiClient from '../../lib/api-client';

interface AgentEditorProps {
  tab: Tab;
}

type SectionId = 'overview' | 'prompt' | 'tools' | 'json';

const SECTIONS: { id: SectionId; label: string; icon: React.ReactNode }[] = [
  { id: 'overview', label: 'Overview', icon: <Info size={13} /> },
  { id: 'prompt',   label: 'Prompt',   icon: <FileText size={13} /> },
  { id: 'tools',    label: 'Tools',    icon: <Wrench size={13} /> },
  { id: 'json',     label: 'JSON',     icon: <Code size={13} /> },
];

export default function AgentEditor({ tab }: AgentEditorProps) {
  const t = useLayoutTokens();
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
        native_tools: [],
        cli_tools: [],
        custom_tools: [],
        tools: [],
        skills: [],
        middleware: [],
        subagents: [],
        backend: { type: 'state' },
        guardrails: {},
        use_deepagents: false,
        // JSON-tab overrides
        ...jsonConfig,
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

  // Reusable styles matching DeepAgentEditor
  const cardStyle: React.CSSProperties = {
    background: t.bgContent,
    border: `1px solid ${t.border}`,
    borderRadius: 4,
    padding: 12,
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
      <div style={cardStyle}>
        <div style={labelStyle}>Name</div>
        <input
          value={editableName}
          onChange={e => { setEditableName(e.target.value); updateTopField('name', e.target.value); }}
          style={inputStyle}
        />
      </div>
      <div style={cardStyle}>
        <div style={labelStyle}>Description</div>
        <input
          value={editableDesc}
          onChange={e => { setEditableDesc(e.target.value); updateTopField('description', e.target.value); }}
          style={inputStyle}
        />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        <div style={cardStyle}>
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
        <div style={cardStyle}>
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
        <div style={cardStyle}>
          <div style={labelStyle}>Temperature</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input
              type="range"
              min={0}
              max={2}
              step={0.1}
              value={editableTemp}
              onChange={e => { const v = parseFloat(e.target.value); setEditableTemp(v); updateConfigField('temperature', v); }}
              style={{ flex: 1, accentColor: t.accent }}
            />
            <span style={{ ...valueStyle, fontFamily: 'monospace', minWidth: 28 }}>{editableTemp.toFixed(1)}</span>
          </div>
        </div>
        <div style={cardStyle}>
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
        <div style={cardStyle}>
          <div style={labelStyle}>Version</div>
          <div style={valueStyle}>{agent.version || '—'}</div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Public</div>
          <div style={valueStyle}>{agent.is_public ? 'Yes' : 'No'}</div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Usage Count</div>
          <div style={valueStyle}>{agent.usage_count ?? 0}</div>
        </div>
        <div style={cardStyle}>
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

  // ── Tools section ──
  const renderTools = () => {
    const native = config.native_tools || [];
    const cli = config.cli_tools || [];
    const custom = config.custom_tools || [];
    const groups = [
      { label: 'Native Tools', items: native },
      { label: 'CLI Tools', items: cli },
      { label: 'Custom Tools', items: custom },
    ];
    return (
      <div style={{ padding: 4 }}>
        {groups.map(g => (
          <div key={g.label} style={cardStyle}>
            <div style={labelStyle}>{g.label} ({g.items.length})</div>
            {g.items.length === 0 ? (
              <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic' }}>(none)</div>
            ) : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {g.items.map((tool: string, i: number) => (
                  <span key={i} style={{
                    fontSize: 11,
                    padding: '3px 8px',
                    background: t.bgHover,
                    border: `1px solid ${t.border}`,
                    borderRadius: 3,
                    color: t.textPrimary,
                    fontFamily: 'monospace',
                  }}>
                    {tool}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
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
