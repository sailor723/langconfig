/**
 * DetailPanel — right-side panel showing details of the selected node.
 * Read-only display. (Edit button is in the header, not here.)
 */

import { useState } from 'react';
import type { AgentStructure, MainAgentInfo, SubAgent } from '../types';

interface Props {
  structure: AgentStructure | null;
  selectedNodeId: string | null;
}

export default function DetailPanel({ structure, selectedNodeId }: Props) {
  const [expanded, setExpanded] = useState(false);

  if (!structure) {
    return (
      <div
        className="w-72 border-l p-4 text-xs"
        style={{
          backgroundColor: 'var(--color-panel-dark)',
          borderColor: 'var(--color-border)',
          color: 'var(--color-text-muted)',
        }}
      >
        <div className="text-center mt-8">
          <div className="text-3xl mb-2">👈</div>
          <p>Pick an agent to begin</p>
        </div>
      </div>
    );
  }

  const isMain = !selectedNodeId || selectedNodeId === 'main';
  const isTool = selectedNodeId?.startsWith('tool-') ?? false;

  // Tool node case
  if (isTool && selectedNodeId) {
    const toolName = selectedNodeId.replace(/^tool-/, '');
    return (
      <div
        className="w-72 border-l overflow-y-auto scrollbar-thin"
        style={{
          backgroundColor: 'var(--color-panel-dark)',
          borderColor: 'var(--color-border)',
        }}
      >
        <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
          <div className="flex items-center gap-2">
            <span className="text-2xl">🔧</span>
            <div className="flex-1 min-w-0">
              <div className="text-xs uppercase tracking-widest font-bold" style={{ color: '#93c5fd' }}>
                Native Tool
              </div>
              <div className="text-sm font-semibold font-mono truncate" style={{ color: 'var(--color-text-primary)' }}>
                {toolName}
              </div>
            </div>
          </div>
        </div>
        <div className="px-4 py-3 space-y-3 text-xs">
          <div>
            <div className="text-[10px] uppercase tracking-widest font-semibold mb-1" style={{ color: 'var(--color-text-muted)' }}>
              Type
            </div>
            <div style={{ color: 'var(--color-text-primary)' }}>
              Native tool (always available to main agent)
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-widest font-semibold mb-1" style={{ color: 'var(--color-text-muted)' }}>
              Note
            </div>
            <div style={{ color: 'var(--color-text-muted)' }}>
              Native tools are bound directly to the main agent and can be called in any conversation turn. They are separate from sub-agent tools (which require delegation via <code>task()</code>).
            </div>
          </div>
        </div>
      </div>
    );
  }

  const item: MainAgentInfo | SubAgent | null = isMain
    ? structure.main_agent
    : structure.sub_agents.find(s => s.id === selectedNodeId) ?? null;

  if (!item) {
    return (
      <div
        className="w-72 border-l p-4 text-xs"
        style={{
          backgroundColor: 'var(--color-panel-dark)',
          borderColor: 'var(--color-border)',
          color: 'var(--color-text-muted)',
        }}
      >
        <p>No selection</p>
      </div>
    );
  }

  const isMainAgent = isMain;

  return (
    <div
      className="w-72 border-l overflow-y-auto scrollbar-thin"
      style={{
        backgroundColor: 'var(--color-panel-dark)',
        borderColor: 'var(--color-border)',
      }}
    >
      {/* Header */}
      <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
        <div className="flex items-center gap-2">
          <span className="text-2xl">{isMainAgent ? '🤖' : '🔹'}</span>
          <div className="flex-1 min-w-0">
            <div className="text-xs uppercase tracking-widest font-bold" style={{ color: 'var(--color-text-muted)' }}>
              {isMainAgent ? 'Main Agent' : 'Sub-Agent'}
            </div>
            <div className="text-sm font-semibold truncate" style={{ color: 'var(--color-text-primary)' }}>
              {(item as any).name}
            </div>
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-3 text-xs">
        {/* Description */}
        {(item as any).description && (
          <div>
            <div className="text-[10px] uppercase tracking-widest font-semibold mb-1" style={{ color: 'var(--color-text-muted)' }}>
              Description
            </div>
            <div style={{ color: 'var(--color-text-primary)' }}>
              {(item as any).description}
            </div>
          </div>
        )}

        {/* Model (main only) */}
        {isMainAgent && (
          <div>
            <div className="text-[10px] uppercase tracking-widest font-semibold mb-1" style={{ color: 'var(--color-text-muted)' }}>
              Model
            </div>
            <div className="font-mono" style={{ color: 'var(--color-text-primary)' }}>
              {(item as MainAgentInfo).model}
            </div>
          </div>
        )}

        {/* Params (main only) */}
        {isMainAgent && (
          <div className="grid grid-cols-2 gap-2">
            <div>
              <div className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: 'var(--color-text-muted)' }}>
                Temperature
              </div>
              <div className="font-mono" style={{ color: 'var(--color-text-primary)' }}>
                {(item as MainAgentInfo).temperature.toFixed(1)}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: 'var(--color-text-muted)' }}>
                Max Tokens
              </div>
              <div className="font-mono" style={{ color: 'var(--color-text-primary)' }}>
                {(item as MainAgentInfo).max_tokens.toLocaleString()}
              </div>
            </div>
          </div>
        )}

        {/* Middleware (main only) */}
        {isMainAgent && (item as MainAgentInfo).middleware.length > 0 && (
          <div>
            <div className="text-[10px] uppercase tracking-widest font-semibold mb-1" style={{ color: 'var(--color-text-muted)' }}>
              Middleware
            </div>
            <div className="flex flex-wrap gap-1">
              {(item as MainAgentInfo).middleware.map(m => (
                <span key={m} className="text-[10px] px-1.5 py-0.5 rounded"
                  style={{ backgroundColor: 'var(--color-input-background)', color: 'var(--color-text-primary)' }}>
                  {m}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Tools (main only, summary) */}
        {isMainAgent && (item as MainAgentInfo).tools.length > 0 && (
          <div>
            <div className="text-[10px] uppercase tracking-widest font-semibold mb-1" style={{ color: 'var(--color-text-muted)' }}>
              Main Tools ({(item as MainAgentInfo).tools.length})
            </div>
            <div className="flex flex-wrap gap-1">
              {(item as MainAgentInfo).tools.map(t => (
                <span key={t} className="text-[10px] px-1.5 py-0.5 rounded font-mono"
                  style={{ backgroundColor: 'rgba(59,130,246,0.12)', color: '#93c5fd' }}>
                  🔧 {t}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Tools (sub) */}
        {!isMainAgent && (item as SubAgent).tools && (item as SubAgent).tools.length > 0 && (
          <div>
            <div className="text-[10px] uppercase tracking-widest font-semibold mb-1" style={{ color: 'var(--color-text-muted)' }}>
              Allowed Tools ({(item as SubAgent).tools.length})
            </div>
            <div className="flex flex-wrap gap-1">
              {(item as SubAgent).tools.map(t => (
                <span key={t} className="text-[10px] px-1.5 py-0.5 rounded font-mono"
                  style={{ backgroundColor: 'rgba(59,130,246,0.12)', color: '#93c5fd' }}>
                  {t}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Source (sub only) */}
        {!isMainAgent && (
          <div>
            <div className="text-[10px] uppercase tracking-widest font-semibold mb-1" style={{ color: 'var(--color-text-muted)' }}>
              Source
            </div>
            <div style={{ color: 'var(--color-text-primary)' }}>
              {(item as SubAgent).source === 'skill' ? '📚 Auto-generated from Skill' : '👤 User-defined'}
            </div>
          </div>
        )}

        {/* Instructions preview (sub) */}
        {!isMainAgent && (item as SubAgent).instructions_preview && (
          <div>
            <div className="flex items-center justify-between mb-1">
              <div className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: 'var(--color-text-muted)' }}>
                Instructions ({(item as SubAgent).instructions_preview!.length} chars)
              </div>
              <button
                onClick={() => setExpanded(v => !v)}
                className="text-[10px] px-1.5 py-0.5 rounded font-medium transition-colors"
                style={{
                  backgroundColor: 'var(--color-input-background)',
                  color: 'var(--color-text-primary)',
                  border: '1px solid var(--color-border)',
                }}
              >
                {expanded ? '▲ Collapse' : '▼ Expand'}
              </button>
            </div>
            <div
              className="px-2 py-1.5 rounded text-[10px] leading-relaxed"
              style={{
                backgroundColor: 'var(--color-input-background)',
                color: 'var(--color-text-primary)',
                fontFamily: 'monospace',
                whiteSpace: 'pre-wrap',
                overflowY: 'auto',
                maxHeight: expanded ? 600 : 140,
                transition: 'max-height 0.2s',
              }}
            >
              {(item as SubAgent).instructions_preview}
            </div>
          </div>
        )}

        {/* System prompt preview (main) */}
        {isMainAgent && (item as MainAgentInfo).system_prompt_preview && (
          <div>
            <div className="flex items-center justify-between mb-1">
              <div className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: 'var(--color-text-muted)' }}>
                System Prompt ({(item as MainAgentInfo).system_prompt_preview!.length} chars)
              </div>
              <button
                onClick={() => setExpanded(v => !v)}
                className="text-[10px] px-1.5 py-0.5 rounded font-medium transition-colors"
                style={{
                  backgroundColor: 'var(--color-input-background)',
                  color: 'var(--color-text-primary)',
                  border: '1px solid var(--color-border)',
                }}
              >
                {expanded ? '▲ Collapse' : '▼ Expand'}
              </button>
            </div>
            <div
              className="px-2 py-1.5 rounded text-[10px] leading-relaxed"
              style={{
                backgroundColor: 'var(--color-input-background)',
                color: 'var(--color-text-primary)',
                fontFamily: 'monospace',
                whiteSpace: 'pre-wrap',
                overflowY: 'auto',
                maxHeight: expanded ? 600 : 140,
                transition: 'max-height 0.2s',
              }}
            >
              {(item as MainAgentInfo).system_prompt_preview}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}