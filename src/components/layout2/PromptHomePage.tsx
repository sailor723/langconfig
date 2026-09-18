/**
 * PromptHomePage — landing page for the Prompts activity.
 *
 * Follows the AgentHomePage pattern: header bar (title + refresh + new),
 * a hero intro, then educational sections based on LangChain's official
 * prompt documentation (PromptTemplate, ChatPromptTemplate,
 * MessagesPlaceholder, few-shot prompting, best practices), followed by
 * a search box and a gallery grid of prompt templates extracted from
 * agents' system prompts.
 * Clicking a prompt opens the prompt-detail editor tab.
 */
import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useLayoutTokens } from './tokens';
import { useLayoutState } from './useLayout';
import apiClient from '../../lib/api-client';
import {
  FileText, Search, Plus, Loader, RefreshCw, Bot, PenLine,
  Brain, Sparkles, Code, Layers, BookOpen, Database,
  Sliders, MessagesSquare,
} from 'lucide-react';

// ── Data types (mirrors PromptBrowserSidebar) ────────────────

interface RawAgent {
  id: number;
  name: string;
  description?: string;
  config?: { system_prompt?: string };
  system_prompt?: string;
}

interface PromptEntry {
  id: number;        // agent id (acts as prompt id)
  name: string;      // display name e.g. "Customer Support Prompt"
  content: string;   // full prompt text
  agentName: string; // source agent name
}

function extractPrompt(agent: RawAgent): string {
  return agent.system_prompt || agent.config?.system_prompt || '';
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max).trimEnd() + '…';
}

// ── Bilingual content (grounded in LangChain prompt docs) ────

