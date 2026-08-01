/**
 * SkillHomePage — landing page for the Skills activity.
 *
 * Follows the ToolHomePage pattern: header bar (title + refresh + new),
 * hero intro, educational sections grounded in the Agent Skills spec
 * (SKILL.md — adopted by the LangChain ecosystem, Claude Skills, etc.),
 * followed by a search box and a gallery grid of all skills.
 */
import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useLayoutTokens } from './tokens';
import { useLayoutState } from './useLayout';
import apiClient from '../../lib/api-client';
import {
  Award, Search, Plus, Loader, RefreshCw, Brain, Sparkles,
  Code, Zap, Shield, ListChecks, PenLine, FileText, Tag,
} from 'lucide-react';

// ── Data types ───────────────────────────────────────────────

interface SkillSummary {
  skill_id: string;
  name: string;
  description: string;
  version: string;
  source_type: string;
  tags: string[];
  triggers: string[];
  usage_count: number;
  avg_success_rate: number;
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max).trimEnd() + '…';
}

// ── Bilingual content (grounded in the Agent Skills spec) ───

function useContent() {
  const { i18n } = useTranslation();
  const isZh = i18n.language.startsWith('zh');
  return isZh ? {
    title: 'Skills',
    subtitle: '技能：打包的能力单元',

    heroP1: '技能（Skill）是"可打包、可复用、可自动触发"的能力单元——一个 SKILL.md 清单加上可选的资源文件，就构成完整的技能。它让智能体在遇到匹配场景时，无需等待用户逐字指导，自动加载指令并完成任务。',
    heroP2: '技能标准已被 Claude Skills、LangChain 生态等主流 Agent 框架采用：通过 Frontmatter 元数据 + Markdown 指令描述能力，通过 Triggers 定义自动触发条件。',
    heroCta: 'New Skill',

    whatTitle: '什么是 Skill？',
    whatSubtitle: 'Agent Skills 标准：SKILL.md',
    whatP1: '一个技能 = 一个目录。目录里的 SKILL.md 通过 Frontmatter 声明 name、description、tags、triggers、allowed_tools 等元数据，正文则用 Markdown 写下逐步指令。智能体根据 description 匹配技能，根据 triggers 自动激活，然后加载指令开始执行。',
    whatP2: '这与提示词模板互补：提示词定义"怎么说"，技能定义"怎么做"——技能把指令、示例、工具许可打包成可复用的完整能力，而且可以在多个 Agent 间共享。',
    whatNote: '技能的精髓：智能体"按需取用"。description 决定是否匹配，triggers 决定是否自动激活。',
    skillCode: `---
name: api-rate-limiter
description: >-
  Implements exponential backoff for API calls.
  Use when requests fail with 429 or 5xx errors.
tags: [api, rate-limit, retry]
triggers:
  - "retry failed API requests"
  - "rate limited"
allowed_tools: [execute_python]
---

# Instructions

1. Detect retryable status codes (429, 502, 503).
2. Back off exponentially: 1s, 2s, 4s, 8s.
3. Log each attempt with the retry counter.`,

    compTitle: '技能解剖',
    compSubtitle: '一个 SKILL.md 的四个核心部分',
    comp1Title: 'Frontmatter 清单',
    comp1Desc: 'name / description / tags / version 等元数据。description 是智能体匹配技能的依据——写得准确，才能被正确调用。',
    comp2Title: '指令正文',
    comp2Desc: 'Markdown 步骤化指令，描述如何完成该技能的任务。指令应简洁、可执行，必要时附示例与注意事项。',
    comp3Title: 'Triggers 触发器',
    comp3Desc: '用户消息命中触发条件时技能自动激活。精确的触发词让技能"按需现身"，减少误触发。',
    comp4Title: 'Allowed Tools 工具许可',
    comp4Desc: '声明技能执行时允许使用的工具白名单。最小权限原则：只开放完成任务所需的工具。',

    bpTitle: '最佳实践',
    bpSubtitle: '编写高质量技能的四个关键建议',
    bp1Title: '清晰的描述',
    bp1Desc: 'description 决定技能何时被匹配。用一句话说明"做什么 + 何时用"，例如 "Retry failed API calls with backoff"。',
    bp2Title: '指令精炼',
    bp2Desc: '上下文窗口宝贵。指令要步骤化、简洁、可执行，避免冗长的背景铺陈；复杂逻辑移到技能资源文件中。',
    bp3Title: '附带示例',
    bp3Desc: '在指令或单独示例文件中提供输入-输出示例。示例比抽象描述更能稳定智能体的执行结果。',
    bp4Title: '精确的触发器',
    bp4Desc: 'Triggers 覆盖自然语言变体（如 "retry failed requests" / "429 rate limited"）。过宽的触发词会导致误激活。',

    loopTitle: '工作原理',
    loopSubtitle: '技能被调用的四步流程',
    loop1: '触发检测',
    loop1Desc: '用户消息匹配技能的 Triggers 条件，或智能体判断任务需要该技能，技能被激活。',
    loop2: '匹配选择',
    loop2Desc: '智能体通过 description 从技能库中选出最合适的技能（同场景多技能时可排序）。',
    loop3: '加载指令',
    loop3Desc: '系统读取 SKILL.md 与资源文件，将指令注入当前上下文，作为任务执行的行动指南。',
    loop4: '执行完成',
    loop4Desc: '智能体按指令完成任务，在 allowed_tools 白名单内调用工具，最终产出结果。',

    searchPlaceholder: '搜索技能…',
    loading: '加载中…',
    empty: '暂无技能',
    emptyHint: '创建你的第一个技能——智能体将在需要时自动调用它',
    noMatch: '没有匹配的技能',
    newSkill: 'New Skill',
    edit: 'Edit',
    builtin: 'builtin',
    personal: 'personal',
    uses: 'uses',
  } : {
    title: 'Skills',
    subtitle: 'Skills — packaged capabilities',

    heroP1: 'A Skill is a packaged, reusable, auto-triggerable capability unit — a single SKILL.md manifest plus optional resource files. It lets an agent automatically load instructions and complete a task when the right scenario appears, without the user typing step-by-step guidance.',
    heroP2: 'The Agent Skills spec has been adopted by Claude Skills, the LangChain ecosystem and other major agent frameworks: frontmatter metadata + Markdown instructions describe the capability, and Triggers define automatic activation conditions.',
    heroCta: 'New Skill',

    whatTitle: 'What is a Skill?',
    whatSubtitle: 'The Agent Skills spec: SKILL.md',
    whatP1: 'A skill is a directory. Its SKILL.md declares metadata — name, description, tags, triggers, allowed_tools — in frontmatter, and writes step-by-step instructions in the Markdown body. The agent matches skills by description, auto-activates by triggers, then loads the instructions and executes.',
    whatP2: 'Skills complement prompt templates: prompts define "how to speak", skills define "how to do". A skill packages instructions, examples and tool permissions into a reusable capability that can be shared across agents.',
    whatNote: 'The essence: agents pull skills "on demand". description decides the match; triggers decide automatic activation.',
    skillCode: `---
name: api-rate-limiter
description: >-
  Implements exponential backoff for API calls.
  Use when requests fail with 429 or 5xx errors.
tags: [api, rate-limit, retry]
triggers:
  - "retry failed API requests"
  - "rate limited"
allowed_tools: [execute_python]
---

# Instructions

1. Detect retryable status codes (429, 502, 503).
2. Back off exponentially: 1s, 2s, 4s, 8s.
3. Log each attempt with the retry counter.`,

    compTitle: 'Anatomy of a Skill',
    compSubtitle: 'The four core parts of a SKILL.md',
    comp1Title: 'Frontmatter Manifest',
    comp1Desc: 'Metadata: name / description / tags / version. The description is how agents match the skill — write it precisely so it gets invoked correctly.',
    comp2Title: 'Instructions Body',
    comp2Desc: 'Step-by-step Markdown instructions describing how to complete the skill\'s task. Keep them concise and executable; add examples when useful.',
    comp3Title: 'Triggers',
    comp3Desc: 'The skill auto-activates when a user message matches a trigger. Precise trigger phrases make skills appear "on demand" and reduce false activation.',
    comp4Title: 'Allowed Tools',
    comp4Desc: 'The whitelist of tools the skill may use while executing. Principle of least privilege: only open the tools needed for the task.',

    bpTitle: 'Best Practices',
    bpSubtitle: 'Four key tips for writing high-quality skills',
    bp1Title: 'Clear Description',
    bp1Desc: 'The description decides when the skill is matched. One sentence: "what it does + when to use it", e.g. "Retry failed API calls with backoff".',
    bp2Title: 'Concise Instructions',
    bp2Desc: 'Context windows are precious. Make instructions stepwise, concise and executable; move complex logic into skill resource files.',
    bp3Title: 'Include Examples',
    bp3Desc: 'Provide input→output examples in the instructions or a separate file. Examples stabilize execution far better than abstract descriptions.',
    bp4Title: 'Precise Triggers',
    bp4Desc: 'Cover natural-language variants (e.g. "retry failed requests" / "429 rate limited"). Overly broad triggers cause false activation.',

    loopTitle: 'How It Works',
    loopSubtitle: 'The four-step lifecycle of a skill invocation',
    loop1: 'Trigger Detection',
    loop1Desc: 'A user message matches the skill\'s Triggers, or the agent judges the task needs the skill — the skill activates.',
    loop2: 'Match & Select',
    loop2Desc: 'The agent picks the best skill from the library by description (ranking when several skills fit the scenario).',
    loop3: 'Load Instructions',
    loop3Desc: 'The system reads SKILL.md plus resources and injects the instructions into the context as the action guide.',
    loop4: 'Execute & Deliver',
    loop4Desc: 'The agent follows the instructions, calls tools within the allowed_tools whitelist, and produces the final result.',

    searchPlaceholder: 'Search skills…',
    loading: 'Loading…',
    empty: 'No skills yet',
    emptyHint: 'Create your first skill — agents will call it automatically when needed',
    noMatch: 'No matching skills',
    newSkill: 'New Skill',
    edit: 'Edit',
    builtin: 'builtin',
    personal: 'personal',
    uses: 'uses',
  };
}

