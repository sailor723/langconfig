/**
 * SkillView — skill detail viewer opened from SkillBrowserSidebar.
 *
 * Shows the full skill definition: name, description, tags, triggers,
 * instructions (the main SKILL.md body), allowed tools, and source files.
 */
import { useEffect, useState, useCallback } from 'react';
import { useLayoutTokens } from './tokens';
import type { Tab } from './useLayout';
import apiClient from '../../lib/api-client';
import {
  Award, Loader, FileText, Wrench, Tag, Zap, BookOpen, ChevronDown, ChevronRight,
} from 'lucide-react';

interface SkillDetail {
  skill_id: string;
  name: string;
  description: string;
  version: string;
  source_type: string;
  tags: string[];
  triggers: string[];
  allowed_tools: string[] | null;
  instructions: string;
  examples: string | null;
  source_path: string;
  author: string | null;
  required_context: string[];
  usage_count: number;
  avg_success_rate: number;
}

interface SkillViewProps {
  tab: Tab;
}

export default function SkillView({ tab }: SkillViewProps) {
  const t = useLayoutTokens();
  const skillId = tab.data?.skillId as string;
  const initial = tab.data?.skill as SkillDetail | undefined;

  const [skill, setSkill] = useState<SkillDetail | null>(initial || null);
  const [loading, setLoading] = useState(!initial);
  const [error, setError] = useState<string | null>(null);
  const [showInstructions, setShowInstructions] = useState(true);

  useEffect(() => {
    if (!skillId) return;
    let cancelled = false;
    setLoading(true);
    apiClient.getSkill(skillId)
      .then(res => { if (!cancelled) setSkill(res.data as SkillDetail); })
      .catch(err => { if (!cancelled) setError(err?.message || 'Failed to load skill'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [skillId]);

  const cardStyle: React.CSSProperties = {
    background: t.bgContent,
    border: `1px solid ${t.border}`,
    borderRadius: 4,
    padding: 12,
    marginBottom: 10,
  };
  const labelStyle: React.CSSProperties = {
    fontSize: 11,
    color: t.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    marginBottom: 4,
  };
  const valueStyle: React.CSSProperties = {
    fontSize: 13,
    color: t.textPrimary,
  };

  if (loading) {
    return (
      <div style={{ padding: 24, display: 'flex', alignItems: 'center', gap: 8, color: t.textMuted }}>
        <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
        Loading skill...
      </div>
    );
  }

  if (error) {
    return <div style={{ padding: 24, color: '#e5484d' }}>{error}</div>;
  }

  if (!skill) {
    return <div style={{ padding: 24, color: t.textMuted }}>Skill not found</div>;
  }

  return (
    /* Scrollable content — same pattern as PromptDetailTab / SkillEditorTab:
       outer column-flex with overflow hidden, inner flex:1 body scrolls */
    <div style={{ height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Scroll body */}
      <div style={{
        flex: 1, minHeight: 0, overflow: 'auto',
        padding: '20px', maxWidth: 800, width: '100%',
        boxSizing: 'border-box', margin: '0 auto',
      }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <Award size={24} style={{ color: t.accent }} />
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: t.textPrimary }}>
            {skill.name || skill.skill_id}
          </div>
          <div style={{ fontSize: 12, color: t.textMuted }}>
            {skill.skill_id} · v{skill.version || '?'} · {skill.source_type}
          </div>
        </div>
      </div>

      {/* Description */}
      {skill.description && (
        <div style={cardStyle}>
          <div style={labelStyle}>Description</div>
          <div style={valueStyle}>{skill.description}</div>
        </div>
      )}

      {/* Metadata chips */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginBottom: 10 }}>
        {(skill.tags || []).length > 0 && (
          <div style={cardStyle}>
            <div style={{ ...labelStyle, display: 'flex', alignItems: 'center', gap: 4 }}>
              <Tag size={11} /> Tags
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {skill.tags.map(tag => (
                <span key={tag} style={{
                  fontSize: 11, padding: '2px 8px', borderRadius: 10,
                  background: t.bgHover, border: `1px solid ${t.border}`,
                  color: t.textPrimary,
                }}>
                  {tag}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Triggers */}
        {(skill.triggers || []).length > 0 && (
          <div style={cardStyle}>
            <div style={{ ...labelStyle, display: 'flex', alignItems: 'center', gap: 4 }}>
              <Zap size={11} /> Triggers
            </div>
            <div>
              {skill.triggers.map((tr, i) => (
                <div key={i} style={{ fontSize: 12, color: t.textPrimary, marginBottom: 2 }}>
                  {tr}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Allowed Tools */}
        {skill.allowed_tools && skill.allowed_tools.length > 0 && (
          <div style={cardStyle}>
            <div style={{ ...labelStyle, display: 'flex', alignItems: 'center', gap: 4 }}>
              <Wrench size={11} /> Allowed Tools
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {skill.allowed_tools.map(tool => (
                <span key={tool} style={{
                  fontSize: 11, padding: '2px 6px', borderRadius: 3,
                  background: t.accent + '18', border: `1px solid ${t.accent}40`,
                  color: t.accent, fontFamily: 'monospace',
                }}>
                  {tool}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Instructions (SKILL.md body) */}
      {skill.instructions && (
        <div style={cardStyle}>
          <div
            onClick={() => setShowInstructions(v => !v)}
            style={{
              display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', userSelect: 'none',
              ...labelStyle,
            }}
          >
            {showInstructions ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            <BookOpen size={11} /> Instructions
          </div>
          {showInstructions && (
            <pre style={{
              whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              fontFamily: '"SF Mono", "Fira Code", monospace',
              fontSize: 12, color: t.textPrimary,
              lineHeight: 1.5, margin: '8px 0 0 0',
            }}>
              {skill.instructions}
            </pre>
          )}
          {/* Copy / Download row */}
          <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
            <button onClick={async () => {
              const text = `# ${skill.name || skill.skill_id}\n\n${skill.description || ''}\n\n## Instructions\n\n${skill.instructions}`;
              await navigator.clipboard.writeText(text);
            }} style={{
              fontSize: 11, height: 24, padding: '0 8px',
              background: t.bgHover, border: `1px solid ${t.border}`,
              borderRadius: 3, color: t.textPrimary, cursor: 'pointer',
            }}>Copy</button>
            <button onClick={() => {
              const text = `# ${skill.name || skill.skill_id}\n\n${skill.description || ''}\n\n## Tags\n${(skill.tags || []).join(', ')}\n\n## Instructions\n\n${skill.instructions}`;
              const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a'); a.href = url;
              a.download = `${skill.skill_id}.md`; a.click();
              URL.revokeObjectURL(url);
            }} style={{
              fontSize: 11, height: 24, padding: '0 8px',
              background: t.bgHover, border: `1px solid ${t.border}`,
              borderRadius: 3, color: t.textPrimary, cursor: 'pointer',
            }}>Download</button>
          </div>
        </div>
      )}

      {/* Examples */}
      {skill.examples && (
        <div style={cardStyle}>
          <div style={{ ...labelStyle }}>
            <FileText size={11} /> Examples
          </div>
          <pre style={{
            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            fontFamily: '"SF Mono", "Fira Code", monospace',
            fontSize: 12, color: t.textPrimary,
            lineHeight: 1.5, margin: '8px 0 0 0',
          }}>
            {skill.examples}
          </pre>
        </div>
      )}

      {/* Stats */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <div style={cardStyle}>
          <div style={labelStyle}>Usage</div>
          <div style={valueStyle}>{skill.usage_count ?? 0} runs</div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Success Rate</div>
          <div style={valueStyle}>
            {skill.avg_success_rate != null ? `${(skill.avg_success_rate * 100).toFixed(0)}%` : '—'}
          </div>
        </div>
        {(skill.required_context || []).length > 0 && (
          <div style={cardStyle}>
            <div style={labelStyle}>Required Context</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {skill.required_context.map((ctx, i) => (
                <span key={i} style={{ fontSize: 12, color: t.textPrimary, fontFamily: 'monospace' }}>
                  {ctx}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
      </div>
    </div>
  );
}
