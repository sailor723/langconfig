/**
 * MainAgentNode — center node, the hero of the visualization.
 * Read-only display of the DeepAgent's core config.
 */

import { memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';

interface Data {
  label: string;
  model: string;
  prompt_preview: string;
  temperature: number;
  max_tokens: number;
  middleware: string[];
}

const MainAgentNode = memo(({ data, selected }: NodeProps<Data>) => {
  const borderColor = selected ? '#10b981' : 'var(--color-primary)';
  return (
    <div
      className="rounded-2xl px-4 py-3 shadow-lg"
      style={{
        backgroundColor: 'var(--color-panel-dark)',
        border: `2px solid ${borderColor}`,
        minWidth: 260,
        color: 'var(--color-text-primary)',
      }}
    >
      {/* Handles for edges (sub-agents connect to source bottom) */}
      <Handle type="source" position={Position.Bottom} style={{ background: 'var(--color-primary)', opacity: 0 }} />
      <Handle type="target" position={Position.Top} style={{ background: 'var(--color-primary)', opacity: 0 }} />

      {/* Header */}
      <div className="flex items-center gap-2 mb-2">
        <span
          className="inline-flex items-center justify-center rounded-lg text-lg"
          style={{ width: 32, height: 32, backgroundColor: 'var(--color-primary)', color: '#fff' }}
        >
          🤖
        </span>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold truncate">{data.label}</div>
          <div className="text-[10px] font-mono truncate" style={{ color: 'var(--color-text-muted)' }}>
            {data.model}
          </div>
        </div>
        <span
          className="text-[9px] px-1.5 py-0.5 rounded font-bold uppercase"
          style={{ backgroundColor: 'var(--color-primary)', color: '#fff' }}
        >
          ★ Main
        </span>
      </div>

      {/* Stats row */}
      <div className="flex items-center gap-2 text-[10px] mb-2" style={{ color: 'var(--color-text-muted)' }}>
        <span>🌡 {data.temperature.toFixed(1)}</span>
        <span>📏 {data.max_tokens.toLocaleString()}t</span>
        {data.middleware.length > 0 && <span>🔧 {data.middleware.length} mw</span>}
      </div>

      {/* Prompt preview */}
      {data.prompt_preview && (
        <div
          className="text-[10px] px-2 py-1 rounded leading-relaxed"
          style={{
            backgroundColor: 'var(--color-input-background)',
            color: 'var(--color-text-muted)',
            maxHeight: 60,
            overflow: 'hidden',
          }}
        >
          {data.prompt_preview}
          {data.prompt_preview.length >= 200 && '…'}
        </div>
      )}
    </div>
  );
});

MainAgentNode.displayName = 'MainAgentNode';
export default MainAgentNode;