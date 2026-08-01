/**
 * ModelHomePage — landing page for the Models activity.
 *
 * Follows the DeepAgentHomePage / ToolHomePage pattern: a hero banner plus a
 * provider gallery. Clicking a provider opens the same model-cards grid tab
 * that clicking the provider in the Models sidebar opens.
 */
import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useLayoutTokens } from './tokens';
import { useLayoutState } from './useLayout';
import { PROVIDER_META, LS_KEY_DEFAULT } from './ModelCardsSidebar';
import apiClient from '../../lib/api-client';
import {
  Sparkles, RefreshCw, Loader, Search, Play, KeyRound, ArrowRight,
  Cpu, Database, Layers, Zap, CheckCircle2, Globe,
} from 'lucide-react';

interface CloudModel {
  model_id: string;
  display_name: string;
  provider: string;
  capabilities: Record<string, any>;
  is_active: boolean;
}

interface LocalModel {
  id: number;
  name: string;
  display_name: string;
  provider: string;
  is_validated: boolean;
  is_active: boolean;
  capabilities: Record<string, any>;
}

interface ProviderSummary {
  provider: string;
  cloud: number;
  local: number;
}

function useContent() {
  const { i18n } = useTranslation();
  const isZh = i18n.language.startsWith('zh');

  return isZh ? {
    title: '模型',
    subtitle: '配置和管理你的 AI 模型',
    heroP1: 'Model Hub 统一管理云端与本地模型提供商。你可以为 OpenAI、Anthropic、DeepSeek、Google、Ollama 等提供商配置 API Key、浏览可用模型，并一键在 Playground 中测试任意模型。',
    heroP2: '每个模型卡片都展示其能力标签、上下文窗口、价格与速度信息。模型默认值、降级策略和每日限额可在模型详情中调整，所有 Agent、工作流和对话共享同一份模型配置。',
    statModels: '模型总数',
    statCloud: '云端',
    statLocal: '本地',
    statProviders: '提供商',
    searchPlaceholder: '搜索提供商或模型…',
    providersTitle: '模型提供商',
    providersSubtitle: '点击卡片打开该提供商的模型网格，与左侧 Models 侧边栏行为一致。',
    viewModels: '查看模型',
    noMatch: '没有匹配的提供商或模型',
    noProviders: '暂未配置任何模型提供商',
    loading: '加载模型中…',
    retry: '重试',
    failed: '加载失败，请重试',
    quickTitle: '快速开始',
    quickSubtitle: '从浏览提供商、测试默认模型或管理模型配置开始。',
    quick1Title: '浏览提供商',
    quick1Desc: '查看每个提供商的模型卡片、能力标签、价格和上下文窗口。',
    quick1Cta: '打开提供商',
    quick2Title: '测试默认模型',
    quick2Desc: '在 Playground 中直接运行当前默认模型，快速验证配置。',
    quick2Cta: '打开 Playground',
    quick3Title: '管理模型配置',
    quick3Desc: '查看 API Key 状态、模型验证情况和提供商详情。',
    quick3Cta: '浏览模型',
    conceptTitle: '模型如何工作',
    conceptSubtitle: 'LangConfig 将模型配置集中在 Model Hub，供所有 Agent 与工作流复用。',
    concept1Title: '统一模型注册表',
    concept1Desc: '云端模型通过 API 提供商发现，本地模型可手动注册并验证，所有模型共享统一的调用接口。',
    concept2Title: '默认模型与降级',
    concept2Desc: '全局默认模型用于新对话与工作流，主模型失败时可自动切换到备用模型。',
    concept3Title: '即测即用',
    concept3Desc: '任意模型都可直接打开 Playground 测试，无需切换页面。',
    defaultBadge: '默认',
    keySet: '已配置 Key',
    keyMissing: '缺少 Key',
    play: '测试',
  } : {
    title: 'Models',
    subtitle: 'Configure and manage your AI models',
    heroP1: 'Model Hub manages cloud and local model providers in one place. Configure API keys for OpenAI, Anthropic, DeepSeek, Google, Ollama, and more, browse available models, and test any model instantly in the Playground.',
    heroP2: 'Every model card shows capability badges, context window, pricing, and speed. Defaults, fallback models, and daily limits are configured per provider, and every Agent, workflow, and chat shares the same model registry.',
    statModels: 'Models',
    statCloud: 'Cloud',
    statLocal: 'Local',
    statProviders: 'Providers',
    searchPlaceholder: 'Search providers or models…',
    providersTitle: 'Model Providers',
    providersSubtitle: 'Click a card to open that provider’s model grid, matching the Models sidebar behavior.',
    viewModels: 'View Models',
    noMatch: 'No matching providers or models',
    noProviders: 'No model providers configured yet',
    loading: 'Loading models…',
    retry: 'Retry',
    failed: 'Failed to load. Please try again.',
    quickTitle: 'Quick Start',
    quickSubtitle: 'Browse providers, test the default model, or manage model configuration.',
    quick1Title: 'Browse Providers',
    quick1Desc: 'Inspect each provider’s model cards, capability badges, pricing, and context windows.',
    quick1Cta: 'Open Provider',
    quick2Title: 'Test Default Model',
    quick2Desc: 'Run the current default model directly in the Playground to verify configuration.',
    quick2Cta: 'Open Playground',
    quick3Title: 'Manage Config',
    quick3Desc: 'Review API key status, model validation, and provider details.',
    quick3Cta: 'Browse Models',
    conceptTitle: 'How Models Work',
    conceptSubtitle: 'LangConfig centralizes model configuration in Model Hub for every Agent and workflow.',
    concept1Title: 'Unified Registry',
    concept1Desc: 'Cloud models are discovered through providers; local models can be registered and validated manually. All models share one invocation interface.',
    concept2Title: 'Default & Fallback',
    concept2Desc: 'A global default model powers new chats and workflows, with automatic fallback when the primary model fails.',
    concept3Title: 'Test Instantly',
    concept3Desc: 'Open any model in the Playground directly from its card, without leaving the page.',
    defaultBadge: 'Default',
    keySet: 'Key set',
    keyMissing: 'No key',
    play: 'Play',
  };
}

