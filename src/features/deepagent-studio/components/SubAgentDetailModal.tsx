/**
 * SubAgentDetailModal — full-screen popup showing all sub-agent / skill
 * details (description, model, tools, full instructions preview).
 *
 * Triggered by clicking a sub-agent node (dispatches 'da:open-subagent-detail').
 */

import { useEffect, useState } from 'react';
import { X, Copy, Check, ExternalLink, FlaskConical, Tag, Zap, Clock, TrendingUp, FileCode } from 'lucide-react';

interface SubAgentDetail {
  id?: string;
  label: string;
  description: string;
  source: 'skill' | 'user' | 'generated';
  model?: string;
  tools: string[];
  instructions_preview?: string;
  status: 'idle' | 'running' | 'success' | 'error';
  // Extended review fields (from /api/skills/{id} response)
  version?: string;
  source_type?: string;
  source_path?: string;
  tags?: string[];
  triggers?: string[];
  examples?: Array<{ user?: string; assistant?: string }> | any[];
  usage_count?: number;
  last_used_at?: string | null;
  avg_success_rate?: number;
  required_context?: string[];
  author?: string;
}

export default function SubAgentDetailModal() {
  const [data, setData] = useState<SubAgentDetail | null>(null);
  const [promptExpanded, setPromptExpanded] = useState(true);  // open by default — skill.md is the main thing
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const handler = async (e: Event) => {
      const ce = e as CustomEvent<SubAgentDetail>;
      // Set the basic data immediately so the modal opens fast
      setData(ce.detail);
      setPromptExpanded(true);

      // If this is a skill-backed sub-agent, fetch the full skill detail
      // to populate review fields (tags, triggers, examples, stats, etc.)
      if (ce.detail.source === 'skill' && ce.detail.id) {
        try {
          const baseURL = (window as any).__DA_API_BASE__ ?? 'http://localhost:8765';
          const res = await fetch(`${baseURL}/api/skills/${encodeURIComponent(ce.detail.id)}`);
          if (res.ok) {
            const detail = await res.json();
            setData(prev => prev ? { ...prev, ...detail } : prev);
          }
        } catch (err) {
          // Non-fatal — basic info still shown
          console.warn('[SubAgentDetailModal] failed to fetch full skill detail', err);
        }
      }
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
        className="relative rounded-2xl shadow-2xl w-full max-w-3xl max-h-[92vh] overflow-hidden flex flex-col"
        style={{
          backgroundColor: '#FAF9F5',
          border: '2px solid #D97757',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Compact header — saves vertical space for the prompt */}
        <div
          className="flex items-center gap-2.5 px-4 py-2"
          style={{
            background: 'linear-gradient(135deg, #D97757 0%, #A85A2E 100%)',
          }}
        >
          <span className="text-xl">🤖</span>
          <div className="flex-1 min-w-0 flex items-center gap-2 flex-wrap">
            <div className="text-base font-bold truncate" style={{ color: '#FFFFFF' }}>
              {data.label}
            </div>
            <span
              className="text-[9px] px-1.5 py-px rounded font-bold uppercase tracking-wider"
              style={{ backgroundColor: 'rgba(255,255,255,0.20)', color: '#FFFFFF' }}
            >
              {sourceLabel}
            </span>
            <span
              className="text-[9px] px-1.5 py-px rounded font-mono"
              style={{ backgroundColor: 'rgba(255,255,255,0.15)', color: '#FFFFFF' }}
            >
              ● {data.status}
            </span>
            {data.model && (
              <span
                className="text-[9px] px-1.5 py-px rounded font-mono"
                style={{ backgroundColor: 'rgba(255,255,255,0.15)', color: '#FFFFFF' }}
                title={`Model: ${data.model}`}
              >
                {data.model}
              </span>
            )}
            {/* Open in Skill Builder — visible when this is a skill-backed sub-agent */}
            {data.source === 'skill' && data.id && (
              <button
                onClick={() => {
                  // Close modal and navigate to /skills library
                  window.dispatchEvent(new CustomEvent('da:navigate-skills', { detail: { skillId: data.id } }));
                  setData(null);
                }}
                className="flex items-center gap-1 text-[9px] px-2 py-px rounded font-bold uppercase tracking-wider transition-colors"
                style={{ backgroundColor: '#FFFFFF', color: '#A85A2E' }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.backgroundColor = '#F5E6DC'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.backgroundColor = '#FFFFFF'; }}
                title={`Open ${data.id} in Skill Library / Builder`}
              >
                <ExternalLink size={10} />
                Open in Builder
              </button>
            )}
          </div>
          <button
            onClick={() => setData(null)}
            className="rounded-full p-1 flex items-center justify-center transition-colors flex-shrink-0"
            style={{ backgroundColor: 'rgba(255,255,255,0.15)', color: '#FFFFFF' }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'rgba(255,255,255,0.3)'; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'rgba(255,255,255,0.15)'; }}
            title="Close (Esc)"
          >
            <X size={14} />
          </button>
        </div>

        {/* Body — scrollable */}
        <div className="flex-1 overflow-auto px-5 py-4 space-y-4">
          {/* Description */}
          {data.description && (
            <Section title="Description" icon="📋">
              <p className="text-sm" style={{ color: '#1F1E1B', lineHeight: 1.6 }}>{data.description}</p>
            </Section>
          )}

          {/* Construction & Testing — version, source, tags, triggers, examples, stats */}
          {(data.version || data.source_type || data.source_path || data.tags?.length || data.triggers?.length || data.usage_count !== undefined) && (
            <Section title="Construction & Testing" icon="🔬">
              {/* Row: version + source_type + author + path */}
              <div className="flex items-center gap-2 flex-wrap mb-2">
                {data.version && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded font-mono"
                    style={{ backgroundColor: '#F5E6DC', color: '#A85A2E', border: '1px solid #D97757' }}>
                    v{data.version}
                  </span>
                )}
                {data.source_type && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded font-mono"
                    style={{ backgroundColor: '#FAF9F5', color: '#5C5A55', border: '1px solid #C8B6A6' }}>
                    source: {data.source_type}
                  </span>
                )}
                {data.author && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded font-mono"
                    style={{ backgroundColor: '#FAF9F5', color: '#5C5A55', border: '1px solid #C8B6A6' }}>
                    by {data.author}
                  </span>
                )}
                {data.source_path && (
                  <span className="text-[10px] font-mono flex items-center gap-1"
                    style={{ color: '#5C5A55' }} title={`Source file: ${data.source_path}`}>
                    <FileCode size={10} /> {data.source_path.length > 40 ? `…${data.source_path.slice(-37)}` : data.source_path}
                  </span>
                )}
              </div>

              {/* Tags */}
              {data.tags && data.tags.length > 0 && (
                <div className="mb-2 flex items-start gap-2 flex-wrap">
                  <span className="text-[10px] uppercase tracking-wider font-bold flex items-center gap-1 flex-shrink-0"
                    style={{ color: '#A85A2E' }}>
                    <Tag size={10} /> Tags
                  </span>
                  {data.tags.map(t => (
                    <span key={t} className="text-[10px] px-1.5 py-0.5 rounded font-mono"
                      style={{ backgroundColor: 'rgba(168,90,46,0.08)', color: '#A85A2E', border: '1px dashed #C8B6A6' }}>
                      {t}
                    </span>
                  ))}
                </div>
              )}

              {/* Triggers — when the router picks this skill */}
              {data.triggers && data.triggers.length > 0 && (
                <div className="mb-2">
                  <div className="text-[10px] uppercase tracking-wider font-bold flex items-center gap-1 mb-1"
                    style={{ color: '#A85A2E' }}>
                    <Zap size={10} /> Triggers (when router picks this skill)
                  </div>
                  <ul className="text-xs space-y-0.5" style={{ color: '#1F1E1B' }}>
                    {data.triggers.map((t, i) => (
                      <li key={i} className="flex items-start gap-1.5">
                        <span style={{ color: '#D97757' }}>›</span>
                        <span>{t}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Usage stats */}
              {(data.usage_count !== undefined || data.last_used_at !== undefined || data.avg_success_rate !== undefined) && (
                <div className="flex items-center gap-3 flex-wrap px-2.5 py-1.5 rounded-lg"
                  style={{ backgroundColor: '#FFFFFF', border: '1px solid #E8E4DA' }}>
                  <div className="flex items-center gap-1">
                    <FlaskConical size={11} style={{ color: '#A85A2E' }} />
                    <span className="text-[10px] uppercase tracking-wider font-bold" style={{ color: '#A85A2E' }}>
                      Tested
                    </span>
                  </div>
                  {data.usage_count !== undefined && (
                    <span className="text-xs font-mono" style={{ color: '#1F1E1B' }}>
                      {data.usage_count}×
                    </span>
                  )}
                  {data.avg_success_rate !== undefined && (
                    <span className="text-xs font-mono flex items-center gap-1" style={{ color: data.avg_success_rate >= 0.8 ? '#10b981' : data.avg_success_rate >= 0.5 ? '#D97757' : '#ef4444' }}>
                      <TrendingUp size={10} />
                      {(data.avg_success_rate * 100).toFixed(0)}% success
                    </span>
                  )}
                  {data.last_used_at && (
                    <span className="text-xs flex items-center gap-1 font-mono" style={{ color: '#5C5A55' }}>
                      <Clock size={10} /> last: {new Date(data.last_used_at).toLocaleString()}
                    </span>
                  )}
                  {data.last_used_at === null && data.usage_count !== undefined && (
                    <span className="text-xs font-mono" style={{ color: '#5C5A55' }}>never used</span>
                  )}
                </div>
              )}

              {/* Examples */}
              {data.examples && Array.isArray(data.examples) && data.examples.length > 0 && (
                <div className="mt-2">
                  <div className="text-[10px] uppercase tracking-wider font-bold mb-1" style={{ color: '#A85A2E' }}>
                    📚 Examples
                  </div>
                  <div className="space-y-1.5 max-h-32 overflow-auto">
                    {data.examples.slice(0, 3).map((ex: any, i: number) => (
                      <div key={i} className="rounded-lg p-2"
                        style={{ backgroundColor: '#FFFFFF', border: '1px solid #E8E4DA' }}>
                        {ex.user && (
                          <div className="text-xs mb-1" style={{ color: '#1F1E1B' }}>
                            <span className="font-bold" style={{ color: '#A85A2E' }}>USER:</span> {ex.user}
                          </div>
                        )}
                        {ex.assistant && (
                          <div className="text-xs" style={{ color: '#5C5A55' }}>
                            <span className="font-bold" style={{ color: '#A85A2E' }}>ASST:</span> {ex.assistant}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </Section>
          )}

          {/* Configuration — single compact row: total + tool names inline */}
          <Section title="Configuration" icon="⚙️">
            <div
              className="px-3 py-2 rounded-lg flex items-start gap-2 flex-wrap"
              style={{ backgroundColor: '#F5E6DC', border: '1px solid #D97757' }}
            >
              <span
                className="text-[10px] uppercase tracking-widest font-bold flex-shrink-0"
                style={{ color: '#A85A2E' }}
              >
                Tools ({data.tools?.length ?? 0}):
              </span>
              {data.tools && data.tools.length > 0 ? (
                <div className="flex flex-wrap gap-1 flex-1">
                  {data.tools.map(t => (
                    <span
                      key={t}
                      className="text-[10px] px-1.5 py-0.5 rounded font-mono"
                      style={{ backgroundColor: '#FAF9F5', color: '#A85A2E', border: '1px solid #D97757' }}
                    >
                      🔧 {t}
                    </span>
                  ))}
                </div>
              ) : (
                <span className="text-[11px]" style={{ color: '#5C5A55' }}>
                  none — uses main agent's tools via delegation
                </span>
              )}
            </div>
          </Section>

          {/* Skill ID (when source='skill') — small inline chip */}
          {data.source === 'skill' && data.id && (
            <div className="flex items-center gap-2">
              <span
                className="text-[10px] uppercase tracking-widest font-bold"
                style={{ color: '#A85A2E' }}
              >
                🎯 Skill
              </span>
              <code
                className="text-xs font-mono px-2 py-0.5 rounded"
                style={{ backgroundColor: 'rgba(168,90,46,0.10)', color: '#A85A2E', border: '1px dashed #D97757' }}
              >
                {data.id}
              </code>
            </div>
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
                <button
                  onClick={() => setPromptExpanded(v => !v)}
                  className="text-[10px] px-2 py-0.5 rounded font-medium"
                  style={{ backgroundColor: '#D97757', color: '#FFFFFF' }}
                  title={promptExpanded ? 'Collapse prompt' : 'Expand prompt to fill more'}
                >
                  {promptExpanded ? '▲ Collapse' : '▼ Expand'}
                </button>
              </div>
            }
          >
            {prompt ? (
              <pre
                className="text-sm leading-relaxed p-3 rounded-lg font-mono whitespace-pre-wrap overflow-auto"
                style={{
                  backgroundColor: '#FFFFFF',
                  color: '#1F1E1B',
                  border: '1px solid #E8E4DA',
                  maxHeight: promptExpanded ? 560 : 200,
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