/**
 * DeepAgentCreator — form to create a new DeepAgent from scratch.
 *
 * Mirrors the DeepAgentEditor section structure (Overview, Prompt, Tools,
 * Skills, Subagents, Middleware, Guardrails, JSON). On submit, calls
 * POST /api/deepagents/ and switches to the resulting DeepAgentEditor tab.
 */
import { useState, useEffect } from 'react';
import type { Tab } from './useLayout';
import { useLayoutTokens } from './tokens';
import { useLayoutState } from './useLayout';
import { useAvailableModels } from '../../hooks/useAvailableModels';
import { useAvailableTools } from '../../hooks/useAvailableTools';
import apiClient from '../../lib/api-client';
import { Loader, Plus, X } from 'lucide-react';
import { SectionId as _SectionId, SECTIONS } from './editorConstants';
import SkillsPicker from './editorSkillsPicker';

const CATEGORIES = ['research', 'coding', 'analysis', 'general', 'custom'];

interface DeepAgentCreatorProps {
  tab: Tab;
}

// Section structure mirrors DeepAgentEditor for parity.
type SectionId = _SectionId;

// Available middleware toggles — mirrors the catalog in DeepAgentHomePage.
// Only types the backend accepts (MiddlewareType enum) are listed:
// 'memory'/'model_fallback'/'pii'/'tool_call_limit' are intentionally omitted
// because the backend does not implement them; 'hitl' is the backend id for
// human-in-the-loop (previously a dead 'human_in_the_loop' option).
const MIDDLEWARE_OPTIONS = [
  { id: 'todo_list',     label: 'TodoList',         desc: 'Task planning & tracking' },
  { id: 'filesystem',    label: 'Filesystem',       desc: 'File operations (ls/read/write/edit)' },
  { id: 'summarization', label: 'Summarization',    desc: 'Auto-summarize near token limits' },
  { id: 'hitl',          label: 'Human-in-Loop',    desc: 'Pause for human approval' },
  { id: 'tool_retry',    label: 'Tool Retry',       desc: 'Auto-retry failed tool calls' },
  { id: 'subagent',      label: 'Subagents',        desc: 'Delegate to specialized subagents' },
];

// Backend options for memory persistence.
const BACKEND_TYPES = [
  { id: 'state',     label: 'In-Memory (State)',    desc: 'Temporary, lost on restart' },
  { id: 'sqlite',    label: 'SQLite',               desc: 'Local persistent file' },
  { id: 'postgres',  label: 'PostgreSQL',           desc: 'Server-side persistent' },
  { id: 'composite', label: 'Composite (Mixed)',    desc: 'Hybrid short-term + long-term' },
];

