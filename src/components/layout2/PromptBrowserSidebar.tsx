/**
 * PromptBrowserSidebar — lists prompt templates directly.
 *
 * Extracts system prompts from agents and presents them as standalone prompt
 * entries, showing name + content preview. Clicking opens the prompt editor.
 */
import { useState, useEffect, useCallback } from 'react';
import { useLayoutTokens } from './tokens';
import { useLayoutState } from './useLayout';
import apiClient from '../../lib/api-client';
import { FileText, Search, Loader, Plus } from 'lucide-react';

interface RawAgent {
  id: number;
  name: string;
  description?: string;
  config?: {
    system_prompt?: string;
  };
  system_prompt?: string;
}

interface PromptEntry {
  id: number;           // agent id (acts as prompt id)
  name: string;         // display name e.g. "Customer Support Prompt"
  content: string;      // the full prompt text
  agentName: string;    // source agent name
}

function extractPrompt(agent: RawAgent): string {
  return agent.system_prompt || agent.config?.system_prompt || '';
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max).trimEnd() + '…';
}

export default function PromptBrowserSidebar() {
  const t = useLayoutTokens();
  const { openTab } = useLayoutState();
  const [prompts, setPrompts] = useState<PromptEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [activePromptId, setActivePromptId] = useState<string | null>(null);

  useEffect(() => {
    apiClient.listDeepAgents({ public_only: false })
      .then(res => {
        const data = (res as any).data ?? ([] as RawAgent[]);
        const entries: PromptEntry[] = data
          .filter((a: RawAgent) => extractPrompt(a).trim().length > 0)
          .map((a: RawAgent) => ({
            id: a.id,
            name: truncate(a.name.replace(/Agent$/i, '').trim() + ' Prompt', 40),
            content: extractPrompt(a),
            agentName: a.name,
          }));
        setPrompts(entries);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const openPrompt = useCallback((entry: PromptEntry) => {
    setActivePromptId(String(entry.id));
    openTab({
      id: `prompt-${entry.id}`,
      label: entry.name,
      viewType: 'prompt-detail',
      data: { promptText: entry.content, promptName: entry.name, agentName: entry.agentName },
    });
  }, [openTab]);

  const handleNewPrompt = useCallback(() => {
    const id = `prompt-new-${Date.now()}`;
    setActivePromptId(id);
    openTab({
      id,
      label: 'New Prompt',
      viewType: 'prompt-detail',
      data: { promptText: '', promptName: 'Untitled Prompt' },
    });
  }, [openTab]);

  const filtered = searchQuery
    ? prompts.filter(p =>
        p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        p.content.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : prompts;

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px 8px' }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: t.textPrimary }}>
          Prompt Templates
        </span>
        <span style={{ fontSize: 10, color: t.textMuted }}>
          {prompts.length}
        </span>
      </div>

      {/* New Prompt */}
      <div style={{ padding: '0 12px 8px' }}>
        <button
          onClick={handleNewPrompt}
          style={{
            width: '100%',
            padding: '7px 12px',
            borderRadius: 6,
            border: `1px dashed ${t.border}`,
            background: 'transparent',
            color: t.textMuted,
            cursor: 'pointer',
            fontSize: 11,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 6,
          }}
          onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; e.currentTarget.style.color = t.textPrimary; }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = t.textMuted; }}
        >
          <Plus size={13} />
          New Blank Prompt
        </button>
      </div>

      {/* Search */}
      <div style={{ position: 'relative', padding: '0 12px 8px' }}>
        <Search size={13} style={{ position: 'absolute', left: 20, top: 8, color: t.textMuted }} />
        <input
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          placeholder="Search prompts..."
          style={{
            width: '100%',
            padding: '6px 10px 6px 28px',
            borderRadius: 6,
            border: `1px solid ${t.border}`,
            background: t.bgInput,
            color: t.textPrimary,
            fontSize: 12,
            outline: 'none',
          }}
        />
      </div>

      {/* Prompt list */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 12px 12px' }}>
        {loading ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '16px 8px', fontSize: 12, color: t.textMuted }}>
            <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
            Loading prompt templates...
          </div>
        ) : filtered.length === 0 ? (
          <div style={{ padding: '24px 8px', textAlign: 'center', fontSize: 12, color: t.textMuted }}>
            {prompts.length === 0
              ? 'No prompt templates found. Create one!'
              : 'No prompts match your search'}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {filtered.map((entry) => {
              const isActive = activePromptId === String(entry.id);
              return (
                <button
                  key={entry.id}
                  onClick={() => openPrompt(entry)}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 3,
                    width: '100%',
                    padding: '8px 10px',
                    borderRadius: 6,
                    border: 'none',
                    background: isActive ? t.bgHover : 'transparent',
                    color: t.textPrimary,
                    cursor: 'pointer',
                    fontSize: 12,
                    textAlign: 'left',
                  }}
                  onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = 'rgba(255,255,255,0.04)'; }}
                  onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
                >
                  {/* Title row */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                    <FileText size={14} style={{ color: t.accent, flexShrink: 0 }} />
                    <span style={{ fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {entry.name}
                    </span>
                    <span style={{
                      fontSize: 9,
                      padding: '1px 5px',
                      borderRadius: 4,
                      background: t.bgHover,
                      color: t.textMuted,
                      flexShrink: 0,
                      lineHeight: '16px',
                    }}>
                      System
                    </span>
                  </div>
                  {/* Content preview */}
                  <div
                    style={{
                      fontSize: 10,
                      color: t.textMuted,
                      lineHeight: 1.4,
                      overflow: 'hidden',
                      display: '-webkit-box',
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: 'vertical',
                      paddingLeft: 20,
                    }}
                  >
                    {truncate(entry.content, 160)}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
