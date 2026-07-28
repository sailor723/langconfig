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
import {
  Info, FileText, Wrench, Users, Layers, Shield, Code, ChevronDown, ChevronRight,
  Play, Square, Loader, Save,
} from 'lucide-react';
import type { Tab } from './useLayout';
import { chatStore } from './chatStore';
import { useAvailableModels } from '../../hooks/useAvailableModels';
import { useAvailableTools } from '../../hooks/useAvailableTools';
import apiClient from '../../lib/api-client';

interface DeepAgentEditorProps {
  tab: Tab;
}

type SectionId = 'overview' | 'prompt' | 'tools' | 'subagents' | 'middleware' | 'guardrails' | 'json';

const SECTIONS: { id: SectionId; label: string; icon: React.ReactNode }[] = [
  { id: 'overview',   label: 'Overview',   icon: <Info size={13} /> },
  { id: 'prompt',     label: 'Prompt',     icon: <FileText size={13} /> },
  { id: 'tools',      label: 'Tools',      icon: <Wrench size={13} /> },
  { id: 'subagents',  label: 'Subagents',  icon: <Users size={13} /> },
  { id: 'middleware', label: 'Middleware', icon: <Layers size={13} /> },
  { id: 'guardrails', label: 'Guardrails', icon: <Shield size={13} /> },
  { id: 'json',       label: 'JSON',       icon: <Code size={13} /> },
];

export default function DeepAgentEditor({ tab }: DeepAgentEditorProps) {
  const t = useLayoutTokens();
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
  // Editable model — synced from config, updates jsonEdit on change
  const [editableModel, setEditableModel] = useState(config.model || '');

  // ── Tools state (interactive picker) ──
  const { isLoading: toolsLoading, groupedByCategory } = useAvailableTools();
  const [availableCustomTools, setAvailableCustomTools] = useState<
    { id: number; tool_id: string; name: string; description: string }[]
  >([]);
  const [selectedNativeTools, setSelectedNativeTools] = useState<string[]>(config.native_tools || []);
  const [selectedCustomTools, setSelectedCustomTools] = useState<string[]>(config.custom_tools || []);

  // Seed tool state from jsonEdit on mount (since payload may change after load)
  useEffect(() => {
    try {
      const p = JSON.parse(jsonEdit);
      const c = p.config || {};
      setSelectedNativeTools(c.native_tools || []);
      setSelectedCustomTools(c.custom_tools || []);
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
    if (!agent.id || running) return;
    setRunning(true);
    try {
      // Use SSE streaming — chatStore handles session start + message send + incremental updates
      await chatStore.sendStreamMessage(agent.id, testPrompt, agent.name ?? 'DeepAgent');
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

  /** Parse the JSON textarea and PUT the updated agent back to the backend */
  const handleSave = async () => {
    if (!agent.id || saving) return;
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
      await apiClient.updateDeepAgent(agent.id, payload);
      setSaveMsg({ ok: true, text: 'Saved successfully' });
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

  // ── Overview section ──
  const renderOverview = () => (
    <div style={{ padding: 4 }}>
      <div style={cardStyle}>
        <div style={labelStyle}>Name</div>
        <div style={{ ...valueStyle, fontSize: 18, fontWeight: 600 }}>{agent.name || '—'}</div>
      </div>
      <div style={cardStyle}>
        <div style={labelStyle}>Description</div>
        <div style={valueStyle}>{agent.description || '—'}</div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        <div style={cardStyle}>
          <div style={labelStyle}>Category</div>
          <div style={valueStyle}>{agent.category || '—'}</div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Model</div>
          <select
            value={editableModel}
            onChange={e => handleModelChange(e.target.value)}
            disabled={modelsLoading}
            style={{
              width: '100%',
              height: 28,
              padding: '0 6px',
              background: t.bgContent,
              border: `1px solid ${t.border}`,
              borderRadius: 3,
              color: t.textPrimary,
              fontSize: 12,
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
        <div style={cardStyle}>
          <div style={labelStyle}>Temperature</div>
          <div style={valueStyle}>{config.temperature ?? '—'}</div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Max Tokens</div>
          <div style={valueStyle}>{config.max_tokens ?? '—'}</div>
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

  // ── Tools section ──
  const renderTools = () => {
    const nativeCount = selectedNativeTools.length;
    const customCount = selectedCustomTools.length;
    const totalCount = nativeCount + customCount;
    const allNativeLoaded = Object.values(groupedByCategory).flat();
    // Reusable tool card
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
    return (
      <div style={{ padding: 4 }}>
        {/* Native tools grouped by category */}
        <div style={cardStyle}>
          <div style={labelStyle}>
            Native Tools ({nativeCount}/{allNativeLoaded.length} selected)
          </div>
          {toolsLoading ? (
            <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic' }}>Loading tools...</div>
          ) : allNativeLoaded.length === 0 ? (
            <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic' }}>(none available)</div>
          ) : (
            Object.entries(groupedByCategory).map(([cat, tools]) => (
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
                  {tools.map(tool => toolCard(
                    tool,
                    selectedNativeTools.includes(tool.id),
                    () => toggleNativeTool(tool.id),
                  ))}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Custom tools */}
        <div style={cardStyle}>
          <div style={labelStyle}>
            Custom Tools ({customCount}/{availableCustomTools.length} selected)
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
              {availableCustomTools.map(tool => toolCard(
                { id: tool.tool_id, name: tool.name, description: tool.description },
                selectedCustomTools.includes(tool.tool_id),
                () => toggleCustomTool(tool.tool_id),
              ))}
            </div>
          )}
        </div>

        {/* Selected summary chips */}
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

  // ── Subagents section ──
  const renderSubagents = () => {
    // Try multiple data locations (DB-level, normalized config, etc.)
    const subs =
      agent.subagents ||
      agent.subagents_config ||
      agent.config?.subagents ||
      agent.config?.skills ||
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
    overview:   renderOverview,
    prompt:     renderPrompt,
    tools:      renderTools,
    subagents:  renderSubagents,
    middleware: renderMiddleware,
    guardrails: renderGuardrails,
    json:       renderJson,
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
          disabled={running || !agent.id}
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
            cursor: running || !agent.id ? 'not-allowed' : 'pointer',
            opacity: running || !agent.id ? 0.6 : 1,
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
          disabled={saving || !agent.id}
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
            cursor: saving || !agent.id ? 'not-allowed' : 'pointer',
            opacity: saving || !agent.id ? 0.6 : 1,
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

        {/* ── Section content ── */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
          <h2 style={{
            fontSize: 16,
            fontWeight: 600,
            color: t.textPrimary,
            margin: '0 0 12px 0',
          }}>
            {agent.name || 'DeepAgent'}
          </h2>
          {sections[activeSection]()}

          {/* Hint about chat sidebar */}
          <div style={{
            marginTop: 16,
            padding: 10,
            fontSize: 11,
            color: t.textMuted,
            fontStyle: 'italic',
          }}>
            💬 After clicking <strong style={{ color: t.textPrimary }}>▶ Run</strong>, the conversation appears in the <strong style={{ color: t.textPrimary }}>Chat</strong> panel on the right.
          </div>
        </div>
      </div>
    </div>
  );
}