function StatChip({ label, value, color }: { label: string; value: number; color: string }) {
  const t = useLayoutTokens();
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '8px 12px', borderRadius: 8,
      background: t.bgContent, border: `1px solid ${t.border}`,
    }}>
      <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />
      <div>
        <div style={{ fontSize: 16, fontWeight: 700, color: t.textPrimary, lineHeight: 1.1 }}>{value}</div>
        <div style={{ fontSize: 10, color: t.textMuted }}>{label}</div>
      </div>
    </div>
  );
}

function ProviderCard({
  provider, cloudCount, localCount, hasKey, hasDefault, onClick,
}: {
  provider: string;
  cloudCount: number;
  localCount: number;
  hasKey: boolean;
  hasDefault: boolean;
  onClick: () => void;
}) {
  const t = useLayoutTokens();
  const meta = PROVIDER_META[provider] ?? { label: provider, dot: '#888' };
  const total = cloudCount + localCount;

  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex', flexDirection: 'column', gap: 10,
        padding: 14, borderRadius: 8, cursor: 'pointer',
        background: t.bgContent, border: `1px solid ${hasDefault ? meta.dot : t.border}`,
        textAlign: 'left', transition: 'border-color 0.15s, box-shadow 0.15s',
        minWidth: 0,
      }}
      onMouseEnter={e => {
        e.currentTarget.style.borderColor = meta.dot;
        e.currentTarget.style.boxShadow = `0 0 0 1px ${meta.dot}55`;
      }}
      onMouseLeave={e => {
        e.currentTarget.style.borderColor = hasDefault ? meta.dot : t.border;
        e.currentTarget.style.boxShadow = 'none';
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
        <span style={{
          width: 30, height: 30, borderRadius: 7, flexShrink: 0,
          background: meta.dot, color: '#fff',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontWeight: 700, fontSize: 15, textTransform: 'uppercase',
        }}>
          {meta.label[0] || '?'}
        </span>
        <span style={{
          flex: 1, minWidth: 0, fontSize: 13, fontWeight: 600, color: t.textPrimary,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {meta.label}
        </span>
        {hasDefault && (
          <span style={{
            flexShrink: 0, fontSize: 9, fontWeight: 700, padding: '2px 6px',
            borderRadius: 999, background: '#10b981', color: '#fff',
          }}>
            ★ Default
          </span>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, color: t.textMuted }}>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 4,
          padding: '2px 6px', borderRadius: 4, background: t.bgHover,
        }}>
          <Globe size={10} /> {cloudCount} cloud
        </span>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 4,
          padding: '2px 6px', borderRadius: 4, background: t.bgHover,
        }}>
          <Cpu size={10} /> {localCount} local
        </span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 10,
          color: hasKey ? '#10b981' : '#f59e0b', flexShrink: 0,
        }}>
          <KeyRound size={11} />
          {hasKey ? 'Key set' : 'No key'}
        </span>
        <span style={{
          marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 4,
          fontSize: 10, fontWeight: 600, color: meta.dot, flexShrink: 0,
        }}>
          View Models <ArrowRight size={11} />
        </span>
      </div>

      <div style={{ fontSize: 10, color: t.textDim }}>
        {total} model{total === 1 ? '' : 's'}
      </div>
    </button>
  );
}

