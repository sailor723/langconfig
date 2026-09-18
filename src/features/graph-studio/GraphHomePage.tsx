/**
 * GraphHomePage — landing page for the Graph (LangGraph) activity.
 *
 * Shown when the user opens the Graph activity and BEFORE any assistant is
 * selected. Rich introduction modeled on LangGraph's core benefits (durable
 * execution, streaming, human-in-the-loop, persistence) plus cards for the
 * code-defined assistants that open the studio. Supports zh/en via i18n.
 */
import { useEffect, useState, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useLayoutTokens } from '../../components/layout2/tokens';
import {
  Workflow, GitBranch, Brain, Database, Network, Layers, Plus, Loader,
  ArrowRight, Rocket, RefreshCw, Puzzle, ShieldCheck, Repeat, UserCheck,
  Users, Boxes, Share2, Cpu, History, PlayCircle, Zap, FileCode2,
  CircleDot, Route,
} from 'lucide-react';
import { studio, useStudioState } from './studioStore';
import type { Assistant } from './api';

interface GraphHomePageProps {
  /** Called when the user enters the studio (optionally after selecting an assistant). */
  onEnterStudio?: () => void;
}

// ── CSS visual components (no images) ───────────────────────

/** Hero visual — a mini state-graph: START → nodes → conditional → END. */
function GraphVisual() {
  const t = useLayoutTokens();
  const node: React.CSSProperties = {
    padding: '6px 14px', borderRadius: 8, fontSize: 11, fontWeight: 600,
    background: `${t.accent}15`, border: `1px solid ${t.accent}35`, color: t.textPrimary,
    whiteSpace: 'nowrap',
  };
  const line: React.CSSProperties = { width: 1, height: 12, background: t.border, margin: '0 auto' };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: 8 }}>
      <div style={{ padding: '6px 14px', borderRadius: 999, background: '#4caf5022', border: '1px solid #4caf5055', color: '#4caf50', fontSize: 10, fontWeight: 700, letterSpacing: 0.5 }}>START</div>
      <div style={line} />
      <div style={node}>🧠 llm_agent</div>
      <div style={line} />
      <div style={node}>🔧 call_tool</div>
      <div style={line} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 10, color: t.textDim }}>should_continue?</span>
      </div>
      <div style={{ display: 'flex', gap: 20, marginTop: 4 }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <div style={{ width: 1, height: 10, background: t.border }} />
          <div style={{ padding: '4px 10px', borderRadius: 6, background: '#6366f115', border: '1px solid #6366f140', color: '#818cf8', fontSize: 9, fontWeight: 600 }}>loop</div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <div style={{ width: 1, height: 10, background: t.border }} />
          <div style={{ padding: '4px 10px', borderRadius: 999, background: '#e5484d15', border: '1px solid #e5484d40', color: '#e5484d', fontSize: 9, fontWeight: 700 }}>END</div>
        </div>
      </div>
    </div>
  );
}

/** Checkpointer visual — a stack of snapshots being persisted. */
function CheckpointVisual() {
  const t = useLayoutTokens();
  const rows = [
    { label: 'checkpoint #4', state: '✓ persisted', w: 88 },
    { label: 'checkpoint #3', state: '✓ persisted', w: 82 },
    { label: 'checkpoint #2', state: '✓ persisted', w: 76 },
    { label: 'checkpoint #1', state: '✓ persisted', w: 70 },
  ];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 5, padding: 14 }}>
      {rows.map((r, i) => (
        <div key={r.label} style={{
          width: `${r.w}%`, padding: '5px 10px', borderRadius: 6,
          background: `${t.accent}${i === 0 ? '22' : '12'}`,
          border: `1px solid ${t.accent}35`,
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span style={{ fontSize: 10, fontFamily: 'monospace', color: t.textPrimary }}>{r.label}</span>
          <span style={{ fontSize: 9, color: '#4caf50', fontWeight: 600 }}>{r.state}</span>
        </div>
      ))}
      <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, color: t.textDim }}>
        <History size={12} /> time-travel · rewind · replay · fork
      </div>
    </div>
  );
}

// ── Content (zh / en) ───────────────────────────────────────