// ── Section wrapper ──────────────────────────────────────────

function Section({ title, children, subtitle }: { title: string; children: React.ReactNode; subtitle?: string }) {
  const t = useLayoutTokens();
  return (
    <div style={{ marginBottom: 28 }}>
      <div style={{ marginBottom: 10 }}>
        <h2 style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, margin: 0, letterSpacing: '-0.2px' }}>
          {title}
        </h2>
        {subtitle && <p style={{ fontSize: 12, color: t.textMuted, margin: '4px 0 0 0', lineHeight: 1.5 }}>{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

// ── Feature card ─────────────────────────────────────────────

function FeatureCard({ icon: Icon, title, desc, color }: { icon: typeof Brain; title: string; desc: string; color?: string }) {
  const t = useLayoutTokens();
  const accent = color || t.accent;
  return (
    <div
      style={{
        padding: 16, borderRadius: 8,
        background: t.bgContent,
        border: `1px solid ${t.border}`,
        display: 'flex', flexDirection: 'column', gap: 8,
      }}
    >
      <div
        style={{
          width: 32, height: 32, borderRadius: 7,
          background: `${accent}15`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        <Icon size={16} color={accent} />
      </div>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, marginBottom: 2 }}>{title}</div>
        <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.5, margin: 0 }}>{desc}</p>
      </div>
    </div>
  );
}

