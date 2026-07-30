/**
 * AgentHomePage — landing page for the Agents activity.
 *
 * Lightweight template browser with search, category filter, and "New Agent" action.
 * Renders in the main viewer when no agent tab is open.
 */
import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useLayoutTokens } from './tokens';
import { useLayoutState } from './useLayout';
import apiClient from '../../lib/api-client';
import {
  Brain, Sparkles, Cpu, Search, Code, Layers, Plus, Loader,
  BookOpen, RefreshCw,
} from 'lucide-react';

// ── Template data ────────────────────────────────────────────

interface TemplateAgent {
  id: number;
  name: string;
  description: string;
  icon?: string;
  category?: string;
  tags?: string[];
  system_prompt?: string;
  model?: string;
  temperature?: number;
  native_tools?: string[];
}

const CATEGORY_CONFIG: Record<string, { icon: typeof Brain; color: string; labelEn: string; labelZh: string }> = {
  code_review:   { icon: Code,    color: '#3b82f6', labelEn: 'Code Review',    labelZh: 'Code Review' },
  testing:       { icon: Search,  color: '#22c55e', labelEn: 'Testing',        labelZh: 'Testing' },
  qa_validation: { icon: Layers,  color: '#f59e0b', labelEn: 'QA & Validation', labelZh: 'QA & Validation' },
  research:      { icon: Cpu,     color: '#8b5cf6', labelEn: 'Research',       labelZh: 'Research' },
  documentation: { icon: Sparkles, color: '#ec4899', labelEn: 'Documentation',  labelZh: 'Documentation' },
  data:          { icon: Cpu,     color: '#06b6d4', labelEn: 'Data Processing', labelZh: 'Data Processing' },
};

function getCategoryConfig(cat: string) {
  return CATEGORY_CONFIG[cat] || { icon: Brain, color: '#6b7280', labelEn: cat, labelZh: cat };
}

// ── Content (zh / en) ───────────────────────────────────────

function useContent() {
  const { i18n } = useTranslation();
  const isZh = i18n.language.startsWith('zh');

  return isZh ? {
    title: 'Agents',
    subtitle: '构建和管理你的 AI Agent',
    desc: '创建、配置和测试你的 AI 助手。为每个任务选择最合适的模型、工具和提示词模板。',
    cta: '新建 Agent',
    tplSearchPlaceholder: '搜索模板…',
    tplFilterAll: '全部',
    tplLoading: '加载中…',
    tplEmpty: '暂无 Agent',
    tplEmptyHint: '点击上方按钮创建你的第一个 Agent',
    tplNoMatch: '没有匹配的 Agent',
    tplError: '加载失败，请重试',
    tplIntroTab: '概览',
    tplBrowseTab: '浏览',
  } : {
    title: 'Agents',
    subtitle: 'Build and manage your AI Agents',
    desc: 'Create, configure, and test your AI assistants. Pick the right model, tools, and prompt for every task.',
    cta: 'New Agent',
    tplSearchPlaceholder: 'Search templates…',
    tplFilterAll: 'All',
    tplLoading: 'Loading…',
    tplEmpty: 'No Agents yet',
    tplEmptyHint: 'Click the button above to create your first Agent',
    tplNoMatch: 'No matching Agents',
    tplError: 'Failed to load. Please try again.',
    tplIntroTab: 'Overview',
    tplBrowseTab: 'Browse',
  };
}

// ── Template card ────────────────────────────────────────────

