import { useState } from 'react';
import { ChevronDown, ChevronRight, Brain, Wrench } from 'lucide-react';

export interface ThinkingStep {
  type: 'tool_start' | 'tool_end' | 'custom_event';
  tool_name?: string;
  data?: any;
}

interface Props {
  steps: ThinkingStep[];
  defaultExpanded?: boolean;
}

export default function ThinkingBlock({ steps, defaultExpanded = false }: Props) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  if (steps.length === 0) return null;

  return (
    <div className="mt-2">
      <button
        onClick={() => setExpanded(v => !v)}
        className="flex items-center gap-1.5 text-xs font-medium transition-colors rounded-md px-2 py-1 hover:bg-black/5"
        style={{ color: 'var(--color-text-muted)' }}
      >
        {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        <Brain className="w-3.5 h-3.5" />
        <span>{expanded ? 'Hide thinking' : `Show thinking (${steps.length} steps)`}</span>
      </button>

      {expanded && (
        <div
          className="mt-2 rounded-lg border text-xs font-mono overflow-hidden"
          style={{
            backgroundColor: 'var(--color-background-dark, #f9fafb)',
            borderColor: 'var(--color-border-dark, #e5e7eb)',
          }}
        >
          <div className="max-h-72 overflow-y-auto p-3 space-y-2">
            {steps.map((step, i) => (
              <div key={i} className="flex items-start gap-2">
                {step.type === 'tool_start' ? (
                  <Wrench className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-blue-500" />
                ) : (
                  <div className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 flex items-center justify-center">
                    <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                  </div>
                )}
                <div className="flex-1 min-w-0">
                  <div className="font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                    {step.type === 'tool_start' ? `🔧 ${step.tool_name}` : step.type === 'tool_end' ? `✅ ${step.tool_name}` : '📋 progress'}
                  </div>
                  {step.data?.input && (
                    <pre className="mt-0.5 p-1.5 rounded text-[11px] whitespace-pre-wrap overflow-x-auto" style={{ backgroundColor: 'rgba(0,0,0,0.03)', color: 'var(--color-text-muted)' }}>
                      {JSON.stringify(step.data.input, null, 2).slice(0, 200)}
                    </pre>
                  )}
                  {step.type === 'tool_end' && step.data?.output && (
                    <div className="mt-0.5 p-1.5 rounded text-[11px]" style={{ backgroundColor: 'rgba(16,185,129,0.06)', color: 'var(--color-text-muted)' }}>
                      {typeof step.data.output === 'string' ? step.data.output.slice(0, 200) : JSON.stringify(step.data.output).slice(0, 200)}
                      {step.data.output?.length > 200 && '...'}
                    </div>
                  )}
                  {step.data?.payload?.message && (
                    <div style={{ color: 'var(--color-text-muted)' }}>{step.data.payload.message}</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