function QuickStartCard({
  icon: Icon, title, desc, cta, onClick, color,
}: {
  icon: typeof Sparkles;
  title: string;
  desc: string;
  cta: string;
  onClick: () => void;
  color: string;
}) {
  const t = useLayoutTokens();
  return (
    <button
      onClick={onClick}
      style={{
        flex: 1, minWidth: 180, padding: 16, borderRadius: 8,
        background: t.bgContent, border: `1px solid ${t.border}`,
        cursor: 'pointer', textAlign: 'left',
        display: 'flex', flexDirection: 'column', gap: 8,
        transition: 'border-color 0.15s',
      }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = color; }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; }}
    >
      <span style={{
        width: 30, height: 30, borderRadius: 7,
        background: `${color}18`, color,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <Icon size={15} />
      </span>
      <span style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary }}>{title}</span>
      <span style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.45 }}>{desc}</span>
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        fontSize: 11, fontWeight: 600, color, marginTop: 2,
      }}>
        {cta} <ArrowRight size={11} />
      </span>
    </button>
  );
}

function ConceptCard({
  icon: Icon, title, desc, color,
}: {
  icon: typeof Sparkles;
  title: string;
  desc: string;
  color: string;
}) {
  const t = useLayoutTokens();
  return (
    <div style={{
      padding: 16, borderRadius: 8,
      background: t.bgContent, border: `1px solid ${t.border}`,
      display: 'flex', flexDirection: 'column', gap: 8,
    }}>
      <span style={{
        width: 30, height: 30, borderRadius: 7,
        background: `${color}15`, color,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <Icon size={15} />
      </span>
      <span style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary }}>{title}</span>
      <span style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.5 }}>{desc}</span>
    </div>
  );
}

function Section({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  const t = useLayoutTokens();
  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ marginBottom: 10 }}>
        <h2 style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, margin: 0 }}>{title}</h2>
        <p style={{ fontSize: 11, color: t.textMuted, margin: '3px 0 0 0' }}>{subtitle}</p>
      </div>
      {children}
    </div>
  );
}