// ── Step card ────────────────────────────────────────────────

function StepCard({ num, title, desc }: { num: number; title: string; desc: string }) {
  const t = useLayoutTokens();
  return (
    <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
      <div
        style={{
          width: 26, height: 26, borderRadius: '50%',
          background: t.accent, color: '#fff',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 12, fontWeight: 700, flexShrink: 0, marginTop: 1,
        }}
      >
        {num}
      </div>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, marginBottom: 2 }}>{title}</div>
        <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.5, margin: 0 }}>{desc}</p>
      </div>
    </div>
  );
}

// ── Skill card ───────────────────────────────────────────────

function SkillCard({ skill, onClick, footer }: {
  skill: SkillSummary;
  onClick: () => void;
  footer?: React.ReactNode;
}) {
  const t = useLayoutTokens();
  return (
    <div
      onClick={onClick}
      style={{
        padding: 14, borderRadius: 8, cursor: 'pointer',
        background: t.bgContent, border: `1px solid ${t.border}`,
        transition: 'border-color 0.15s',
        display: 'flex', flexDirection: 'column', gap: 8,
      }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = t.accent; }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
        <div style={{
          width: 28, height: 28, borderRadius: 6, flexShrink: 0,
          background: `${t.accent}18`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <Award size={14} color={t.accent} />
        </div>
        <span style={{
          fontSize: 13, fontWeight: 600, color: t.textPrimary,
          flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {skill.name || skill.skill_id}
        </span>
      </div>

      <p style={{
        fontSize: 11, color: t.textDim, margin: 0, lineHeight: 1.5,
        display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden',
      }}>
        {truncate(skill.description || '(no description)', 220)}
      </p>

      <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, color: t.textMuted, marginTop: 2 }}>
        <span style={{
          padding: '1px 6px', borderRadius: 4,
          background: t.bgHover, color: t.textMuted, fontSize: 9,
        }}>
          {skill.source_type}
        </span>
        {(skill.tags || []).slice(0, 2).map(tag => (
          <span key={tag} style={{
            padding: '1px 6px', borderRadius: 4,
            background: `${t.accent}12`, color: t.textMuted, fontSize: 9,
            fontFamily: 'monospace',
          }}>
            {tag}
          </span>
        ))}
        {typeof skill.usage_count === 'number' && (
          <span style={{
            marginLeft: 'auto', flexShrink: 0, padding: '1px 6px', borderRadius: 4,
            background: t.bgHover, color: t.textMuted, fontSize: 9,
          }}>
            {skill.usage_count} uses
          </span>
        )}
        {footer && (
          <span style={{ marginLeft: footer ? 4 : 'auto', flexShrink: 0, color: t.accent, fontWeight: 600 }}>
            {footer}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────

export default function SkillHomePage() {
  const t = useLayoutTokens();
  const c = useContent();
  const { openTab } = useLayoutState();
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');

  const loadSkills = useCallback(() => {
    setLoading(true);
    return apiClient.listSkills()
      .then(res => {
        const list: SkillSummary[] = Array.isArray(res.data) ? res.data : [];
        setSkills(list);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadSkills();
  }, [loadSkills]);

  const handleRefresh = useCallback(() => {
    loadSkills();
  }, [loadSkills]);

  /** Open skill details (same as sidebar click) */
  const openSkill = useCallback((skill: SkillSummary) => {
    openTab({
      id: `skill-${skill.skill_id}`,
      label: skill.name || skill.skill_id,
      viewType: 'skill',
      data: { skillId: skill.skill_id, skill },
    });
  }, [openTab]);

  /** Open the editor for an existing skill */
  const openEdit = useCallback((skill: SkillSummary) => {
    openTab({
      id: `skill-edit-${skill.skill_id}`,
      label: `Edit: ${skill.name || skill.skill_id}`,
      viewType: 'skill-editor',
      data: { skill },
    });
  }, [openTab]);

  /** Open the editor for a new skill */
  const handleNewSkill = useCallback(() => {
    openTab({
      id: `skill-new-${Date.now()}`,
      label: c.newSkill,
      viewType: 'skill-editor',
      data: { skill: {} },
    });
  }, [openTab, c.newSkill]);

  const q = searchQuery.trim().toLowerCase();
  const filtered = q
    ? skills.filter(s =>
        (s.name || '').toLowerCase().includes(q) ||
        (s.description || '').toLowerCase().includes(q) ||
        (s.tags || []).some(tag => tag.toLowerCase().includes(q))
      )
    : skills;

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
          <Award size={16} style={{ color: t.accent }} />
          <span style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary }}>{c.title}</span>
          <span style={{ fontSize: 11, color: t.textMuted }}>{c.subtitle}</span>
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
            onClick={handleNewSkill}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '6px 12px', borderRadius: 6,
              background: t.accent, color: '#fff',
              fontSize: 12, fontWeight: 600, border: 'none', cursor: 'pointer',
            }}
            onMouseEnter={e => { e.currentTarget.style.opacity = '0.9'; }}
            onMouseLeave={e => { e.currentTarget.style.opacity = '1'; }}
          >
            <Plus size={13} /> {c.heroCta}
          </button>
        </div>
      </div>

      {/* ── Content area ── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '24px' }}>
        {/* Hero banner */}
        <div
          style={{
            background: `linear-gradient(135deg, ${t.accent}22 0%, ${t.accent}08 55%, ${t.bgContent} 100%)`,
            border: `1px solid ${t.border}`,
            borderRadius: 12,
            padding: '24px 24px',
            marginBottom: 24,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
            <div
              style={{
                width: 40, height: 40, borderRadius: 10,
                background: `linear-gradient(135deg, ${t.accent}, ${t.accent}cc)`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                boxShadow: `0 3px 12px ${t.accent}35`,
              }}
            >
              <PenLine size={20} color="#fff" />
            </div>
            <div>
              <h1 style={{ fontSize: 18, fontWeight: 750, color: t.textPrimary, margin: 0, letterSpacing: '-0.3px' }}>
                {c.title}
              </h1>
              <p style={{ fontSize: 12, color: t.textMuted, margin: '2px 0 0 0' }}>{c.subtitle}</p>
            </div>
          </div>
          <p style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6, margin: '0 0 4px 0', maxWidth: 640 }}>{c.heroP1}</p>
          <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.5, margin: 0, maxWidth: 640, opacity: 0.8 }}>{c.heroP2}</p>
        </div>

        {/* ── What is a Skill? ── */}
        <Section title={c.whatTitle} subtitle={c.whatSubtitle}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <div
              style={{
                padding: 18, borderRadius: 10,
                background: `linear-gradient(135deg, #6366f115, ${t.bgContent})`,
                border: `1px solid ${t.border}`,
                fontSize: 11, color: t.textMuted, lineHeight: 1.7,
              }}
            >
              <p style={{ margin: '0 0 10px 0' }}>{c.whatP1}</p>
              <p style={{ margin: 0 }}>{c.whatP2}</p>
            </div>
            <div style={{ borderRadius: 10, overflow: 'hidden', border: `1px solid ${t.border}` }}>
              <div
                style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '6px 12px', fontSize: 10, fontWeight: 600,
                  background: t.bgContent, color: t.textMuted,
                  borderBottom: `1px solid ${t.border}`,
                  fontFamily: 'monospace',
                }}
              >
                <Code size={11} /> SKILL.md · example
              </div>
              <pre
                style={{
                  margin: 0, padding: 12,
                  fontSize: 11, lineHeight: 1.6,
                  color: t.textPrimary,
                  background: t.bgHover,
                  fontFamily: '"SF Mono", "Fira Code", monospace',
                  overflowX: 'auto',
                }}
              >
                {c.skillCode}
              </pre>
            </div>
          </div>
          <div style={{
            marginTop: 10, padding: 10, borderRadius: 6,
            background: `${t.accent}06`, border: `1px solid ${t.border}`,
            fontSize: 11, color: t.textMuted, lineHeight: 1.6,
          }}>
            💡 {c.whatNote}
          </div>
        </Section>

        {/* ── Anatomy ── */}
        <Section title={c.compTitle} subtitle={c.compSubtitle}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 10 }}>
            <FeatureCard icon={FileText} color="#6366f1" title={c.comp1Title} desc={c.comp1Desc} />
            <FeatureCard icon={ListChecks} color="#22c55e" title={c.comp2Title} desc={c.comp2Desc} />
            <FeatureCard icon={Zap} color="#f59e0b" title={c.comp3Title} desc={c.comp3Desc} />
            <FeatureCard icon={Shield} color="#8b5cf6" title={c.comp4Title} desc={c.comp4Desc} />
          </div>
        </Section>

        {/* ── Best Practices ── */}
        <Section title={c.bpTitle} subtitle={c.bpSubtitle}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 10 }}>
            <FeatureCard icon={Brain} color="#ec4899" title={c.bp1Title} desc={c.bp1Desc} />
            <FeatureCard icon={Sparkles} color="#06b6d4" title={c.bp2Title} desc={c.bp2Desc} />
            <FeatureCard icon={Tag} color="#f97316" title={c.bp3Title} desc={c.bp3Desc} />
            <FeatureCard icon={Zap} color="#3b82f6" title={c.bp4Title} desc={c.bp4Desc} />
          </div>
        </Section>

        {/* ── How It Works ── */}
        <Section title={c.loopTitle} subtitle={c.loopSubtitle}>
          <div
            style={{
              padding: 24, borderRadius: 10,
              background: t.bgContent,
              border: `1px solid ${t.border}`,
            }}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <StepCard num={1} title={c.loop1} desc={c.loop1Desc} />
              <StepCard num={2} title={c.loop2} desc={c.loop2Desc} />
              <StepCard num={3} title={c.loop3} desc={c.loop3Desc} />
              <StepCard num={4} title={c.loop4} desc={c.loop4Desc} />
            </div>
          </div>
        </Section>

        {/* ── Library: search + gallery ── */}
        <Section title={`${c.title} (${skills.length})`}>
          <div style={{ position: 'relative', marginBottom: 16, maxWidth: 480 }}>
            <Search size={14} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: t.textMuted }} />
            <input
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder={c.searchPlaceholder}
              style={{
                width: '100%',
                padding: '8px 12px 8px 34px',
                borderRadius: 8,
                border: `1px solid ${t.border}`,
                background: t.bgInput,
                color: t.textPrimary,
                fontSize: 12,
                outline: 'none',
              }}
            />
          </div>

          <div>
            {loading ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: t.textMuted, padding: 16 }}>
                <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
                {c.loading}
              </div>
            ) : skills.length === 0 ? (
              <div style={{ padding: '40px 16px', textAlign: 'center' }}>
                <Award size={36} style={{ color: t.textMuted, opacity: 0.3, marginBottom: 8 }} />
                <p style={{ fontSize: 13, color: t.textMuted, margin: 0 }}>{c.empty}</p>
                <p style={{ fontSize: 11, color: t.textMuted, margin: '4px 0 0 0' }}>{c.emptyHint}</p>
              </div>
            ) : filtered.length === 0 ? (
              <p style={{ fontSize: 12, color: t.textMuted, padding: 16, textAlign: 'center' }}>{c.noMatch}</p>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 10 }}>
                {filtered.map(skill => {
                  const isBuiltin = skill.source_type === 'builtin';
                  return (
                    <SkillCard
                      key={skill.skill_id}
                      skill={skill}
                      // Builtin → view details; personal → open the editor (same as the tools arrangement)
                      onClick={() => isBuiltin ? openSkill(skill) : openEdit(skill)}
                      footer={isBuiltin ? undefined : (<>{c.edit} →</>)}
                    />
                  );
                })}
              </div>
            )}
          </div>
        </Section>
      </div>
    </div>
  );
}
