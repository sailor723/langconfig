/**
 * DeepAgentHomePage — landing page for the DeepAgents activity.
 *
 * Rich introduction (~70%) focusing on the agent harness, middleware stack
 * (TodoList, Filesystem, Memory, etc.), and template cards (~30%).
 * Supports zh/en language switching via react-i18next.
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useLayoutTokens } from './tokens';
import { useLayoutState } from './useLayout';
import apiClient from '../../lib/api-client';
import {
  Brain, Cpu, Search, Code, Layers, Plus, Loader,
  GitBranch, Shield, Workflow, Puzzle, Database, Lightbulb,
  ArrowRight, Rocket, BookOpen,
  Network, FileText, Sliders, Bot, ListTodo, FolderOpen,
  MessagesSquare, GanttChartSquare, UserCheck,
  RefreshCw, AlertTriangle, ScrollText, Terminal,
  Globe, Box, Bug,
} from 'lucide-react';

// ── CSS visual components (replace unavailable images) ───────

/** Hero decorative visual — layers + icons */
function HeroVisual() {
  const t = useLayoutTokens();
  return (
    <div style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden', borderRadius: 10 }}>
      {/* Background gradient rings */}
      <div style={{ position: 'absolute', top: '20%', left: '10%', width: '80%', height: '80%', borderRadius: '50%', background: `${t.accent}12`, transform: 'translate(-10%, -10%)' }} />
      <div style={{ position: 'absolute', bottom: '10%', right: '5%', width: '60%', height: '60%', borderRadius: '50%', background: `${t.accent}08`, transform: 'translate(10%, 10%)' }} />
      {/* Center icons cluster */}
      <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', display: 'flex', gap: 8, alignItems: 'center' }}>
        <div style={{ width: 40, height: 40, borderRadius: 10, background: t.accent, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: `0 2px 12px ${t.accent}40` }}>
          <Brain size={20} color="#fff" />
        </div>
        <div style={{ width: 8, height: 8, borderRadius: '50%', background: t.textMuted, opacity: 0.3 }} />
        <div style={{ width: 32, height: 32, borderRadius: 8, background: `${t.accent}20`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <GitBranch size={16} color={t.accent} />
        </div>
        <div style={{ width: 8, height: 8, borderRadius: '50%', background: t.textMuted, opacity: 0.3 }} />
        <div style={{ width: 32, height: 32, borderRadius: 8, background: `${t.accent}20`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Database size={16} color={t.accent} />
        </div>
      </div>
      {/* Small decorative nodes */}
      <div style={{ position: 'absolute', top: '15%', left: '20%', width: 6, height: 6, borderRadius: '50%', background: t.accent, opacity: 0.4 }} />
      <div style={{ position: 'absolute', bottom: '20%', left: '30%', width: 5, height: 5, borderRadius: '50%', background: t.accent, opacity: 0.3 }} />
      <div style={{ position: 'absolute', top: '25%', right: '25%', width: 7, height: 7, borderRadius: '50%', background: t.accent, opacity: 0.35 }} />
      <div style={{ position: 'absolute', bottom: '30%', right: '20%', width: 5, height: 5, borderRadius: '50%', background: t.accent, opacity: 0.25 }} />
    </div>
  );
}

/** Middleware layers visual — colored stacked boxes */
function MiddlewareStackVisual() {
  const t = useLayoutTokens();
  const layers = [
    { label: 'TodoList', color: '#6366f1', w: 85 },
    { label: 'Filesystem', color: '#22c55e', w: 78 },
    { label: 'Memory', color: '#f59e0b', w: 72 },
    { label: 'Summarization', color: '#3b82f6', w: 65 },
    { label: 'Human-in-Loop', color: '#8b5cf6', w: 58 },
    { label: 'LangChain Agent', color: t.accent, w: 95, bold: true },
    { label: 'Fallback', color: '#06b6d4', w: 50 },
    { label: 'PII Filter', color: '#f97316', w: 45 },
  ];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, padding: 12 }}>
      {layers.map((l, i) => (
        <div
          key={l.label}
          style={{
            width: `${l.w}%`, padding: '5px 0', borderRadius: 5,
            background: i === 5 ? `${l.color}22` : `${l.color}15`,
            border: `1px solid ${l.color}40`,
            textAlign: 'center', fontSize: i === 5 ? 10 : 9,
            fontWeight: l.bold ? 700 : 500, color: l.color,
            whiteSpace: 'nowrap',
          }}
        >
          {l.bold ? `🤖 ${l.label}` : l.label}
        </div>
      ))}
    </div>
  );
}

/** Architecture visual — simple node-link diagram */
function ArchVisual() {
  const t = useLayoutTokens();
  const nodeStyle: React.CSSProperties = {
    padding: '6px 12px', borderRadius: 6,
    fontSize: 10, fontWeight: 600, textAlign: 'center' as const,
    background: `${t.accent}15`, border: `1px solid ${t.accent}30`,
    color: t.textPrimary,
  };
  const lineStyle: React.CSSProperties = {
    width: 1, height: 14, background: t.border, margin: '0 auto',
  };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0, padding: 20 }}>
      <div style={nodeStyle}>🎯 Define</div>
      <div style={lineStyle} />
      <div style={{ ...nodeStyle, background: '#6366f115', borderColor: '#6366f130', color: '#6366f1' }}>⚙️ Config</div>
      <div style={lineStyle} />
      <div style={{ ...nodeStyle, background: '#22c55e15', borderColor: '#22c55e30', color: '#22c55e' }}>📦 Deploy</div>
      <div style={lineStyle} />
      <div style={{ ...nodeStyle, background: '#f59e0b15', borderColor: '#f59e0b30', color: '#f59e0b' }}>🔄 Iterate</div>
    </div>
  );
}

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
  architecture:  { icon: Layers,  color: '#ec4899', labelEn: 'Architecture',   labelZh: 'Architecture' },
  documentation: { icon: FileText, color: '#06b6d4', labelEn: 'Documentation',  labelZh: 'Documentation' },
  debugging:     { icon: Bug,     color: '#f97316', labelEn: 'Debugging',      labelZh: 'Debugging' },
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
    heroTitle: '深度智能体',
    heroSubtitle: '基于 LangGraph 的智能体运行时框架 — Agent Harness',
    heroP1: 'DeepAgents 是一个面向长时间运行任务的开放式智能体运行时（Agent Harness）。它为 LLM 智能体提供了执行环境、工具系统、上下文管理和持久化存储等核心基础设施，让你可以快速构建能够规划、委派、记忆和自主决策的生产级智能体系统。',
    heroP2: '与从零构建不同，Harness 提供了"电池已包含"的完整方案：内置的中间件系统为你处理了任务规划（TodoList）、文件操作（Filesystem）、长期记忆（Memory）、上下文压缩、人工审批、模型降级等生产级别的关注点，让开发者可以专注于业务逻辑本身。',
    heroP3: 'DeepAgents 由 LangChain 开发并开源，无缝集成 LangGraph 工作流引擎和 LangSmith 可观测性平台。支持任何模型提供商，可在本地、云端或 LangSmith 上部署运行。',
    heroCta: '立即开始构建',
    heroBrowse: '浏览下方模板',

    // Agent Harness section
    harnessTitle: '什么是 Agent Harness？',
    harnessSubtitle: 'Agent Harness（智能体工具箱）是围绕 LLM 的一层生产级基础设施，它提供了模型本身不具备但生产环境必需的能力。',
    harnessP1: 'LLM 本身只是一个"大脑"——它能理解语言、生成文本，但无法操作文件、无法记住之前的对话、也无法执行代码或规划复杂任务。Agent Harness 就是围绕这个大脑构建的"身体"，它提供了 LLM 在真实世界中有效运作所需的一切能力。',
    harnessBrain: '🧠 LLM（大脑）',
    harnessBrainDesc: '理解指令、生成文本、推理决策。但无法操作外部世界，没有记忆，没有工具。',
    harnessBody: '+ Harness（身体）',
    harnessBodyDesc: '文件系统、任务规划器、记忆存储、安全护栏、工具集成、上下文管理…',
    harnessAgent: '= 生产级智能体',
    harnessAgentDesc: '可以自主运行数分钟到数小时，处理数十个步骤的复杂任务，安全可靠。',
    harnessInsight: '核心洞察：Harness 是你真正控制的部分。模型可以更换，但 Harness（系统提示词、工具描述、中间件架构）决定了智能体的行为上限。LangChain 在 Nemotron 3 Ultra 上的实验表明，仅通过优化 Harness 而不更换模型，可以将智能体在基准测试中的表现从 0.52 提升到 0.86，接近 Opus 4.8（0.87）的水平，而成本仅为后者的十分之一。',

    // Middleware
    middlewareTitle: '中间件系统',
    middlewareSubtitle: 'DeepAgents 的中间件（Middleware）是 Harness 的核心。每个中间件包装在 LangChain Agent 周围，为其注入特定的能力。以下是最核心的三个内建中间件：',
    mwTodoName: 'TodoListMiddleware',
    mwTodoLabel: '任务规划与跟踪',
    mwTodoDesc: '为智能体配备任务规划能力。智能体可以创建待办事项列表、标记完成状态、重新排列优先级、跟踪复杂多步骤任务的执行进度。这是 DeepAgents 实现"自主规划"的基础 — 智能体不再只是被动响应，而是可以主动制定和执行计划。',
    mwTodoCode: '# 示例：智能体可调用的工具\ntodo.create, todo.update, todo.complete, todo.list',
    mwFileLabel: '文件系统操作',
    mwFileDesc: '为智能体提供完整的文件系统操作能力。智能体可以创建、读取、编辑、搜索和删除文件。文件可以存储在内存（StateBackend）中实现临时存储，也可以通过 StoreBackend 持久化到 PostgreSQL、SQLite 或 MongoDB 等后端。内置的工具结果超限自动卸载机制 — 当工具调用结果超过 20000 tokens 时自动写入文件系统。',
    mwFileCode: '# 示例：智能体可调用的工具\nls, read_file, write_file, edit_file, glob, grep',
    mwMemLabel: '长期记忆与持久化',
    mwMemDesc: 'DeepAgents 将记忆作为一等公民。智能体可以跨会话读取和写入记忆文件，实现持续学习和个性化。支持三种记忆模式：短期记忆（对话历史/检查点）、长期记忆（跨会话持久化）和技能记忆（可重用的指令集）。使用 CompositeBackend 可以组合多种存储后端，实现灵活的混合存储策略。',
    mwMemCode: '# 支持的后端\nStateBackend（内存）、StoreBackend（持久）、CompositeBackend（混合）',
    mwFullCatalog: '完整中间件目录',

    // Middleware catalog items
    mwSummaryName: 'SummarizationMiddleware',
    mwSummaryLabel: '对话历史摘要',
    mwSummaryDesc: '当上下文接近 Token 限制时自动摘要历史对话，避免智能体丢失早期关键信息。',
    mwHitlName: 'HumanInTheLoopMiddleware',
    mwHitlLabel: '人工审批',
    mwHitlDesc: '在工具调用前暂停执行，等待人工审批。支持批准、拒绝、重定向和添加信息四种决策模式。',
    mwModelLimitName: 'ModelCallLimitMiddleware',
    mwModelLimitLabel: '模型调用限制',
    mwModelLimitDesc: '限制单次执行中的模型调用次数，防止无限循环和过度消耗 Token。',
    mwRetryName: 'ToolRetryMiddleware',
    mwRetryLabel: '工具重试',
    mwRetryDesc: '工具调用失败时自动重试，支持指数退避策略，提高系统鲁棒性。',
    mwPIIName: 'PIIMiddleware',
    mwPIILabel: '敏感信息检测',
    mwPIIDesc: '自动检测并处理个人身份信息（PII），确保智能体输出符合隐私合规要求。',
    mwSelectorName: 'LLMToolSelectorMiddleware',
    mwSelectorLabel: '工具预选择',
    mwSelectorDesc: '使用 LLM 在主模型调用前预选择相关工具，减少每次调用时传递给模型的工具数量。',
    mwFallbackName: 'ModelFallbackMiddleware',
    mwFallbackLabel: '模型降级',
    mwFallbackDesc: '主模型失败时自动切换到备用模型，确保系统的高可用性。',
    mwShellName: 'ShellToolMiddleware',
    mwShellLabel: 'Shell 执行',
    mwShellDesc: '为智能体提供持久化的 Shell 会话，支持执行命令、运行脚本等操作。',
    mwFileSearchName: 'FilesystemFileSearchMiddleware',
    mwFileSearchLabel: '文件搜索',
    mwFileSearchDesc: '提供 Glob 和 Grep 搜索工具，让智能体能够在文件系统中快速定位目标文件。',
    mwContextName: 'ContextEditingMiddleware',
    mwContextLabel: '上下文编辑',
    mwContextDesc: '管理和修剪对话上下文，清除已完成的工具调用记录，保持上下文窗口的清洁和高效。',
    mwToolLimitName: 'ToolCallLimitMiddleware',
    mwToolLimitLabel: '工具调用限制',
    mwToolLimitDesc: '控制智能体的工具执行次数，按调用次数限制防止资源过度消耗。',
    mwEmulatorName: 'LLMToolEmulator',
    mwEmulatorLabel: '工具模拟器',
    mwEmulatorDesc: '在测试环境中使用 LLM 模拟工具执行结果，便于调试和测试智能体行为。',

    // Why use
    whyTitle: '为什么要用 Deep Agents？',
    whySubtitle: '三个核心设计原则，让 DeepAgents 成为构建生产级多智能体系统的理想选择。',
    pillar1Title: '分解复杂目标',
    pillar1Desc: '内置规划工具让智能体能够将复杂任务分解为可管理的子任务，跟踪执行进度，并在学习过程中动态调整策略。',
    pillar1B1: '支持多步骤推理和任务分解',
    pillar1B2: '智能体可自主创建和执行任务计划',
    pillar1B3: 'TodoListMiddleware 提供原生任务跟踪',
    pillar2Title: '并行委派子任务',
    pillar2Desc: '可以衍生出独立的子智能体来处理并行子任务，每个子智能体拥有隔离的上下文窗口，避免主智能体的上下文污染。',
    pillar2B1: '每个子智能体有独立的上下文环境',
    pillar2B2: '支持同步和异步两种委派模式',
    pillar2B3: 'v0.5+ 支持远程异步子智能体',
    pillar3Title: '跨会话持久化知识',
    pillar3Desc: '虚拟文件系统和记忆系统让智能体可以在多次运行间保持知识和上下文，实现真正的持续学习和个性化服务。',
    pillar3B1: '多后端支持：内存、SQLite、PostgreSQL',
    pillar3B2: '记忆文件可通过 edit_file 工具更新',
    pillar3B3: '支持智能体作用域和用户作用域两种隔离级别',

    // Features
    featTitle: '核心能力',
    featSubtitle: 'DeepAgents 提供了 8 大核心能力，覆盖从基础工具到高级编排的完整层次。',
    feat1Title: '子智能体委派',
    feat1Desc: '将复杂任务分解为多个子任务，由专门的子智能体并行或串行处理。每个子智能体拥有独立上下文，主智能体只接收最终结果，有效避免上下文污染。',
    feat2Title: '中间件流水线',
    feat2Desc: '在智能体和输出之间注入 RAG 检索、验证检查、工具选择和反思层。支持自定义中间件开发，可灵活组合构建生产级可靠性的系统。',
    feat3Title: '长期记忆',
    feat3Desc: '文件系统、SQLite、PostgreSQL、MongoDB 等多种持久化后端。智能体可在多次会话间保持上下文，支持无限记忆扩展和灵活的混合存储策略。',
    feat4Title: '工具集成',
    feat4Desc: '无缝连接原生工具、MCP 服务器、自定义 Python 函数和第三方 API。支持渐进式工具能力发现（Skills 模式）和工具预选择优化。',
    feat5Title: '护栏与安全',
    feat5Desc: '内容审查、Token 限制、自动摘要触发器和人工审批关卡。支持四种人工介入模式：批准、拒绝、重定向、补充信息。',
    feat6Title: '规划与推理',
    feat6Desc: '内置规划循环，让智能体在生成最终输出前进行研究、批判、优化和策略调整。TodoListMiddleware 提供了原生的任务创建、更新、完成和列表跟踪能力。',
    feat7Title: '原生上下文管理',
    feat7Desc: '对话历史压缩、大型工具结果自动卸载到文件系统、子智能体上下文隔离、提示缓存 — 四大内置机制有效降低延迟和成本。',
    feat8Title: '模型无关',
    feat8Desc: '支持 OpenAI、Anthropic、Google、NVIDIA 等任何模型提供商。子智能体可使用与主智能体不同的模型。每个模型有预配置的 Harness Profile。',

    // Architecture
    archTitle: '架构概览',
    archSubtitle: '从定义目标到部署迭代，四个步骤构建生产级 DeepAgent。',
    arch1: '定义目标',
    arch1Desc: '描述你的多智能体系统需要完成什么任务 — 代码审查、研究助手、客服机器人。DeepAgent 会自动规划执行策略，TodoListMiddleware 会生成任务分解计划。',
    arch2: '配置子智能体与中间件',
    arch2Desc: '添加专门化的子智能体，为每个智能体分配角色和工具。选择需要的中间件：FilesystemMiddleware 提供文件操作能力，Memory 系统处理持久化存储。',
    arch3: '选择后端与部署方式',
    arch3Desc: '配置记忆后端（StateBackend/StoreBackend/CompositeBackend），选择模型提供商，设置沙箱和执行环境。',
    arch4: '运行、观测与迭代',
    arch4Desc: '在编辑器中运行 DeepAgent，通过 LangSmith 跟踪每一步决策。查看中间件执行日志，分析失败模式，快速迭代优化。',

    // Middleware wrapping
    wrapTitle: '中间件包裹模型',
    wrapSubtitle: '下图展示了中间件如何层层包裹在 LangChain Agent 周围，每一层在模型调用前后注入特定能力。',
    wrapLayer1: '⚡ TodoListMiddleware — 任务规划（创建/更新/完成待办事项）',
    wrapLayer2: '📁 FilesystemMiddleware — 文件操作（ls/read/write/edit/glob/grep）',
    wrapLayer3: '💾 Memory — 记忆系统（短期/长期/技能记忆 + 多后端持久化）',
    wrapLayer4: '📝 SummarizationMiddleware — 上下文摘要（接近限制时自动压缩历史）',
    wrapLayer5: '👤 HumanInTheLoopMiddleware — 人工审批（工具调用前暂停等待审批）',
    wrapLayer6: '🤖 LangChain Agent（核心模型 + 工具调用）',
    wrapLayer7: '🔄 ModelFallbackMiddleware — 模型降级（主模型失败时自动切换备用模型）',
    wrapLayer8: '🛡️ PIIMiddleware — 敏感信息检测（输出前过滤个人身份信息）',

    // Comparison
    compTitle: '何时使用 Deep Agents？',
    compSubtitle: '根据你的需求选择合适的框架层级。',
    compColDeep: 'Deep Agents',
    compColLangGraph: 'LangGraph',
    compColLangChain: 'LangChain',
    compRowAutonomy: '自主决策',
    compRowAutonomyDeep: '✅ 原生支持（规划 + 任务分解）',
    compRowAutonomyLG: '需要手动配置',
    compRowAutonomyLC: '基础支持',
    compRowSubagents: '子智能体委派',
    compRowSubagentsDeep: '✅ 一等公民（同步/异步）',
    compRowSubagentsLG: '需手动构建子图',
    compRowSubagentsLC: '不支持',
    compRowLongRunning: '长时间运行任务',
    compRowLongRunningDeep: '✅ 专为此设计（数分钟到数小时）',
    compRowLongRunningLG: '支持（需手动管理状态）',
    compRowLongRunningLC: '有限支持',
    compRowCtx: '上下文管理',
    compRowCtxDeep: '✅ 自动摘要、卸载、隔离、缓存',
    compRowCtxLG: '需手动实现',
    compRowCtxLC: '基础',
    compRowMemory: '记忆持久化',
    compRowMemoryDeep: '✅ 多后端 + CompositeBackend',
    compRowMemoryLG: '可集成 Store API',
    compRowMemoryLC: '不支持',
    compRowMW: '中间件系统',
    compRowMWDeep: '✅ 12+ 内置中间件',
    compRowMWLG: '需自己构建',
    compRowMWLC: '基础',
    compRowSafety: '安全检查',
    compRowSafetyDeep: '✅ 内置 PII、HITL、Token 限制',
    compRowSafetyLG: '可添加节点',
    compRowSafetyLC: '基础',
    compRowControl: '底层控制',
    compRowControlDeep: '基于 LangGraph',
    compRowControlLG: '✅ 精细控制节点和状态',
    compRowControlLC: '中等',
    compRowQuick: '快速上手',
    compRowQuickDeep: '学习曲线较高',
    compRowQuickLG: '中等',
    compRowQuickLC: '✅ 最简单',
    compRowScenario: '典型场景',
    compRowScenarioDeep: '研究助手、编码代理、客服系统',
    compRowScenarioLG: '工作流自动化、状态机',
    compRowScenarioLC: '简单 RAG、链式调用',
    compFooter: '简单来说：需要高度自主、长时间运行、多智能体协作的场景选择 Deep Agents；需要精细控制工作流状态和节点逻辑的选择 LangGraph；快速构建标准 LLM 应用的选择 LangChain。三者并非互斥 — Deep Agents 构建在 LangGraph 之上，你可以同时使用它们的能力。',

    // Quick start
    quickTitle: '快速开始',
    qs1Title: '从空白开始',
    qs1Desc: '从一个空白 DeepAgent 开始，自行配置中间件、子智能体和记忆系统。',
    qs1Cta: '创建空白智能体',
    qs2Title: '从模板开始',
    qs2Desc: '浏览预置的模板，覆盖代码审查、研究、测试等场景。模板已配置好最佳中间件组合。',
    qs2Cta: '选择下方模板',
    qs3Title: '从已有智能体',
    qs3Desc: '克隆并定制已有的 DeepAgent 配置。快速迭代，无需从零开始。',
    qs3Cta: '浏览你的智能体',

    // Templates
    tplTitle: '模板',
    tplIntroTab: '介绍',
    tplBrowseTab: '浏览模板',
    tplFilterAll: '全部',
    tplSearchPlaceholder: '按名称或标签搜索模板...',
    tplNoMatch: '没有匹配的模板',
    tplLoading: '正在加载模板...',
    tplError: '无法加载模板',
    tplEmpty: '暂无可用模板',
    tplEmptyHint: '创建一个新的 DeepAgent 来开始使用',
    tplNoDesc: '暂无描述',
  } : {
    // Hero
    heroTitle: 'DeepAgents',
    heroSubtitle: 'Multi-agent orchestration framework powered by LangGraph — Agent Harness',
    heroP1: 'DeepAgents is an open-source agent runtime (Agent Harness) designed for long-running tasks. It provides the core infrastructure — execution environment, tool system, context management, and persistent storage — that lets you build production-grade agent systems capable of planning, delegation, memory, and autonomous decision-making.',
    heroP2: 'Unlike building from scratch, the Harness comes batteries-included: built-in middleware handles task planning (TodoList), file operations (Filesystem), long-term memory (Memory), context compression, human approval, model fallback, and other production concerns — allowing developers to focus on business logic.',
    heroP3: 'Developed and open-sourced by LangChain, DeepAgents seamlessly integrates with the LangGraph workflow engine and the LangSmith observability platform. Supports any model provider and can be deployed locally, in the cloud, or on LangSmith.',
    heroCta: 'Start Building',
    heroBrowse: 'Browse Templates',

    // Agent Harness section
    harnessTitle: 'What is an Agent Harness?',
    harnessSubtitle: 'An Agent Harness is the production-grade infrastructure layer around an LLM, providing capabilities that the model itself lacks but production environments require.',
    harnessP1: 'An LLM is just a "brain" — it understands language and generates text, but it cannot operate files, remember past conversations, execute code, or plan complex tasks. The Agent Harness is the "body" built around this brain, providing everything the LLM needs to operate effectively in the real world.',
    harnessBrain: '🧠 LLM (Brain)',
    harnessBrainDesc: 'Understands instructions, generates text, reasons and decides. But cannot interact with the outside world — no memory, no tools.',
    harnessBody: '+ Harness (Body)',
    harnessBodyDesc: 'Filesystem, task planner, memory storage, safety guardrails, tool integration, context management...',
    harnessAgent: '= Production Agent',
    harnessAgentDesc: 'Runs autonomously for minutes to hours, handles complex multi-step tasks, safe and reliable.',
    harnessInsight: 'Key Insight: The Harness is what you truly control. Models can be swapped, but the Harness (system prompt, tool descriptions, middleware architecture) determines agent behavior. LangChain experiments on Nemotron 3 Ultra showed that optimizing only the Harness — without changing the model — lifted benchmark performance from 0.52 to 0.86, approaching Opus 4.8 (0.87), at one-tenth the cost.',

    // Middleware
    middlewareTitle: 'Middleware System',
    middlewareSubtitle: 'Middleware is the core of the DeepAgents Harness. Each middleware layer wraps around the LangChain Agent to inject specific capabilities. Below are the three most important built-in middleware components:',
    mwTodoName: 'TodoListMiddleware',
    mwTodoLabel: 'Task Planning & Tracking',
    mwTodoDesc: 'Equips the agent with task planning capabilities. The agent can create todo lists, mark completion status, reprioritize, and track progress of complex multi-step tasks. This is the foundation of "autonomous planning" in DeepAgents — agents no longer just react, they actively plan and execute.',
    mwTodoCode: '# Example: Agent-callable tools\ntodo.create, todo.update, todo.complete, todo.list',
    mwFileLabel: 'Filesystem Operations',
    mwFileDesc: 'Provides complete filesystem operations. Agents can create, read, edit, search, and delete files. Files can be stored in memory (StateBackend) for temporary storage, or persisted to PostgreSQL, SQLite, or MongoDB via StoreBackend. Built-in tool-result offloading automatically writes large results (>20K tokens) to the filesystem.',
    mwFileCode: '# Example: Agent-callable tools\nls, read_file, write_file, edit_file, glob, grep',
    mwMemLabel: 'Long-term Memory & Persistence',
    mwMemDesc: 'DeepAgents treats memory as a first-class citizen. Agents can read and write memory files across sessions for continuous learning. Three memory modes: short-term (conversation history/checkpoints), long-term (cross-session persistence), and skill memory (reusable instruction sets). CompositeBackend combines multiple storage backends for flexible hybrid strategies.',
    mwMemCode: '# Supported backends\nStateBackend (memory), StoreBackend (persistent), CompositeBackend (hybrid)',
    mwFullCatalog: 'Complete Middleware Catalog',

    // Middleware catalog items
    mwSummaryName: 'SummarizationMiddleware',
    mwSummaryLabel: 'Conversation Summarization',
    mwSummaryDesc: 'Automatically summarizes conversation history when approaching the token limit, preventing the agent from losing early critical information.',
    mwHitlName: 'HumanInTheLoopMiddleware',
    mwHitlLabel: 'Human Approval',
    mwHitlDesc: 'Pauses execution before tool calls, awaiting human approval. Supports four decision modes: approve, reject, redirect, and supplement information.',
    mwModelLimitName: 'ModelCallLimitMiddleware',
    mwModelLimitLabel: 'Model Call Limits',
    mwModelLimitDesc: 'Limits model invocations per execution to prevent infinite loops and excessive token consumption.',
    mwRetryName: 'ToolRetryMiddleware',
    mwRetryLabel: 'Tool Retry',
    mwRetryDesc: 'Automatically retries failed tool calls with exponential backoff, improving system robustness.',
    mwPIIName: 'PIIMiddleware',
    mwPIILabel: 'PII Detection',
    mwPIIDesc: 'Automatically detects and handles personally identifiable information (PII) to ensure privacy compliance.',
    mwSelectorName: 'LLMToolSelectorMiddleware',
    mwSelectorLabel: 'Tool Pre-selection',
    mwSelectorDesc: 'Uses an LLM to pre-select relevant tools before the main model call, reducing the tool set passed to the model.',
    mwFallbackName: 'ModelFallbackMiddleware',
    mwFallbackLabel: 'Model Fallback',
    mwFallbackDesc: 'Automatically switches to a fallback model when the primary model fails, ensuring high availability.',
    mwShellName: 'ShellToolMiddleware',
    mwShellLabel: 'Shell Execution',
    mwShellDesc: 'Provides persistent shell sessions for agents, supporting command execution and script running.',
    mwFileSearchName: 'FilesystemFileSearchMiddleware',
    mwFileSearchLabel: 'File Search',
    mwFileSearchDesc: 'Provides Glob and Grep search tools, enabling agents to quickly locate target files in the filesystem.',
    mwContextName: 'ContextEditingMiddleware',
    mwContextLabel: 'Context Editing',
    mwContextDesc: 'Manages and prunes conversation context, clearing completed tool call records to keep the context window clean and efficient.',
    mwToolLimitName: 'ToolCallLimitMiddleware',
    mwToolLimitLabel: 'Tool Call Limits',
    mwToolLimitDesc: 'Controls agent tool execution count, preventing excessive resource consumption.',
    mwEmulatorName: 'LLMToolEmulator',
    mwEmulatorLabel: 'Tool Emulator',
    mwEmulatorDesc: 'Uses an LLM to simulate tool execution results in test environments for debugging and testing agent behavior.',

    // Why use
    whyTitle: 'Why Use Deep Agents?',
    whySubtitle: 'Three core design principles make DeepAgents the ideal choice for building production-grade multi-agent systems.',
    pillar1Title: 'Decompose Complex Objectives',
    pillar1Desc: 'Built-in planning tools let agents break complex tasks into manageable subtasks, track progress, and dynamically adjust strategies as they learn.',
    pillar1B1: 'Multi-step reasoning and task decomposition',
    pillar1B2: 'Autonomous plan creation and execution',
    pillar1B3: 'Native task tracking via TodoListMiddleware',
    pillar2Title: 'Delegate in Parallel',
    pillar2Desc: 'Spawn independent sub-agents for parallel subtasks, each with isolated context windows to prevent context pollution of the main agent.',
    pillar2B1: 'Independent context per sub-agent',
    pillar2B2: 'Both sync and async delegation modes',
    pillar2B3: 'Remote async sub-agents (v0.5+)',
    pillar3Title: 'Persist Across Sessions',
    pillar3Desc: 'Virtual filesystem and memory systems let agents retain knowledge and context across runs, enabling true continuous learning and personalization.',
    pillar3B1: 'Multi-backend: memory, SQLite, PostgreSQL',
    pillar3B2: 'Memory files updatable via edit_file tool',
    pillar3B3: 'Agent-scoped and user-scoped isolation levels',

    // Features
    featTitle: 'Core Capabilities',
    featSubtitle: 'DeepAgents provides 8 core capabilities covering the full stack from basic tools to advanced orchestration.',
    feat1Title: 'Subagent Delegation',
    feat1Desc: 'Decompose complex tasks into smaller subtasks handled by specialized sub-agents running in parallel or sequence. Each sub-agent has independent context; the main agent receives only the final result.',
    feat2Title: 'Middleware Pipeline',
    feat2Desc: 'Inject RAG retrieval, validation checks, tool selection, and reflection layers between the agent and its output. Supports custom middleware development for production-grade reliability.',
    feat3Title: 'Long-term Memory',
    feat3Desc: 'Multiple persistence backends: filesystem, SQLite, PostgreSQL, MongoDB. Agents retain context across sessions with unlimited memory expansion and flexible hybrid storage.',
    feat4Title: 'Tool Integration',
    feat4Desc: 'Seamlessly connect native tools, MCP servers, custom Python functions, and third-party APIs. Supports progressive skill discovery and tool pre-selection optimization.',
    feat5Title: 'Guardrails & Safety',
    feat5Desc: 'Content moderation, token limits, automatic summarization triggers, and human approval gates. Four intervention modes: approve, reject, redirect, supplement.',
    feat6Title: 'Planning & Reasoning',
    feat6Desc: 'Built-in planning loop lets the agent research, critique, optimize, and adjust strategies before producing final output. Native task tracking via TodoListMiddleware.',
    feat7Title: 'Context Management',
    feat7Desc: 'Conversation history compression, large tool result offloading, sub-agent context isolation, and prompt caching — four built-in mechanisms for reduced latency and cost.',
    feat8Title: 'Model Agnostic',
    feat8Desc: 'Supports OpenAI, Anthropic, Google, NVIDIA, and any model provider. Sub-agents can use different models than the main agent. Pre-configured Harness Profiles per model.',

    // Architecture
    archTitle: 'Architecture Overview',
    archSubtitle: 'Four steps from defining objectives to deploying production-grade DeepAgents.',
    arch1: 'Define Objectives',
    arch1Desc: 'Describe what your multi-agent system needs to accomplish — code review, research assistant, or customer support bot. DeepAgent automatically plans execution strategy.',
    arch2: 'Configure Sub-agents & Middleware',
    arch2Desc: 'Add specialized sub-agents with assigned roles and tools. Select middleware: FilesystemMiddleware for file operations, Memory system for persistent storage.',
    arch3: 'Choose Backend & Deployment',
    arch3Desc: 'Configure memory backend (StateBackend/StoreBackend/CompositeBackend), select model providers, set up sandbox and execution environment.',
    arch4: 'Run, Observe & Iterate',
    arch4Desc: 'Run your DeepAgent in the editor, trace every decision via LangSmith. Review middleware execution logs, analyze failure patterns, iterate quickly.',

    // Middleware wrapping
    wrapTitle: 'Middleware Wrapping',
    wrapSubtitle: 'This diagram shows how middleware layers wrap around the LangChain Agent, each injecting specific capabilities before and after model calls.',
    wrapLayer1: '⚡ TodoListMiddleware — Task planning (create/update/complete todos)',
    wrapLayer2: '📁 FilesystemMiddleware — File ops (ls/read/write/edit/glob/grep)',
    wrapLayer3: '💾 Memory System — Short/long-term/skill memory + multi-backend',
    wrapLayer4: '📝 SummarizationMiddleware — Auto-summarize near token limits',
    wrapLayer5: '👤 HumanInTheLoopMiddleware — Pause for human approval',
    wrapLayer6: '🤖 LangChain Agent (Core model + tool calling)',
    wrapLayer7: '🔄 ModelFallbackMiddleware — Auto-switch on primary failure',
    wrapLayer8: '🛡️ PIIMiddleware — Filter PII before output',

    // Comparison
    compTitle: 'When to Use Deep Agents?',
    compSubtitle: 'Choose the right framework layer for your needs.',
    compColDeep: 'Deep Agents',
    compColLangGraph: 'LangGraph',
    compColLangChain: 'LangChain',
    compRowAutonomy: 'Autonomous Decision-making',
    compRowAutonomyDeep: '✅ Native (planning + decomposition)',
    compRowAutonomyLG: 'Manual setup needed',
    compRowAutonomyLC: 'Basic support',
    compRowSubagents: 'Subagent Delegation',
    compRowSubagentsDeep: '✅ First-class (sync/async)',
    compRowSubagentsLG: 'Manual subgraph construction',
    compRowSubagentsLC: 'Not supported',
    compRowLongRunning: 'Long-running Tasks',
    compRowLongRunningDeep: '✅ Designed for this (minutes to hours)',
    compRowLongRunningLG: 'Supported (manual state management)',
    compRowLongRunningLC: 'Limited support',
    compRowCtx: 'Context Management',
    compRowCtxDeep: '✅ Auto-summarize, offload, isolate, cache',
    compRowCtxLG: 'Manual implementation',
    compRowCtxLC: 'Basic',
    compRowMemory: 'Memory Persistence',
    compRowMemoryDeep: '✅ Multi-backend + CompositeBackend',
    compRowMemoryLG: 'Integrate via Store API',
    compRowMemoryLC: 'Not supported',
    compRowMW: 'Middleware System',
    compRowMWDeep: '✅ 12+ built-in middleware',
    compRowMWLG: 'Build your own',
    compRowMWLC: 'Basic',
    compRowSafety: 'Safety Checks',
    compRowSafetyDeep: '✅ Built-in PII, HITL, token limits',
    compRowSafetyLG: 'Add via nodes',
    compRowSafetyLC: 'Basic',
    compRowControl: 'Low-level Control',
    compRowControlDeep: 'Built on LangGraph',
    compRowControlLG: '✅ Fine-grained node/state control',
    compRowControlLC: 'Medium',
    compRowQuick: 'Quick Start',
    compRowQuickDeep: 'Steeper learning curve',
    compRowQuickLG: 'Medium',
    compRowQuickLC: '✅ Easiest',
    compRowScenario: 'Typical Use Cases',
    compRowScenarioDeep: 'Research assistant, coding agent, customer support',
    compRowScenarioLG: 'Workflow automation, state machines',
    compRowScenarioLC: 'Simple RAG, chain calls',
    compFooter: 'In short: choose Deep Agents for highly autonomous, long-running, multi-agent collaboration; LangGraph for fine-grained workflow state and node control; LangChain for quick standard LLM applications. They are not mutually exclusive — Deep Agents is built on LangGraph.',

    // Quick start
    quickTitle: 'Quick Start',
    qs1Title: 'From Scratch',
    qs1Desc: 'Start with a blank DeepAgent and configure every layer — middleware, sub-agents, and memory system — yourself.',
    qs1Cta: 'Create Blank Agent',
    qs2Title: 'From a Template',
    qs2Desc: 'Browse pre-built templates for code review, research, testing, and more. Templates come with optimal middleware combinations pre-configured.',
    qs2Cta: 'Choose a Template',
    qs3Title: 'From Existing Agent',
    qs3Desc: 'Clone and customize an existing DeepAgent configuration. Iterate quickly without starting from zero.',
    qs3Cta: 'Browse Your Agents',

    // Templates
    tplTitle: 'Templates',
    tplIntroTab: 'Introduction',
    tplBrowseTab: 'Browse Templates',
    tplFilterAll: 'All',
    tplSearchPlaceholder: 'Search templates by name or tag...',
    tplNoMatch: 'No templates match your search.',
    tplLoading: 'Loading templates...',
    tplError: 'Failed to load templates',
    tplEmpty: 'No templates available',
    tplEmptyHint: 'Create a new DeepAgent to get started',
    tplNoDesc: 'No description',
  };

  return c;
}

