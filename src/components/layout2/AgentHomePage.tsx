/**
 * AgentHomePage — landing page for the Agents activity.
 *
 * Rich introduction (~60%) explaining agent concepts (Observe-Reason-Act loop),
 * core building blocks, capabilities, and architecture, followed by a
 * template/gallery browser (~40%).
 * Supports zh/en language switching via react-i18next.
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useLayoutTokens } from './tokens';
import { useLayoutState } from './useLayout';
import apiClient from '../../lib/api-client';
import {
  Brain, Sparkles, Cpu, Search, Code, Layers, Plus, Loader,
  BookOpen, RefreshCw, GitBranch, Shield, Workflow, Puzzle,
  Database, Lightbulb, ArrowRight, Rocket, FileText,
  Sliders, Bot, MessagesSquare, Pencil,
} from 'lucide-react';

// ── Template data ────────────────────────────────────────────

interface TemplateAgent {
  id: string | number;
  name: string;
  description: string;
  icon?: string;
  category?: string;
  tags?: string[];
  system_prompt?: string;
  model?: string;
  temperature?: number;
  native_tools?: string[];
  is_builtin?: boolean;
}

const CATEGORY_CONFIG: Record<string, { icon: typeof Brain; color: string; labelEn: string; labelZh: string }> = {
  system:        { icon: Layers,  color: '#8b5cf6', labelEn: 'Template',        labelZh: 'Template' },
  custom:        { icon: Bot,     color: '#f97316', labelEn: 'Customer Build',  labelZh: 'Customer Build' },
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

  const c = isZh ? {
    // Hero
    heroTitle: 'Agents',
    heroSubtitle: '构建和管理你的 AI 智能体',
    heroP1: 'Agent（智能体）是由 LLM 驱动的自主系统。与传统链式调用不同，智能体运行在"观察 → 推理 → 行动"的循环中：感知输入 → 决定行动 → 调用工具 → 观察结果 → 继续迭代，直到完成任务。',
    heroP2: '每个 Agent 都是一个自包含的 AI 助手，拥有独立的系统提示词、选定的模型和自定义工具集。LangChain Agent 运行时负责编排——根据模型的决策调用正确的工具、管理对话上下文，并通过 SSE 实时流式传输响应。',
    heroP3: '基于 LangChain 久经考验的 Agent 框架，你的智能体支持任何 LLM 提供商（OpenAI、Anthropic、Google 等）、通过 MCP 服务器或原生函数定义的自定义工具，并可以从本地开发部署到生产服务器。',
    heroCta: '新建 Agent',
    heroBrowse: '浏览模板',

    // What is an Agent
    whatTitle: '什么是 Agent？',
    whatSubtitle: '在 LangChain 中，Agent 是能够决定行动步骤、调用外部工具并基于结果调整行为的智能系统。',
    whatP1: '与传统链式调用不同（链式调用预先定义了固定的执行路径），Agent 是"有主见的"——它们可以根据上下文动态决定下一步做什么。这种灵活性使得 Agent 特别适合需要知识检索、多步骤推理或外部工具交互的开放任务。',
    whatLoop1: '👁️ 观察 (Observe)',
    whatLoop1Desc: '接收用户输入，理解意图，感知当前环境和可用工具。',
    whatLoop2: '🧠 推理 (Reason)',
    whatLoop2Desc: '分析任务，决定需要哪些工具，规划执行步骤。',
    whatLoop3: '🔧 行动 (Act)',
    whatLoop3Desc: '调用工具（搜索、计算、文件操作等），处理结果，决定是否需要继续循环。',
    whatNote: '这个循环会持续进行，直到 Agent 确定任务完成或达到终止条件。你可以通过 max_iterations 参数控制最大循环次数。',

    // Core Components
    compTitle: '核心构建块',
    compSubtitle: '每个 Agent 由四个核心组件构成，共同决定了智能体的行为、能力和交互方式。',
    comp1Title: 'LLM 模型',
    comp1Desc: '智能体的"大脑"。支持 OpenAI、Anthropic、Google、Mistral、Groq 等主流提供商。你可以选择不同参数规格的模型来平衡推理能力与响应速度。每个模型可以独立配置温度、最大 Token 等参数。',
    comp2Title: '工具集',
    comp2Desc: '智能体的"双手"。内置工具包括：Web 搜索、文件操作、代码执行、数据库查询、API 调用等。支持 MCP 服务器协议和自定义 Python 函数工具，实现无限扩展。',
    comp3Title: '系统提示词',
    comp3Desc: '智能体的"个性"。通过精心设计的系统提示词定义 Agent 的角色、行为约束、输出格式和专业知识。提示词决定了 Agent 如何理解任务、如何选择工具、以及如何呈现结果。',
    comp4Title: '上下文记忆',
    comp4Desc: '智能体的"备忘录"。管理对话历史以保持连贯性，支持滑动窗口、摘要压缩和持久化存储。Agent 可以记住用户偏好、历史决策和已完成的步骤。',

    // Capabilities
    capTitle: '关键能力',
    capSubtitle: 'Agent 框架提供了以下核心能力，覆盖从基础交互到高级编排的完整层次。',
    cap1Title: '工具编排',
    cap1Desc: 'Agent 根据任务决策自动选择和调用工具。支持并行工具调用（同时调用多个独立工具）、结果合并以及依赖链式执行（一个工具的输出作为另一个工具的输入）。',
    cap2Title: '多模型支持',
    cap2Desc: '无缝切换不同模型提供商和规格。支持模型降级——主模型失败时自动切换备用模型。同个 Agent 的推理和工具调用可使用不同模型优化成本和效果。',
    cap3Title: '实时流式传输',
    cap3Desc: '通过 Server-Sent Events (SSE) 实时流式传输 Agent 的推理过程和工具调用结果。用户可以看到思考链的每个步骤——模型在思考什么、调用了什么工具、得到了什么结果。',
    cap4Title: '错误恢复',
    cap4Desc: '工具调用失败时自动重试（支持指数退避），解析错误时自动修正，模型响应异常时优雅降级。内置速率限制和超时控制，防止无限循环和资源过度消耗。',
    cap5Title: '上下文管理',
    cap5Desc: '滑动窗口限制历史 Token 数，自动对早期对话进行摘要压缩，工具调用结果超出限制时自动截断。支持多轮深度对话而不超出模型上下文窗口。',
    cap6Title: '自定义提示词',
    cap6Desc: '为每个 Agent 定制系统提示词，定义角色、行为约束和专业知识。支持提示词模板变量注入（如用户名称、当前日期、会话上下文），以及少样本示例增强。',

    // Architecture
    archTitle: '工作原理',
    archSubtitle: '从定义到运行，Agent 的执行流程分为四个阶段。',
    arch1: '定义角色',
    arch1Desc: '在编辑器中配置 Agent：编写系统提示词定义角色和行为，选择 LLM 模型并调整参数（温度、最大 Token），挂载所需的工具集。',
    arch2: '启动会话',
    arch2Desc: '发送消息启动对话。Agent 运行时创建上下文窗口，注入系统提示词和历史记忆（如果有），准备执行循环。',
    arch3: '推理循环',
    arch3Desc: 'Agent 执行 Observe → Reason → Act 循环：观察用户输入和工具结果，推理下一步行动，调用对应工具，观察新结果，直到任务完成或达到终止条件。',
    arch4: '输出结果',
    arch4Desc: 'Agent 生成最终响应并通过 SSE 流式传输给用户。会话上下文被保存，工具调用记录和 Token 消耗被记录供后续分析。',

    // Quick start
    quickTitle: '快速开始',
    qs1Title: '从空白创建',
    qs1Desc: '从一个空白 Agent 开始，自行配置模型、工具和系统提示词。',
    qs1Cta: '创建新 Agent',
    qs2Title: '从模板开始',
    qs2Desc: '浏览预置的 Agent 模板，覆盖代码审查、研究助手、测试等场景。',
    qs2Cta: '选择模板',
    qs3Title: '从已有 Agent',
    qs3Desc: '克隆和定制已有的 Agent 配置，快速迭代无需从零开始。',
    qs3Cta: '浏览你的 Agent',

    // Templates
    tplSearchPlaceholder: '搜索模板…',
    tplFilterAll: '全部',
    tplLoading: '加载中…',
    tplEmpty: '暂无 Agent',
    tplEmptyHint: '点击上方按钮创建你的第一个 Agent',
    tplNoMatch: '没有匹配的 Agent',
    tplError: '加载失败，请重试',
    tplNoDesc: '暂无描述',
  } : {
    // Hero
    heroTitle: 'Agents',
    heroSubtitle: 'Build and manage your AI Agents',
    heroP1: 'An Agent is an LLM-powered autonomous system. Unlike traditional chain-based interactions, agents operate in an "Observe \u2192 Reason \u2192 Act" loop: they perceive input, decide what to do, invoke tools, observe results, and iterate until the task is complete.',
    heroP2: 'Each Agent you create is a self-contained AI assistant with a defined system prompt, a selected model, and a custom set of tools. The LangChain Agent runtime handles orchestration — calling the right tools based on the model\'s decisions, managing conversation context, and streaming responses in real-time via SSE.',
    heroP3: 'Built on LangChain\'s battle-tested agent framework, your agents support any LLM provider (OpenAI, Anthropic, Google, and more), custom tool definitions via MCP servers or native Python functions, and can be deployed anywhere — from local development to production servers.',
    heroCta: 'New Agent',
    heroBrowse: 'Browse Templates',

    // What is an Agent
    whatTitle: 'What is an Agent?',
    whatSubtitle: 'In LangChain, an Agent is an intelligent system that can decide action steps, invoke external tools, and adjust its behavior based on results.',
    whatP1: 'Unlike traditional chains which follow a fixed, pre-defined execution path, agents are "opinionated" — they dynamically decide what to do next based on context. This flexibility makes agents ideal for open-ended tasks requiring knowledge retrieval, multi-step reasoning, or external tool interaction.',
    whatLoop1: '\uD83D\uDC41\u200DObserve',
    whatLoop1Desc: 'Receive user input, understand intent, perceive the current environment and available tools.',
    whatLoop2: '\uD83E\uDDE0 Reason',
    whatLoop2Desc: 'Analyze the task, determine which tools are needed, plan execution steps.',
    whatLoop3: '\uD83D\uDD27 Act',
    whatLoop3Desc: 'Invoke tools (search, compute, file ops, etc.), process results, decide whether to continue the loop.',
    whatNote: 'This loop continues until the agent determines the task is complete or a termination condition is met. You can control the maximum loop count via the max_iterations parameter.',

    // Core Components
    compTitle: 'Core Building Blocks',
    compSubtitle: 'Every Agent is composed of four core components that together define its behavior, capabilities, and interaction style.',
    comp1Title: 'LLM Model',
    comp1Desc: 'The "brain" of the agent. Supports major providers: OpenAI, Anthropic, Google, Mistral, Groq, and more. Choose different model sizes to balance reasoning power with response speed. Each model supports independent configuration of temperature, max tokens, and other parameters.',
    comp2Title: 'Tool Set',
    comp2Desc: 'The "hands" of the agent. Built-in tools include: web search (Tavily/SerpAPI), file operations, code execution, database queries, and API calls. Supports MCP server protocol and custom Python function tools for unlimited extensibility.',
    comp3Title: 'System Prompt',
    comp3Desc: 'The "personality" of the agent. A carefully crafted system prompt defines the agent\'s role, behavior constraints, output format, and domain expertise. It determines how the agent interprets tasks, selects tools, and presents results.',
    comp4Title: 'Context Memory',
    comp4Desc: 'The "notepad" of the agent. Manages conversation history for coherence, supporting sliding window, summary compression, and persistent storage. Agents can remember user preferences, past decisions, and previously completed steps.',

    // Capabilities
    capTitle: 'Key Capabilities',
    capSubtitle: 'The Agent framework provides core capabilities from basic interaction to advanced orchestration.',
    cap1Title: 'Tool Orchestration',
    cap1Desc: 'Agents automatically select and invoke tools based on task decisions. Supports parallel tool calls (invoking multiple independent tools simultaneously), result merging, and dependency chaining (output of one tool as input to another).',
    cap2Title: 'Multi-Provider Support',
    cap2Desc: 'Seamlessly switch between different model providers and sizes. Supports model fallback — automatic switch to a backup model when the primary fails. Reasoning and tool-calling can use different models to optimize cost and performance.',
    cap3Title: 'Real-time Streaming',
    cap3Desc: 'Stream the agent\'s reasoning process and tool call results in real-time via Server-Sent Events (SSE). Users can see every step — what the model is thinking, which tools were called, and what results were obtained.',
    cap4Title: 'Error Recovery',
    cap4Desc: 'Automatic retry on tool call failures (with exponential backoff), auto-correction on parse errors, and graceful degradation on model anomalies. Built-in rate limiting and timeout controls prevent infinite loops and resource exhaustion.',
    cap5Title: 'Context Management',
    cap5Desc: 'Sliding window to limit history tokens, automatic summarization compression of early conversation, auto-truncation of oversized tool results. Supports deep multi-turn conversations without exceeding the model\'s context window.',
    cap6Title: 'Custom Prompts',
    cap6Desc: 'Customize system prompts per agent to define role, behavior constraints, and domain expertise. Supports prompt template variable injection (user name, current date, session context) and few-shot examples for enhanced performance.',

    // Architecture
    archTitle: 'How It Works',
    archSubtitle: 'From definition to execution, the agent workflow follows four stages.',
    arch1: 'Define Role',
    arch1Desc: 'Configure your Agent in the editor: write a system prompt to define role and behavior, select an LLM model and tune parameters (temperature, max tokens), and attach the desired tool set.',
    arch2: 'Start Session',
    arch2Desc: 'Send a message to begin a conversation. The Agent runtime creates a context window, injects the system prompt and history memory (if any), and prepares the execution loop.',
    arch3: 'Reasoning Loop',
    arch3Desc: 'The Agent executes the Observe \u2192 Reason \u2192 Act cycle: observes user input and tool results, reasons about the next action, invokes the corresponding tool, observes new results — repeating until the task is complete or a termination condition is met.',
    arch4: 'Produce Output',
    arch4Desc: 'The Agent generates its final response and streams it via SSE. Session context is saved, tool call records and token consumption are logged for later analysis.',

    // Quick start
    quickTitle: 'Quick Start',
    qs1Title: 'From Scratch',
    qs1Desc: 'Start with a blank Agent and configure every layer — model, tools, and system prompt — yourself.',
    qs1Cta: 'Create Agent',
    qs2Title: 'From a Template',
    qs2Desc: 'Browse pre-built Agent templates for code review, research assistant, testing, and more.',
    qs2Cta: 'Choose Template',
    qs3Title: 'From Existing Agent',
    qs3Desc: 'Clone and customize an existing Agent configuration. Iterate quickly without starting from zero.',
    qs3Cta: 'Browse Your Agents',

    // Templates
    tplSearchPlaceholder: 'Search templates\u2026',
    tplFilterAll: 'All',
    tplLoading: 'Loading\u2026',
    tplEmpty: 'No Agents yet',
    tplEmptyHint: 'Click the button above to create your first Agent',
    tplNoMatch: 'No matching Agents',
    tplError: 'Failed to load. Please try again.',
    tplNoDesc: 'No description',
  };

  return c;
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

function FeatureCard({ icon: Icon, title, desc }: { icon: typeof Brain; title: string; desc: string }) {
  const t = useLayoutTokens();
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
          background: `${t.accent}15`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        <Icon size={16} color={t.accent} />
      </div>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, marginBottom: 2 }}>{title}</div>
        <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.5, margin: 0 }}>{desc}</p>
      </div>
    </div>
  );
}

// ── Quick-start action card ──────────────────────────────────

function QuickStartCard({
  icon: Icon, title, desc, cta, onClick, accent,
}: {
  icon: typeof Brain; title: string; desc: string; cta: string; onClick: () => void; accent: string;
}) {
  const t = useLayoutTokens();
  return (
    <button
      onClick={onClick}
      style={{
        flex: 1, minWidth: 180,
        padding: 18, borderRadius: 10,
        background: t.bgContent,
        border: `1px solid ${t.border}`,
        cursor: 'pointer',
        textAlign: 'left',
        display: 'flex', flexDirection: 'column', gap: 8,
        transition: 'border-color 0.15s, box-shadow 0.15s',
      }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = accent; e.currentTarget.style.boxShadow = '0 2px 10px rgba(0,0,0,0.08)'; }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.boxShadow = 'none'; }}
    >
      <div
        style={{
          width: 32, height: 32, borderRadius: 7,
          background: `${accent}15`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}
      >
        <Icon size={16} color={accent} />
      </div>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, marginBottom: 1 }}>{title}</div>
        <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.4, margin: 0 }}>{desc}</p>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, fontWeight: 600, color: accent, marginTop: 4 }}>
        {cta}
        <ArrowRight size={12} />
      </div>
    </button>
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

// ── Template card ────────────────────────────────────────────

function TemplateCard({ agent, onClick, onEdit }: {
  agent: TemplateAgent;
  onClick: () => void;
  /** Open the editor with the FULL agent loaded (user-created agents only). */
  onEdit?: (e: React.MouseEvent) => void;
}) {
  const t = useLayoutTokens();
  const c = useContent();
  const catCfg = getCategoryConfig(agent.category || '');
  const CatIcon = catCfg.icon;

  return (
    <div style={{ position: 'relative' }}>
      {onEdit && (
        <button
          onClick={e => { e.stopPropagation(); onEdit(e); }}
          title="Edit agent"
          style={{
            position: 'absolute', top: 8, right: 8, zIndex: 2,
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            width: 26, height: 26, borderRadius: 5,
            background: t.bgContent, color: t.textMuted,
            border: `1px solid ${t.border}`, cursor: 'pointer',
          }}
          onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; e.currentTarget.style.color = t.textPrimary; }}
          onMouseLeave={e => { e.currentTarget.style.background = t.bgContent; e.currentTarget.style.color = t.textMuted; }}
        >
          <Pencil size={13} />
        </button>
      )}
      <div
        onClick={onClick}
        style={{
          padding: 14, paddingRight: onEdit ? 40 : 14, borderRadius: 8, cursor: 'pointer',
          background: t.bgContent, border: `1px solid ${t.border}`,
          transition: 'border-color 0.15s',
        }}
        onMouseEnter={e => { e.currentTarget.style.borderColor = t.accent; }}
        onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; }}
      >
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

        <p style={{ fontSize: 11, color: t.textDim, margin: 0, lineHeight: 1.5, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
          {agent.description || c.tplNoDesc}
        </p>

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
    </div>
  );
}