export default function ModelHomePage() {
  const t = useLayoutTokens();
  const c = useContent();
  const { openTab } = useLayoutState();
  const [cloudModels, setCloudModels] = useState<CloudModel[]>([]);
  const [localModels, setLocalModels] = useState<LocalModel[]>([]);
  const [providers, setProviders] = useState<ProviderSummary[]>([]);
  const [apiKeyStatus, setApiKeyStatus] = useState<Record<string, boolean>>({});
  const [defaultModel, setDefaultModel] = useState<string>(() => localStorage.getItem(LS_KEY_DEFAULT) || '');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const loadData = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      apiClient.listAvailableModels(),
      apiClient.getApiKeys().catch(() => ({ data: [] as any })),
      apiClient.getModelDefaults().catch(() => ({ data: { primary_model: '' } as any })),
    ])
      .then(([modelsRes, keysRes, defaultsRes]: any) => {
        const payload: any = modelsRes?.data ?? {};
        const cloud: CloudModel[] = Array.isArray(payload.cloud_models) ? payload.cloud_models : [];
        const local: LocalModel[] = Array.isArray(payload.local_models) ? payload.local_models : [];
        setCloudModels(cloud);
        setLocalModels(local);

        const byProv: Record<string, { cloud: number; local: number }> = {};
        for (const m of cloud) {
          if (!byProv[m.provider]) byProv[m.provider] = { cloud: 0, local: 0 };
          byProv[m.provider].cloud++;
        }
        for (const m of local) {
          if (!byProv[m.provider]) byProv[m.provider] = { cloud: 0, local: 0 };
          byProv[m.provider].local++;
        }
        setProviders(
          Object.entries(byProv)
            .map(([provider, counts]) => ({ provider, ...counts }))
            .sort((a, b) => a.provider.localeCompare(b.provider))
        );

        const keys: Array<{ provider: string; is_set: boolean }> = Array.isArray(keysRes?.data) ? keysRes.data : [];
        const status: Record<string, boolean> = {};
        for (const k of keys) status[k.provider] = k.is_set || false;
        setApiKeyStatus(status);

        const serverDefault: string = defaultsRes?.data?.primary_model || '';
        const nextDefault = localStorage.getItem(LS_KEY_DEFAULT) || serverDefault;
        if (nextDefault) {
          localStorage.setItem(LS_KEY_DEFAULT, nextDefault);
          setDefaultModel(nextDefault);
        }
      })
      .catch(err => {
        setError(err?.response?.data?.detail ?? err?.message ?? c.failed);
      })
      .finally(() => setLoading(false));
  }, [c.failed]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  /** Open a provider's model grid — same tab as the Models sidebar click. */
  const handleOpenProvider = useCallback((provider: string) => {
    const meta = PROVIDER_META[provider] ?? { label: provider, dot: '#888' };
    openTab({
      id: `provider-${provider}`,
      label: meta.label,
      viewType: 'model-cards',
      data: { provider },
    });
  }, [openTab]);

  /** Open the default model in the Playground, if known. */
  const handlePlayDefault = useCallback(() => {
    const cloudDefault = cloudModels.find(m => m.model_id === defaultModel);
    const localDefault = localModels.find(m => m.name === defaultModel);
    if (cloudDefault) {
      openTab({
        id: `playground-${cloudDefault.model_id}`,
        label: `Test: ${cloudDefault.display_name}`,
        viewType: 'model-viewer',
        data: { modelId: cloudDefault.model_id, modelName: cloudDefault.display_name, provider: cloudDefault.provider },
      });
      return;
    }
    if (localDefault) {
      openTab({
        id: `playground-${localDefault.name}`,
        label: `Test: ${localDefault.display_name}`,
        viewType: 'model-viewer',
        data: { modelId: localDefault.name, modelName: localDefault.display_name, provider: localDefault.provider },
      });
      return;
    }
    if (providers[0]) handleOpenProvider(providers[0].provider);
  }, [cloudModels, localModels, defaultModel, providers, openTab, handleOpenProvider]);

  const q = searchQuery.trim().toLowerCase();
  const filtered = q
    ? providers.filter(p => {
        const meta = PROVIDER_META[p.provider] ?? { label: p.provider };
        if (meta.label.toLowerCase().includes(q) || p.provider.toLowerCase().includes(q)) return true;
        const cloudHit = cloudModels.some(m =>
          m.provider === p.provider &&
          (`${m.display_name} ${m.model_id}`.toLowerCase().includes(q))
        );
        const localHit = localModels.some(m =>
          m.provider === p.provider &&
          (`${m.display_name} ${m.name}`.toLowerCase().includes(q))
        );
        return cloudHit || localHit;
      })
    : providers;

  const totalModels = cloudModels.length + localModels.length;
  const cloudDefault = cloudModels.find(m => m.model_id === defaultModel);
  const localDefault = localModels.find(m => m.name === defaultModel);
  const defaultProvider = cloudDefault?.provider || localDefault?.provider || '';

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
          <Sparkles size={16} style={{ color: t.accent }} />
          <span style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary }}>{c.title}</span>
          <span style={{ fontSize: 11, color: t.textMuted }}>{c.subtitle}</span>
        </div>
        <button
          onClick={loadData}
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
      </div>

      {/* ── Scrollable content ── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '24px 28px' }}>
        {/* Hero banner */}
        <div
          style={{
            background: `linear-gradient(135deg, ${t.accent}22 0%, ${t.accent}08 55%, ${t.bgContent} 100%)`,
            border: `1px solid ${t.border}`,
            borderRadius: 12,
            padding: '26px 28px',
            marginBottom: 24,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
            <span style={{
              width: 40, height: 40, borderRadius: 10,
              background: `linear-gradient(135deg, ${t.accent}, ${t.accent}cc)`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: `0 3px 12px ${t.accent}35`,
            }}>
              <Sparkles size={20} color="#fff" />
            </span>
            <div>
              <h1 style={{ fontSize: 18, fontWeight: 750, color: t.textPrimary, margin: 0, letterSpacing: '-0.3px' }}>
                {c.title}
              </h1>
              <p style={{ fontSize: 12, color: t.textMuted, margin: '2px 0 0 0' }}>{c.subtitle}</p>
            </div>
          </div>
          <p style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6, margin: '0 0 6px 0', maxWidth: 680 }}>{c.heroP1}</p>
          <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.5, margin: 0, maxWidth: 680, opacity: 0.8 }}>{c.heroP2}</p>

          {/* Stats */}
          <div style={{ display: 'flex', gap: 10, marginTop: 16, flexWrap: 'wrap' }}>
            <StatChip label={c.statModels} value={totalModels} color={t.accent} />
            <StatChip label={c.statCloud} value={cloudModels.length} color="#10b981" />
            <StatChip label={c.statLocal} value={localModels.length} color="#f59e0b" />
            <StatChip label={c.statProviders} value={providers.length} color="#a855f7" />
          </div>
        </div>

        {loading ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '24px 0', fontSize: 13, color: t.textMuted }}>
            <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
            {c.loading}
          </div>
        ) : error ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '24px 0', fontSize: 13, color: '#ef5350' }}>
            {c.failed}
            <button
              onClick={loadData}
              style={{
                background: 'transparent', border: `1px solid ${t.border}`,
                color: t.textPrimary, padding: '4px 10px', borderRadius: 4, cursor: 'pointer',
              }}
            >
              {c.retry}
            </button>
          </div>
        ) : (
          <>
            {/* Provider gallery */}
            <Section title={c.providersTitle} subtitle={c.providersSubtitle}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
                <div style={{ position: 'relative', flex: 1, minWidth: 220, maxWidth: 360 }}>
                  <Search size={14} style={{
                    position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)',
                    color: t.textMuted, pointerEvents: 'none',
                  }} />
                  <input
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                    placeholder={c.searchPlaceholder}
                    style={{
                      width: '100%', padding: '7px 10px 7px 30px',
                      background: t.bgInput, border: `1px solid ${t.border}`,
                      borderRadius: 5, color: t.textPrimary, fontSize: 12,
                      outline: 'none', boxSizing: 'border-box',
                    }}
                  />
                </div>
                <span style={{ fontSize: 11, color: t.textMuted }}>{filtered.length} / {providers.length}</span>
              </div>

              {filtered.length === 0 ? (
                <div style={{ padding: '20px 0', fontSize: 12, color: t.textMuted, fontStyle: 'italic' }}>
                  {q ? c.noMatch : c.noProviders}
                </div>
              ) : (
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))',
                  gap: 12,
                }}>
                  {filtered.map(p => (
                    <ProviderCard
                      key={p.provider}
                      provider={p.provider}
                      cloudCount={p.cloud}
                      localCount={p.local}
                      hasKey={!!apiKeyStatus[p.provider]}
                      hasDefault={p.provider === defaultProvider}
                      onClick={() => handleOpenProvider(p.provider)}
                    />
                  ))}
                </div>
              )}
            </Section>

            {/* Quick start */}
            <Section title={c.quickTitle} subtitle={c.quickSubtitle}>
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                <QuickStartCard
                  icon={Globe}
                  title={c.quick1Title}
                  desc={c.quick1Desc}
                  cta={c.quick1Cta}
                  color="#3b82f6"
                  onClick={() => providers[0] && handleOpenProvider(providers[0].provider)}
                />
                <QuickStartCard
                  icon={Play}
                  title={c.quick2Title}
                  desc={c.quick2Desc}
                  cta={c.quick2Cta}
                  color="#10b981"
                  onClick={handlePlayDefault}
                />
                <QuickStartCard
                  icon={Layers}
                  title={c.quick3Title}
                  desc={c.quick3Desc}
                  cta={c.quick3Cta}
                  color="#a855f7"
                  onClick={() => providers[0] && handleOpenProvider(providers[0].provider)}
                />
              </div>
            </Section>

            {/* Concepts */}
            <Section title={c.conceptTitle} subtitle={c.conceptSubtitle}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
                <ConceptCard icon={Database} title={c.concept1Title} desc={c.concept1Desc} color="#10b981" />
                <ConceptCard icon={Zap} title={c.concept2Title} desc={c.concept2Desc} color="#f59e0b" />
                <ConceptCard icon={CheckCircle2} title={c.concept3Title} desc={c.concept3Desc} color="#3b82f6" />
              </div>
            </Section>
          </>
        )}
      </div>
    </div>
  );
}