// ── Section wrapper ──────────────────────────────────────────

function Section({ title, children, subtitle }: { title: string; children: React.ReactNode; subtitle?: string }) {
  const t = useLayoutTokens();
  return (
    <div style={{ marginBottom: 32 }}>
      <div style={{ marginBottom: 12 }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, color: t.textPrimary, margin: 0, letterSpacing: '-0.2px' }}>
          {title}
        </h2>
        {subtitle && <p style={{ fontSize: 12, color: t.textMuted, margin: '4px 0 0 0', lineHeight: 1.5 }}>{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

// ── Pillar card ──────────────────────────────────────────────

function PillarCard({ icon: Icon, title, desc, bullets }: { icon: typeof Brain; title: string; desc: string; bullets?: string[] }) {
  const t = useLayoutTokens();
  return (
    <div
      style={{
        padding: 20, borderRadius: 10,
        background: t.bgContent,
        border: `1px solid ${t.border}`,
        display: 'flex', flexDirection: 'column', gap: 10,
        flex: 1, minWidth: 220,
      }}
    >
      <div
        style={{
          width: 36, height: 36, borderRadius: 8,
          background: `${t.accent}15`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}
      >
        <Icon size={18} color={t.accent} />
      </div>
      <div>
        <div style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary, marginBottom: 4 }}>{title}</div>
        <p style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.5, margin: 0 }}>{desc}</p>
        {bullets && (
          <ul style={{ margin: '8px 0 0 0', paddingLeft: 16, fontSize: 11, color: t.textMuted, lineHeight: 1.6 }}>
            {bullets.map(b => <li key={b}>{b}</li>)}
          </ul>
        )}
      </div>
    </div>
  );
}