function useContent() {
  const { i18n } = useTranslation();
  const isZh = i18n.language.startsWith('zh');

  const c = isZh ? {
    // Header
    headerTitle: 'LangGraph 图工程',
    headerRefresh: '刷新',
    headerCta: '进入 Studio',

    // Hero
    heroTitle: 'LangGraph',
    heroSubtitle: '有状态、可编排的智能体 — 低层级的图运行时',
    heroP1: 'LangGraph 是一个低层级的编排框架和运行时，用于构建、管理和部署长期运行的有状态智能体。它让你可以在同一个图中混合确定性的手工编码步骤与 LLM 驱动的智能体步骤，构建行为完全符合你业务要求的智能体。',
    heroP2: 'LangGraph 专注于智能体编排的核心能力：持久化执行、流式输出、人工介入（Human-in-the-Loop）和检查点持久化。Klarna、Uber、J.P. Morgan 等公司都在用它构建生产级智能体系统。',
    heroP3: 'LangConfig 的 Graph Engineering 工作区为这些代码定义的图提供可视化画布：在画布上查看图结构，通过 SSE 流式运行，并在检查器中查看检查点状态 — 全部运行在你自己的后端上。',
    heroCta: '进入 Studio',
    heroBrowse: '浏览下方图',

    // Graphs (assistants)
    graphsTitle: '可用图',
    graphsSubtitle: '选择下方任意一个代码定义的图进入 Studio — 在画布上检查结构、运行并调试。',
    graphsLoading: '正在加载图...',
    graphsError: '无法加载图',
    graphsEmpty: '暂无可用的图',
    graphsEmptyHint: '在后端代码中注册一个 LangGraph assistant 后刷新',
    graphsOpen: '打开',

    // What is LangGraph
    whatTitle: '什么是 LangGraph？',
    whatSubtitle: 'LangGraph 将智能体建模为一个有向图：节点是 Python 函数，边是它们之间的转换，显式的状态在每一步之间流动。',
    elStateName: 'State（状态）',
    elStateDesc: '一个类型化的字典（TypedDict），定义所有节点读写的数据契约。每个节点读取整个状态并返回部分更新。',
    elNodeName: 'Node（节点）',
    elNodeDesc: '一个 Python 函数，接收状态并返回部分状态更新。节点的粒度由你决定 — 一次 LLM 调用、一次工具执行、一次决策。',
    elEdgeName: 'Edge（边）',
    elEdgeDesc: '节点之间的转换。普通边固定流转，条件边由函数在运行时决定下一个节点 — 这是循环、分支和重试的机制。',
    elGraphName: 'Graph（图）',
    elGraphDesc: '节点与边的集合，可以循环（plan → act → reflect → repeat），支持子图嵌套与并行扇出/扇入。',
    elCheckpointName: 'Checkpointer（检查点）',
    elCheckpointDesc: '持久化层：每个节点执行前后都会把状态快照写入存储，支持断点续跑、人工审核和会话隔离。',

    // Core capabilities
    capTitle: '核心能力',
    capSubtitle: 'LangGraph 为任何长期运行、有状态的工作流或智能体提供底层基础设施。',
    cap1Title: '持久化执行',
    cap1Desc: '图中途崩溃或重启也不会丢失状态，可以从最后一个已完成的节点继续，而不是从头开始。',
    cap2Title: '流式输出',
    cap2Desc: '支持 messages / values / updates 多种流式模式，实时推送中间消息、状态值变化和节点更新，构建流畅的用户体验。',
    cap3Title: '人工介入',
    cap3Desc: 'interrupt_before / interrupt_after 在指定节点暂停执行，人类可以在任意点检查和修改智能体状态后再继续。',
    cap4Title: '持久化与记忆',
    cap4Desc: '短期工作记忆（对话历史/检查点）与跨会话的长期记忆相结合，创建真正有状态、持续学习的智能体。',
    cap5Title: '时间旅行',
    cap5Desc: '每个步骤都被持久化，可以回退、重放甚至分叉执行 — 调试复杂智能体行为的有力工具。',
    cap6Title: '多智能体编排',
    cap6Desc: '支持 Supervisor、Swarm、层级和全连接网络等编排模式，通过子图组织复杂的多智能体系统。',
    cap7Title: '确定性 + 智能体混合',
    cap7Desc: '在同一张图中混合确定性、可审计的代码路径与 LLM 驱动的自主路径，精确控制 AI 应用在何处、如何介入。',
    cap8Title: '模型无关',
    cap8Desc: '与 OpenAI、Anthropic、Google 等任何 LangChain 兼容模型配合使用，也可与 LangChain 之外的组件集成。',

    // Multi-agent patterns
    patternTitle: '多智能体编排模式',
    patternSubtitle: 'LangGraph 支持多种多智能体架构模式，按协作方式选择最合适的一种。',
    p1Title: 'Supervisor（主管）',
    p1Desc: '一个主智能体作为编排者，将任务委托给专门的工作智能体，并汇总结果。是最常用的模式。',
    p1B1: '主智能体拥有全局视角',
    p1B2: '工作智能体拥有隔离的上下文',
    p1B3: '适合任务可分层的场景',
    p2Title: 'Swarm（蜂群）',
    p2Desc: '对等的智能体之间通过 handoff 指令互相转交控制权，适合流水线式协作。',
    p2B1: '无中心协调者',
    p2B2: '每次只有一个智能体运行',
    p2B3: '适合职责清晰的接力任务',
    p3Title: 'Hierarchical（层级）',
    p3Desc: '嵌套的主管模式：每个子团队有自己的主管，主管之间再协作，适合超大规模系统。',
    p3B1: '递归的组织结构',
    p3B2: '每个层级可独立测试',
    p3B3: '适合企业级复杂业务',
    p4Title: 'Network（全连接）',
    p4Desc: '所有智能体互相通信、共同决策，最大程度地发挥协作能力，但复杂度最高。',
    p4B1: '完全点对点协作',
    p4B2: '共享消息传递机制',
    p4B3: '适合研究型多智能体场景',

    // How it works
    howTitle: '工作原理',
    howSubtitle: '从定义状态到持久化运行，四个步骤构建一个 LangGraph 智能体。',
    how1: '定义状态',
    how1Desc: '用 TypedDict 定义状态模式，声明节点间共享的数据结构。',
    how2: '添加节点',
    how2Desc: '把 Python 函数注册为节点 — LLM 调用、工具执行或任何自定义逻辑。',
    how3: '连接边',
    how3Desc: '用普通边固定流转，用条件边实现分支、循环与重试。',
    how4: '编译并持久化',
    how4Desc: 'compile() 编译成 Runnable，传入 checkpointer 启用持久化，即可 invoke / stream / batch。',

    // Ecosystem
    ecoTitle: 'LangChain 生态中的位置',
    ecoSubtitle: 'LangGraph 是编排运行时 — 它专注于智能体编排所需的核心底层能力。',
    ecoHeadProduct: '产品',
    ecoHeadRole: '角色',
    ecoHeadIdeal: '适合',
    eco1Product: 'LangChain',
    eco1Role: '智能体框架：模型、工具与智能体循环的抽象与集成。',
    eco1Ideal: '快速构建标准 LLM 应用',
    eco2Product: 'LangGraph',
    eco2Role: '编排运行时：持久化执行、流式、人工介入与持久化。',
    eco2Ideal: '需要精细控制循环与状态的生产级智能体',
    eco3Product: 'LangSmith',
    eco3Role: '可观测平台：追踪、评估、提示词管理与部署。',
    eco3Ideal: '生产环境调试与评测',
    eco4Product: 'Deep Agents',
    eco4Role: '基于 LangGraph 的智能体工具箱：规划、子智能体、文件系统与上下文管理。',
    eco4Ideal: '高度自主、长期运行的多智能体协作',
    ecoFooter: 'LangGraph 位于生态的最底层 — LangChain 的智能体与 Deep Agents 都构建在它之上。',

    // Quick start
    quickTitle: '快速开始',
    qs1Title: '打开 Studio',
    qs1Desc: '点击上方"进入 Studio"或选择下方任意一张图，在画布上查看节点、边与条件分支。',
    qs1Cta: '打开 Studio',
    qs2Title: '检查图结构',
    qs2Desc: '查看每个节点的源代码、工具与元数据，理解图的数据流与执行路径。',
    qs2Cta: '查看图结构',
    qs3Title: '运行并迭代',
    qs3Desc: '在控制台输入消息流式运行，在检查器中查看检查点状态，反复调试直到符合预期。',
    qs3Cta: '开始运行',
  } : {
    // Header
    headerTitle: 'LangGraph Engineering',
    headerRefresh: 'Refresh',
    headerCta: 'Open Studio',

    // Hero
    heroTitle: 'LangGraph',
    heroSubtitle: 'Stateful, orchestrated agents — the low-level graph runtime',
    heroP1: 'LangGraph is a low-level orchestration framework and runtime for building, managing, and deploying long-running, stateful agents. It lets you mix deterministic, hand-coded steps with LLM-driven agentic steps in the same graph, so you can build bespoke agents that behave exactly the way your application requires.',
    heroP2: 'LangGraph is focused on the capabilities at the heart of agent orchestration: durable execution, streaming, human-in-the-loop, and persistence. It is trusted by companies shaping the future of agents — Klarna, Uber, J.P. Morgan, and more.',
    heroP3: 'LangConfig\'s Graph Engineering workspace puts a visual canvas on top of these code-defined graphs: inspect the structure on the canvas, run with SSE streaming, and inspect checkpointed state in the inspector — all against your own backend.',
    heroCta: 'Open Studio',
    heroBrowse: 'Browse graphs below',

    // Graphs (assistants)
    graphsTitle: 'Available Graphs',
    graphsSubtitle: 'Pick a code-defined graph below to open the Studio — inspect its structure, run it, and debug it on the canvas.',
    graphsLoading: 'Loading graphs...',
    graphsError: 'Failed to load graphs',
    graphsEmpty: 'No graphs available',
    graphsEmptyHint: 'Register a LangGraph assistant in the backend code, then refresh',
    graphsOpen: 'Open',

    // What is LangGraph
    whatTitle: 'What is LangGraph?',
    whatSubtitle: 'LangGraph models your agent as a directed graph: nodes are Python functions, edges are transitions between them, and explicit state flows between every step.',
    elStateName: 'State',
    elStateDesc: 'A typed dict (TypedDict) that defines the data contract every node reads and writes. Nodes read the full state and return partial updates.',
    elNodeName: 'Node',
    elNodeDesc: 'A Python function that takes the state and returns a partial state update. Granularity is yours — one LLM call, one tool execution, one decision.',
    elEdgeName: 'Edge',
    elEdgeDesc: 'Transitions between nodes. Plain edges always route; conditional edges are decided at runtime by a function — the mechanism behind loops, branches, and retries.',
    elGraphName: 'Graph',
    elGraphDesc: 'The collection of nodes and edges. Graphs can cycle (plan → act → reflect → repeat), nest subgraphs, and fan out / fan in in parallel.',
    elCheckpointName: 'Checkpointer',
    elCheckpointDesc: 'The persistence layer: a state snapshot is written to storage before and after every node, enabling resumable runs, human review, and session isolation.',

    // Core capabilities
    capTitle: 'Core Capabilities',
    capSubtitle: 'LangGraph provides low-level supporting infrastructure for any long-running, stateful workflow or agent.',
    cap1Title: 'Durable Execution',
    cap1Desc: 'If the graph crashes or restarts mid-run, state is never lost — resume from the last completed node instead of starting over.',
    cap2Title: 'Streaming',
    cap2Desc: 'Stream messages, values, and updates in real time with multiple stream modes — perfect for fluid, responsive UX.',
    cap3Title: 'Human-in-the-Loop',
    cap3Desc: 'Pause execution with interrupt_before / interrupt_after, and inspect or modify agent state at any point before continuing.',
    cap4Title: 'Memory & Persistence',
    cap4Desc: 'Combine short-term working memory (conversation history / checkpoints) with long-term memory across sessions for stateful, learning agents.',
    cap5Title: 'Time-Travel Debugging',
    cap5Desc: 'Every step is persisted, so you can rewind, replay, or even fork execution — a powerful tool for debugging complex agent behavior.',
    cap6Title: 'Multi-Agent Orchestration',
    cap6Desc: 'Supervisor, swarm, hierarchical, and fully-connected network patterns — organize complex multi-agent systems through subgraphs.',
    cap7Title: 'Deterministic + Agentic',
    cap7Desc: 'Mix deterministic, auditable code paths with LLM-driven autonomous steps in one graph, with fine-grained control over where AI applies.',
    cap8Title: 'Model-Agnostic',
    cap8Desc: 'Works with any LangChain-compatible model — OpenAI, Anthropic, Google and more — and integrates with non-LangChain components too.',

    // Multi-agent patterns
    patternTitle: 'Multi-Agent Patterns',
    patternSubtitle: 'LangGraph supports several multi-agent architectures — choose the one that matches how your agents should collaborate.',
    p1Title: 'Supervisor',
    p1Desc: 'A single orchestrator agent delegates tasks to specialized worker agents and aggregates the results. The most common pattern.',
    p1B1: 'Orchestrator keeps the global view',
    p1B2: 'Workers have isolated contexts',
    p1B3: 'Great for hierarchical tasks',
    p2Title: 'Swarm',
    p2Desc: 'Peer agents hand off control to each other via handoff commands — ideal for pipeline-style collaboration.',
    p2B1: 'No central coordinator',
    p2B2: 'Exactly one agent runs at a time',
    p2B3: 'Great for clear handoff chains',
    p3Title: 'Hierarchical',
    p3Desc: 'Nested supervisor structures: each sub-team has its own supervisor, and supervisors collaborate — for very large systems.',
    p3B1: 'Recursive organization',
    p3B2: 'Each level tests independently',
    p3B3: 'For enterprise-scale complexity',
    p4Title: 'Network',
    p4Desc: 'All agents communicate with each other and decide together — maximum collaboration, highest complexity.',
    p4B1: 'Fully peer-to-peer',
    p4B2: 'Shared messaging between agents',
    p4B3: 'For research-grade scenarios',

    // How it works
    howTitle: 'How It Works',
    howSubtitle: 'From defining state to running with persistence — four steps to a LangGraph agent.',
    how1: 'Define State',
    how1Desc: 'Define the state schema with TypedDict — the shared data contract between nodes.',
    how2: 'Add Nodes',
    how2Desc: 'Register Python functions as nodes — an LLM call, a tool execution, or any custom logic.',
    how3: 'Connect Edges',
    how3Desc: 'Route deterministically with plain edges, or branch / loop / retry with conditional edges.',
    how4: 'Compile & Persist',
    how4Desc: 'compile() produces a Runnable; pass a checkpointer to enable persistence, then invoke / stream / batch.',

    // Ecosystem
    ecoTitle: 'Where LangGraph Sits in the Ecosystem',
    ecoSubtitle: 'LangGraph is the orchestration runtime — focused entirely on the low-level capabilities agents need.',
    ecoHeadProduct: 'Product',
    ecoHeadRole: 'Role',
    ecoHeadIdeal: 'Best for',
    eco1Product: 'LangChain',
    eco1Role: 'The agent framework: abstractions and integrations for models, tools, and agent loops.',
    eco1Ideal: 'Standard LLM apps, fast',
    eco2Product: 'LangGraph',
    eco2Role: 'The orchestration runtime: durable execution, streaming, human-in-the-loop, persistence.',
    eco2Ideal: 'Production agents needing fine-grained control',
    eco3Product: 'LangSmith',
    eco3Role: 'The observability platform: tracing, evaluation, prompt management, and deployment.',
    eco3Ideal: 'Debugging and evaluation in production',
    eco4Product: 'Deep Agents',
    eco4Role: 'An agent harness on LangGraph: planning, subagents, filesystem tools, and context management.',
    eco4Ideal: 'Highly autonomous, long-running multi-agent work',
    ecoFooter: 'LangGraph sits at the base of the stack — both LangChain\'s agents and Deep Agents are built on top of it.',

    // Quick start
    quickTitle: 'Quick Start',
    qs1Title: 'Open the Studio',
    qs1Desc: 'Click "Open Studio" above or pick any graph below to inspect its nodes, edges, and conditional branches on the canvas.',
    qs1Cta: 'Open Studio',
    qs2Title: 'Inspect the Graph',
    qs2Desc: 'View each node\'s source, tools, and metadata to understand data flow and execution paths.',
    qs2Cta: 'Inspect the graph',
    qs3Title: 'Run & Iterate',
    qs3Desc: 'Stream a run from the console, inspect checkpointed state in the inspector, and iterate until it behaves as expected.',
    qs3Cta: 'Start a run',
  };

  return c;
}

