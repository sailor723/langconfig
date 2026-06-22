/**
 * SubAgentDetailModal — full-screen popup showing all sub-agent / skill
 * details (description, model, tools, full instructions preview).
 *
 * Triggered by clicking a sub-agent node (dispatches 'da:open-subagent-detail').
 */

import { useEffect, useState } from 'react';
import { X, Copy, Check } from 'lucide-react';

interface SubAgentDetail {
  id?: string;
  label: string;
  description: string;
  source: 'skill' | 'user' | 'generated';
  model?: string;
  tools: string[];
  instructions_preview?: string;
  status: 'idle' | 'running' | 'success' | 'error';
}

export default function SubAgentDetailModal() {
  const [data, setData] = useState<SubAgentDetail | null>(null);
  const [promptExpanded, setPromptExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const handler = (e: Event) => {
      const ce = e as CustomEvent<SubAgentDetail>;
      setData(ce.detail);
      setPromptExpanded(false);
    };
    window.addEventListener('da:open-subagent-detail', handler);
    return () => window.removeEventListener('da:open-subagent-detail', handler);
  }, []);

  // Close on ESC
  useEffect(() => {
    if (!data) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setData(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [data]);

  if (!data) return null;

  const prompt = data.instructions_preview ?? '';
  const sourceLabel = data.source === 'skill' ? 'Skill-backed' : data.source === 'user' ? 'User-defined' : 'Generated';

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
      style={{ backgroundColor: 'rgba(31,30,27,0.55)' }}
      onClick={() => setData(null)}
    >
      <div
        className="relative rounded-2xl shadow-2xl w-full max-w-2xl max-h-[88vh] overflow-hidden flex flex-col"
        style={{
          backgroundColor: '#FAF9F5',
          border: '2px solid #D97757',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="flex items-center gap-3 px-5 py-3"
          style={{
            background: 'linear-gradient(135deg, #D97757 0%, #A85A2E 100%)',
          }}
        >
          <span className="text-3xl">🤖</span>
          <div className="flex-1 min-w-0">
            <div className="text-[10px] uppercase tracking-widest font-bold" style={{ color: '#FAF9F5', opacity: 0.85 }}>
              Sub-Agent
            </div>
            <div className="text-lg font-bold truncate" style={{ color: '#FFFFFF' }}>
              {data.label}
            </div>
            <div className="text-[11px] mt-0.5" style={{ color: '#FAF9F5', opacity: 0.85 }}>
              {sourceLabel} · status: {data.status}
            </div>
          </div>
          <button
            onClick={() => setData(null)}
            className="rounded-full p-1.5 flex items-center justify-center transition-colors"
            style={{ backgroundColor: 'rgba(255,255,255,0.15)', color: '#FFFFFF' }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'rgba(255,255,255,0.3)'; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'rgba(255,255,255,0.15)'; }}
            title="Close (Esc)"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body — scrollable */}
        <div className="flex-1 overflow-auto px-5 py-4 space-y-4">
          {/* Description */}
          {data.description && (
            <Section title="Description" icon="📋">
              <p style={{ color: '#1F1E1B', lineHeight: 1.5 }}>{data.description}</p>
            </Section>
          )}

          {/* Model + Tools */}
          <Section title="Configuration" icon="⚙️">
            <div className={`grid gap-3 ${data.model ? 'grid-cols-2' : 'grid-cols-1'}`}>
              {data.model && (
                <div className="px-3 py-2 rounded-lg" style={{ backgroundColor: '#F5E6DC', border: '1px solid #D97757' }}>
                  <div className="text-[10px] uppercase tracking-widest font-bold" style={{ color: '#A85A2E' }}>
                    Model
                  </div>
                  <div className="font-mono text-sm mt-0.5 truncate" style={{ color: '#1F1E1B' }} title={data.model}>
                    {data.model}
                  </div>
                </div>
              )}
              <div className="px-3 py-2 rounded-lg" style={{ backgroundColor: '#F5E6DC', border: '1px solid #D97757' }}>
                <div className="text-[10px] uppercase tracking-widest font-bold" style={{ color: '#A85A2E' }}>
                  Tools Bound
                </div>
                <div className="font-mono text-sm mt-0.5" style={{ color: '#1F1E1B' }}>
                  {data.tools?.length ?? 0}
                </div>
              </div>
            </div>
            {data.tools && data.tools.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {data.tools.map(t => (
                  <span
                    key={t}
                    className="text-xs px-2 py-0.5 rounded font-mono"
                    style={{ backgroundColor: '#FAF9F5', color: '#A85A2E', border: '1px solid #D97757' }}
                  >
                    🔧 {t}
                  </span>
                ))}
              </div>
            )}
            {(!data.tools || data.tools.length === 0) && (
              <div
                className="mt-2 px-3 py-2 rounded-lg text-[11px]"
                style={{ backgroundColor: '#FFFFFF', color: '#5C5A55', border: '1px dashed #C8B6A6' }}
              >
                No native tools bound — uses the main agent's tools via delegation.
              </div>
            )}
          </Section>

          {/* Skill ID (when source='skill') */}
          {data.source === 'skill' && data.id && (
            <Section title="Skill Identity" icon="🎯">
              <div
                className="px-3 py-2 rounded-lg font-mono text-sm"
                style={{ backgroundColor: 'rgba(168,90,46,0.10)', color: '#A85A2E', border: '1px dashed #D97757' }}
              >
                skill: {data.id}
              </div>
            </Section>
          )}

          {/* Skill prompt / instructions */}
          <Section
            title="Skill Prompt (Instructions Preview)"
            icon="📜"
            right={
              <div className="flex items-center gap-1.5">
                {prompt && (
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(prompt);
                      setCopied(true);
                      setTimeout(() => setCopied(false), 1500);
                    }}
                    className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded font-medium"
                    style={{
                      backgroundColor: copied ? '#10b981' : '#FAF9F5',
                      color: copied ? '#FFFFFF' : '#A85A2E',
                      border: '1px solid #D97757',
                      transition: 'all 0.15s',
                    }}
                    title="Copy prompt to clipboard"
                  >
                    {copied ? <><Check size={11} /> Copied</> : <><Copy size={11} /> Copy</>}
                  </button>
                )}
                {prompt.length > 200 && (
                  <button
                    onClick={() => setPromptExpanded(v => !v)}
                    className="text-[10px] px-2 py-0.5 rounded font-medium"
                    style={{ backgroundColor: '#D97757', color: '#FFFFFF' }}
                  >
                    {promptExpanded ? '▲ Collapse' : '▼ Expand'}
                  </button>
                )}
              </div>
            }
          >
            {prompt ? (
              <pre
                className="text-[11px] leading-relaxed p-3 rounded-lg font-mono whitespace-pre-wrap overflow-auto"
                style={{
                  backgroundColor: '#FFFFFF',
                  color: '#1F1E1B',
                  border: '1px solid #E8E4DA',
                  maxHeight: promptExpanded ? 480 : 180,
                  transition: 'max-height 0.2s',
                }}
              >
                {prompt}
              </pre>
            ) : (
              <div
                className="px-3 py-4 rounded-lg text-[11px] text-center"
                style={{ backgroundColor: '#FFFFFF', color: '#5C5A55', border: '1px dashed #C8B6A6' }}
              >
                <div className="mb-1">📜</div>
                <div>No instructions_preview available for this skill.</div>
                <div className="mt-1 opacity-70">Try reloading or check the skill source on the backend.</div>
              </div>
            )}
            <div className="text-[10px] mt-1 flex justify-between" style={{ color: '#5C5A55' }}>
              <span>{prompt ? `${prompt.length} chars · ${prompt.split(/\s+/).filter(Boolean).length} words` : 'no content'}</span>
              <span>source: skill registry</span>
            </div>
          </Section>
        </div>

        {/* Footer */}
        <div
          className="px-5 py-2.5 flex items-center justify-between"
          style={{ backgroundColor: '#F5E6DC', borderTop: '1px solid #E8E4DA' }}
        >
          <span className="text-[10px]" style={{ color: '#A85A2E' }}>
            Press <kbd className="px-1.5 py-0.5 rounded text-[9px] font-mono" style={{ backgroundColor: '#FFFFFF', border: '1px solid #D97757' }}>Esc</kbd> to close
          </span>
          <span className="text-[10px]" style={{ color: '#A85A2E' }}>
            DeepAgent Studio · Phase 8
          </span>
        </div>
      </div>
    </div>
  );
}

/** Section block used inside the modal. */
function Section({
  title, icon, right, children,
}: {
  title: string;
  icon: string;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5">
          <span className="text-sm">{icon}</span>
          <span
            className="text-[11px] uppercase tracking-widest font-bold"
            style={{ color: '#A85A2E' }}
          >
            {title}
          </span>
        </div>
        {right}
      </div>
      {children}
    </div>
  );
}