// ── Middleware card ───────────────────────────────────────────

function MiddlewareCard({
  icon: Icon, name, label, desc, color,
}: {
  icon: typeof Brain; name: string; label: string; desc: string; color: string;
}) {
  const t = useLayoutTokens();
  return (
    <div
      style={{
        padding: 14, borderRadius: 10,
        background: t.bgContent,
        border: `1px solid ${t.border}`,
        display: 'flex', flexDirection: 'column', gap: 8,
        overflow: 'hidden',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div
          style={{
            width: 30, height: 30, borderRadius: 7,
            background: `${color}18`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          <Icon size={15} color={color} />
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: t.textPrimary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</div>
          <p style={{ fontSize: 10, color: color, fontWeight: 500, margin: '1px 0 0 0', lineHeight: 1.3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</p>
        </div>
      </div>
      <p style={{
        fontSize: 11, color: t.textMuted, lineHeight: 1.5, margin: 0,
        overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical',
      }}>
        {desc}
      </p>
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

// ── Comparison row ───────────────────────────────────────────

function ComparisonRow({
  label, deep, langgraph, langchain,
}: {
  label: string; deep: string; langgraph: string; langchain: string;
}) {
  const t = useLayoutTokens();
  const cell = (text: string, best: boolean) => (
    <td style={{ padding: '8px 10px', fontSize: 11, color: t.textMuted, borderBottom: `1px solid ${t.border}`, lineHeight: 1.4 }}>
      {best ? <span style={{ color: t.accent, fontWeight: 600 }}>{text}</span> : text}
    </td>
  );
  return (
    <tr>
      <td style={{ padding: '8px 10px', fontSize: 11, fontWeight: 600, color: t.textPrimary, borderBottom: `1px solid ${t.border}`, whiteSpace: 'nowrap' }}>
        {label}
      </td>
      {cell(deep, true)}
      {cell(langgraph, false)}
      {cell(langchain, false)}
    </tr>
  );
}

// ── Hero Card ────────────────────────────────────────────────

function HeroCard({ onNewAgent }: { onNewAgent: () => void }) {
  const t = useLayoutTokens();
  const c = useContent();

  return (
    <div>
      {/* ── Hero banner ─────────────────────────────────── */}
      <div
        style={{
          display: 'flex', gap: 24,
          background: `linear-gradient(135deg, ${t.accent}22 0%, ${t.accent}08 55%, ${t.bgContent} 100%)`,
          border: `1px solid ${t.border}`,
          borderRadius: 12,
          padding: '36px 36px 30px',
          marginBottom: 28,
          alignItems: 'center',
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 16 }}>
            <div
              style={{
                width: 50, height: 50, borderRadius: 12,
                background: `linear-gradient(135deg, ${t.accent}, ${t.accent}cc)`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                boxShadow: `0 4px 14px ${t.accent}35`,
              }}
            >
              <Brain size={26} color="#fff" />
            </div>
            <div>
              <h1 style={{ fontSize: 26, fontWeight: 750, color: t.textPrimary, margin: 0, letterSpacing: '-0.4px' }}>
                {c.heroTitle}
              </h1>
              <p style={{ fontSize: 13, color: t.textMuted, margin: '3px 0 0 0' }}>
                {c.heroSubtitle}
              </p>
            </div>
          </div>

          <p style={{ fontSize: 13, color: t.textMuted, lineHeight: 1.7, margin: '0 0 6px 0', maxWidth: 580 }}>{c.heroP1}</p>
          <p style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6, margin: '0 0 4px 0', maxWidth: 580, opacity: 0.85 }}>{c.heroP2}</p>
          <p style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6, margin: '0 0 20px 0', maxWidth: 580, opacity: 0.75 }}>{c.heroP3}</p>

          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button
              onClick={onNewAgent}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 8,
                padding: '10px 22px', borderRadius: 8, border: 'none',
                background: t.accent, color: '#fff',
                fontSize: 13, fontWeight: 600, cursor: 'pointer',
              }}
              onMouseEnter={e => { e.currentTarget.style.opacity = '0.9'; }}
              onMouseLeave={e => { e.currentTarget.style.opacity = '1'; }}
            >
              <Rocket size={16} />
              {c.heroCta}
            </button>
            <button
              onClick={() => document.getElementById('deepagent-templates')?.scrollIntoView({ behavior: 'smooth' })}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                padding: '10px 18px', borderRadius: 8,
                border: `1px solid ${t.border}`,
                background: 'transparent',
                color: t.textPrimary,
                fontSize: 13, fontWeight: 500, cursor: 'pointer',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
            >
              <BookOpen size={14} />
              {c.heroBrowse}
            </button>
          </div>
        </div>

        {/* Hero illustration — local asset, never expires */}
        <div
          style={{
            flexShrink: 0, width: 260, height: 200, borderRadius: 10,
            overflow: 'hidden',
            border: `1px solid ${t.border}`,
            background: `linear-gradient(135deg, ${t.accent}10, transparent)`,
          }}
        >
          <HeroVisual />
        </div>
      </div>

      {/* ── What is an Agent Harness ────────────────────── */}
      <Section title={c.harnessTitle} subtitle={c.harnessSubtitle}>
        <div
          style={{
            padding: 20, borderRadius: 10,
            background: t.bgContent,
            border: `1px solid ${t.border}`,
            marginBottom: 4,
          }}
        >
          <p style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.7, margin: '0 0 14px 0' }}>{c.harnessP1}</p>

          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 180, padding: 12, borderRadius: 8, background: `${t.accent}08`, border: `1px solid ${t.border}` }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: t.textPrimary, marginBottom: 4 }}>{c.harnessBrain}</div>
              <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.5, margin: 0 }}>{c.harnessBrainDesc}</p>
            </div>
            <div style={{ flex: 1, minWidth: 180, padding: 12, borderRadius: 8, background: `${t.accent}08`, border: `1px solid ${t.border}` }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: t.textPrimary, marginBottom: 4 }}>{c.harnessBody}</div>
              <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.5, margin: 0 }}>{c.harnessBodyDesc}</p>
            </div>
            <div style={{ flex: 1, minWidth: 180, padding: 12, borderRadius: 8, background: `${t.accent}08`, border: `1px solid ${t.border}` }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: t.textPrimary, marginBottom: 4 }}>{c.harnessAgent}</div>
              <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.5, margin: 0 }}>{c.harnessAgentDesc}</p>
            </div>
          </div>

          <div style={{
            marginTop: 14, padding: 12, borderRadius: 8,
            background: `${t.accent}08`, border: `1px solid ${t.border}`,
            fontSize: 11, color: t.textMuted, lineHeight: 1.6,
          }}>
            <strong style={{ color: t.accent }}>{c.harnessInsight.split('：')[0] || 'Key Insight:'}</strong> {c.harnessInsight}
          </div>
        </div>
      </Section>

      {/* ── Middleware Stack ────────────────────────────── */}
      <Section title={c.middlewareTitle} subtitle={c.middlewareSubtitle}>
        {/* Highlighted core middleware */}
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginBottom: 16 }}>
          <div
            style={{
              flex: 1, minWidth: 240,
              padding: 20, borderRadius: 10,
              background: `linear-gradient(135deg, #6366f115, ${t.bgContent})`,
              border: `1px solid ${t.border}`,
              display: 'flex', flexDirection: 'column', gap: 10,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{ width: 38, height: 38, borderRadius: 8, background: '#6366f120', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <ListTodo size={19} color="#6366f1" />
              </div>
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary }}>{c.mwTodoName}</div>
                <div style={{ fontSize: 10, color: '#6366f1', fontWeight: 500 }}>{c.mwTodoLabel}</div>
              </div>
            </div>
            <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.6, margin: 0 }}>{c.mwTodoDesc}</p>
            <div style={{ fontSize: 10, color: t.textMuted, background: `${t.border}40`, borderRadius: 4, padding: '6px 8px', fontFamily: 'monospace', lineHeight: 1.5, overflow: 'hidden' }}>
              {c.mwTodoCode}
            </div>
          </div>

          <div
            style={{
              flex: 1, minWidth: 240,
              padding: 20, borderRadius: 10,
              background: `linear-gradient(135deg, #22c55e15, ${t.bgContent})`,
              border: `1px solid ${t.border}`,
              display: 'flex', flexDirection: 'column', gap: 10,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{ width: 38, height: 38, borderRadius: 8, background: '#22c55e20', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <FolderOpen size={19} color="#22c55e" />
              </div>
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary }}>FilesystemMiddleware</div>
                <div style={{ fontSize: 10, color: '#22c55e', fontWeight: 500 }}>{c.mwFileLabel}</div>
              </div>
            </div>
            <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.6, margin: 0 }}>{c.mwFileDesc}</p>
            <div style={{ fontSize: 10, color: t.textMuted, background: `${t.border}40`, borderRadius: 4, padding: '6px 8px', fontFamily: 'monospace', lineHeight: 1.5, overflow: 'hidden' }}>
              {c.mwFileCode}
            </div>
          </div>

          <div
            style={{
              flex: 1, minWidth: 240,
              padding: 20, borderRadius: 10,
              background: `linear-gradient(135deg, #f59e0b15, ${t.bgContent})`,
              border: `1px solid ${t.border}`,
              display: 'flex', flexDirection: 'column', gap: 10,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{ width: 38, height: 38, borderRadius: 8, background: '#f59e0b20', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Database size={19} color="#f59e0b" />
              </div>
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary }}>Memory 系统</div>
                <div style={{ fontSize: 10, color: '#f59e0b', fontWeight: 500 }}>{c.mwMemLabel}</div>
              </div>
            </div>
            <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.6, margin: 0 }}>{c.mwMemDesc}</p>
            <div style={{ fontSize: 10, color: t.textMuted, background: `${t.border}40`, borderRadius: 4, padding: '6px 8px', fontFamily: 'monospace', lineHeight: 1.5, overflow: 'hidden' }}>
              {c.mwMemCode}
            </div>
          </div>
        </div>

        {/* Full middleware catalog — max 4 columns */}
        <div style={{ marginBottom: 16 }}>
          <h4 style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, margin: '0 0 8px 0' }}>{c.mwFullCatalog}</h4>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
            <MiddlewareCard icon={ScrollText} color="#3b82f6" name={c.mwSummaryName} label={c.mwSummaryLabel} desc={c.mwSummaryDesc} />
            <MiddlewareCard icon={UserCheck} color="#8b5cf6" name={c.mwHitlName} label={c.mwHitlLabel} desc={c.mwHitlDesc} />
            <MiddlewareCard icon={GanttChartSquare} color="#ec4899" name={c.mwModelLimitName} label={c.mwModelLimitLabel} desc={c.mwModelLimitDesc} />
            <MiddlewareCard icon={RefreshCw} color="#22c55e" name={c.mwRetryName} label={c.mwRetryLabel} desc={c.mwRetryDesc} />
            <MiddlewareCard icon={AlertTriangle} color="#f59e0b" name={c.mwPIIName} label={c.mwPIILabel} desc={c.mwPIIDesc} />
            <MiddlewareCard icon={Bot} color="#6366f1" name={c.mwSelectorName} label={c.mwSelectorLabel} desc={c.mwSelectorDesc} />
            <MiddlewareCard icon={Sliders} color="#06b6d4" name={c.mwFallbackName} label={c.mwFallbackLabel} desc={c.mwFallbackDesc} />
            <MiddlewareCard icon={Terminal} color="#10b981" name={c.mwShellName} label={c.mwShellLabel} desc={c.mwShellDesc} />
            <MiddlewareCard icon={Globe} color="#f97316" name={c.mwFileSearchName} label={c.mwFileSearchLabel} desc={c.mwFileSearchDesc} />
            <MiddlewareCard icon={MessagesSquare} color="#a855f7" name={c.mwContextName} label={c.mwContextLabel} desc={c.mwContextDesc} />
            <MiddlewareCard icon={Box} color="#64748b" name={c.mwToolLimitName} label={c.mwToolLimitLabel} desc={c.mwToolLimitDesc} />
            <MiddlewareCard icon={Layers} color="#0891b2" name={c.mwEmulatorName} label={c.mwEmulatorLabel} desc={c.mwEmulatorDesc} />
          </div>
        </div>
      </Section>

      {/* ── Why use Deep Agents — 3 pillars ────────────── */}
      <Section title={c.whyTitle} subtitle={c.whySubtitle}>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 4 }}>
          <PillarCard
            icon={GitBranch} title={c.pillar1Title} desc={c.pillar1Desc}
            bullets={[c.pillar1B1, c.pillar1B2, c.pillar1B3]}
          />
          <PillarCard
            icon={Network} title={c.pillar2Title} desc={c.pillar2Desc}
            bullets={[c.pillar2B1, c.pillar2B2, c.pillar2B3]}
          />
          <PillarCard
            icon={Database} title={c.pillar3Title} desc={c.pillar3Desc}
            bullets={[c.pillar3B1, c.pillar3B2, c.pillar3B3]}
          />
        </div>
      </Section>

      {/* ── Core Capabilities ──────────────────────────── */}
      <Section title={c.featTitle} subtitle={c.featSubtitle}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 10 }}>
          <FeatureCard icon={Workflow} title={c.feat1Title} desc={c.feat1Desc} />
          <FeatureCard icon={Sliders} title={c.feat2Title} desc={c.feat2Desc} />
          <FeatureCard icon={Database} title={c.feat3Title} desc={c.feat3Desc} />
          <FeatureCard icon={Puzzle} title={c.feat4Title} desc={c.feat4Desc} />
          <FeatureCard icon={Shield} title={c.feat5Title} desc={c.feat5Desc} />
          <FeatureCard icon={Lightbulb} title={c.feat6Title} desc={c.feat6Desc} />
          <FeatureCard icon={FileText} title={c.feat7Title} desc={c.feat7Desc} />
          <FeatureCard icon={Bot} title={c.feat8Title} desc={c.feat8Desc} />
        </div>
      </Section>

      {/* ── Architecture Overview ──────────────────────── */}
      <Section title={c.archTitle} subtitle={c.archSubtitle}>
        <div
          style={{
            display: 'flex', gap: 24,
            padding: 24, borderRadius: 10,
            background: t.bgContent,
            border: `1px solid ${t.border}`,
            alignItems: 'flex-start',
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <StepCard num={1} title={c.arch1} desc={c.arch1Desc} />
              <StepCard num={2} title={c.arch2} desc={c.arch2Desc} />
              <StepCard num={3} title={c.arch3} desc={c.arch3Desc} />
              <StepCard num={4} title={c.arch4} desc={c.arch4Desc} />
            </div>
          </div>
          <div
            style={{
              flexShrink: 0, width: 240, borderRadius: 8,
              overflow: 'hidden', border: `1px solid ${t.border}`,
            }}
          >
            <ArchVisual />
          </div>
        </div>
      </Section>

      {/* ── Middleware wrapping diagram ────────────────── */}
      <Section title={c.wrapTitle} subtitle={c.wrapSubtitle}>
        <div
          style={{
            display: 'flex', gap: 20,
            padding: 20, borderRadius: 10,
            background: t.bgContent,
            border: `1px solid ${t.border}`,
            alignItems: 'center',
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11, color: t.textMuted, lineHeight: 1.6 }}>
              <div style={{ padding: '8px 12px', borderRadius: 6, background: '#6366f115', border: '1px solid #6366f130', color: '#6366f1', fontWeight: 600 }}>
                {c.wrapLayer1}
              </div>
              <div style={{ padding: '8px 12px', borderRadius: 6, background: '#22c55e15', border: '1px solid #22c55e30', color: '#22c55e', fontWeight: 600 }}>
                {c.wrapLayer2}
              </div>
              <div style={{ padding: '8px 12px', borderRadius: 6, background: '#f59e0b15', border: '1px solid #f59e0b30', color: '#f59e0b', fontWeight: 600 }}>
                {c.wrapLayer3}
              </div>
              <div style={{ padding: '8px 12px', borderRadius: 6, background: '#3b82f615', border: '1px solid #3b82f630', color: '#3b82f6', fontWeight: 600 }}>
                {c.wrapLayer4}
              </div>
              <div style={{ padding: '8px 12px', borderRadius: 6, background: '#8b5cf615', border: '1px solid #8b5cf630', color: '#8b5cf6', fontWeight: 600 }}>
                {c.wrapLayer5}
              </div>
              <div style={{ padding: '10px 14px', borderRadius: 6, background: `${t.accent}18`, border: `2px solid ${t.accent}40`, textAlign: 'center', fontWeight: 700, color: t.accent }}>
                {c.wrapLayer6}
              </div>
              <div style={{ padding: '8px 12px', borderRadius: 6, background: '#06b6d415', border: '1px solid #06b6d430', color: '#06b6d4', fontWeight: 600 }}>
                {c.wrapLayer7}
              </div>
              <div style={{ padding: '8px 12px', borderRadius: 6, background: '#f9731615', border: '1px solid #f9731630', color: '#f97316', fontWeight: 600 }}>
                {c.wrapLayer8}
              </div>
            </div>
          </div>
          <div
            style={{
              flexShrink: 0, width: 200, borderRadius: 8,
              overflow: 'hidden', border: `1px solid ${t.border}`,
            }}
          >
            <MiddlewareStackVisual />
          </div>
        </div>
      </Section>

      {/* ── When to use (comparison) ───────────────────── */}
      <Section title={c.compTitle} subtitle={c.compSubtitle}>
        <div
          style={{
            padding: 16, borderRadius: 10,
            background: t.bgContent,
            border: `1px solid ${t.border}`,
            marginBottom: 4, overflowX: 'auto',
          }}
        >
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={{ padding: '8px 10px', fontSize: 11, fontWeight: 600, color: t.textPrimary, borderBottom: `2px solid ${t.border}`, textAlign: 'left' }}>Scenario</th>
                <th style={{ padding: '8px 10px', fontSize: 11, fontWeight: 600, color: t.accent, borderBottom: `2px solid ${t.border}`, textAlign: 'left' }}>{c.compColDeep}</th>
                <th style={{ padding: '8px 10px', fontSize: 11, fontWeight: 600, color: t.textMuted, borderBottom: `2px solid ${t.border}`, textAlign: 'left' }}>{c.compColLangGraph}</th>
                <th style={{ padding: '8px 10px', fontSize: 11, fontWeight: 600, color: t.textMuted, borderBottom: `2px solid ${t.border}`, textAlign: 'left' }}>{c.compColLangChain}</th>
              </tr>
            </thead>
            <tbody>
              <ComparisonRow label={c.compRowAutonomy} deep={c.compRowAutonomyDeep} langgraph={c.compRowAutonomyLG} langchain={c.compRowAutonomyLC} />
              <ComparisonRow label={c.compRowSubagents} deep={c.compRowSubagentsDeep} langgraph={c.compRowSubagentsLG} langchain={c.compRowSubagentsLC} />
              <ComparisonRow label={c.compRowLongRunning} deep={c.compRowLongRunningDeep} langgraph={c.compRowLongRunningLG} langchain={c.compRowLongRunningLC} />
              <ComparisonRow label={c.compRowCtx} deep={c.compRowCtxDeep} langgraph={c.compRowCtxLG} langchain={c.compRowCtxLC} />
              <ComparisonRow label={c.compRowMemory} deep={c.compRowMemoryDeep} langgraph={c.compRowMemoryLG} langchain={c.compRowMemoryLC} />
              <ComparisonRow label={c.compRowMW} deep={c.compRowMWDeep} langgraph={c.compRowMWLG} langchain={c.compRowMWLC} />
              <ComparisonRow label={c.compRowSafety} deep={c.compRowSafetyDeep} langgraph={c.compRowSafetyLG} langchain={c.compRowSafetyLC} />
              <ComparisonRow label={c.compRowControl} deep={c.compRowControlDeep} langgraph={c.compRowControlLG} langchain={c.compRowControlLC} />
              <ComparisonRow label={c.compRowQuick} deep={c.compRowQuickDeep} langgraph={c.compRowQuickLG} langchain={c.compRowQuickLC} />
              <ComparisonRow label={c.compRowScenario} deep={c.compRowScenarioDeep} langgraph={c.compRowScenarioLG} langchain={c.compRowScenarioLC} />
            </tbody>
          </table>
          <p style={{ fontSize: 11, color: t.textMuted, margin: '12px 0 0 0', lineHeight: 1.6 }}>
            {c.compFooter}
          </p>
        </div>
      </Section>

      {/* ── Quick-start actions ────────────────────────── */}
      <Section title={c.quickTitle}>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <QuickStartCard icon={Rocket} accent={t.accent} title={c.qs1Title} desc={c.qs1Desc} cta={c.qs1Cta} onClick={onNewAgent} />
          <QuickStartCard icon={Code} accent="#8b5cf6" title={c.qs2Title} desc={c.qs2Desc} cta={c.qs2Cta} onClick={() => document.getElementById('deepagent-templates')?.scrollIntoView({ behavior: 'smooth' })} />
          <QuickStartCard icon={GitBranch} accent="#06b6d4" title={c.qs3Title} desc={c.qs3Desc} cta={c.qs3Cta} onClick={() => {/* sidebar agents */}} />
        </div>
      </Section>
    </div>
  );
}