// ── Hero intro section (rich content) ────────────────────────

function HeroCard({ onNewAgent }: { onNewAgent: () => void }) {
  const t = useLayoutTokens();
  const c = useContent();

  return (
    <div>
      {/* ── Hero banner ─────────────────────────────────── */}
      <div
        style={{
          background: `linear-gradient(135deg, ${t.accent}22 0%, ${t.accent}08 55%, ${t.bgContent} 100%)`,
          border: `1px solid ${t.border}`,
          borderRadius: 12,
          padding: '32px 28px',
          marginBottom: 24,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14 }}>
          <div
            style={{
              width: 44, height: 44, borderRadius: 11,
              background: `linear-gradient(135deg, ${t.accent}, ${t.accent}cc)`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: `0 3px 12px ${t.accent}35`,
            }}
          >
            <Brain size={22} color="#fff" />
          </div>
          <div>
            <h1 style={{ fontSize: 20, fontWeight: 750, color: t.textPrimary, margin: 0, letterSpacing: '-0.3px' }}>
              {c.heroTitle}
            </h1>
            <p style={{ fontSize: 12, color: t.textMuted, margin: '2px 0 0 0' }}>
              {c.heroSubtitle}
            </p>
          </div>
        </div>

        <p style={{ fontSize: 13, color: t.textMuted, lineHeight: 1.7, margin: '0 0 6px 0', maxWidth: 620 }}>{c.heroP1}</p>
        <p style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6, margin: '0 0 4px 0', maxWidth: 620, opacity: 0.85 }}>{c.heroP2}</p>
        <p style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6, margin: '0 0 18px 0', maxWidth: 620, opacity: 0.75 }}>{c.heroP3}</p>

        <div style={{ display: 'flex', gap: 10 }}>
          <button
            onClick={onNewAgent}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '8px 18px', borderRadius: 6,
              background: t.accent, color: '#fff',
              fontSize: 13, fontWeight: 600, border: 'none', cursor: 'pointer',
            }}
            onMouseEnter={e => { e.currentTarget.style.opacity = '0.9'; }}
            onMouseLeave={e => { e.currentTarget.style.opacity = '1'; }}
          >
            <Plus size={14} /> {c.heroCta}
          </button>
          <button
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '8px 16px', borderRadius: 6,
              border: `1px solid ${t.border}`,
              background: 'transparent',
              color: t.textPrimary,
              fontSize: 13, fontWeight: 500, cursor: 'pointer',
            }}
            onClick={() => document.getElementById('agent-templates')?.scrollIntoView({ behavior: 'smooth' })}
            onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
          >
            <BookOpen size={14} />
            {c.heroBrowse}
          </button>
        </div>
      </div>

      {/* ── What is an Agent — Observe → Reason → Act ───── */}
      <Section title={c.whatTitle} subtitle={c.whatSubtitle}>
        <div
          style={{
            padding: 20, borderRadius: 10,
            background: t.bgContent,
            border: `1px solid ${t.border}`,
          }}
        >
          <p style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.7, margin: '0 0 14px 0' }}>{c.whatP1}</p>

          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 180, padding: 12, borderRadius: 8, background: `${t.accent}08`, border: `1px solid ${t.border}` }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: t.textPrimary, marginBottom: 4 }}>{c.whatLoop1}</div>
              <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.5, margin: 0 }}>{c.whatLoop1Desc}</p>
            </div>
            <div style={{ flex: 1, minWidth: 180, padding: 12, borderRadius: 8, background: `${t.accent}08`, border: `1px solid ${t.border}` }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: t.textPrimary, marginBottom: 4 }}>{c.whatLoop2}</div>
              <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.5, margin: 0 }}>{c.whatLoop2Desc}</p>
            </div>
            <div style={{ flex: 1, minWidth: 180, padding: 12, borderRadius: 8, background: `${t.accent}08`, border: `1px solid ${t.border}` }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: t.textPrimary, marginBottom: 4 }}>{c.whatLoop3}</div>
              <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.5, margin: 0 }}>{c.whatLoop3Desc}</p>
            </div>
          </div>

          <div style={{
            marginTop: 12, padding: 10, borderRadius: 6,
            background: `${t.accent}06`, border: `1px solid ${t.border}`,
            fontSize: 11, color: t.textMuted, lineHeight: 1.6,
          }}>
            💡 {c.whatNote}
          </div>
        </div>
      </Section>

      {/* ── Core Building Blocks ────────────────────────── */}
      <Section title={c.compTitle} subtitle={c.compSubtitle}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10 }}>
          <div
            style={{
              padding: 18, borderRadius: 10,
              background: `linear-gradient(135deg, #6366f115, ${t.bgContent})`,
              border: `1px solid ${t.border}`,
              display: 'flex', flexDirection: 'column', gap: 10,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{ width: 36, height: 36, borderRadius: 8, background: '#6366f120', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Cpu size={18} color="#6366f1" />
              </div>
              <div style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary }}>{c.comp1Title}</div>
            </div>
            <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.6, margin: 0 }}>{c.comp1Desc}</p>
          </div>

          <div
            style={{
              padding: 18, borderRadius: 10,
              background: `linear-gradient(135deg, #22c55e15, ${t.bgContent})`,
              border: `1px solid ${t.border}`,
              display: 'flex', flexDirection: 'column', gap: 10,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{ width: 36, height: 36, borderRadius: 8, background: '#22c55e20', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Puzzle size={18} color="#22c55e" />
              </div>
              <div style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary }}>{c.comp2Title}</div>
            </div>
            <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.6, margin: 0 }}>{c.comp2Desc}</p>
          </div>

          <div
            style={{
              padding: 18, borderRadius: 10,
              background: `linear-gradient(135deg, #f59e0b15, ${t.bgContent})`,
              border: `1px solid ${t.border}`,
              display: 'flex', flexDirection: 'column', gap: 10,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{ width: 36, height: 36, borderRadius: 8, background: '#f59e0b20', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <FileText size={18} color="#f59e0b" />
              </div>
              <div style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary }}>{c.comp3Title}</div>
            </div>
            <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.6, margin: 0 }}>{c.comp3Desc}</p>
          </div>

          <div
            style={{
              padding: 18, borderRadius: 10,
              background: `linear-gradient(135deg, #3b82f615, ${t.bgContent})`,
              border: `1px solid ${t.border}`,
              display: 'flex', flexDirection: 'column', gap: 10,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{ width: 36, height: 36, borderRadius: 8, background: '#3b82f620', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Database size={18} color="#3b82f6" />
              </div>
              <div style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary }}>{c.comp4Title}</div>
            </div>
            <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.6, margin: 0 }}>{c.comp4Desc}</p>
          </div>
        </div>
      </Section>

      {/* ── Key Capabilities ───────────────────────────── */}
      <Section title={c.capTitle} subtitle={c.capSubtitle}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 10 }}>
          <FeatureCard icon={Workflow} title={c.cap1Title} desc={c.cap1Desc} />
          <FeatureCard icon={Bot} title={c.cap2Title} desc={c.cap2Desc} />
          <FeatureCard icon={MessagesSquare} title={c.cap3Title} desc={c.cap3Desc} />
          <FeatureCard icon={Shield} title={c.cap4Title} desc={c.cap4Desc} />
          <FeatureCard icon={Sliders} title={c.cap5Title} desc={c.cap5Desc} />
          <FeatureCard icon={Lightbulb} title={c.cap6Title} desc={c.cap6Desc} />
        </div>
      </Section>

      {/* ── How It Works (architecture stages) ─────────── */}
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

      {/* ── Quick-start actions ────────────────────────── */}
      <Section title={c.quickTitle}>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <QuickStartCard icon={Rocket} accent={t.accent} title={c.qs1Title} desc={c.qs1Desc} cta={c.qs1Cta} onClick={onNewAgent} />
          <QuickStartCard icon={Code} accent="#8b5cf6" title={c.qs2Title} desc={c.qs2Desc} cta={c.qs2Cta} onClick={() => document.getElementById('agent-templates')?.scrollIntoView({ behavior: 'smooth' })} />
          <QuickStartCard icon={GitBranch} accent="#06b6d4" title={c.qs3Title} desc={c.qs3Desc} cta={c.qs3Cta} onClick={() => {/* browse sidebar */}} />
        </div>
      </Section>
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

  // Load templates from API — all built-in presets are system templates.
  // A single shared AbortController ensures refresh/unmount cancel in-flight
  // requests so out-of-order responses can never overwrite newer data.
  const abortRef = useRef<AbortController | null>(null);

  const loadTemplates = useCallback(() => {
    abortRef.current?.abort();
    const abort = new AbortController();
    abortRef.current = abort;
    setLoading(true);
    setError(null);
    // Load built-in system templates + user-created regular agents
    // (use_deepagents=false) so the Agents browser shows editable custom builds.
    Promise.all([
      apiClient.apiFetch(`${apiClient.baseURL}/api/agents/templates`, { signal: abort.signal }),
      apiClient.listDeepAgents({ public_only: false, signal: abort.signal }),
    ])
      .then(([tplRes, dbRes]: any) => {
        if (abort.signal.aborted) return; // superseded by a newer request
        const tplData = (tplRes as any)?.data ?? tplRes ?? [];
        const tpl = (Array.isArray(tplData) ? tplData : []).map((t: any) => ({
          id: t.id,
          name: t.name,
          description: t.description || '',
          category: 'system',
          tags: t.tags || [],
          system_prompt: t.system_prompt,
          model: t.model,
          temperature: t.temperature,
          native_tools: t.mcp_tools || t.native_tools || [],
          is_builtin: true,
        }));

        // User-created REGULAR agents (use_deepagents=false) live in the same
        // deep_agent_templates table; surface them here with numeric ids so
        // the Edit button works.
        const dbData = (dbRes as any)?.data ?? dbRes ?? [];
        const userCreated = (Array.isArray(dbData) ? dbData : [])
          .filter((a: any) => a.config?.use_deepagents === false)
          .map((a: any) => ({
            id: a.id,
            name: a.name,
            description: a.description || '',
            category: 'custom',
            tags: a.tags || [],
            system_prompt: a.config?.system_prompt,
            model: a.config?.model,
            temperature: a.config?.temperature,
            native_tools: a.config?.native_tools || [],
            is_builtin: false,
          }));

        // Built-in first, then user-created (dedup by name)
        const seen = new Set(tpl.map((t: any) => t.name));
        setTemplates([...tpl, ...userCreated.filter((c: any) => !seen.has(c.name))]);
      })
      .catch(err => {
        if (abort.signal.aborted) return; // superseded by a newer request
        if (err?.name !== 'AbortError' && err?.name !== 'CanceledError') {
          console.error('Failed to load templates:', err);
          setError(c.tplError);
        }
      })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return abort;
  }, [c.tplError]);

  useEffect(() => {
    loadTemplates();
    return () => abortRef.current?.abort();
  }, [loadTemplates]);

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
        category: agent.category,
        new: true,
        tags: agent.tags || [],
        config: {
          system_prompt: agent.system_prompt,
          model: agent.model,
          temperature: agent.temperature || 0.7,
          native_tools: agent.native_tools || [],
        },
      },
    });
  };

  /** Open the editor with the FULL agent record (user-created agents only), so
   * Save persists every field instead of the card's partial config skeleton. */
  const handleEditClick = async (agent: TemplateAgent) => {
    if (typeof agent.id !== 'number') return; // built-in presets have string ids
    try {
      const res: any = await apiClient.getDeepAgent(agent.id);
      const full = (res as any)?.data ?? res;
      openTab({
        id: `agent-edit-${agent.id}`,
        label: agent.name,
        viewType: 'agent',
        data: full,
      });
    } catch (err: any) {
      console.error('Failed to load full agent for editing:', err);
      handleTemplateClick(agent);
    }
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
          <span style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary }}>{c.heroTitle}</span>
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
            <Plus size={13} /> {c.heroCta}
          </button>
        </div>
      </div>

      {/* ── Content area — rich intro + templates ──────── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '24px 24px' }}>
        {/* Rich intro section */}
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
                <TemplateCard
                  key={a.id}
                  agent={a}
                  onClick={() => handleTemplateClick(a)}
                  onEdit={typeof a.id === 'number' ? () => handleEditClick(a) : undefined}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