function useContent() {
  const { i18n } = useTranslation();
  const isZh = i18n.language.startsWith('zh');
  return isZh ? {
    title: 'Prompts',
    subtitle: '提示词：浏览、学习与复用',

    heroP1: '提示词是模型的输入，也是智能体的"灵魂"——它定义角色、任务、约束与输出格式。LangChain 中，提示词（Prompt）是传给模型的具体文本，提示词模板（Prompt Template）则是用 {变量} 占位符生成提示词的可复用结构。',
    heroP2: '这里汇集了所有智能体的系统提示词。浏览、搜索、复用它们，或从空白创建新的提示词。',
    heroCta: '新建提示词',

    // What is a prompt
    whatTitle: '什么是提示词？',
    whatSubtitle: 'LangChain 官方概念：Prompt 与 Prompt Template',
    whatP1: '在 LangChain 中，Prompt 是发给模型的具体输入。质量决定一切——同一个模型，清晰的提示词产出高质量结果，含糊的提示词产出随意结果。Prompt Template 把固定文本与变量分开，通过运行时填充占位符生成不同的提示词，避免字符串拼接的维护噩梦。',
    whatP2: '建议使用 ChatPromptTemplate：现代模型原生支持 System / Human / AI 多角色消息，角色化的提示词显著优于把所有指令揉进一段纯文本。',
    whatNote: '提示词模板的价值：可复用、可维护、变量自动注入。模板 = 固定内容 + {变量} 占位符。',
    templateCode: `from langchain.prompts import ChatPromptTemplate

chat = ChatPromptTemplate.from_messages([
    ("system", "You are a {role} assistant."),
    ("human", "{question}"),
])

prompt = chat.invoke({
    "role": "customer support",
    "question": "How do I refund an order?",
})`,

    // Core building blocks
    compTitle: '核心构建块',
    compSubtitle: 'LangChain 提示词体系的核心组件',
    comp1Title: 'PromptTemplate',
    comp1Desc: '单段纯文本模板，用 {变量} 标记占位符。适合简单的文本补全任务，输出是一段完整字符串，无角色区分。',
    comp2Title: 'ChatPromptTemplate',
    comp2Desc: '消息列表模板，每条消息带角色标识（system / human / ai）。为对话模型与 Agent 设计，是官方推荐的首选方式。',
    comp3Title: 'MessagesPlaceholder',
    comp3Desc: '在模板中预留位置，动态插入对话历史或任意消息列表。是实现多轮对话记忆与工具调用结果注入的关键机制。',
    comp4Title: 'Few-shot 示例',
    comp4Desc: '在提示词中提供少量输入-输出示例，引导模型遵循特定模式与格式。示例比规则更能稳定模型的输出行为。',

    // Best practices
    bpTitle: '提示词工程最佳实践',
    bpSubtitle: '来自 LangChain 提示词工程指南的关键建议',
    bp1Title: '具体明确',
    bp1Desc: '明确角色、任务、约束与输入字段。告诉模型"你是谁、要做什么、遵守什么规则、输入什么数据"，而不是笼统的指令。',
    bp2Title: '使用分隔符',
    bp2Desc: '用分隔符（如 ###、```、XML 标签）清晰区分指令与用户输入，减少注入风险，让模型准确区分"规则"与"数据"。',
    bp3Title: '提供示例',
    bp3Desc: '少样本提示（Few-shot）用输入-输出对展示期望的输出风格、结构与格式。复杂任务下示例远胜抽象描述。',
    bp4Title: '指定输出格式',
    bp4Desc: '明确要求 JSON / 列表 / 步骤式等结构化输出，配合 Output Parser 将模型输出转换为程序可直接使用的数据。',

    // How it works
    archTitle: '工作原理',
    archSubtitle: '提示词从模板到模型调用的四个阶段',
    arch1: '定义模板',
    arch1Desc: '编写带 {变量} 占位符的提示词模板，或使用多角色 ChatPromptTemplate 构建消息结构。',
    arch2: '注入变量',
    arch2Desc: '运行时传入变量值（如角色、问题、上下文），模板自动填充生成最终的完整提示词。',
    arch3: '构建消息',
    arch3Desc: '通过 MessagesPlaceholder 注入对话历史，将系统指令与多轮消息组装为模型输入。',
    arch4: '调用模型',
    arch4Desc: '将格式化后的提示词发送给模型，获取流式响应，并用 Output Parser 解析为结构化结果。',

    // Library
    searchPlaceholder: '搜索提示词…',
    loading: '加载中…',
    empty: '暂无提示词',
    emptyHint: '创建你的第一个提示词，或为智能体编写系统提示词',
    noMatch: '没有匹配的提示词',
    newPrompt: 'New Prompt',
    source: '来源',
  } : {
    title: 'Prompts',
    subtitle: 'Prompt engineering — browse, learn and reuse',

    heroP1: 'A prompt is the input to a model — and the "personality" of an agent. It defines the role, task, constraints and output format. In LangChain, a Prompt is the concrete text sent to the model, while a Prompt Template is a reusable structure that generates prompts by filling {variable} placeholders at runtime.',
    heroP2: 'This library collects the system prompts of every agent. Browse, search and reuse them, or create a blank prompt from scratch.',
    heroCta: 'New Prompt',

    // What is a prompt
    whatTitle: 'What is a Prompt?',
    whatSubtitle: 'LangChain concepts: Prompt vs Prompt Template',
    whatP1: 'In LangChain, a Prompt is the concrete input sent to a model. Quality is everything — with the same model, a clear prompt produces high-quality output while a vague one produces arbitrary results. Prompt Templates separate fixed text from variables and generate prompts by filling placeholders at runtime, avoiding string-concatenation maintenance nightmares.',
    whatP2: 'ChatPromptTemplate is recommended: modern chat models natively support System / Human / AI multi-role messages, and role-structured prompts outperform single blocks of text that mix everything together.',
    whatNote: 'Why templates matter: reusable, maintainable, automatic variable injection. Template = fixed content + {variable} placeholders.',
    templateCode: `from langchain.prompts import ChatPromptTemplate

chat = ChatPromptTemplate.from_messages([
    ("system", "You are a {role} assistant."),
    ("human", "{question}"),
])

prompt = chat.invoke({
    "role": "customer support",
    "question": "How do I refund an order?",
})`,

    // Core building blocks
    compTitle: 'Core Building Blocks',
    compSubtitle: 'The core components of the LangChain prompt system',
    comp1Title: 'PromptTemplate',
    comp1Desc: 'A single text template with {variable} placeholders. Best for simple text-completion tasks; output is one plain string with no roles.',
    comp2Title: 'ChatPromptTemplate',
    comp2Desc: 'A message-list template where each message carries a role (system / human / ai). Designed for chat models and agents — the recommended default.',
    comp3Title: 'MessagesPlaceholder',
    comp3Desc: 'Reserves a position in the template to dynamically insert conversation history or arbitrary message lists. Key to multi-turn memory and tool-result injection.',
    comp4Title: 'Few-shot Examples',
    comp4Desc: 'Provide a few input→output examples inside the prompt to steer the model toward a pattern or format. Examples stabilize behavior better than abstract rules.',

    // Best practices
    bpTitle: 'Prompt Engineering Best Practices',
    bpSubtitle: 'Key advice from the LangChain prompt engineering guide',
    bp1Title: 'Be Specific',
    bp1Desc: 'State the role, task, constraints and input fields explicitly. Tell the model who it is, what to do, which rules to follow, and what data it receives.',
    bp2Title: 'Use Delimiters',
    bp2Desc: 'Use delimiters (###, ```, XML tags) to clearly separate instructions from user input, reducing injection risk and helping the model tell "rules" from "data".',
    bp3Title: 'Provide Examples',
    bp3Desc: 'Few-shot prompting shows input/output pairs that demonstrate the desired style, structure and format. Examples beat abstract descriptions for complex tasks.',
    bp4Title: 'Specify Output Format',
    bp4Desc: 'Ask for structured output (JSON, lists, steps) explicitly and pair with an Output Parser so model responses become directly usable data.',

    // How it works
    archTitle: 'How It Works',
    archSubtitle: 'From template to model call in four stages',
    arch1: 'Define Template',
    arch1Desc: 'Write a template with {variable} placeholders, or build a multi-role message structure with ChatPromptTemplate.',
    arch2: 'Inject Variables',
    arch2Desc: 'Pass variable values (role, question, context) at runtime; the template fills placeholders to produce the final prompt.',
    arch3: 'Build Messages',
    arch3Desc: 'Insert conversation history via MessagesPlaceholder and assemble system instructions with multi-turn messages.',
    arch4: 'Invoke Model',
    arch4Desc: 'Send the formatted prompt to the model, stream the response, and parse it into structured results with an Output Parser.',

    // Library
    searchPlaceholder: 'Search prompts…',
    loading: 'Loading…',
    empty: 'No prompts yet',
    emptyHint: 'Create your first prompt, or write a system prompt for an agent',
    noMatch: 'No matching prompts',
    newPrompt: 'New Prompt',
    source: 'Source',
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
        overflow: 'hidden',
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

// ── Prompt card ──────────────────────────────────────────────

function PromptCard({ entry, onClick }: { entry: PromptEntry; onClick: () => void }) {
  const t = useLayoutTokens();
  const c = useContent();
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
          <FileText size={14} color={t.accent} />
        </div>
        <span style={{
          fontSize: 13, fontWeight: 600, color: t.textPrimary,
          flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {entry.name}
        </span>
      </div>

      <p style={{
        fontSize: 11, color: t.textDim, margin: 0, lineHeight: 1.5,
        display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden',
      }}>
        {truncate(entry.content, 220)}
      </p>

      <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, color: t.textMuted, marginTop: 2 }}>
        <Bot size={11} />
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {c.source}: {entry.agentName}
        </span>
        <span style={{
          marginLeft: 'auto', flexShrink: 0, padding: '1px 6px', borderRadius: 4,
          background: t.bgHover, color: t.textMuted, fontSize: 9,
        }}>
          {entry.content.length.toLocaleString()} chars
        </span>
      </div>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────

export default function PromptHomePage() {
  const t = useLayoutTokens();
  const c = useContent();
  const { openTab } = useLayoutState();
  const [prompts, setPrompts] = useState<PromptEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');

  const loadPrompts = useCallback(() => {
    setLoading(true);
    return apiClient.listDeepAgents({ public_only: false })
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

  useEffect(() => {
    loadPrompts();
  }, [loadPrompts]);

  const handleRefresh = useCallback(() => {
    loadPrompts();
  }, [loadPrompts]);

  const openPrompt = useCallback((entry: PromptEntry) => {
    openTab({
      id: `prompt-${entry.id}`,
      label: entry.name,
      viewType: 'prompt-detail',
      data: { promptText: entry.content, promptName: entry.name, agentName: entry.agentName },
    });
  }, [openTab]);

  const handleNewPrompt = useCallback(() => {
    const id = `prompt-new-${Date.now()}`;
    openTab({
      id,
      label: c.newPrompt,
      viewType: 'prompt-detail',
      data: { promptText: '', promptName: 'Untitled Prompt' },
    });
  }, [openTab, c.newPrompt]);

  const filtered = searchQuery.trim()
    ? prompts.filter(p =>
        p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        p.content.toLowerCase().includes(searchQuery.toLowerCase()) ||
        p.agentName.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : prompts;

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
          <FileText size={16} style={{ color: t.accent }} />
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
            onClick={handleNewPrompt}
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

        {/* ── What is a Prompt? ── */}
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
                <Code size={11} /> ChatPromptTemplate · example
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
                {c.templateCode}
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

        {/* ── Core Building Blocks ── */}
        <Section title={c.compTitle} subtitle={c.compSubtitle}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 10 }}>
            <FeatureCard icon={Code} color="#6366f1" title={c.comp1Title} desc={c.comp1Desc} />
            <FeatureCard icon={MessagesSquare} color="#22c55e" title={c.comp2Title} desc={c.comp2Desc} />
            <FeatureCard icon={Layers} color="#f59e0b" title={c.comp3Title} desc={c.comp3Desc} />
            <FeatureCard icon={BookOpen} color="#8b5cf6" title={c.comp4Title} desc={c.comp4Desc} />
          </div>
        </Section>

        {/* ── Best Practices ── */}
        <Section title={c.bpTitle} subtitle={c.bpSubtitle}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 10 }}>
            <FeatureCard icon={Brain} color="#ec4899" title={c.bp1Title} desc={c.bp1Desc} />
            <FeatureCard icon={Sliders} color="#06b6d4" title={c.bp2Title} desc={c.bp2Desc} />
            <FeatureCard icon={Sparkles} color="#f97316" title={c.bp3Title} desc={c.bp3Desc} />
            <FeatureCard icon={Database} color="#3b82f6" title={c.bp4Title} desc={c.bp4Desc} />
          </div>
        </Section>

        {/* ── How It Works ── */}
        <Section title={c.archTitle} subtitle={c.archSubtitle}>
          <div
            style={{
              padding: 24, borderRadius: 10,
              background: t.bgContent,
              border: `1px solid ${t.border}`,
            }}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <StepCard num={1} title={c.arch1} desc={c.arch1Desc} />
              <StepCard num={2} title={c.arch2} desc={c.arch2Desc} />
              <StepCard num={3} title={c.arch3} desc={c.arch3Desc} />
              <StepCard num={4} title={c.arch4} desc={c.arch4Desc} />
            </div>
          </div>
        </Section>

        {/* ── Search + gallery ── */}
        <Section title={c.title} subtitle={`${prompts.length} ${c.source.toLowerCase()} prompts`}>
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
            ) : prompts.length === 0 ? (
              <div style={{ padding: '40px 16px', textAlign: 'center' }}>
                <FileText size={36} style={{ color: t.textMuted, opacity: 0.3, marginBottom: 8 }} />
                <p style={{ fontSize: 13, color: t.textMuted, margin: 0 }}>{c.empty}</p>
                <p style={{ fontSize: 11, color: t.textMuted, margin: '4px 0 0 0' }}>{c.emptyHint}</p>
              </div>
            ) : filtered.length === 0 ? (
              <p style={{ fontSize: 12, color: t.textMuted, padding: 16, textAlign: 'center' }}>{c.noMatch}</p>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 10 }}>
                {filtered.map(p => (
                  <PromptCard key={p.id} entry={p} onClick={() => openPrompt(p)} />
                ))}
              </div>
            )}
          </div>
        </Section>
      </div>
    </div>
  );
}