// ── Template card ────────────────────────────────────────────

function TemplateCard({ agent, onClick }: { agent: TemplateAgent; onClick: () => void }) {
  const t = useLayoutTokens();
  const c = useContent();
  const cfg = getCategoryConfig(agent.category || '');
  const Icon = cfg.icon;

  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex', flexDirection: 'column', gap: 8,
        padding: 14, borderRadius: 8,
        background: t.bgContent,
        border: `1px solid ${t.border}`,
        cursor: 'pointer',
        textAlign: 'left',
        transition: 'border-color 0.15s, box-shadow 0.15s',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.borderColor = t.accent;
        e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.08)';
      }}
      onMouseLeave={e => {
        e.currentTarget.style.borderColor = t.border;
        e.currentTarget.style.boxShadow = 'none';
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <div style={{ width: 28, height: 28, borderRadius: 6, background: `${cfg.color}15`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
          <Icon size={14} color={cfg.color} />
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: t.textPrimary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {agent.name}
          </div>
          <div style={{ fontSize: 10, color: t.textMuted }}>{cfg.labelEn}</div>
        </div>
      </div>

      <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.4, margin: 0, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
        {agent.description || c.tplNoDesc}
      </p>

      {agent.tags && agent.tags.length > 0 && (
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {agent.tags.slice(0, 3).map(tag => (
            <span key={tag} style={{ fontSize: 9, padding: '1px 6px', borderRadius: 4, background: `${t.accent}10`, color: t.textMuted }}>
              {tag}
            </span>
          ))}
        </div>
      )}
    </button>
  );
}

// ── Main component ───────────────────────────────────────────

export default function DeepAgentHomePage() {
  const t = useLayoutTokens();
  const c = useContent();
  const { openTab } = useLayoutState();
  const [templates, setTemplates] = useState<TemplateAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeCategory, setActiveCategory] = useState<string>('all');

  // Load deep agent templates — merges built-in presets + user-created agents.
  // A single shared AbortController cancels in-flight requests on refresh/unmount
  // so out-of-order responses can never overwrite newer data.
  const abortRef = useRef<AbortController | null>(null);

  const loadTemplates = useCallback(() => {
    abortRef.current?.abort();
    const abort = new AbortController();
    abortRef.current = abort;
    setLoading(true);
    setError(null);
    Promise.all([
      apiClient.listDeepAgentTemplates({ signal: abort.signal }),
      apiClient.listDeepAgents({ public_only: false }),
    ])
      .then(([builtinRes, dbRes]: any) => {
        if (abort.signal.aborted) return; // superseded by a newer request
        // Unwrap Axios response objects (both use this.client.get)
        const builtinData = (builtinRes as any)?.data ?? builtinRes ?? [];
        const builtinRaw = Array.isArray(builtinData) ? builtinData : [];

        // Built-in presets (from DeepAgentTemplateRegistry) → "System Templates"
        const builtin = builtinRaw.map((t: any) => ({
          id: t.template_id,
          name: t.name,
          description: t.description || '',
          category: 'system',
          tags: t.capabilities || [],
          system_prompt: t.system_prompt,
          model: t.model,
          temperature: t.temperature,
          native_tools: t.native_tools || [],
          is_builtin: true,
        }));

        // User-created agents (from deep_agent_templates DB table) → "Custom Builds"
        const dbData = (dbRes as any)?.data ?? dbRes ?? [];
        const dbAgents = Array.isArray(dbData) ? dbData : [];
        const userCreated = dbAgents.map((a: any) => ({
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

        // Merge: built-in first, then user-created (dedup by name)
        const seen = new Set(builtin.map((t: any) => t.name));
        setTemplates([...builtin, ...userCreated.filter((c: any) => !seen.has(c.name))]);
      })
      .catch(err => {
        if (abort.signal.aborted) return; // superseded by a newer request
        if (err?.name !== 'AbortError' && err?.name !== 'CanceledError') {
          console.error('Failed to load deep agent templates:', err);
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
    openTab({ id: `new-deepagent-${Date.now()}`, label: 'New DeepAgent', viewType: 'deepagent-create', data: {} });
  };

  const handleRefresh = () => {
    loadTemplates();
  };

  const handleTemplateClick = (agent: TemplateAgent) => {
    openTab({
      id: `deepagent-tpl-${agent.id}`,
      label: agent.name,
      viewType: 'deepagent',
      data: {
        id: agent.id,
        name: agent.name,
        description: agent.description,
        category: agent.category,
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

      {/* ── Scrollable content area — intro + templates ── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '28px 32px' }}>
        <HeroCard onNewAgent={handleNewAgent} />

        {/* Search + category filter */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16,
          flexWrap: 'wrap',
        }}>
          <div style={{ position: 'relative', flex: 1, minWidth: 220, maxWidth: 360 }}>
            <Search size={14} style={{
              position: 'absolute', left: 10, top: '50%',
              transform: 'translateY(-50%)', color: t.textMuted,
            }} />
            <input
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder={c.tplSearchPlaceholder}
              style={{
                width: '100%',
                padding: '8px 10px 8px 32px',
                background: t.bgContent,
                border: `1px solid ${t.border}`,
                borderRadius: 4,
                color: t.textPrimary,
                fontSize: 12,
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
          </div>

          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <button
              onClick={() => setActiveCategory('all')}
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
        </div>

        {/* Templates grid */}
        <div id="deepagent-templates">
          {loading ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: t.textMuted, padding: 16 }}>
              <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
              {c.tplLoading}
            </div>
          ) : error ? (
            <p style={{ fontSize: 12, color: t.textMuted, padding: 16 }}>{error}</p>
          ) : templates.length === 0 ? (
            <div style={{ padding: '24px 16px', textAlign: 'center' }}>
              <Cpu size={32} style={{ color: t.textMuted, opacity: 0.3, marginBottom: 8 }} />
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