// ── Shared section components ───────────────────────────────

function Section({ title, children, subtitle }: { title: string; children: React.ReactNode; subtitle?: string }) {
  const t = useLayoutTokens();
  return (
    <div style={{ marginBottom: 32 }}>
      <div style={{ marginBottom: 12 }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, color: t.textPrimary, margin: 0, letterSpacing: '-0.2px' }}>{title}</h2>
        {subtitle && <p style={{ fontSize: 12, color: t.textMuted, margin: '4px 0 0 0', lineHeight: 1.5 }}>{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

function PillarCard({ icon: Icon, title, desc, bullets }: { icon: typeof Brain; title: string; desc: string; bullets?: string[] }) {
  const t = useLayoutTokens();
  return (
    <div style={{
      padding: 20, borderRadius: 10, background: t.bgContent,
      border: `1px solid ${t.border}`,
      display: 'flex', flexDirection: 'column', gap: 10,
      flex: 1, minWidth: 220,
    }}>
      <div style={{
        width: 36, height: 36, borderRadius: 8, background: `${t.accent}15`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
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

function FeatureCard({ icon: Icon, title, desc }: { icon: typeof Brain; title: string; desc: string }) {
  const t = useLayoutTokens();
  return (
    <div style={{
      padding: 16, borderRadius: 8, background: t.bgContent,
      border: `1px solid ${t.border}`,
      display: 'flex', flexDirection: 'column', gap: 8, overflow: 'hidden',
    }}>
      <div style={{
        width: 32, height: 32, borderRadius: 7, background: `${t.accent}15`,
        display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
      }}>
        <Icon size={16} color={t.accent} />
      </div>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, marginBottom: 2 }}>{title}</div>
        <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.5, margin: 0 }}>{desc}</p>
      </div>
    </div>
  );
}

function StepCard({ num, title, desc }: { num: number; title: string; desc: string }) {
  const t = useLayoutTokens();
  return (
    <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
      <div style={{
        width: 26, height: 26, borderRadius: '50%', background: t.accent, color: '#fff',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 12, fontWeight: 700, flexShrink: 0, marginTop: 1,
      }}>{num}</div>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, marginBottom: 2 }}>{title}</div>
        <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.5, margin: 0 }}>{desc}</p>
      </div>
    </div>
  );
}

