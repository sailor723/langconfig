import { useState, useEffect } from 'react';
import { FileText, ChevronDown, ChevronRight, Wrench, BookMarked, Sparkles } from 'lucide-react';
import apiClient from '../../../lib/api-client';

interface ContextPanelProps {
  selectedAgentId: number | null;
  sessionId: string | null;
}

export default function ContextPanel({ selectedAgentId, sessionId }: ContextPanelProps) {
  const [agentConfig, setAgentConfig] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [expandedSection, setExpandedSection] = useState<string | null>('prompt');

  useEffect(() => {
    if (!selectedAgentId) return;
    let cancelled = false;
    setLoading(true);
    apiClient.getDeepAgent(selectedAgentId)
      .then((res: any) => {
        if (cancelled) return;
        const agent = res.data ?? res;
        setAgentConfig(agent?.config ?? agent ?? null);
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [selectedAgentId]);

  const toggleSection = (section: string) => {
    setExpandedSection(prev => prev === section ? null : section);
  };

  const config = agentConfig;
  const systemPrompt = config?.system_prompt || '';
  const skills: string[] = config?.skills || [];
  const tools: string[] = config?.native_tools || config?.tools || [];
  const model = config?.model || '';

  return (
    <div className="text-xs overflow-y-auto h-full" style={{ color: 'var(--color-text-primary)' }}>
      {loading ? (
        <div className="p-4 text-center" style={{ color: 'var(--color-text-muted)' }}>Loading...</div>
      ) : !config ? (
        <div className="p-4 text-center" style={{ color: 'var(--color-text-muted)' }}>No agent selected</div>
      ) : (
        <div className="p-3 space-y-2">
          <div className="flex items-center gap-2 p-2 rounded-lg" style={{ backgroundColor: 'var(--color-background-light)' }}>
            <Sparkles className="w-3.5 h-3.5" style={{ color: 'var(--color-primary)' }} />
            <div>
              <div className="font-medium text-xs">{model || '-'}</div>
            </div>
          </div>

          <div>
            <button onClick={() => toggleSection('prompt')}
              className="flex items-center gap-1.5 w-full text-left py-1.5 font-medium"
              style={{ color: 'var(--color-text-primary)' }}>
              {expandedSection === 'prompt' ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
              <FileText className="w-3.5 h-3.5" />
              <span>System Prompt ({systemPrompt.length} chars)</span>
            </button>
            {expandedSection === 'prompt' && systemPrompt && (
              <pre className="mt-1 p-2 rounded text-[11px] font-mono leading-relaxed whitespace-pre-wrap max-h-48 overflow-y-auto"
                style={{ backgroundColor: 'var(--color-background-light)', color: 'var(--color-text-secondary)' }}>
                {systemPrompt}
              </pre>
            )}
          </div>

          {skills.length > 0 && (
            <div>
              <button onClick={() => toggleSection('skills')}
                className="flex items-center gap-1.5 w-full text-left py-1.5 font-medium"
                style={{ color: 'var(--color-text-primary)' }}>
                {expandedSection === 'skills' ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                <BookMarked className="w-3.5 h-3.5" />
                <span>Skills ({skills.length})</span>
              </button>
              {expandedSection === 'skills' && (
                <div className="mt-1 space-y-1">
                  {skills.map((s: string) => (
                    <div key={s} className="px-2 py-1 rounded text-[11px] font-mono"
                      style={{ backgroundColor: 'var(--color-background-light)' }}>📚 {s}</div>
                  ))}
                </div>
              )}
            </div>
          )}

          {tools.length > 0 && (
            <div>
              <button onClick={() => toggleSection('tools')}
                className="flex items-center gap-1.5 w-full text-left py-1.5 font-medium"
                style={{ color: 'var(--color-text-primary)' }}>
                {expandedSection === 'tools' ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                <Wrench className="w-3.5 h-3.5" />
                <span>Tools ({tools.length})</span>
              </button>
              {expandedSection === 'tools' && (
                <div className="mt-1 space-y-1">
                  {tools.map((t: string) => (
                    <div key={t} className="px-2 py-1 rounded text-[11px] font-mono"
                      style={{ backgroundColor: 'var(--color-background-light)' }}>🔧 {t}</div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
