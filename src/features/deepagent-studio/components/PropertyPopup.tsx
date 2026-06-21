/**
 * PropertyPopup — modal that opens when the user clicks a property row
 * inside the Main Agent node. Displays full details for that property,
 * with a visual "← back to {agent name}" indicator (the back-line).
 */

import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import type { AgentStructure } from '../types';

interface PopupState {
  nodeId: string;
  nodeLabel: string;
  prop: string;
}

interface Props {
  structure: AgentStructure | null;
}

const PROP_META: Record<string, { label: string; icon: string; desc: string }> = {
  llm: { label: 'LLM', icon: '🤖', desc: 'Language model used by the main agent — model, temperature, max tokens.' },
  prompt: { label: 'Prompt', icon: '📜', desc: 'System prompt that defines the agent\'s role, behavior, and tools.' },
  tools: { label: 'Tools', icon: '🔧', desc: 'Native tools always available to the main agent (called directly without delegation).' },
};

export default function PropertyPopup({ structure }: Props) {
  const [popup, setPopup] = useState<PopupState | null>(null);

  useEffect(() => {
    const handler = (e: Event) => {
      const ce = e as CustomEvent<PopupState>;
      setPopup(ce.detail);
    };
    window.addEventListener('da:open-property', handler);
    return () => window.removeEventListener('da:open-property', handler);
  }, []);

  if (!popup || !structure) return null;

  const meta = PROP_META[popup.prop];
  if (!meta) return null;

  const mainAgent = structure.main_agent;
  let content: React.ReactNode = null;

  switch (popup.prop) {
    case 'llm':
      content = (
        <div className="space-y-3">
          <Row label="Model" value={mainAgent.model} mono />
          <Row label="Temperature" value={mainAgent.temperature.toFixed(2)} mono />
          <Row label="Max Tokens" value={mainAgent.max_tokens?.toLocaleString() ?? '—'} mono />
          <div
            className="text-[11px] px-3 py-2 rounded leading-relaxed mt-3"
            style={{ backgroundColor: 'var(--color-input-background)', color: 'var(--color-text-muted)' }}
          >
            💡 Temperature 0 = deterministic · 1 = very creative · 0.7 = balanced. Max tokens caps each response.
          </div>
        </div>
      );
      break;

    case 'prompt':
      content = (
        <div>
          <div className="flex items-center justify-between mb-2">
            <div className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: 'var(--color-text-muted)' }}>
              System Prompt · {mainAgent.system_prompt_preview.length} chars
            </div>
          </div>
          <pre
            className="text-[11px] leading-relaxed p-3 rounded font-mono whitespace-pre-wrap overflow-auto"
            style={{
              backgroundColor: 'var(--color-input-background)',
              color: 'var(--color-text-primary)',
              maxHeight: 480,
              border: '1px solid var(--color-border)',
            }}
          >
            {mainAgent.system_prompt_preview || '(empty — no system prompt configured)'}
          </pre>
        </div>
      );
      break;

    case 'tools':
      content = (
        <div>
          <div className="text-[10px] uppercase tracking-widest font-semibold mb-2" style={{ color: 'var(--color-text-muted)' }}>
            {mainAgent.tools.length} Native Tools
          </div>
          {mainAgent.tools.length === 0 ? (
            <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
              (no native tools configured)
            </div>
          ) : (
            <div className="space-y-1">
              {mainAgent.tools.map(t => (
                <div
                  key={t}
                  className="text-xs px-3 py-1.5 rounded font-mono flex items-center gap-2"
                  style={{ backgroundColor: 'var(--color-input-background)', color: '#93c5fd' }}
                >
                  <span>🔧</span>
                  <span>{t}</span>
                </div>
              ))}
            </div>
          )}
          <div
            className="text-[11px] px-3 py-2 rounded leading-relaxed mt-3"
            style={{ backgroundColor: 'var(--color-input-background)', color: 'var(--color-text-muted)' }}
          >
            💡 Native tools are bound directly to the main agent — no delegation needed. Different from sub-agent tools (which require <code>task()</code>).
          </div>
        </div>
      );
      break;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-6"
      style={{ backgroundColor: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(2px)' }}
      onClick={() => setPopup(null)}
    >
      <div
        className="rounded-xl shadow-2xl max-w-2xl w-full max-h-[80vh] overflow-hidden flex flex-col"
        style={{
          backgroundColor: 'var(--color-panel-dark)',
          border: '1px solid var(--color-border)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header with back-line indicator */}
        <div
          className="flex items-center justify-between px-4 py-3 border-b"
          style={{ borderColor: 'var(--color-border)', backgroundColor: 'rgba(255,255,255,0.02)' }}
        >
          <div className="flex items-center gap-3">
            <span className="text-2xl">{meta.icon}</span>
            <div>
              <div className="text-base font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                {meta.label}
              </div>
              {/* Visual "back-line" — text + connector symbol */}
              <div
                className="text-[10px] font-mono flex items-center gap-1 mt-0.5"
                style={{ color: 'var(--color-text-muted)' }}
              >
                <span
                  className="inline-block"
                  style={{
                    borderLeft: '1.5px solid var(--color-primary)',
                    borderBottom: '1.5px solid var(--color-primary)',
                    width: 10,
                    height: 10,
                    transform: 'rotate(45deg)',
                  }}
                />
                <span>back to:</span>
                <span style={{ color: 'var(--color-primary)' }}>🤖 {popup.nodeLabel}</span>
              </div>
            </div>
          </div>
          <button
            onClick={() => setPopup(null)}
            className="p-1.5 rounded hover:bg-white/10 transition-colors"
            style={{ color: 'var(--color-text-muted)' }}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Description */}
        <div className="px-5 pt-3 pb-1 text-[11px]" style={{ color: 'var(--color-text-muted)' }}>
          {meta.desc}
        </div>

        {/* Body */}
        <div className="px-5 py-4 overflow-auto flex-1">
          {content}
        </div>

        {/* Footer */}
        <div
          className="flex items-center justify-between px-4 py-2.5 border-t text-[10px]"
          style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
        >
          <span>Click outside or press Close to return to {popup.nodeLabel}</span>
          <button
            onClick={() => setPopup(null)}
            className="px-3 py-1 rounded font-medium transition-colors"
            style={{ backgroundColor: 'var(--color-primary)', color: '#fff' }}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

/** Simple key/value row in the popup. */
function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div
      className="flex items-center justify-between px-3 py-2 rounded"
      style={{ backgroundColor: 'var(--color-input-background)' }}
    >
      <span className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: 'var(--color-text-muted)' }}>
        {label}
      </span>
      <span
        className={`text-sm ${mono ? 'font-mono' : ''}`}
        style={{ color: 'var(--color-text-primary)' }}
      >
        {value}
      </span>
    </div>
  );
}