function QuickStartCard({
  icon: Icon, title, desc, cta, onClick, accent,
}: {
  icon: typeof Brain; title: string; desc: string; cta: string; onClick: () => void; accent: string;
}) {
  const t = useLayoutTokens();
  return (
    <button onClick={onClick} style={{
      flex: 1, minWidth: 180, padding: 18, borderRadius: 10,
      background: t.bgContent, border: `1px solid ${t.border}`,
      cursor: 'pointer', textAlign: 'left',
      display: 'flex', flexDirection: 'column', gap: 8,
      transition: 'border-color 0.15s, box-shadow 0.15s',
    }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = accent; e.currentTarget.style.boxShadow = '0 2px 10px rgba(0,0,0,0.08)'; }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.boxShadow = 'none'; }}
    >
      <div style={{
        width: 32, height: 32, borderRadius: 7, background: `${accent}15`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
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

// ── Assistant (graph) card ──────────────────────────────────

function GraphCard({
  assistant, onOpen, accent,
}: {
  assistant: Assistant; onOpen: () => void; accent: string;
}) {
  const t = useLayoutTokens();
  return (
    <button onClick={onOpen} style={{
      padding: 16, borderRadius: 10, background: t.bgContent,
      border: `1px solid ${t.border}`,
      cursor: 'pointer', textAlign: 'left',
      display: 'flex', flexDirection: 'column', gap: 8,
      transition: 'border-color 0.15s, box-shadow 0.15s',
    }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = accent; e.currentTarget.style.boxShadow = '0 2px 10px rgba(0,0,0,0.08)'; }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.boxShadow = 'none'; }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{
          width: 32, height: 32, borderRadius: 7, background: `${accent}15`,
          display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
        }}>
          <Workflow size={16} color={accent} />
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {assistant.name}
          </div>
          <div style={{ fontSize: 10, fontFamily: 'monospace', color: t.textDim, marginTop: 1 }}>{assistant.graph_id}</div>
        </div>
      </div>
      {assistant.description && (
        <p style={{
          fontSize: 11, color: t.textMuted, lineHeight: 1.5, margin: 0,
          overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
        }}>{assistant.description}</p>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, fontWeight: 600, color: accent, marginTop: 2 }}>
        <PlayCircle size={12} /> Open
      </div>
    </button>
  );
}

