/**
 * ToolHomePage — landing page for the Tools activity.
 *
 * Follows the PromptHomePage / AgentHomePage pattern: header bar
 * (title + refresh + new), hero intro, educational sections grounded in
 * LangChain's official tools docs (@tool decorator, StructuredTool,
 * bind_tools, tool calling loop, toolkits), followed by a search box and
 * gallery grid of native + custom tools.
 */
import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useLayoutTokens } from './tokens';
import { useLayoutState } from './useLayout';
import apiClient from '../../lib/api-client';
import {
  Wrench, Search, Plus, Loader, RefreshCw, Brain, Sparkles,
  Code, Layers, MessagesSquare, Package, Shield, Database, PenLine,
} from 'lucide-react';

// ── Data types ───────────────────────────────────────────────

interface ToolItem {
  id: string;
  name: string;
  description: string;
  category: string;
  requires_api_key: string | null;
}

interface CustomToolSummary {
  tool_id: string;
  name: string;
  tool_type: string;
  category: string;
}

// ── Bilingual content (grounded in LangChain tool docs) ─────

function useContent() {
  const { i18n } = useTranslation();
  const isZh = i18n.language.startsWith('zh');
  return isZh ? {
    title: 'Tools',
    subtitle: '工具：让模型能够行动',

    heroP1: '大语言模型本质上是"文本变换函数"：知识有截止日期，也无法查询数据库、调用 API 或执行代码。工具（Tool）就是桥梁——把有明确输入输出的可调用函数交给模型，让它在对话中自行决定何时调用、传什么参数，再基于结果继续推理。',
    heroP2: '这里汇集了所有原生工具与自定义工具。浏览、搜索、复用它们，或创建你自己的工具。',
    heroCta: 'New Tool',

    whatTitle: '什么是 Tool？',
    whatSubtitle: 'LangChain 概念：函数 + 描述',
    whatP1: '工具的本质是"函数 + 描述"。模型不直接执行代码——它通过 name 和 description 判断"该调哪个工具、传什么参数"，实际执行由 Python 运行时完成。因此工具的定义质量（名称、描述、参数 schema）直接决定了模型使用工具的可靠性。',
    whatP2: '类型注解是必需的：它们定义了工具的输入 schema；docstring 会成为工具描述——这是写给模型看的，务必准确说明工具用途与每个参数的含义。',
    whatNote: '工具定义质量 = 模型使用可靠性。含糊的描述会让模型选错工具或传错参数。',
    toolCode: `from langchain.tools import tool

@tool
def search_database(query: str, limit: int = 10) -> str:
    """Search the customer database for records
    matching the query.

    Args:
        query: Search terms to look for
        limit: Maximum number of results
    """
    return f"Found {limit} results for '{query}'"`,

    compTitle: '核心概念',
    compSubtitle: 'LangChain 工具体系的关键组件',
    comp1Title: '@tool 装饰器',
    comp1Desc: '创建工具的最简方式：从函数自动提取 name、docstring 描述与类型注解生成的参数 schema，一行代码即可把普通函数变成工具。',
    comp2Title: 'StructuredTool',
    comp2Desc: '程序化创建工具：用 Pydantic BaseModel 定义 args_schema，支持复杂多参数输入、字段校验与默认值，适合生产级工具。',
    comp3Title: 'bind_tools / ToolNode',
    comp3Desc: '用 model.bind_tools(tools) 把工具挂载到模型；在 LangGraph 中由 ToolNode 执行调用并把 ToolMessage 结果回传给模型。',
    comp4Title: 'Toolkits 工具包',
    comp4Desc: '面向特定领域的一组工具集合（如数据库、文件系统、浏览器），开箱即用地赋予 Agent 完整的领域操作能力。',

    bpTitle: '最佳实践',
    bpSubtitle: '让模型可靠使用工具的四个关键建议',
    bp1Title: '清晰命名',
    bp1Desc: '工具 name 是其唯一标识。名称要无歧义地传达用途——"GetCurrentWeather" 远胜 "GCW"。多工具时名称还能表达工具间的关系。',
    bp2Title: '详尽描述',
    bp2Desc: 'description 是模型选择工具的"说明书"，写在 docstring 里。准确说明做什么、何时用、参数含义，必要时给出示例。',
    bp3Title: '结构化输入',
    bp3Desc: '多参数场景使用 Pydantic schema 定义 args_schema：字段类型 + Field(description=...) 会进入模型可见的 JSON Schema，并自动校验输入。',
    bp4Title: '错误处理',
    bp4Desc: '在工具内部捕获异常并返回可读错误信息，而不是抛异常中断 Agent 循环。返回结构化结果，让模型能根据错误继续尝试。',

    loopTitle: '工具调用循环',
    loopSubtitle: 'Agent 使用工具的四步闭环',
    loop1: '模型决策',
    loop1Desc: '模型根据对话上下文判断是否需要工具，并生成 tool_calls（工具名 + 参数）。',
    loop2: '执行工具',
    loop2Desc: '运行时（LangGraph ToolNode）执行对应工具函数，获取真实数据或触发实际动作。',
    loop3: '结果回传',
    loop3Desc: '执行结果以 ToolMessage 追加回消息列表，模型据此继续推理。',
    loop4: '生成答复',
    loop4Desc: '模型综合工具结果生成最终答复；若需更多信息则继续发起新的工具调用。',

    searchPlaceholder: '搜索工具…',
    loading: '加载中…',
    empty: '暂无工具',
    emptyHint: '工具让智能体能够行动——创建你的第一个自定义工具',
    noMatch: '没有匹配的工具',
    newTool: 'New Tool',
    nativeSection: 'Native Tools',
    customSection: 'Custom Tools',
    noCustom: 'No custom tools yet — create one with the + button',
    keyBadge: 'API key',
    nativeBadge: 'native',
    open: 'open',
  } : {
    title: 'Tools',
    subtitle: 'Tools — let models take action',

    heroP1: 'LLMs are fundamentally "text-transform functions": their knowledge has a cutoff date, and they cannot query databases, call APIs, or execute code on their own. Tools are the bridge — callable functions with well-defined inputs and outputs are passed to the model, which decides when to invoke them and what arguments to provide, then reasons over the results.',
    heroP2: 'This library collects every native and custom tool. Browse, search and reuse them, or create your own.',
    heroCta: 'New Tool',

    whatTitle: 'What is a Tool?',
    whatSubtitle: 'LangChain concept: function + description',
    whatP1: 'A tool is essentially "function + description". The model does not run code — it uses name and description to decide which tool to call and with what arguments; execution happens in the Python runtime. So the quality of your tool definitions (name, description, args schema) directly determines how reliably the model uses them.',
    whatP2: 'Type hints are required: they define the tool\'s input schema. The docstring becomes the tool description — it is written for the model, so state the purpose and every parameter\'s meaning clearly.',
    whatNote: 'Tool definition quality = model usage reliability. Vague descriptions make the model pick the wrong tool or pass wrong arguments.',
    toolCode: `from langchain.tools import tool

@tool
def search_database(query: str, limit: int = 10) -> str:
    """Search the customer database for records
    matching the query.

    Args:
        query: Search terms to look for
        limit: Maximum number of results
    """
    return f"Found {limit} results for '{query}'"`,

    compTitle: 'Core Concepts',
    compSubtitle: 'Key components of the LangChain tool system',
    comp1Title: '@tool Decorator',
    comp1Desc: 'The simplest way to create a tool: name, docstring description and an args schema generated from type hints are extracted automatically — one line turns a plain function into a tool.',
    comp2Title: 'StructuredTool',
    comp2Desc: 'Programmatic tool creation with a Pydantic BaseModel args_schema: complex multi-arg inputs, field validation and defaults — ideal for production-grade tools.',
    comp3Title: 'bind_tools / ToolNode',
    comp3Desc: 'Attach tools to a model with model.bind_tools(tools); in LangGraph a ToolNode executes the calls and returns ToolMessage results to the model.',
    comp4Title: 'Toolkits',
    comp4Desc: 'Collections of tools for a specific domain (database, filesystem, browser) — ready-made capability sets for agents out of the box.',

    bpTitle: 'Best Practices',
    bpSubtitle: 'Four key tips for reliable tool use by models',
    bp1Title: 'Clear Names',
    bp1Desc: 'The tool name is its unique identifier. It should unambiguously convey purpose — "GetCurrentWeather" beats "GCW". With multiple tools, names can also express relationships.',
    bp2Title: 'Detailed Descriptions',
    bp2Desc: 'The description is the model\'s instruction manual, written in the docstring. State what it does, when to use it, and what each parameter means — add examples when needed.',
    bp3Title: 'Structured Inputs',
    bp3Desc: 'For multi-arg tools use a Pydantic args_schema: field types plus Field(description=...) land in the model-visible JSON Schema and validate inputs automatically.',
    bp4Title: 'Error Handling',
    bp4Desc: 'Catch exceptions inside tools and return readable error messages instead of breaking the agent loop. Return structured results so the model can retry or adapt.',

    loopTitle: 'The Tool Calling Loop',
    loopSubtitle: 'The closed four-step loop of an agent using tools',
    loop1: 'Model Decides',
    loop1Desc: 'Based on context, the model decides a tool is needed and emits tool_calls (tool name + arguments).',
    loop2: 'Execute Tool',
    loop2Desc: 'The runtime (LangGraph ToolNode) invokes the tool function and fetches real data or triggers the actual action.',
    loop3: 'Feed Back Result',
    loop3Desc: 'The result is appended to the message list as a ToolMessage for the model to reason over.',
    loop4: 'Produce Answer',
    loop4Desc: 'The model synthesizes a final answer from the tool result, or issues further tool calls if more info is needed.',

    searchPlaceholder: 'Search tools…',
    loading: 'Loading…',
    empty: 'No tools available',
    emptyHint: 'Tools let agents take action — create your first custom tool',
    noMatch: 'No matching tools',
    newTool: 'New Tool',
    nativeSection: 'Native Tools',
    customSection: 'Custom Tools',
    noCustom: 'No custom tools yet — create one with the + button',
    keyBadge: 'API key',
    nativeBadge: 'native',
    open: 'open',
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

// ── Tool card (shared by native + custom tools) ─────────────

function ToolCard({
  name, desc, badges, footer, onClick,
}: {
  name: string;
  desc: string;
  badges: React.ReactNode[];
  footer?: React.ReactNode;
  onClick: () => void;
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
          <Wrench size={14} color={t.accent} />
        </div>
        <span style={{
          fontSize: 13, fontWeight: 600, color: t.textPrimary,
          flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {name}
        </span>
      </div>

      <p style={{
        fontSize: 11, color: t.textDim, margin: 0, lineHeight: 1.5,
        display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden',
      }}>
        {desc}
      </p>

      <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, color: t.textMuted, marginTop: 2 }}>
        {badges}
        {footer && (
          <span style={{ marginLeft: 'auto', flexShrink: 0, color: t.accent, fontWeight: 600 }}>
            {footer}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────

export default function ToolHomePage() {
  const t = useLayoutTokens();
  const c = useContent();
  const { openTab } = useLayoutState();
  const [tools, setTools] = useState<ToolItem[]>([]);
  const [customTools, setCustomTools] = useState<CustomToolSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');

  const loadData = useCallback(() => {
    setLoading(true);
    Promise.all([
      apiClient.listToolRegistry().catch(() => [] as ToolItem[]),
      apiClient.listCustomTools().catch(() => [] as CustomToolSummary[]),
    ]).then(([toolRes, customRes]) => {
      const native: ToolItem[] = Array.isArray(toolRes) ? toolRes : ((toolRes as any)?.data || []);
      const custom: CustomToolSummary[] = Array.isArray(customRes) ? customRes : ((customRes as any)?.data || []);
      setTools(native);
      setCustomTools(custom);
    }).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleRefresh = useCallback(() => {
    loadData();
  }, [loadData]);

  /** Open a native tool's category grid (same as sidebar click) */
  const openCategory = useCallback((category: string) => {
    const items = tools.filter(t => (t.category || 'other') === category);
    openTab({
      id: `tool-cat-${category}`,
      label: category.charAt(0).toUpperCase() + category.slice(1),
      viewType: 'tool-category',
      data: { category, tools: items },
    });
  }, [openTab, tools]);

  /** Open the custom tool builder */
  const handleNewTool = useCallback(() => {
    openTab({
      id: `custom-tool-new-${Date.now()}`,
      label: c.newTool,
      viewType: 'custom-tool-builder',
      data: {},
    });
  }, [openTab, c.newTool]);

  const openCustomTool = useCallback((toolId: string) => {
    openTab({
      id: `custom-tool-${toolId}`,
      label: 'Edit Tool',
      viewType: 'custom-tool-builder',
      data: { existingToolId: toolId },
    });
  }, [openTab]);

  const q = searchQuery.trim().toLowerCase();
  const filteredNative = q
    ? tools.filter(t =>
        t.name.toLowerCase().includes(q) ||
        t.description.toLowerCase().includes(q) ||
        (t.category || '').toLowerCase().includes(q)
      )
    : tools;
  const filteredCustom = q
    ? customTools.filter(t =>
        t.name.toLowerCase().includes(q) ||
        (t.category || '').toLowerCase().includes(q) ||
        (t.tool_type || '').toLowerCase().includes(q)
      )
    : customTools;

  // Group native tools for display (flat grid, category badge on each card)
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
          <Wrench size={16} style={{ color: t.accent }} />
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
            onClick={handleNewTool}
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

        {/* ── What is a Tool? ── */}
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
                <Code size={11} /> @tool decorator · example
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
                {c.toolCode}
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

        {/* ── Core Concepts ── */}
        <Section title={c.compTitle} subtitle={c.compSubtitle}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 10 }}>
            <FeatureCard icon={Code} color="#6366f1" title={c.comp1Title} desc={c.comp1Desc} />
            <FeatureCard icon={Layers} color="#22c55e" title={c.comp2Title} desc={c.comp2Desc} />
            <FeatureCard icon={MessagesSquare} color="#f59e0b" title={c.comp3Title} desc={c.comp3Desc} />
            <FeatureCard icon={Package} color="#8b5cf6" title={c.comp4Title} desc={c.comp4Desc} />
          </div>
        </Section>

        {/* ── Best Practices ── */}
        <Section title={c.bpTitle} subtitle={c.bpSubtitle}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 10 }}>
            <FeatureCard icon={Brain} color="#ec4899" title={c.bp1Title} desc={c.bp1Desc} />
            <FeatureCard icon={Sparkles} color="#06b6d4" title={c.bp2Title} desc={c.bp2Desc} />
            <FeatureCard icon={Database} color="#f97316" title={c.bp3Title} desc={c.bp3Desc} />
            <FeatureCard icon={Shield} color="#3b82f6" title={c.bp4Title} desc={c.bp4Desc} />
          </div>
        </Section>

        {/* ── Tool Calling Loop ── */}
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
        <Section title={`${c.nativeSection} (${tools.length}) · ${c.customSection} (${customTools.length})`}>
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
            ) : filteredNative.length === 0 && filteredCustom.length === 0 ? (
              <p style={{ fontSize: 12, color: t.textMuted, padding: 16, textAlign: 'center' }}>{c.noMatch}</p>
            ) : (
              <>
                {/* ── Native tools (first) ── */}
                <div style={{ fontSize: 12, fontWeight: 600, color: t.textPrimary, marginBottom: 8 }}>
                  {c.nativeSection}
                </div>
                {filteredNative.length === 0 ? (
                  <p style={{ fontSize: 12, color: t.textMuted, padding: '8px 0' }}>{c.empty}</p>
                ) : (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 10, marginBottom: 16 }}>
                    {filteredNative.map(tool => (
                      <ToolCard
                        key={tool.id}
                        name={tool.name}
                        desc={tool.description}
                        badges={[
                          <span key="cat" style={{
                            padding: '1px 6px', borderRadius: 4,
                            background: t.bgHover, color: t.textMuted, fontSize: 9,
                          }}>
                            {tool.category}
                          </span>,
                          ...(tool.requires_api_key
                            ? [<span key="key" style={{
                                padding: '1px 6px', borderRadius: 4,
                                background: '#f59e0b18', color: '#f59e0b', fontSize: 9,
                              }}>
                                {c.keyBadge}
                              </span>]
                            : []),
                        ]}
                        footer={<>{c.open} →</>}
                        onClick={() => openCategory(tool.category || 'other')}
                      />
                    ))}
                  </div>
                )}

                {/* ── Custom tools (second) ── */}
                <div style={{ fontSize: 12, fontWeight: 600, color: t.textPrimary, marginBottom: 8 }}>
                  {c.customSection}
                </div>
                {filteredCustom.length === 0 ? (
                  <p style={{ fontSize: 12, color: t.textMuted, padding: '8px 0' }}>{c.noCustom}</p>
                ) : (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 10 }}>
                    {filteredCustom.map(tool => (
                      <ToolCard
                        key={tool.tool_id}
                        name={tool.name}
                        desc={`Custom tool · ${tool.tool_type}`}
                        badges={[
                          <span key="cat" style={{
                            padding: '1px 6px', borderRadius: 4,
                            background: t.bgHover, color: t.textMuted, fontSize: 9,
                          }}>
                            {tool.category || 'custom'}
                          </span>
                        ]}
                        footer={<>Edit →</>}
                        onClick={() => openCustomTool(tool.tool_id)}
                      />
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </Section>
      </div>
    </div>
  );
}