function TemplateCard({ agent, onClick }: { agent: TemplateAgent; onClick: () => void }) {
  const t = useLayoutTokens();
  const catCfg = getCategoryConfig(agent.category || '');
  const CatIcon = catCfg.icon;

  return (
    <div
      onClick={onClick}
      style={{
        padding: 14, borderRadius: 8, cursor: 'pointer',
        background: t.bgContent, border: `1px solid ${t.border}`,
        transition: 'border-color 0.15s',
      }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = t.accent; }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; }}
    >
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <div style={{
          width: 28, height: 28, borderRadius: 6,
          background: `${catCfg.color}18`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <CatIcon size={14} color={catCfg.color} />
        </div>
        <span style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {agent.name}
        </span>
      </div>

      {/* Description */}
      <p style={{ fontSize: 11, color: t.textDim, margin: 0, lineHeight: 1.5, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
        {agent.description}
      </p>

      {/* Tags */}
      {agent.tags && agent.tags.length > 0 && (
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 8 }}>
          {agent.tags.slice(0, 3).map(tag => (
            <span key={tag} style={{
              fontSize: 9, padding: '2px 6px', borderRadius: 4,
              background: t.bgHover, color: t.textDim,
            }}>
              {tag}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Hero intro section ───────────────────────────────────────

function HeroCard({ onNewAgent }: { onNewAgent: () => void }) {
  const t = useLayoutTokens();
  const c = useContent();

  return (
    <div style={{ maxWidth: 720, margin: '0 auto' }}>
      {/* Minimal hero banner */}
      <div style={{
        padding: '32px 28px', borderRadius: 10,
        background: `linear-gradient(135deg, ${t.accent}08 0%, ${t.accent}02 100%)`,
        border: `1px solid ${t.border}`,
        marginBottom: 20,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
          <div style={{
            width: 40, height: 40, borderRadius: 10,
            background: t.accent, display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: `0 2px 12px ${t.accent}30`,
          }}>
            <Brain size={20} color="#fff" />
          </div>
          <div>
            <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: t.textPrimary }}>{c.title}</h2>
            <p style={{ margin: '2px 0 0 0', fontSize: 12, color: t.textMuted }}>{c.subtitle}</p>
          </div>
        </div>
        <p style={{ fontSize: 13, color: t.textDim, lineHeight: 1.6, margin: 0 }}>{c.desc}</p>
        <button
          onClick={onNewAgent}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 16,
            padding: '8px 18px', borderRadius: 6,
            background: t.accent, color: '#fff',
            fontSize: 13, fontWeight: 600, border: 'none', cursor: 'pointer',
          }}
        >
          <Plus size={14} /> {c.cta}
        </button>
      </div>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────

export default function AgentHomePage() {
  const t = useLayoutTokens();
  const c = useContent();
  const { openTab } = useLayoutState();
  const [templates, setTemplates] = useState<TemplateAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeCategory, setActiveCategory] = useState<string>('all');

  // Load templates from API
  const loadTemplates = () => {
    const abort = new AbortController();
    setLoading(true);
    setError(null);
    apiClient.apiFetch(`${apiClient.baseURL}/api/agents/templates`, { signal: abort.signal })
      .then((res: any) => {
        const tpl = (res as any[]) || [];
        setTemplates(tpl);
      })
      .catch(err => {
        if (err?.name !== 'AbortError') {
          console.error('Failed to load templates:', err);
          setError(c.tplError);
        }
      })
      .finally(() => setLoading(false));
    return abort;
  };

  useEffect(() => {
    const abort = loadTemplates();
    return () => abort.abort();
  }, []);

  const handleNewAgent = () => {
    openTab({ id: `new-agent-${Date.now()}`, label: 'New Agent', viewType: 'agent', data: { new: true } });
  };

  const handleRefresh = () => {
    loadTemplates();
  };

  const handleTemplateClick = (agent: TemplateAgent) => {
    openTab({
      id: `agent-tpl-${agent.id}`,
      label: agent.name,
      viewType: 'agent',
      data: {
        id: agent.id,
        name: agent.name,
        description: agent.description,
        system_prompt: agent.system_prompt,
        model: agent.model,
        temperature: agent.temperature || 0.7,
        native_tools: agent.native_tools || [],
        tags: agent.tags || [],
      },
    });
  };

  // Group templates by category
  const grouped = templates.reduce<Record<string, TemplateAgent[]>>((acc, t) => {
    const cat = t.category || 'other';
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(t);
    return acc;
  }, {});

  // Filtered templates based on search + category
  const filtered = templates.filter(t => {
    const matchCat = activeCategory === 'all' || (t.category || 'other') === activeCategory;
    if (!matchCat) return false;
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      t.name.toLowerCase().includes(q) ||
      (t.description || '').toLowerCase().includes(q) ||
      (t.tags || []).some(tag => tag.toLowerCase().includes(q))
    );
  });

  const categoryList = Object.keys(grouped);

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* ── Header bar ── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 24px', height: 44,
        borderBottom: `1px solid ${t.border}`,
        background: t.bgContent, flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <BookOpen size={16} style={{ color: t.accent }} />
          <span style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary }}>{c.title}</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <button
            onClick={handleRefresh}
            disabled={loading}
            title="Refresh"
            style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: 28, height: 28, borderRadius: 4,
              background: 'transparent', color: t.textMuted,
              border: 'none', cursor: 'pointer',
              opacity: loading ? 0.5 : 1,
            }}
            onMouseEnter={e => { if (!loading) e.currentTarget.style.background = t.bgHover; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
          >
            {loading ? <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <RefreshCw size={14} />}
          </button>
          <button
            onClick={handleNewAgent}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '6px 12px', borderRadius: 6,
              background: t.accent, color: '#fff',
              fontSize: 12, fontWeight: 600, border: 'none', cursor: 'pointer',
            }}
          >
            <Plus size={13} /> {c.cta}
          </button>
        </div>
      </div>

      {/* ── Content area ── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '24px 24px' }}>
        {/* Hero intro */}
        <HeroCard onNewAgent={handleNewAgent} />

        {/* Category filter pills */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 16 }}>
          <button
            onClick={() => {
              setActiveCategory('all');
              setSearchQuery('');
            }}
            style={{
              padding: '5px 12px', fontSize: 11, fontWeight: 500,
              border: `1px solid ${activeCategory === 'all' ? t.accent : t.border}`,
              borderRadius: 14, cursor: 'pointer',
              background: activeCategory === 'all' ? `${t.accent}15` : 'transparent',
              color: activeCategory === 'all' ? t.accent : t.textPrimary,
            }}
          >
            {c.tplFilterAll} ({templates.length})
          </button>
          {categoryList.map(cat => {
            const cfg = getCategoryConfig(cat);
            const active = activeCategory === cat;
            return (
              <button
                key={cat}
                onClick={() => setActiveCategory(cat)}
                style={{
                  padding: '5px 12px', fontSize: 11, fontWeight: 500,
                  border: `1px solid ${active ? t.accent : t.border}`,
                  borderRadius: 14, cursor: 'pointer',
                  background: active ? `${t.accent}15` : 'transparent',
                  color: active ? t.accent : t.textPrimary,
                }}
              >
                {cfg.labelEn} ({grouped[cat].length})
              </button>
            );
          })}
        </div>

        {/* Template grid */}
        <div id="agent-templates">
          {loading ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: t.textMuted, padding: 16 }}>
              <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
              {c.tplLoading}
            </div>
          ) : error ? (
            <p style={{ fontSize: 12, color: t.textMuted, padding: 16 }}>{error}</p>
          ) : templates.length === 0 && searchQuery.trim() ? (
            <p style={{ fontSize: 12, color: t.textMuted, padding: 16, textAlign: 'center' }}>
              {c.tplNoMatch}
            </p>
          ) : templates.length === 0 ? (
            <div style={{ padding: '24px 16px', textAlign: 'center' }}>
              <Brain size={32} style={{ color: t.textMuted, opacity: 0.3, marginBottom: 8 }} />
              <p style={{ fontSize: 13, color: t.textMuted, margin: 0 }}>{c.tplEmpty}</p>
              <p style={{ fontSize: 11, color: t.textMuted, margin: '4px 0 0 0' }}>{c.tplEmptyHint}</p>
            </div>
          ) : filtered.length === 0 ? (
            <p style={{ fontSize: 12, color: t.textMuted, padding: 16, textAlign: 'center' }}>
              {c.tplNoMatch}
            </p>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 10 }}>
              {filtered.map(a => (
                <TemplateCard key={a.id} agent={a} onClick={() => handleTemplateClick(a)} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