export default function DeepAgentCreator({ tab }: DeepAgentCreatorProps) {
  const t = useLayoutTokens();
  const { closeTab, openTab } = useLayoutState();
  const { cloudModels, localModels, isLoading: modelsLoading } = useAvailableModels({ includeLocal: true });
  const { isLoading: nativeToolsLoading, groupedByCategory, defaultToolIds } = useAvailableTools();

  // Section state
  const [activeSection, setActiveSection] = useState<SectionId>('overview');

  // Form state
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState('general');
  const [systemPrompt, setSystemPrompt] = useState(
    'You are a helpful AI assistant. Be concise and accurate.',
  );
  // Use the globally stored default model from localStorage, if set
  const [model, setModel] = useState(() => localStorage.getItem('langconfig.defaultModel') || '');
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState<number | ''>('');

  // Tools (native via useAvailableTools hook above + custom below)
  // Skills
  const [availableSkills, setAvailableSkills] = useState<any[]>([]);
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [showAllSkills, setShowAllSkills] = useState(true);
  const [skillsLoading, setSkillsLoading] = useState(false);

  // Subagents
  const [subagents, setSubagents] = useState<Array<{ name: string; description: string; model: string; system_prompt: string }>>([]);

  // Middleware
  const [enabledMiddleware, setEnabledMiddleware] = useState<string[]>([
    'todo_list', 'filesystem',
  ]);
  const [backendType, setBackendType] = useState('state');

  // Guardrails
  const [enableAutoEviction, setEnableAutoEviction] = useState(false);
  const [enableSummarization, setEnableSummarization] = useState(false);
  const [longTermMemory, setLongTermMemory] = useState(true);
  const [tokenLimit, setTokenLimit] = useState<number | ''>(8000);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Custom tools
  const [availableCustomTools, setAvailableCustomTools] = useState<
    { id: number; tool_id: string; name: string; description: string }[]
  >([]);
  const [selectedNativeTools, setSelectedNativeTools] = useState<string[]>(defaultToolIds);
  // Apply the default tool set once loaded (async hook) when nothing is
  // selected yet — new agents start with the universal base pre-checked.
  useEffect(() => {
    if (defaultToolIds.length && selectedNativeTools.length === 0) {
      setSelectedNativeTools(defaultToolIds);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaultToolIds]);
  const [selectedCustomTools, setSelectedCustomTools] = useState<string[]>([]);
  const [showAllTools, setShowAllTools] = useState(true);

  // Load available tools and skills on mount
  useEffect(() => {
    const abort = new AbortController();
    // Load custom tools
    apiClient.listCustomTools().then((res: any) => {
      if (!abort.signal.aborted && res?.data) setAvailableCustomTools(res.data);
    }).catch(() => {});
    (async () => {
      setSkillsLoading(true);
      try {
        const res = await apiClient.apiFetch(`${apiClient.baseURL}/api/skills`, { signal: abort.signal });
        const skills = Array.isArray(res) ? res : (res?.data || []);
        setAvailableSkills(skills);
      } catch {
        setAvailableSkills([]);
      } finally {
        setSkillsLoading(false);
      }
    })();
    return () => abort.abort();
  }, []);

  const canSubmit = name.trim().length > 0 && systemPrompt.trim().length > 0 && !submitting;

  // Valid MiddlewareType values the backend accepts.
  const VALID_MW_TYPES = ['todo_list', 'filesystem', 'subagent', 'hitl', 'summarization', 'tool_retry'] as const;

  // Build config payload matching the backend DeepAgentConfig model.
  const buildConfig = () => ({
    system_prompt: systemPrompt.trim(),
    model: model || undefined,
    temperature,
    max_tokens: maxTokens === '' ? undefined : Number(maxTokens),
    native_tools: selectedNativeTools,
    cli_tools: [],
    custom_tools: selectedCustomTools,
    tools: [...selectedNativeTools, ...selectedCustomTools],
    skills: selectedSkills,
    subagents: subagents.map(s => ({
      name: s.name,
      description: s.description,
      type: 'dictionary' as const,
      model: s.model || undefined,
      system_prompt: s.system_prompt || undefined,
    })),
    // Convert string IDs → MiddlewareConfig objects, dropping unknown types
    middleware: enabledMiddleware
      .filter(id => (VALID_MW_TYPES as readonly string[]).includes(id))
      .map(id => ({ type: id, enabled: true, config: {} })),
    // Map frontend labels to valid BackendType enum values
    backend: (() => {
      const typeMap: Record<string, string> = {
        state: 'state',
        memory: 'state',
        sqlite: 'store',
        postgres: 'store',
      };
      const type = typeMap[backendType] || backendType;
      return type === 'composite'
        ? { type, mappings: { '/memory/': { type: 'vectordb', config: {} } } }
        : { type };
    })(),
    guardrails: {
      enable_auto_eviction: enableAutoEviction,
      enable_summarization: enableSummarization,
      long_term_memory: longTermMemory,
      // Omit token_limits when not set so backend uses its own defaults
      // (summarization_threshold=60000 < eviction_threshold=80000 < max_total_tokens=100000)
      ...(tokenLimit === '' ? {} : {
        token_limits: {
          max_total_tokens: Number(tokenLimit),
          summarization_threshold: Math.floor(Number(tokenLimit) * 0.6),
          eviction_threshold: Math.floor(Number(tokenLimit) * 0.8),
        },
      }),
    },
    use_deepagents: true,
  });

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);

    try {
      const res = await apiClient.createDeepAgent({
        name: name.trim(),
        description: description.trim() || undefined,
        category,
        config: buildConfig(),
      });

      const agent = res.data;
      closeTab(tab.id);
      openTab({
        id: `deepagent-${agent.id}`,
        label: agent.name,
        viewType: 'deepagent',
        data: { agent },
      });
    } catch (err: any) {
      let detail = err?.response?.data?.detail ?? err?.message ?? 'unknown error';
      // If detail is a list of validation errors (FastAPI 422), format them
      if (Array.isArray(detail)) {
        detail = detail.map((e: any) => `${e.loc?.slice(1).join('.') || '?'}: ${e.msg}`).join('; ');
      } else if (typeof detail === 'object') {
        detail = JSON.stringify(detail);
      }
      setError(`Failed to create agent: ${detail}`);
    } finally {
      setSubmitting(false);
    }
  };

  // ── Styles ──
  const inputBase: React.CSSProperties = {
    width: '100%',
    padding: '8px 10px',
    background: t.bgContent,
    border: `1px solid ${t.border}`,
    borderRadius: 4,
    color: t.textPrimary,
    fontSize: 13,
    outline: 'none',
    boxSizing: 'border-box',
  };
  const labelStyle: React.CSSProperties = {
    fontSize: 11,
    color: t.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    marginBottom: 4,
    display: 'block',
  };
  const cardStyle: React.CSSProperties = {
    background: t.bgSidebar,
    border: `1px solid ${t.border}`,
    borderRadius: 4,
    padding: 14,
    marginBottom: 12,
  };
  const toggleBtn = (active: boolean): React.CSSProperties => ({
    padding: '5px 10px', fontSize: 11, fontWeight: 500,
    border: `1px solid ${active ? t.accent : t.border}`,
    borderRadius: 4, cursor: 'pointer',
    background: active ? `${t.accent}15` : 'transparent',
    color: active ? t.accent : t.textPrimary,
  });

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden', background: t.bgContent }}>
      {/* ── Top action bar ── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 16px', borderBottom: `1px solid ${t.border}`,
        background: t.bgSidebar, flexShrink: 0,
      }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary }}>Create DeepAgent</div>
          <div style={{ fontSize: 11, color: t.textMuted, marginTop: 2 }}>
            Configure a new agent with subagents, middleware, and tool support.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => closeTab(tab.id)} style={{
            height: 28, padding: '0 12px', fontSize: 12,
            background: 'transparent', border: `1px solid ${t.border}`,
            borderRadius: 4, color: t.textPrimary, cursor: 'pointer',
          }}>Cancel</button>
          <button onClick={handleSubmit} disabled={!canSubmit} style={{
            height: 28, padding: '0 14px', fontSize: 12, fontWeight: 600,
            background: canSubmit ? t.accent : t.bgHover,
            color: '#fff', border: 'none', borderRadius: 4,
            cursor: canSubmit ? 'pointer' : 'not-allowed',
            opacity: canSubmit ? 1 : 0.5,
          }}>{submitting ? 'Creating...' : 'Create Agent'}</button>
        </div>
      </div>

      {error && (
        <div style={{
          margin: 12, padding: 12, borderRadius: 4,
          background: '#e5484d18', border: '1px solid #e5484d',
          color: '#e5484d', fontSize: 12,
        }}>{error}</div>
      )}

      {/* ── Body: section nav + section content ── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Section nav (left rail) */}
        <nav style={{
          width: 140, borderRight: `1px solid ${t.border}`,
          background: t.bgSidebar, padding: '8px 0',
          overflowY: 'auto', flexShrink: 0,
        }}>
          {SECTIONS.map(s => {
            const isActive = activeSection === s.id;
            return (
              <button
                key={s.id}
                onClick={() => setActiveSection(s.id)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  width: '100%', padding: '7px 14px',
                  background: isActive ? `${t.accent}15` : 'transparent',
                  color: isActive ? t.accent : t.textPrimary,
                  border: 'none', borderLeft: isActive ? `2px solid ${t.accent}` : '2px solid transparent',
                  fontSize: 12, fontWeight: isActive ? 600 : 500,
                  textAlign: 'left', cursor: 'pointer',
                }}
              >
                {s.icon}
                <span>{s.label}</span>
              </button>
            );
          })}
        </nav>

        {/* Section content */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 20 }}>
          {activeSection === 'overview' && (
            <div>
              <h3 style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary, margin: '0 0 12px 0' }}>Overview</h3>

              <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
                <div style={{ flex: 2, ...cardStyle }}>
                  <label style={labelStyle}>Name <span style={{ color: '#e5484d' }}>*</span></label>
                  <input value={name} onChange={e => setName(e.target.value)} placeholder="my-agent" style={inputBase} autoFocus />
                </div>
                <div style={{ flex: 1, ...cardStyle }}>
                  <label style={labelStyle}>Category</label>
                  <select value={category} onChange={e => setCategory(e.target.value)} style={inputBase}>
                    {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
              </div>

              <div style={cardStyle}>
                <label style={labelStyle}>Description</label>
                <textarea
                  value={description}
                  onChange={e => setDescription(e.target.value)}
                  rows={3}
                  placeholder="Short description of what this agent does..."
                  style={{ ...inputBase, resize: 'vertical', fontFamily: 'inherit' }}
                />
              </div>

              <div style={{ display: 'flex', gap: 12 }}>
                <div style={{ flex: 2, ...cardStyle }}>
                  <label style={labelStyle}>Model</label>
                  <select value={model} onChange={e => setModel(e.target.value)} style={inputBase} disabled={modelsLoading}>
                    <option value="">{modelsLoading ? 'Loading models...' : '(Backend default)'}</option>
                    {cloudModels.length > 0 && (
                      <optgroup label="Cloud Models">
                        {cloudModels.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
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
                <div style={{ flex: 1, ...cardStyle }}>
                  <label style={labelStyle}>Temperature: {temperature.toFixed(1)}</label>
                  <input type="range" min={0} max={2} step={0.1} value={temperature}
                    onChange={e => setTemperature(parseFloat(e.target.value))}
                    style={{ width: '100%', accentColor: t.accent }} />
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: t.textMuted, marginTop: 4 }}>
                    <span>precise (0)</span><span>creative (2)</span>
                  </div>
                </div>
                <div style={{ flex: 1, ...cardStyle }}>
                  <label style={labelStyle}>Max Tokens</label>
                  <input type="number" value={maxTokens} onChange={e => setMaxTokens(e.target.value === '' ? '' : Number(e.target.value))}
                    placeholder="auto" style={inputBase} min={1} />
                </div>
              </div>

              <div style={cardStyle}>
                <label style={labelStyle}>Capabilities</label>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {/* Memory maps to guardrails.long_term_memory in buildConfig */}
                  <button onClick={() => setLongTermMemory(!longTermMemory)} style={toggleBtn(longTermMemory)}>
                    Memory
                  </button>
                  {/* Human-in-Loop maps to the 'hitl' middleware entry in buildConfig */}
                  <button
                    onClick={() => setEnabledMiddleware(prev =>
                      prev.includes('hitl') ? prev.filter(x => x !== 'hitl') : [...prev, 'hitl'])}
                    style={toggleBtn(enabledMiddleware.includes('hitl'))}
                  >
                    Human-in-Loop
                  </button>
                </div>
              </div>
            </div>
          )}

          {activeSection === 'prompt' && (
            <div>
              <h3 style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary, margin: '0 0 12px 0' }}>System Prompt</h3>
              <div style={cardStyle}>
                <textarea
                  value={systemPrompt}
                  onChange={e => setSystemPrompt(e.target.value)}
                  rows={14}
                  placeholder="Instructions that define the agent's behavior..."
                  style={{ ...inputBase, resize: 'vertical', fontFamily: '"SF Mono", "Fira Code", monospace', fontSize: 12, lineHeight: 1.5 }}
                />
                <div style={{ fontSize: 11, color: t.textMuted, marginTop: 4, textAlign: 'right' }}>{systemPrompt.length} chars</div>
              </div>
            </div>
          )}

          {activeSection === 'tools' && (
            <div>
              <h3 style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary, margin: '0 0 4px 0' }}>Tools</h3>
              <p style={{ fontSize: 12, color: t.textMuted, margin: '0 0 12px 0' }}>
                Select native tools and custom tools this agent can call.
              </p>

              {/* ── Tool card sub-component ── */}
              {(() => {
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
                const filterTools = <T extends { id: string }>(tools: T[]): T[] =>
                  showAllTools ? tools : tools.filter(t => selectedNativeTools.includes(t.id));

                // Flatten all native tools
                const allNativeTools = Object.values(groupedByCategory).flat();
                const nativeCount = selectedNativeTools.length;
                const customCount = selectedCustomTools.length;

                return (
                  <>
                    {/* Native tools by category */}
                    <div style={cardStyle}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                        <div style={labelStyle}>
                          Native Tools ({nativeCount}/{allNativeTools.length} selected)
                        </div>
                        <div style={{ flex: 1 }} />
                        {toggleBtn('All', showAllTools, () => setShowAllTools(true))}
                        {toggleBtn('Selected', !showAllTools, () => setShowAllTools(false))}
                      </div>
                      {nativeToolsLoading ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: t.textMuted, fontSize: 12, padding: 8 }}>
                          <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} /> Loading tools...
                        </div>
                      ) : allNativeTools.length === 0 ? (
                        <div style={{ fontSize: 12, color: t.textMuted, fontStyle: 'italic', padding: 8 }}>(none available)</div>
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
                              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
                                {catTools.map((tool: any) => toolCard(
                                  { id: tool.id, name: tool.name, description: tool.description || '' },
                                  selectedNativeTools.includes(tool.id),
                                  () => setSelectedNativeTools(prev =>
                                    prev.includes(tool.id) ? prev.filter(t => t !== tool.id) : [...prev, tool.id]
                                  ),
                                ))}
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>

                    {/* Custom tools */}
                    <div style={cardStyle}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                        <div style={labelStyle}>
                          Custom Tools ({customCount}/{availableCustomTools.length} selected)
                        </div>
                        <div style={{ flex: 1 }} />
                        {toggleBtn('All', showAllTools, () => setShowAllTools(true))}
                        {toggleBtn('Selected', !showAllTools, () => setShowAllTools(false))}
                      </div>
                      {availableCustomTools.length === 0 ? (
                        <div style={{ fontSize: 12, color: t.textMuted, fontStyle: 'italic', padding: 8 }}>
                          (no custom tools — create one in the Tools activity)
                        </div>
                      ) : (
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
                          {(showAllTools
                            ? availableCustomTools
                            : availableCustomTools.filter(t => selectedCustomTools.includes(t.tool_id))
                          ).map(tool => toolCard(
                            { id: tool.tool_id, name: tool.name, description: tool.description },
                            selectedCustomTools.includes(tool.tool_id),
                            () => setSelectedCustomTools(prev =>
                              prev.includes(tool.tool_id) ? prev.filter(t => t !== tool.tool_id) : [...prev, tool.tool_id]
                            ),
                          ))}
                        </div>
                      )}
                    </div>
                  </>
                );
              })()}
            </div>
          )}

          {activeSection === 'skills' && (
            <div>
              <h3 style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary, margin: '0 0 4px 0' }}>Skills</h3>
              <p style={{ fontSize: 12, color: t.textMuted, margin: '0 0 12px 0' }}>Skills are reusable instruction sets triggered by domain keywords.</p>
              {/* Searchable card-grid picker; saves skill_ids (backend resolves by id) */}
              <SkillsPicker
                selectedSkills={selectedSkills}
                onToggle={id => setSelectedSkills(prev =>
                  prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
                )}
                showAll={showAllSkills}
                onShowAllChange={setShowAllSkills}
                skillsLoading={skillsLoading}
                availableSkills={availableSkills}
                t={t}
              />
            </div>
          )}

          {activeSection === 'subagents' && (
            <div>
              <h3 style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary, margin: '0 0 4px 0' }}>Subagents</h3>
              <p style={{ fontSize: 12, color: t.textMuted, margin: '0 0 12px 0' }}>Specialized agents that this agent can delegate to.</p>

              {subagents.length === 0 && (
                <p style={{ fontSize: 12, color: t.textMuted, padding: 12, textAlign: 'center' }}>
                  No subagents yet. Click "Add Subagent" to define a specialized worker.
                </p>
              )}

              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {subagents.map((sub, i) => (
                  <div key={i} style={{ ...cardStyle, position: 'relative' }}>
                    <button
                      onClick={() => setSubagents(prev => prev.filter((_, idx) => idx !== i))}
                      style={{
                        position: 'absolute', top: 8, right: 8,
                        background: 'transparent', border: 'none',
                        color: t.textMuted, cursor: 'pointer',
                      }}
                    ><X size={14} /></button>
                    <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                      <input
                        value={sub.name}
                        onChange={e => setSubagents(prev => prev.map((s, idx) => idx === i ? { ...s, name: e.target.value } : s))}
                        placeholder="Subagent name"
                        style={{ ...inputBase, flex: 1 }}
                      />
                      <input
                        value={sub.model}
                        onChange={e => setSubagents(prev => prev.map((s, idx) => idx === i ? { ...s, model: e.target.value } : s))}
                        placeholder="Model (optional)"
                        style={{ ...inputBase, flex: 1 }}
                      />
                    </div>
                    <input
                      value={sub.description}
                      onChange={e => setSubagents(prev => prev.map((s, idx) => idx === i ? { ...s, description: e.target.value } : s))}
                      placeholder="Description"
                      style={{ ...inputBase, marginBottom: 8 }}
                    />
                    <textarea
                      value={sub.system_prompt}
                      onChange={e => setSubagents(prev => prev.map((s, idx) => idx === i ? { ...s, system_prompt: e.target.value } : s))}
                      placeholder="Subagent system prompt..."
                      rows={4}
                      style={{ ...inputBase, fontFamily: '"SF Mono", "Fira Code", monospace', fontSize: 12, resize: 'vertical' }}
                    />
                  </div>
                ))}
              </div>

              <button
                onClick={() => setSubagents(prev => [...prev, { name: '', description: '', model: '', system_prompt: '' }])}
                style={{
                  marginTop: 12, padding: '8px 14px',
                  background: 'transparent', border: `1px dashed ${t.border}`,
                  borderRadius: 4, color: t.textPrimary, fontSize: 12,
                  cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6,
                }}
              >
                <Plus size={14} /> Add Subagent
              </button>
            </div>
          )}

          {activeSection === 'middleware' && (
            <div>
              <h3 style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary, margin: '0 0 4px 0' }}>Middleware</h3>
              <p style={{ fontSize: 12, color: t.textMuted, margin: '0 0 12px 0' }}>Middleware wraps around the LangChain Agent to inject capabilities.</p>

              <h4 style={{ fontSize: 12, fontWeight: 600, color: t.textMuted, margin: '0 0 8px 0', textTransform: 'uppercase', letterSpacing: 0.4 }}>
                Enabled Middleware
              </h4>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 8, marginBottom: 20 }}>
                {MIDDLEWARE_OPTIONS.map(m => {
                  const enabled = enabledMiddleware.includes(m.id);
                  return (
                    <button key={m.id}
                      onClick={() => setEnabledMiddleware(prev =>
                        enabled ? prev.filter(x => x !== m.id) : [...prev, m.id])}
                      style={{
                        padding: 10, borderRadius: 6,
                        background: enabled ? `${t.accent}15` : t.bgSidebar,
                        border: `1px solid ${enabled ? t.accent : t.border}`,
                        textAlign: 'left', cursor: 'pointer',
                      }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <span style={{ fontSize: 12, fontWeight: 600, color: t.textPrimary }}>{m.label}</span>
                        <span style={{ fontSize: 10, color: enabled ? t.accent : t.textMuted }}>
                          {enabled ? 'ON' : 'OFF'}
                        </span>
                      </div>
                      <div style={{ fontSize: 10, color: t.textMuted, marginTop: 2 }}>{m.desc}</div>
                    </button>
                  );
                })}
              </div>

              <h4 style={{ fontSize: 12, fontWeight: 600, color: t.textMuted, margin: '0 0 8px 0', textTransform: 'uppercase', letterSpacing: 0.4 }}>
                Memory Backend
              </h4>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 8 }}>
                {BACKEND_TYPES.map(b => {
                  const selected = backendType === b.id;
                  return (
                    <button key={b.id}
                      onClick={() => setBackendType(b.id)}
                      style={{
                        padding: 10, borderRadius: 6,
                        background: selected ? `${t.accent}15` : t.bgSidebar,
                        border: `1px solid ${selected ? t.accent : t.border}`,
                        textAlign: 'left', cursor: 'pointer',
                      }}>
                      <div style={{ fontSize: 12, fontWeight: 600, color: t.textPrimary }}>{b.label}</div>
                      <div style={{ fontSize: 10, color: t.textMuted, marginTop: 2 }}>{b.desc}</div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {activeSection === 'guardrails' && (
            <div>
              <h3 style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary, margin: '0 0 4px 0' }}>Guardrails & Safety</h3>
              <p style={{ fontSize: 12, color: t.textMuted, margin: '0 0 12px 0' }}>Safety controls and resource limits for this agent.</p>

              <div style={cardStyle}>
                <label style={labelStyle}>Safety Controls</label>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <button onClick={() => setEnableAutoEviction(!enableAutoEviction)} style={toggleBtn(enableAutoEviction)}>
                    Auto Eviction
                  </button>
                  <button onClick={() => setEnableSummarization(!enableSummarization)} style={toggleBtn(enableSummarization)}>
                    Auto Summarization
                  </button>
                  <button onClick={() => setLongTermMemory(!longTermMemory)} style={toggleBtn(longTermMemory)}>
                    Long-term Memory
                  </button>
                </div>
              </div>

              <div style={cardStyle}>
                <label style={labelStyle}>Token Limit</label>
                <input type="number" value={tokenLimit} onChange={e => setTokenLimit(e.target.value === '' ? '' : Number(e.target.value))}
                  placeholder="8000" style={inputBase} min={1} />
                <div style={{ fontSize: 11, color: t.textMuted, marginTop: 4 }}>
                  Maximum tokens per execution before auto-summarization kicks in.
                </div>
              </div>
            </div>
          )}

          {activeSection === 'json' && (
            <div>
              <h3 style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary, margin: '0 0 4px 0' }}>Config JSON</h3>
              <p style={{ fontSize: 12, color: t.textMuted, margin: '0 0 12px 0' }}>Raw configuration that will be submitted. Edit sections above to modify values.</p>
              <textarea
                readOnly
                value={JSON.stringify(buildConfig(), null, 2)}
                rows={24}
                style={{
                  ...inputBase,
                  fontFamily: '"SF Mono", "Fira Code", monospace',
                  fontSize: 11, lineHeight: 1.5, resize: 'vertical',
                }}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}