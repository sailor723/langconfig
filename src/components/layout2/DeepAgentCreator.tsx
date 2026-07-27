/**
 * DeepAgentCreator — form to create a new DeepAgent from scratch.
 *
 * Opens in a workspace tab. On submit, calls POST /api/deepagents/
 * and switches to the resulting DeepAgentEditor tab.
 */
import { useState } from 'react';
import type { Tab } from './useLayout';
import { useLayoutTokens } from './tokens';
import { useLayoutState } from './useLayout';
import { useAvailableModels } from '../../hooks/useAvailableModels';
import apiClient from '../../lib/api-client';

const CATEGORIES = ['research', 'coding', 'analysis', 'general', 'custom'];

const LS_KEY_DEFAULT = 'langconfig.defaultModel';
function getDefaultModel(): string {
  return localStorage.getItem(LS_KEY_DEFAULT) || '';
}

interface DeepAgentCreatorProps {
  tab: Tab;
}

export default function DeepAgentCreator({ tab }: DeepAgentCreatorProps) {
  const t = useLayoutTokens();
  const { closeTab, openTab } = useLayoutState();
  const { cloudModels, localModels, isLoading: modelsLoading } = useAvailableModels({ includeLocal: true });

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState('general');
  const [systemPrompt, setSystemPrompt] = useState(
    'You are a helpful AI assistant. Be concise and accurate.',
  );
  const [model, setModel] = useState(getDefaultModel);
  const [temperature, setTemperature] = useState(0.7);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = name.trim().length > 0 && systemPrompt.trim().length > 0 && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);

    try {
      const config = {
        system_prompt: systemPrompt.trim(),
        model: model || undefined,
        temperature,
        native_tools: [],
        cli_tools: [],
        custom_tools: [],
        tools: [],
        skills: [],
        middleware: [],
        subagents: [],
        backend: { type: 'memory' },
        guardrails: {
          enable_auto_eviction: false,
          enable_summarization: false,
          long_term_memory: false,
          token_limits: {},
        },
      };

      const res = await apiClient.createDeepAgent({
        name: name.trim(),
        description: description.trim() || undefined,
        category,
        config,
      });

      const agent = res.data;
      // Close the creator tab and open the new agent in DeepAgentEditor
      closeTab(tab.id);
      openTab({
        id: `deepagent-${agent.id}`,
        label: agent.name,
        viewType: 'deepagent',
        data: { agent },
      });
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? err?.message ?? 'unknown error';
      setError(`Failed to create agent: ${detail}`);
    } finally {
      setSubmitting(false);
    }
  };

  // ── Shared input styles ──
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

  return (
    <div style={{
      height: '100%',
      overflow: 'auto',
      padding: 24,
      background: t.bgContent,
    }}>
      <h1 style={{
        fontSize: 20,
        fontWeight: 600,
        color: t.textPrimary,
        margin: '0 0 4px 0',
      }}>
        Create DeepAgent
      </h1>
      <p style={{
        fontSize: 13,
        color: t.textMuted,
        margin: '0 0 20px 0',
      }}>
        Configure a new agent with subagents, middleware, and tool support.
      </p>

      {/* ── Error ── */}
      {error && (
        <div style={{
          ...cardStyle,
          borderColor: '#e5484d',
          color: '#e5484d',
          fontSize: 13,
        }}>
          {error}
        </div>
      )}

      {/* ── Name + Category row ── */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
        <div style={{ flex: 2, ...cardStyle }}>
          <label style={labelStyle}>
            Name <span style={{ color: '#e5484d' }}>*</span>
          </label>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="my-agent"
            style={inputBase}
            autoFocus
          />
        </div>
        <div style={{ flex: 1, ...cardStyle }}>
          <label style={labelStyle}>Category</label>
          <select
            value={category}
            onChange={e => setCategory(e.target.value)}
            style={inputBase}
          >
            {CATEGORIES.map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
      </div>

      {/* ── Description ── */}
      <div style={cardStyle}>
        <label style={labelStyle}>Description</label>
        <input
          value={description}
          onChange={e => setDescription(e.target.value)}
          placeholder="What does this agent do?"
          style={inputBase}
        />
      </div>

      {/* ── System Prompt ── */}
      <div style={cardStyle}>
        <label style={labelStyle}>
          System Prompt <span style={{ color: '#e5484d' }}>*</span>
        </label>
        <textarea
          value={systemPrompt}
          onChange={e => setSystemPrompt(e.target.value)}
          rows={8}
          placeholder="Instructions that define the agent's behavior..."
          style={{
            ...inputBase,
            resize: 'vertical',
            fontFamily: '"SF Mono", "Fira Code", monospace',
            fontSize: 12,
            lineHeight: 1.5,
            minHeight: 120,
          }}
        />
        <div style={{
          fontSize: 11,
          color: t.textMuted,
          marginTop: 4,
          textAlign: 'right',
        }}>
          {systemPrompt.length} chars
        </div>
      </div>

      {/* ── Model + Temperature row ── */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
        <div style={{ flex: 2, ...cardStyle }}>
          <label style={labelStyle}>Model</label>
          <select
            value={model}
            onChange={e => setModel(e.target.value)}
            style={inputBase}
            disabled={modelsLoading}
          >
            <option value="">
              {modelsLoading ? 'Loading models...' : '(Backend default)'}
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
          <div style={{ fontSize: 11, color: t.textMuted, marginTop: 4 }}>
            Default model shown first; select from available providers
          </div>
        </div>
        <div style={{ flex: 1, ...cardStyle }}>
          <label style={labelStyle}>
            Temperature: {temperature.toFixed(1)}
          </label>
          <input
            type="range"
            min={0}
            max={2}
            step={0.1}
            value={temperature}
            onChange={e => setTemperature(parseFloat(e.target.value))}
            style={{ width: '100%', accentColor: t.accent }}
          />
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: 11,
            color: t.textMuted,
          }}>
            <span>precise (0)</span>
            <span>creative (2)</span>
          </div>
        </div>
      </div>

      {/* ── Actions ── */}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
        <button
          onClick={() => closeTab(tab.id)}
          disabled={submitting}
          style={{
            height: 30,
            padding: '0 16px',
            background: 'transparent',
            color: t.textPrimary,
            border: `1px solid ${t.border}`,
            borderRadius: 4,
            fontSize: 12,
            cursor: submitting ? 'not-allowed' : 'pointer',
            opacity: submitting ? 0.6 : 1,
          }}
        >
          Cancel
        </button>
        <button
          onClick={handleSubmit}
          disabled={!canSubmit}
          style={{
            height: 30,
            padding: '0 16px',
            background: canSubmit ? t.accent : t.bgHover,
            color: '#fff',
            border: 'none',
            borderRadius: 4,
            fontSize: 12,
            fontWeight: 600,
            cursor: canSubmit ? 'pointer' : 'not-allowed',
            opacity: canSubmit ? 1 : 0.5,
          }}
        >
          {submitting ? 'Creating...' : 'Create Agent'}
        </button>
      </div>
    </div>
  );
}
