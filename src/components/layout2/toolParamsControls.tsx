/**
 * Per-agent tool options, rendered INSIDE the tool box of an agent's tool panel
 * (AgentEditor → Tools, DeepAgentCreator → Tools).
 *
 * These write `config.tool_params[<tool_id>]`, which the platform hard-pins onto
 * the tool at agent build time (`core/tools/tool_params.py::_with_defaults`):
 * pinned args are removed from the model-facing schema and injected on every
 * call, so the configured value is authoritative for THAT agent while the tool
 * itself stays shared. Both factories apply it — AgentFactory.create_agent and
 * DeepAgentFactory._load_base_tools.
 *
 * Only tools that actually have typed options are rendered; everything else
 * falls back to the generic JSON editor in ToolInspectModal.
 */
import type { CSSProperties, MouseEvent } from 'react';

import type { LayoutTokens } from './tokens';

export interface VisionModelOption {
  id: string;
  name: string;
}

interface Props {
  /** Tool id, e.g. `read_any_file`. */
  toolId: string;
  /** Current `tool_params[toolId]` (may be undefined). */
  params?: Record<string, any>;
  /** Persist the new params object for this tool. */
  onChange: (params: Record<string, any>) => void;
  /** Vision-capable cloud models for the model picker. */
  visionModels?: VisionModelOption[];
  t: LayoutTokens;
}

/** Tool ids that have typed controls here. */
const TOOLS_WITH_OPTIONS = new Set(['read_any_file']);

const selectStyle = (t: LayoutTokens): CSSProperties => ({
  width: '100%',
  height: 24,
  boxSizing: 'border-box',
  padding: '0 6px',
  borderRadius: 4,
  fontSize: 10,
  fontFamily: 'inherit',
  background: 'transparent',
  color: t.textPrimary,
  border: `1px solid ${t.border}`,
  outline: 'none',
  cursor: 'pointer',
});

const labelStyle = (t: LayoutTokens): CSSProperties => ({
  fontSize: 9,
  letterSpacing: 0.3,
  textTransform: 'uppercase',
  color: t.textMuted,
  marginBottom: 2,
});

export default function ToolParamsControls({
  toolId, params, onChange, visionModels = [], t,
}: Props) {
  if (!TOOLS_WITH_OPTIONS.has(toolId)) return null;

  const current = params || {};
  // Absent `vision` = not pinned = the model decides per call (schema default).
  const mode: 'default' | 'vision' | 'ocr' =
    current.vision === false ? 'ocr' : current.vision === true ? 'vision' : 'default';

  const setMode = (next: 'default' | 'vision' | 'ocr') => {
    const out: Record<string, any> = { ...current };
    if (next === 'default') delete out.vision;
    else out.vision = next === 'vision';
    onChange(out);
  };

  const setModel = (model: string) => {
    const out: Record<string, any> = { ...current };
    if (model) out.vision_model = model;
    else delete out.vision_model;
    onChange(out);
  };

  // Stop the card's own onClick (which opens the inspect modal) from firing.
  const swallow = (e: MouseEvent) => e.stopPropagation();

  return (
    <div
      onClick={swallow}
      onMouseDown={swallow}
      style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 2 }}
    >
      <div>
        <div style={labelStyle(t)}>Image reading</div>
        <select
          value={mode}
          onChange={(e) => setMode(e.target.value as 'default' | 'vision' | 'ocr')}
          style={selectStyle(t)}
          title="Pinned for this agent only — the same tool stays shared with every other agent."
        >
          <option value="default">Default (model decides)</option>
          <option value="vision">Vision + OCR</option>
          <option value="ocr">OCR only (no model call)</option>
        </select>
      </div>

      {mode !== 'ocr' && (
        <div>
          <div style={labelStyle(t)}>Vision model</div>
          <select
            value={current.vision_model || ''}
            onChange={(e) => setModel(e.target.value)}
            style={selectStyle(t)}
            title="Which model reads images for this agent."
          >
            <option value="">Platform default</option>
            {visionModels.map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>
        </div>
      )}

      {(mode !== 'default' || current.vision_model || current.question) && (
        <div style={{ fontSize: 9, color: t.accentMuted, lineHeight: '12px' }}>
          pinned for this agent
        </div>
      )}
    </div>
  );
}