// ── Main component ──────────────────────────────────────────

export default function GraphHomePage({ onEnterStudio }: GraphHomePageProps) {
  const t = useLayoutTokens();
  const c = useContent();
  const { assistants, apiOnline } = useStudioState();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Load assistants WITHOUT auto-selecting — the user picks one here.
  const loadGraphs = useCallback(async () => {
    abortRef.current?.abort();
    const abort = new AbortController();
    abortRef.current = abort;
    setLoading(true);
    setError(null);
    try {
      await studio.loadAssistantsOnly();
      if (abort.signal.aborted) return;
    } catch {
      if (abort.signal.aborted) return;
      setError(c.graphsError);
    } finally {
      if (!abort.signal.aborted) setLoading(false);
    }
  }, [c.graphsError]);

  useEffect(() => {
    loadGraphs();
    return () => abortRef.current?.abort();
  }, [loadGraphs]);

  const handleOpenStudio = () => {
    onEnterStudio?.();
  };

  const handleOpenAssistant = (a: Assistant) => {
    // Select the assistant first so the studio re-selects it on mount.
    void studio.selectAssistant(a);
    onEnterStudio?.();
  };

  const grid: React.CSSProperties = {
    display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 12,
  };

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
          <Workflow size={16} style={{ color: t.accent }} />
          <span style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary }}>{c.headerTitle}</span>
          <span style={{
            fontSize: 10, padding: '1px 6px', borderRadius: 999,
            background: `${t.accent}15`, color: t.accent, fontWeight: 600,
          }}>
            LangGraph
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <button
            onClick={loadGraphs}
            disabled={loading}
            title={c.headerRefresh}
            style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: 28, height: 28, borderRadius: 4,
              background: 'transparent', color: t.textMuted,
              border: 'none', cursor: 'pointer', opacity: loading ? 0.5 : 1,
            }}
            onMouseEnter={e => { if (!loading) e.currentTarget.style.background = t.bgHover; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
          >
            {loading ? <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <RefreshCw size={14} />}
          </button>
          <button
            onClick={handleOpenStudio}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '6px 12px', borderRadius: 6,
              background: t.accent, color: '#fff',
              fontSize: 12, fontWeight: 600, border: 'none', cursor: 'pointer',
            }}
          >
            <Plus size={13} /> {c.headerCta}
          </button>
        </div>
      </div>

      {/* ── Scrollable content ── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '28px 32px' }}>
        {/* Hero */}
        <div style={{
          display: 'flex', gap: 24,
          background: `linear-gradient(135deg, ${t.accent}22 0%, ${t.accent}08 55%, ${t.bgContent} 100%)`,
          border: `1px solid ${t.border}`,
          borderRadius: 12,
          padding: '36px 36px 30px',
          marginBottom: 28,
          alignItems: 'center',
        }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 16 }}>
              <div style={{
                width: 50, height: 50, borderRadius: 12,
                background: `linear-gradient(135deg, ${t.accent}, ${t.accent}cc)`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                boxShadow: `0 4px 14px ${t.accent}35`,
              }}>
                <Workflow size={26} color="#fff" />
              </div>
              <div>
                <h1 style={{ fontSize: 26, fontWeight: 750, color: t.textPrimary, margin: 0, letterSpacing: '-0.4px' }}>
                  {c.heroTitle}
                </h1>
                <p style={{ fontSize: 13, color: t.textMuted, margin: '3px 0 0 0' }}>{c.heroSubtitle}</p>
              </div>
            </div>

            <p style={{ fontSize: 13, color: t.textMuted, lineHeight: 1.7, margin: '0 0 6px 0', maxWidth: 600 }}>{c.heroP1}</p>
            <p style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6, margin: '0 0 4px 0', maxWidth: 600, opacity: 0.85 }}>{c.heroP2}</p>
            <p style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6, margin: '0 0 20px 0', maxWidth: 600, opacity: 0.75 }}>{c.heroP3}</p>

            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <button
                onClick={handleOpenStudio}
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
                onClick={() => document.getElementById('graph-assistants')?.scrollIntoView({ behavior: 'smooth' })}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6,
                  padding: '10px 18px', borderRadius: 8,
                  border: `1px solid ${t.border}`,
                  background: 'transparent',
                  color: t.textPrimary, fontSize: 13, fontWeight: 500, cursor: 'pointer',
                }}
              >
                {c.heroBrowse}
                <ArrowRight size={14} />
              </button>
            </div>
          </div>

          <div style={{
            width: 220, flexShrink: 0, alignSelf: 'stretch',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: `${t.accent}0a`, borderRadius: 10,
            border: `1px solid ${t.border}`,
            overflow: 'hidden',
          }}>
            <GraphVisual />
          </div>
        </div>

        {/* Available graphs */}
        <Section title={c.graphsTitle} subtitle={c.graphsSubtitle}>
          <div id="graph-assistants" style={{ scrollMarginTop: 12 }}>
            {error && (
              <div style={{ padding: 14, borderRadius: 8, border: `1px solid #e5484d40`, background: '#e5484d10', fontSize: 12, color: t.textMuted }}>
                {error}
              </div>
            )}
            {!error && loading && assistants.length === 0 && (
              <div style={{ padding: 20, textAlign: 'center', fontSize: 12, color: t.textDim }}>
                <Loader size={16} style={{ animation: 'spin 1s linear infinite', margin: '0 auto 8px', display: 'block', color: t.accent }} />
                {c.graphsLoading}
              </div>
            )}
            {!error && !loading && assistants.length === 0 && (
              <div style={{
                padding: 28, textAlign: 'center', borderRadius: 10,
                border: `1px dashed ${t.border}`, background: t.bgContent,
              }}>
                <Workflow size={22} style={{ color: t.textDim, margin: '0 auto 8px', display: 'block' }} />
                <div style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary }}>{c.graphsEmpty}</div>
                <div style={{ fontSize: 11, color: t.textDim, marginTop: 4 }}>{c.graphsEmptyHint}</div>
              </div>
            )}
            {assistants.length > 0 && (
              <div style={grid}>
                {assistants.map((a) => (
                  <GraphCard key={a.assistant_id} assistant={a} accent={t.accent} onOpen={() => handleOpenAssistant(a)} />
                ))}
              </div>
            )}
            {assistants.length > 0 && (
              <div style={{ marginTop: 10, fontSize: 11, color: t.textDim, display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 7, height: 7, borderRadius: '50%', background: apiOnline ? '#4caf50' : '#e5484d' }} />
                {apiOnline ? 'connected' : 'offline'}
              </div>
            )}
          </div>
        </Section>

        {/* What is LangGraph */}
        <Section title={c.whatTitle} subtitle={c.whatSubtitle}>
          <div style={grid}>
            <FeatureCard icon={CircleDot} title={c.elStateName} desc={c.elStateDesc} />
            <FeatureCard icon={Boxes} title={c.elNodeName} desc={c.elNodeDesc} />
            <FeatureCard icon={Route} title={c.elEdgeName} desc={c.elEdgeDesc} />
            <FeatureCard icon={GitBranch} title={c.elGraphName} desc={c.elGraphDesc} />
            <FeatureCard icon={Database} title={c.elCheckpointName} desc={c.elCheckpointDesc} />
            <div style={{
              borderRadius: 8, border: `1px solid ${t.border}`, background: t.bgContent, overflow: 'hidden',
            }}>
              <CheckpointVisual />
            </div>
          </div>
        </Section>

        {/* Core capabilities */}
        <Section title={c.capTitle} subtitle={c.capSubtitle}>
          <div style={grid}>
            <FeatureCard icon={ShieldCheck} title={c.cap1Title} desc={c.cap1Desc} />
            <FeatureCard icon={Zap} title={c.cap2Title} desc={c.cap2Desc} />
            <FeatureCard icon={UserCheck} title={c.cap3Title} desc={c.cap3Desc} />
            <FeatureCard icon={Brain} title={c.cap4Title} desc={c.cap4Desc} />
            <FeatureCard icon={History} title={c.cap5Title} desc={c.cap5Desc} />
            <FeatureCard icon={Network} title={c.cap6Title} desc={c.cap6Desc} />
            <FeatureCard icon={Puzzle} title={c.cap7Title} desc={c.cap7Desc} />
            <FeatureCard icon={Cpu} title={c.cap8Title} desc={c.cap8Desc} />
          </div>
        </Section>

        {/* Multi-agent patterns */}
        <Section title={c.patternTitle} subtitle={c.patternSubtitle}>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <PillarCard icon={Layers} title={c.p1Title} desc={c.p1Desc} bullets={[c.p1B1, c.p1B2, c.p1B3]} />
            <PillarCard icon={Share2} title={c.p2Title} desc={c.p2Desc} bullets={[c.p2B1, c.p2B2, c.p2B3]} />
            <PillarCard icon={GitBranch} title={c.p3Title} desc={c.p3Desc} bullets={[c.p3B1, c.p3B2, c.p3B3]} />
            <PillarCard icon={Users} title={c.p4Title} desc={c.p4Desc} bullets={[c.p4B1, c.p4B2, c.p4B3]} />
          </div>
        </Section>

        {/* How it works */}
        <Section title={c.howTitle} subtitle={c.howSubtitle}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 18 }}>
            <StepCard num={1} title={c.how1} desc={c.how1Desc} />
            <StepCard num={2} title={c.how2} desc={c.how2Desc} />
            <StepCard num={3} title={c.how3} desc={c.how3Desc} />
            <StepCard num={4} title={c.how4} desc={c.how4Desc} />
          </div>
        </Section>

        {/* Ecosystem comparison */}
        <Section title={c.ecoTitle} subtitle={c.ecoSubtitle}>
          <div style={{
            borderRadius: 10, border: `1px solid ${t.border}`, background: t.bgContent, overflow: 'hidden',
          }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={{ padding: '10px 12px', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, color: t.textDim, borderBottom: `1px solid ${t.border}`, textAlign: 'left', width: 140 }}>{c.ecoHeadProduct}</th>
                  <th style={{ padding: '10px 12px', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, color: t.textDim, borderBottom: `1px solid ${t.border}`, textAlign: 'left' }}>{c.ecoHeadRole}</th>
                  <th style={{ padding: '10px 12px', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, color: t.textDim, borderBottom: `1px solid ${t.border}`, textAlign: 'left', width: 260 }}>{c.ecoHeadIdeal}</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { p: c.eco1Product, r: c.eco1Role, i: c.eco1Ideal, hl: false },
                  { p: c.eco2Product, r: c.eco2Role, i: c.eco2Ideal, hl: true },
                  { p: c.eco3Product, r: c.eco3Role, i: c.eco3Ideal, hl: false },
                  { p: c.eco4Product, r: c.eco4Role, i: c.eco4Ideal, hl: false },
                ].map((row) => (
                  <tr key={row.p} style={row.hl ? { background: `${t.accent}0a` } : undefined}>
                    <td style={{
                      padding: '10px 12px', fontSize: 12, fontWeight: row.hl ? 700 : 500,
                      color: row.hl ? t.accent : t.textPrimary,
                      borderBottom: `1px solid ${t.border}`, whiteSpace: 'nowrap',
                    }}>
                      {row.p} {row.hl && '←'}
                    </td>
                    <td style={{ padding: '10px 12px', fontSize: 11, color: t.textMuted, borderBottom: `1px solid ${t.border}`, lineHeight: 1.5 }}>{row.r}</td>
                    <td style={{ padding: '10px 12px', fontSize: 11, color: t.textMuted, borderBottom: `1px solid ${t.border}`, lineHeight: 1.5 }}>{row.i}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ padding: '10px 12px', fontSize: 11, color: t.textDim, lineHeight: 1.5, borderTop: `1px solid ${t.border}` }}>
              {c.ecoFooter}
            </div>
          </div>
        </Section>

        {/* Quick start */}
        <Section title={c.quickTitle}>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <QuickStartCard icon={PlayCircle} title={c.qs1Title} desc={c.qs1Desc} cta={c.qs1Cta} onClick={handleOpenStudio} accent={t.accent} />
            <QuickStartCard icon={FileCode2} title={c.qs2Title} desc={c.qs2Desc} cta={c.qs2Cta} onClick={handleOpenStudio} accent="#8b5cf6" />
            <QuickStartCard icon={Repeat} title={c.qs3Title} desc={c.qs3Desc} cta={c.qs3Cta} onClick={handleOpenStudio} accent="#4caf50" />
          </div>
        </Section>
      </div>
    </div>
  );
}
