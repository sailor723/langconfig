# LangConfig 系统架构

> LangConfig 平台（Agent IDE）的可视化总览。本文使用 Mermaid 绘图 — 请在 IDE 的 Markdown
> 预览中打开本文件以渲染图表。本文是 [system-architecture.md](./system-architecture.md)
> 的中文版本。

---

## 1. 什么是 LangConfig？

LangConfig 是一个用于**构建、测试并交付 LangChain 智能体与 LangGraph 工作流的可视化平台**。
它作为完整的 **Agent IDE（"工作台"模式）** 运行——你在画布上设计智能体，在侧栏中配置
工具/中间件/技能，与它们对话以验证行为，最后**将它们导出为独立运行的 Python**，可在平台之外
运行（就像你在 VS Code 中开发，然后发布应用一样）。

产品是一个**双工作区系统**：一个轻量级 React IDE 外壳（Obsidian/VS Code 风格：活动栏、
侧栏、标签式工作区、底部面板），前面是 FastAPI 后端；后端在运行时把持久化的智能体定义
**编译成真正的 LangGraph 可执行图**。

### 技术栈

| 层级 | 技术 |
| ---- | ---- |
| 前端 | React 19 + TypeScript + Tailwind CSS 4 + ReactFlow |
| 后端 | Python 3.11/3.13 + FastAPI + LangChain V1 + LangGraph + deepagents 0.7.1 |
| 数据库 | PostgreSQL 16 + pgvector + SQLAlchemy + Alembic |
| 运行时库 | deepagents SDK、langchain/langgraph、LLM 供应商（DeepSeek / OpenAI 兼容）、Tavily 搜索 |

### 五层心智模型

```mermaid
flowchart TB
    L1["1 · UI 层<br/>React IDE 外壳 (src/)"]
    L2["2 · API 层<br/>FastAPI 路由 (backend/api/)"]
    L3["3 · 服务层<br/>构建器、导出器、工作区 (backend/services/)"]
    L4["4 · 核心引擎<br/>工作流、代码生成、技能、中间件 (backend/core/)"]
    L5["5 · 数据与运行时库<br/>PostgreSQL + deepagents/langchain"]

    L1 --> L2 --> L3 --> L4 --> L5
    L3 --> L5
    L4 --> L5

    classDef layer fill:#f8fafc,stroke:#64748b,color:#111;
    class L1,L2,L3,L4,L5 layer;
```

每一层都有**严格的职责**：

1. **UI** — 渲染画布/编辑器，绝不直接访问数据库；只调用 `src/lib/api/` 中的类型化 API 客户端。
2. **API** — FastAPI 路由是薄*控制器*：校验输入、委托给服务、流式输出 SSE。几乎不含业务逻辑。
3. **服务层** — *构建器*（`AgentFactory`、`DeepAgentFactory`）、*导出器*（`api/agents/deep_agents.py` 代码生成 + `services/agent_bundle.py` 包）、工作区/记忆/调度管理器。
4. **核心引擎** — 可复用引擎：工作流执行器、检查点、事件、代码生成、技能注册表、中间件、上下文管理。
5. **数据与运行时** — PostgreSQL 表以及服务层所编排的外部 SDK。

> **关键架构原则：** 智能体*不是*以可执行代码的形式存储——它们以 **JSON 配置行**存储在
> PostgreSQL 中，由服务层在**运行时编译成 LangGraph 图**。这正是你能在 UI 中编辑智能体、
> 然后立即重新运行它的原因。

---

## 2. 什么是 AI 智能体？

**AI 智能体**是一种使用大语言模型（LLM）来*行动*（而不只是回答）的软件系统：给定一个目标后，
它规划一系列步骤、调用工具（搜索、数据库、文件、API、Shell）、观察结果，并不断迭代直到目标完成。
经典循环：

```text
目标 → LLM 推理步骤 → 选择工具 → 执行 → 观察结果 → 反馈 → 重复 → 交付
```

| | 聊天机器人（Chatbot） | AI 智能体 |
|---|---|---|
| 输入 | 一个问题 | 一个*目标* |
| 输出 | 一段回复 | 一个*结果* |
| 循环 | 单轮，结束 | 规划 → 行动 → 观察 → 迭代 |
| 工具 | 无或固定 | 任意工具，由模型自行选择 |
| 状态 | 仅对话 | 对话 + 记忆 + 外部状态 |
| 示例 | "今天天气怎么样？" | "订一张 6000 元以内的机票并邮件发送行程" |

智能体在**服务对象**和**构建方式**上差异巨大：

1. **消费级助手产品** — 封闭、托管、聊天优先（豆包 / Doubao、ChatGPT、Copilot）。
2. **个人 / 消息型 / 桌面工作台智能体** — 自托管或桌面应用，通过聊天应用与你对话，
   操作你的机器（OpenClaw、Hermes Agent、WorkBuddy）。
3. **编程智能体 / Agent IDE** — 在仓库或 IDE 内运行（Claude Code、Cursor、MarsCode）。
4. **开发者框架与运行时** — 用于*构建*上述任何一类智能体的积木（LangChain、LangGraph、Deep Agents）。

LangConfig 属于**第 4 类**：建立在 LangChain 技术栈之上的可视化 IDE，用于构建并交付
前三种智能体（§3–§4）。

---

## 3. 智能体全景 — OpenClaw · Hermes · Doubao · LangChain 技术栈

### 3.1 OpenClaw — 个人消息型智能体

**是什么。** 由奥地利开发者 Peter Steinberger 开发的开源（MIT）自主智能体。2025 年 11 月
24 日以 *Clawdbot* 之名发布，后因 Anthropic 商标异议于 2026 年 1 月更名为 *Moltbot*，
再更名为 *OpenClaw*。TypeScript/Node 网关 + Swift 移动端；在你的机器上本地运行；
是有史以来增长最快的开源项目之一（截至 2026 年 3 月约 24.7 万 GitHub 星标）。你通过
消息应用与它对话——WhatsApp、Telegram、Discord、Slack、Signal、iMessage 以及 15+ 个其他平台。

**工作原理。** 一个常驻网关守护进程：

1. 任何渠道收到消息 → 解析到对应的会话记录（transcript）；
2. LLM 规划并流式返回工具调用；
3. 工具执行（Shell、文件、通过 Playwright 的浏览器、邮件、API）；结果追加到会话记录，
   再次调用 LLM——形成工具循环；
4. 最终回复投递回原始渠道。

消息之间，**心跳**机制会唤醒智能体执行后台工作（邮件、日历、cron 定时任务）。它内置
100+ 个预置**技能**、持久化记忆（`SOUL.md` / `MEMORY.md` / `AGENTS.md`）、子智能体和
Docker 沙箱，并支持 Anthropic、OpenAI、DeepSeek 以及本地模型。

**典型用途。** 聊天应用内的 24/7 个人助手："调研三家竞品并起草摘要"、预订出行、发送邮件、
管理文件、运行定时任务。软件免费；持续成本是你的 LLM API 开销（轻度使用约每月 $5–20，
重度使用更多）。

**优点 / 缺点。**

| 优点 | 缺点 |
|---|---|
| 免费、MIT、社区庞大 | 自托管部署有技术门槛 |
| 供应商无关、本地优先（数据在你的机器上） | 广泛的系统访问权限 = 真实的安全风险 |
| 20+ 消息平台 | Token 成本随使用增长 |
| 技能 / 插件 / 浏览器自动化 | 单用户个人自动化——没有团队治理 |
| 开箱即用：浏览器 + Shell + 定时任务 | 不是框架：你消费它，而不是在其上构建产品 |

### 3.2 Hermes Agent — 自我进化型智能体（Nous Research）

**是什么。** 来自 Nous Research（Hermes 微调模型背后的团队）的开源自我进化智能体框架，
2026 年 2 月 25 日发布。Python 3.11+，开源，供应商无关（OpenRouter、Anthropic、OpenAI、
DeepSeek、Gemini、本地模型）。2026 年增长最快的智能体框架之一——发布后数周内 GitHub
星标即达数万。可在终端、桌面应用以及 16+ 个消息平台运行（Telegram、Discord、Slack、
WhatsApp、Signal、Matrix、iMessage、微信）。

**工作原理。** 一个闭环自我进化循环：

- 完成任意复杂任务（≥5 次工具调用）后，它会**自动编写可复用的技能**——一份 Markdown 技能
  文档，记录方法、边界情况和领域知识；
- 技能在复用时不断精炼，因此智能体对你的工作流会越来越熟练（Nous 基准：累积 20+ 个技能后
  研究任务提速 40%）；
- **三层记忆**（用户画像 / 会话 / 长期；可插拔后端：内置、Honcho、Mem0）跨会话持久化
  身份、偏好和教训；
- 规划 → 执行 → 记忆 → 技能各层、面向外部工具的 MCP 服务器集成、`delegate_task` 子智能体、
  凭据池化，以及本地 / Docker / SSH / 无服务器执行后端。

**典型用途。** 在廉价 VPS 上自托管的科研 / 运维智能体，持续累积你的个人技能库；定时科研与
内容工作；编码与基础设施自动化；一个可从 Telegram、Discord 和 WhatsApp 访问的智能体。

**优点 / 缺点。**

| 优点 | 缺点 |
|---|---|
| 自我进化、复利式技能库 | 项目年轻（2026）——成熟度/稳定性风险 |
| 持久记忆 + 供应商无关 | 自主自我修改需要技能审查与隔离 |
| MCP 集成、子智能体 | 单用户定位——不是企业治理模型 |
| 运行成本低（$5 VPS） | 不是用于交付智能体产品的通用框架 |
| 社区动能巨大 | 未经审查的自动生成技能可能包含危险操作 |

### 3.3 豆包 Doubao — 字节跳动的全场景助手平台

**是什么。** 字节跳动的 AI 助手与智能体平台（2023 年 8 月以 "Grace" 名义上线；国际版
*Dola*）。中国排名第一的 AI 应用（约 1.7 亿月活、1 亿+ 日活）。基于豆包（原云雀/Lark）
LLM 家族——文本、图像、音频、视频，100 万+ token 上下文——并深度接入字节生态
（抖音、头条、飞书/Lark）。对开发者通过火山引擎 API 开放；兄弟产品包括 **Coze（扣子）**——
无代码智能体构建器——以及 **MarsCode** 编程智能体。

**工作原理。** 多模态 LLM + 产品级智能体框架。2026 年字节将豆包重构为三种模式：

- **快速模式（Quick）** — 快速问答与检索；
- **专家模式（Expert）** — 深度推理（数学、长文档、法理逻辑），由具备原生智能体架构的
  豆包 2.0 Pro 驱动；
- **任务模式（Task）** — 自主智能体执行：拆解 → 规划 → 调用工具 → 交付，包括定时后台任务、
  零代码网页/PPT 生成，以及 Excel→图表可视化。

**典型用途。** 日常消费级 AI：中文写作 / 总结 / 学习、图像与音视频生成、会议纪要、深度研究
报告。面向企业：火山引擎 API 与 Coze 无代码智能体。消费端免费；2026 年 6 月起推出付费档
（标准版 ¥68/月、增强版 ¥200/月、专业版 ¥500/月）。

**优点 / 缺点。**

| 优点 | 缺点 |
|---|---|
| 中文输出质量最佳 | 闭源、托管——隐私 / 管辖顾虑 |
| 消费端免费 + 多模态 | 不是框架：无法重新编排或自托管其逻辑 |
| 分发量巨大、token 便宜 | 面向消费者——对自定义企业编码工作流支持弱 |
| 通过 Coze 无代码构建智能体 | 你不拥有数据、提示词或行为 |
| 任务模式 = 真正的自主执行 | 英文 / 代码输出落后于西方助手 |

### 3.4 WorkBuddy — 腾讯的全场景 AI 办公工作台

**是什么。** 腾讯的全场景 AI 智能体桌面工作台——腾讯云 "Buddy" 家族的"AI 数字同事"（与编程
智能体 CodeBuddy 并列）。由腾讯云 CodeBuddy 团队打造：内部试用（2026 年 1 月，2000+ 腾讯员工）
→ 封闭内测（2026 年 2 月）→ 正式发布（2026 年 3 月 9 日）。Windows/macOS 桌面应用，把自主
智能体执行封装成免部署、开箱即用的形态——按腾讯自己的说法，是国内日活用户数最多的效率智能体
工具之一（截至 2026 年 3 月月访问量约 885 万）。其技术底座与开源项目 OpenClaw 同源。

**工作原理。** 三种工作模式，按自主性/风险分级：

- **问答模式（Ask）** — 纯问答 / 咨询，不触碰文件，零风险；
- **规划模式（Plan）** — 先列出逐步执行计划，经确认后才动手；
- **执行模式（Craft）** — 完全自主执行：拆解 → 规划 → 在本机文件上完成多步任务，交付
  可核查的成果（文档、表格、PPT、图表）。

在其之上：**100+ 开箱即用的专家技能（Skills）**（每周更新，也支持自定义技能）；**专家团
（Expert Groups）** 把多智能体协作工作流打包——技能（能力）→ 专家（能力 + 经验）→ 专家团
（多位专家 + 协作流程）；**沙箱**保障执行安全；支持 MCP 协议；接入多家模型（含腾讯混元
Hunyuan 家族）。**远程控制：** 通过 IM 应用（微信、企业微信、QQ、Slack、Telegram、Discord、
钉钉、飞书）从手机发送指令，在电脑上执行任务。办公生态：与腾讯文档深度集成，把"人机协同
写作"带进 Word/Excel/PPT/Markdown（2026 年 7 月，WorkBuddy V5.3+）。

**企业版**（2026 年 6 月 5 日）：WorkBuddy Enterprise AI Workspace——三层递进能力框架
（专家层：技能、MCP、数据/知识连接器、装配层；助手层：具备记忆与自我进化的 24/7 数字助理；
团队层：共享上下文与"上下文飞轮"）；三大核心产品（面向研发团队的 CodeBuddy、面向业务团队的
WorkBuddy、托管智能体 Managed Agents）；统一管理平台，支持 SaaS / 专享 VPC / 私有化多种
部署模式。

**典型用途。** 日常办公自动化：文档处理、数据分析与报表、会议纪要、PPT 生成、竞品调研，
以及从手机远程安排任务。个人版自 ¥99/月起（有免费体验版）；团队版约 $40/席位/月；企业
SaaS 版 ¥198/人/月起。

**优点 / 缺点。**

| 优点 | 缺点 |
|---|---|
| 免部署、预集成、沙箱化——上手门槛低 | 闭源、托管——数据流经腾讯云（私有化需企业版） |
| 100+ 技能 + 专家团多智能体并行 | 办公场景产品——不是用于构建智能体产品的通用框架 |
| Ask / Plan / Craft 按自主性分级 | 深度定制需企业版/私有化 |
| 办公生态（腾讯文档人机协同写作） | 国内优先，海外版仍在起步 |
| IM 远程控制（手机 → 电脑） | 桌面应用、按用户视角——团队治理在企业版 |

### 3.5 LangChain — 框架（抽象层）

**是什么。** 使用最广泛的开源**智能体框架**。官方文档称之为"智能体框架：模型、工具与
智能体循环的抽象和集成"——一套标准化的词汇（模型/对话接口、工具 schema、内容块、智能体
循环）外加 **600+ 集成**（模型、向量库、文档加载器、工具）。v1.0（2025 年 10 月）把
`langchain` 命名空间精简到智能体构建的核心积木——`langchain.agents`（`create_agent`）、
`langchain.messages`、`langchain.tools`、`langchain.chat_models`（`init_chat_model`）、
`langchain.embeddings`——并把遗留的链、检索器和 hub 移入独立的 `langchain-classic` 包。

**工作原理。** 自 v1.0 起，`create_agent`（取代了旧的 `langgraph.prebuilt.create_react_agent`）
成为标准入口，它**在底层运行在 LangGraph 执行引擎之上**。你声明一个模型、一组工具和一个
系统提示词；`create_agent` 将"推理 → 选择工具 → 执行 → 反馈"的循环装配成 LangGraph 图，
并通过**中间件数组**定制，而不是通过继承。官方文档称中间件是 *`create_agent` 的标志性特性*：
可组合的钩子在模型调用前后、每个工具调用前后执行，让你能够**监控**（日志、分析、调试）、
**修改**（提示词、工具选择、输出格式）、**控制**（重试、兜底、提前终止）和**强制**（速率
限制、护栏、PII 检测）。预置中间件包括 `PIIMiddleware`、`SummarizationMiddleware`、
`HumanInTheLoopMiddleware`、`ModelCallLimitMiddleware`、`ToolCallLimitMiddleware`、
`ModelFallbackMiddleware`、Anthropic 提示词缓存、待办清单、LLM 工具选择器和上下文编辑。

**典型用途。** 标准工具调用智能体与 RAG 应用；快速原型；团队构建 LLM 功能的统一方式。
（本仓库的普通智能体正是这样构建的：`AgentFactory.create_agent` — §11。）

### 3.6 LangGraph — 运行时（持久化执行）

**是什么。** 按官方文档，LangGraph 是"一个用于构建、管理和部署长时间运行、有状态智能体的
底层编排框架与运行时"——Klarna、Uber、J.P. Morgan 和 LinkedIn 均在生产环境中使用。你定义
节点、边和状态 schema（`StateGraph`），即可获得其下的生产级基础设施：**持久化执行、流式
输出、人在回路（HITL）中断和持久化**。v1.0（2025 年 10 月 22 日）冻结了公共 API 并盖上
"持久化执行"的印记；Python 与 TypeScript 两条线同步演进。

**工作原理。** LangGraph 刻意保持底层——它不抽象提示词或架构，其核心优势是让你在**同一个
图中混编确定性的手写步骤与 LLM 驱动的智能体步骤**。它的核心收益是**持久化执行**：每次状态
转换都会保存到以**线程标识符**为键的**检查点**（本仓库为 Postgres），因此一次运行可以在
系统故障或数天后的人工审查之后**精确地**从上次记录的状态处暂停并恢复——通过重放最近状态
（副作用与非确定性操作必须包进 `task` 以保证可重放）。流式输出细粒度的 `values`/`updates`/
LLM token 事件；`interrupt()` 打开人工审批点；记忆同时涵盖**短期**（线程级检查点）与
**长期**（跨线程存储）。

**典型用途。** 需要分支、重试、扇出或门控的工作流；多智能体拓扑（supervisor 监督者、swarm
群集）；任何需要长时间运行且可靠恢复的任务。（本仓库：工作流执行引擎 §12 + Graph Studio §13。）
其周边生态补充了可观测性与部署：LangSmith 追踪/评测、**LangSmith Engine**（在你的追踪中
检测问题并提出修复）、**LangSmith Fleet**（无代码智能体构建器），以及 `langgraph-cli`
（`langgraph dev` / `up` / `deploy`）。

### 3.7 Deep Agents — 装配层（harness，开箱即用）

**是什么。** LangChain 的"开箱即用智能体装配层"——`deepagents` SDK（本仓库锁定 0.7.1）。
官方文档把装配层定义为**构建在 LangGraph 之上**的预置工具、提示词和子智能体：一个*长时程
自主*智能体开箱即可工作所需的全部能力——规划、虚拟文件系统、上下文窗口隔离的子智能体、
上下文管理、记忆、技能和人工审批门控。动机是：智能体任务长度大约**每 7 个月翻一番**，
而长时间运行正是朴素工具循环的致命伤。

**工作原理。** Deep Agents **不新增运行时**——`create_deep_agent` 包装同一个 `create_agent`
API，把一套精选中间件预设编译到 LangGraph 引擎之上。按官方文档，装配层能力包括：

- **规划** — `write_todos` 工具在智能体状态中维护一个持久化的任务清单（`pending` /
  `in_progress` / `completed`）；
- **虚拟文件系统** — 基于可插拔后端的 `ls` / `read_file` / `write_file` / `edit_file`，
  外加**声明式文件系统权限**（智能体可以读写哪些路径）；
- **任务委派** — `task` 工具派生出拥有**隔离上下文窗口**的子智能体；任何 LangGraph
  `CompiledStateGraph` 都可以作为子智能体交给 Deep Agent，因此自定义编排可以与默认能力并存；
- **上下文管理** — 三档分层压缩技术：**超过 2 万 token** 的工具结果先卸载到文件系统（替换为
  路径 + 10 行预览），窗口越过 **~85%** 后卸载旧的写/编辑输入，最后才用 LLM **总结**压缩历史，
  同时完整转录保留在磁盘上；
- **代码执行** — 沙箱后端启用时提供 `execute` 工具（本地 shell、Docker、远程），另有进程内
  JS 解释器；
- **技能、记忆、HITL** — `SKILL.md` 渐进式披露、用户画像/会话/长期记忆、审批门控——全部可
  通过**装配层预设（harness profiles）** 预置。

**典型用途。** 长时间、多步骤、非确定性的任务：研究、编程、上市（GTM）自动化。（本仓库的
DeepAgent 由 `DeepAgentFactory.create_deep_agent` 通过技能 + 中间件 + 沙箱流水线构建 — §11。）

### 3.8 一个技术栈，三级台阶——而非三个竞争对手

LangChain 官方将其界定为 **Framework / Runtime / Harness（框架 / 运行时 / 装配层）**——
"组合，而非迁移"：

| | LangChain | LangGraph | Deep Agents |
|---|---|---|---|
| 层级 | 框架 | 运行时 | 装配层 |
| 价值点 | 抽象 + 集成 | 持久化执行、流式、HITL、持久化 | 预置工具、提示词、子智能体 |
| 你写什么 | 模型 + 工具 + 中间件 | 节点、边、状态 schema | 一个提示词 + 工具；其余交给默认值 |
| 何时选用 | 标准工具/RAG 循环 | 分支、重试、扇出、门控 | 长时程自主任务 |

社区中流传一个很好的类比：**LangChain = 流水线**、**LangGraph = 图 / 交通枢纽**、
**Deep Agents = 大脑 / 项目经理**——流水线加快开发速度，图让一切持续运转，
Deep Agents 负责规划与委派。

```mermaid
flowchart TB
    H["Deep Agents · 装配层<br/>规划 · 文件系统 · 子智能体 · 技能"]
    F["LangChain · 框架<br/>create_agent · 中间件 · 集成"]
    R["LangGraph · 运行时<br/>StateGraph · 持久化执行 · HITL · 持久化"]
    M["模型 · 工具 · 向量库 · LangSmith 可观测性"]

    H --> F --> R --> M

    style H fill:#fde68a,stroke:#b45309,color:#111
    style F fill:#bbf7d0,stroke:#15803d,color:#111
    style R fill:#ddd6fe,stroke:#6d28d9,color:#111
```

### 3.9 活动侧边栏 — LangConfig 中技术栈的落点

上面三级台阶不只是抽象库——每一级都对应 LangConfig 的 VS Code 风格**活动侧边栏**中的一个
一等工作区，旁边还有工作流画布（第四块表面）：

| 活动 | 你构建什么 | 技术栈层级 | 入口 |
|---|---|---|---|
| **Agents**（用户图标） | 通过 4 段式编辑器构建普通工具调用智能体（概览 · 提示词 · 工具 · JSON） | LangChain 框架 | `AgentFactory.create_agent` |
| **DeepAgents**（大脑图标） | 长时程自主智能体：技能 + 中间件 + 沙箱 | Deep Agents 装配层 | `DeepAgentFactory.create_deep_agent` |
| **Workflows**（分支图标） | 可视化工作流——在画布上绘制节点 + 边，以 JSON 存入 Postgres | LangGraph 运行时（可视化） | 工作流工作室，执行器 §12 |
| **Graph**（网络图标） | 内省并运行代码定义的 LangGraph 图（`backend/langgraph/*.py`） | LangGraph 运行时（代码） | Graph Studio §13 |

因此 IDE 本身正是围绕技术栈组织的：框架（Agents）、装配层（DeepAgents），以及运行时的
两个面向（Workflows 可视化、Graph 内省）。§2 的"四类智能体"分类法与这个侧边栏，是从两个
角度看到的同一个答案。

---

## 4. 价值主张与用例 — LangChain 技术栈 vs 豆包 · WorkBuddy · OpenClaw · Hermes

本节提到的六种工具处于**两个不同的世界**。OpenClaw、Hermes、豆包和 WorkBuddy 是*你使用的
产品*；LangChain、LangGraph 和 Deep Agents 是*你用来构建的积木*。把它们放在同一轴上比较，
就像拿厨房和餐厅作比较。

| 维度 | LangChain 技术栈（LangChain / LangGraph / DeepAgents） | OpenClaw | Hermes Agent | WorkBuddy | 豆包 Doubao |
|---|---|---|---|---|---|---|
| 类别 | 开发者框架 + 运行时 + 装配层 | 个人消息型智能体 | 自我进化型个人智能体 | 个人 AI 智能体工作台（"AI 数字同事"） | 消费级助手产品 |
| 你的角色 | 构建系统的开发者 | 委托任务的终端用户 | 委托任务的终端用户 | 委托任务的终端用户（职场用户） | 消费者 |
| 编排 | 显式图、持久化、HITL、检查点 | 会话记录 + 工具循环 | 规划 + 技能循环 | Ask / Plan / Craft 三种模式 + 专家团 | 产品管理的任务模式 |
| 数据与运行时 | 归你所有——你的数据库、你的基础设施、你的模型 | 你的机器、你的密钥 | 你的 VPS、你的密钥 | 腾讯云（封闭）；企业版可私有化 | 字节跳动云端（封闭） |
| 扩展方式 | 代码 + 中间件 + 技能 | 技能 + 插件 | 自研技能 + MCP | 100+ 技能 + MCP 连接器 + 自定义技能 | Coze 无代码 |
| 多智能体 | supervisor / swarm / 子智能体（显式） | 子智能体（基础） | `delegate_task` 子智能体 | 专家团（技能 → 专家 → 专家团） | 产品管理 |
| 最适合 | 生产级智能体系统、企业工作流 | 通过聊天进行 24/7 个人自动化 | 自托管的复利式科研/运维智能体 | 日常办公自动化——文档、数据、会议、报告 | 日常消费级 AI（尤其中文） |
| 安全与隐私 | 密钥加密、自托管数据库、HITL 门控、审计日志 | 广泛的系统访问权限——靠你配置 | 技能需要审查 + 隔离 | 沙箱执行 + Ask/Plan/Craft 分级；企业版管理与审计 | 厂商云端，中国管辖 |

### 4.1 安全与数据隐私

你的数据放在哪里决定了一切——这也是自托管的 LangChain 技术栈与托管型消费产品之间
最尖锐的差异。

| 安全维度 | LangChain 技术栈（LangConfig） | OpenClaw | Hermes Agent | WorkBuddy | 豆包 Doubao |
|---|---|---|---|---|---|---|
| 数据存放位置 | 你的 PostgreSQL + 你的基础设施；`STORAGE_MODE=db` 时连技能/文件也存入数据库 | 你的本地机器 | 你的 VPS | 腾讯云（中国管辖）；企业版可私有化/专享 VPC | 字节跳动云端（中国管辖） |
| 透明性 | 开源（MIT）——完全可审计 | 开源（MIT） | 开源 | 闭源 | 闭源，黑盒 |
| 密钥 | 静态加密（`encryption.py`、`settings.api_keys`） | 磁盘上的环境变量密钥 | 磁盘上的环境变量密钥 | 由腾讯云托管 | 由字节跳动托管 |
| 行动安全 | 沙箱化 Shell、工作区级文件系统、HITL 审批门控、审计日志 | 广泛的系统访问——权限靠你 | 技能需要审查 + 容器隔离 | 沙箱 + Ask/Plan/Craft 分级；企业版权限与审计管理 | 平台管理，无组织级策略 |
| 可审计性 | `execution_events` + `audit_logs`（Postgres）、Langfuse/LangSmith 追踪 | 磁盘上的会话记录 | 本地日志 | 企业版管理后台（用量、成员统计、审计） | 厂商侧，导出受限 |
| 合规 | 部署在你所在区域，自己掌控留存（GDPR、HIPAA…） | 个人工具（不适用） | 个人工具（不适用） | 国内托管；私有化版满足数据驻留 | 厂商合规；对企业存在管辖问题 |

要点：

- **LangConfig / 技术栈** — 数据永不离开你的基础设施；每次运行都检查点到 Postgres、每个
  动作都写入审计日志；危险工具位于审批门控之后（`hitl` 路由）；密钥静态加密；
  `STORAGE_MODE=db` 甚至把技能和文件也放进*你的*数据库，而不是厂商的存储桶。
- **OpenClaw / Hermes** — 本地优先对隐私友好且可离线运行，但两者都会获得对你机器和聊天
  账户的*广泛*访问；没有团队策略或审查层，因此安全取决于你的自律（对 Hermes 而言，还要
  审查其自动编写的技能）。
- **豆包** — 控制力最弱：提示词、文档和输出都流经字节跳动基础设施（中国管辖）。个人使用
  没问题；对有数据驻留或保密要求的企业是障碍。
- **WorkBuddy** — 产品中最"开箱即用"的：沙箱化、Ask/Plan/Craft 风险分级，并且有带管理后台
  和私有化的真正企业版。但默认闭源且由腾讯托管：提示词、文件与输出都流经腾讯基础设施
  （除非采用私有化版），你无法重新编排或自托管产品逻辑本身。

**纯本地部署——并且可以向外扩展。** 技能、提示词、工具、检查点和输出都是普通工件，
你可以完全在私有化环境运行：任何一项都无需厂商往返。当单机不够用时，技术栈是*扩展*
而不是替换你——换成云端模型、增加 S3 存储（`STORAGE_MODE=s3`）、把同样的导出智能体部署到
你自己的服务器。OpenClaw 是绑定在一台机器上的"全家桶"智能体；豆包和 WorkBuddy 100% 由厂商
托管（WorkBuddy 仅在私有化企业版中离开云端）；只有这个技术栈能让你从本地起步、按自己的
节奏扩展。

**企业级开源。** LangChain 生态——LangChain、LangGraph、LangSmith，以及由大量工具、
模板和集成组成的丰富社区——由一家公司维护并拥有庞大的贡献者社区，这正是企业所需要的：
可审计性、治理、集成伙伴和支持渠道。OpenClaw 本质上是一位维护者的"全家桶"个人智能体
（难以扩展到团队/企业需求）；豆包和 WorkBuddy 的企业故事是封闭云端上的厂商条款
（WorkBuddy 的私有化版仍在你自己的硬件上运行腾讯的闭源软件）。

### 4.2 用户与用例——谁来用、用来做什么

| 用户画像 | 用例 | 最佳工具 | 为什么 |
|---|---|---|---|
| 消费者 | 日常问答、中文写作、图像/音视频生成 | 豆包 Doubao | 免费、多模态、中文最佳 |
| 个人高级用户 | 在 WhatsApp/Telegram/邮件中的 24/7 个人助手 | OpenClaw · Hermes | 本地、聊天原生、自主、自我进化 |
| 职场个人 / 企业员工 | 日常办公自动化——文档、数据报表、会议纪要、PPT | WorkBuddy | 免部署、开箱即用、100+ 技能、IM 远程控制 |
| 研究者 | 长时程研究、文献综述、深度报告 | Deep Agents（LangConfig）· 豆包深度研究 | 规划 + 子智能体 + 上下文管理；豆包面向消费级 |
| 战略与商业分析师 | 战略深度研究——竞品扫描、市场报告、决策备忘录 | Deep Agents（LangConfig） | 规划 + 子智能体 + 长时程研究 |
| 开发者 | 快速构建工具调用 / RAG 智能体 | LangChain `create_agent` | 最快的标准智能体循环，100+ 集成 |
| 平台工程师 | 持久、有状态、HITL、多智能体的生产工作流 | LangGraph | 持久化执行、检查点、中断、持久化 |
| AI 产品团队 | 基于自有数据/模型构建并交付 AI 应用 | LangConfig（技术栈 + 导出） | 可视化构建 + 独立 Python 导出 |
| 运维与自动化团队 | cron 定时、文件监听触发、后台任务 | LangConfig | `schedules`、`triggers`、`background_tasks`、`webhooks` 路由 |
| 数据分析师 | CSV → SQLite → 图表、看板、演示文稿 | LangConfig | `analysis`、`presentations`、`data_dashboard` 流水线 |
| 业务系统 / 企业 IT | 在现有事务系统（CRM、ERP、财务）上做数据库 CRUD + 智能体 | LangConfig | SQL 工具 + 图编排 + 在你现有 Postgres/数据库上的 HITL 审批 |
| 无代码 / AI 应用构建者 | 可视化组装 AI 应用，零代码、完全拥有 | LangConfig | 画布 + 图编辑 + 独立导出（若接受产品托管则用 Coze） |
| 学习者与教育者 | 通过实践学习 LangChain / LangGraph | LangConfig | 实时图可视化、单步运行、状态检视器、运行控制台 |

### 4.3 逐一对比——LangChain 技术栈 vs 豆包 · OpenClaw · Hermes

- **原生多智能体，天生如此。** 协作在技术栈中是一等公民：supervisor / swarm / 子智能体
  （Deep Agents 的 `delegate_task`）、LangGraph 子图、共享图状态——因此你可以组合出
  专业分工的智能体（规划者、程序员、评审者、执行者），每个都有隔离的上下文，由显式边协调。
  OpenClaw 和 Hermes 各在一台机器上运行*一个*智能体循环；豆包的多智能体行为不透明且由
  产品管理。
- **vs 豆包（Doubao）** — 豆包是封闭产品：固定模型、产品管理的编排、数据在字节云端，而且
  **没有搭建透明度**——你智能体背后的提示词、工具和图都是黑盒；你无法检视、版本化或复现
  它们。技术栈在需要*控制力*的地方胜出——选择模型、定义图、拥有数据、自托管、交付代码。
  豆包在零搭建的消费体验和规模化中文质量上胜出。
- **vs OpenClaw** — OpenClaw 是面向一台机器、通过聊天应用触达的*个人*智能体。
  LangGraph / Deep Agents 面向*系统*：多租户、持久、可审计、可部署到任何地方。它们回答的
  是不同的问题——"自动化我的 Mac" vs "运营一个生产服务"。LangConfig 可以在同一个 IDE 里
  既构建 OpenClaw 式助手，也构建企业工作流。
- **vs Hermes** — Hermes 的自我进化技能循环确实新颖；LangConfig 的 SkillsMiddleware 提供
  同样的渐进式披露技能（按需读取的 `SKILL.md` 目录 — §14），但在*你的*掌控之下：技能经过
  审查、在 `STORAGE_MODE=db` 时存入 Postgres，并作为可审计、受治理的运行时的一部分，
  而不是自主自我修改的智能体。
- **vs WorkBuddy** — WorkBuddy 是*开箱即用*的个人智能体工作台：免部署、预集成、沙箱化，
  还有出色的企业版。技术栈回答的是另一个问题：*你*是构建者——图是显式的、中间件是你的、
  数据留在你的基础设施上，而且你交付可运行的代码。WorkBuddy 在*它自己的产品里*执行；
  技术栈交付的是可以导出、随处运行的智能体。LangConfig 能在同一个 IDE 里既构建
  WorkBuddy 式办公助手，也构建受治理的企业工作流。

### 4.4 为什么 LangChain 技术栈在其擅长的领域胜出

- **胜过豆包** — 豆包是封闭的：你不能改变它的编排、选择它的模型、自托管它，也无法拥有它
  接触的数据。LangGraph 给你显式、可检查点的控制流；你可以选择任何供应商（本仓库默认
  DeepSeek）；并且你交付的是可运行的代码，而不是租用一项功能。
- **胜过 OpenClaw / Hermes** — 它们是绑定到*一台机器*及其聊天应用的单用户个人智能体。
  LangChain 技术栈是为*系统*而生：能扛过重启的持久状态、人在回路审批、多智能体拓扑、
  Postgres 持久化、团队治理，以及任意位置的部署。
- **胜过 WorkBuddy** — WorkBuddy 自动化的是*它自己的*工作区：你在腾讯的产品里、腾讯的云上、
  用腾讯提供的技能工作。技术栈是*构建层*：任意供应商、你的数据、你的图、可导出的代码、
  随处可部署——包括企业自有基础设施内部，而这正是 WorkBuddy 私有化版仍然运行腾讯闭源
  软件的地方。

### 4.5 LangConfig 的独特价值主张

LangConfig 是一个**构建在恰好这套技术栈上的可视化 Agent IDE（"工作台"）**——LangChain V1
+ LangGraph + DeepAgents 0.7.1（见 §1 与 §11）。智能体以 JSON 配置存储，并在**运行时编译成
真正的 LangGraph 可执行图**，这让它兼具产品的便利与框架的控制力：

| 能力 | 豆包 / OpenClaw / WorkBuddy | LangConfig（基于 LangChain 技术栈） |
|---|---|---|
| 无代码构建 | Coze 无代码（产品托管） | 可视化画布 + 图编辑，*以及*完整代码访问 |
| 运行时控制 | 无（固定产品） | 显式图、中断、检查点、Postgres |
| 人在回路 | 无 | 有（`hitl` 路由、审批门控） |
| 自主性旋钮 | 无——由产品决定 | 按工作流：完全自主，或 HITL 门控 |
| 多智能体 | 产品管理 | supervisor / swarm / 子智能体，由你接线 |
| 数据所有权 | 厂商云端 | 你的 PostgreSQL、你的文件、你的技能 |
| 搭建透明度 | 提示词/图不透明（黑盒） | 可检视的 JSON 配置，编译成可见、可版本化的图 |
| 交付 | 不适用（你留在产品内） | 导出独立 Python，可在任何地方运行 |
| 边做边学 | 不适用 | 实时图可视化、单步运行、状态检视器——内建的学习 LangGraph 方式 |

### 4.6 用例决策规则

- 日常消费级帮助、中文工作 → **豆包**；
- 桌面工作台上的日常办公自动化——文档、数据、会议、PPT → **WorkBuddy**；
- 在 WhatsApp/Telegram 中运行 24/7 个人助手 → **OpenClaw**（若想要自我进化的技能库则选
  **Hermes**）；
- 构建*产品或企业工作流*智能体——工具调用/RAG → **LangChain `create_agent`**；
  分支/持久/有状态/HITL → **LangGraph**；长时程自主研究/编程 → **Deep Agents**；
- 你想可视化地构建、测试并*交付*上述任何一类 → **LangConfig**，它基于同一技术栈并导出
  可运行的 Python；
- 对接现有事务 / 遗留业务系统——数据库 CRUD + 智能体（在你现有 Postgres 上的 SQL 工具、
  图编排、HITL 审批）→ **LangConfig**；
- 无代码组装 AI 应用但要求完全所有权 → **LangConfig**（接受产品托管则用 Coze）；
- 可视化学习 LangChain / LangGraph → **LangConfig**——画布展示真实的图，你可以边学习边
  单步运行并检视状态。

### 4.7 平台 + 开箱即用智能体 — 差异化优势

大多数产品要么是**平台**（一切由你构建），要么是**产品**（只能消费我们交付的东西）。
LangConfig 刻意**两者皆是**：同一个孵化新智能体的 IDE，同时内置一套**企业智能体起步产品线**，
它们构建在以上技术栈之上，并与其他任何智能体一样存储——也就是一行可检视、可编辑、可导出的
`deep_agent_templates` 记录。

| 开箱即用智能体 | 它做什么 | 构建于 |
|---|---|---|
| **企业战略咨询智能体** | 长时程深度研究：市场/竞品扫描、战略备忘录、带引用的决策支持——具备规划、子智能体与上下文管理的 DeepAgent | Deep Agents |
| **企业本体（Ontology）管理智能体** | 治理你的领域模型：创建、版本化并审计实体/关系；把业务术语映射到规范本体；校验 schema 并标记漂移 | LangChain + 技能 + 工作流 |
| **企业管理智能体** | 面向你系统的日常运营：在现有事务数据库上做 CRUD、HITL 审批门控、报表与审计拉取——即"数据库 CRUD + 智能体"模式 | LangGraph + SQL 工具 |
| **智能体 IDE 本身（LangConfig）** | 第四个"智能体"是孵化器：可视化地构建、测试并交付下一个企业智能体——无需代码、完全所有权、独立导出 | 整个技术栈 |

为什么这是差异化优势：

- **两条车道，同一技术栈。** 开箱即用智能体为非开发者提供即时价值；IDE 则让开发者有地方
  演进它们。替代方案里两条车道都不存在：豆包/扣子在它们的云上托管智能体，OpenClaw/Hermes
  是单智能体的个人工具，WorkBuddy 的智能体留在它自己的工作区内，而裸的 LangChain/LangGraph
  根本不含产品化的智能体。
- **预构建 ≠ 黑盒。** 与产品型智能体不同，每个开箱即用智能体都是一份可在 IDE 中打开的
  配置——检视它的图、编辑提示词、更换工具、重新导出。起步产品线是*起点*，不是围城。
- **产品线经由平台成长。** 新用例先在 IDE 中孵化，评审通过后可晋升到开箱即用库——这是
  纯产品型厂商无法复制的飞轮。

---

## 5. 图层总览（一览无余）

```mermaid
%%{init: {"themeVariables": {"fontSize": "18px"}}}%%
flowchart TB
    subgraph UI["1 · 前端层 — React 19 + TypeScript + Tailwind 4"]
        direction LR
        A1["IDE 外壳<br/>components/layout2/"]
        A2["功能模块<br/>workflows · agents · graph studio · chat"]
        A3["API 客户端<br/>lib/api/（类型化）"]
    end

    subgraph API["2 · API 层 — FastAPI · 41 个路由 (main.py)"]
        direction LR
        R1["agents + deepagents<br/>CRUD · 提示词预览 · 导出"]
        R2["chat + workflows<br/>SSE · 编排 · hitl"]
        R3["rag + doc_chat + memory<br/>知识 · 存储 · agents_md"]
        R4["tools + skills + workspace<br/>models · settings"]
        R5["graph_studio<br/>代码定义的图 · 线程 · SSE 运行"]
    end

    subgraph SVC["3 · 服务层 — 构建器 + 管理器"]
        direction LR
        F1["AgentFactory<br/>core/agents/factory"]
        F2["DeepAgentFactory<br/>services/deepagent_factory"]
        E1["导出代码生成<br/>api/agents/deep_agents.py + agent_bundle.py"]
        W1["WorkspaceManager<br/>+ 20 个支撑服务"]
    end

    subgraph CORE["4 · 核心引擎"]
        direction LR
        C1["workflows<br/>执行器 · 检查点 · 事件"]
        C2["codegen"]
        C3["skills + middleware"]
        C4["models + context"]
    end

    subgraph LIB["运行时库"]
        direction LR
        L1["deepagents SDK"]
        L2["langchain V1 + langgraph"]
        L3["LLM 供应商"]
        L4["Tavily 搜索"]
    end

    subgraph DB["5 · 数据层"]
        D1(("PostgreSQL 16<br/>+ pgvector :5432"))
        D2["表：<br/>deep_agent_templates · custom_tools · skills<br/>workflows · agent_memories · execution_events"]
    end

    A3 --> R1
    A3 --> R2
    A3 --> R3
    A3 --> R4
    A3 --> R5

    R1 --> F1
    R1 --> F2
    R1 --> E1
    R2 --> F1
    R2 --> F2
    R3 --> F1
    R4 --> F1

    F1 --> C1
    F1 --> C3
    F1 --> C4
    F2 --> C1
    F2 --> C3
    C1 --> L2
    R5 --> L2

    F1 --> L2
    F2 --> L1
    L1 --> L2
    F1 --> L3
    F2 --> L3

    F1 --> D1
    F2 --> D1
    C1 --> D1
    D1 --> D2

    classDef ui fill:#e2e8f0,stroke:#334155,color:#0f172a,font-size:18px;
    classDef api fill:#bfdbfe,stroke:#1d4ed8,color:#1e3a8a,font-size:18px;
    classDef svc fill:#bbf7d0,stroke:#15803d,color:#14532d,font-size:18px;
    classDef core fill:#ddd6fe,stroke:#6d28d9,color:#4c1d95,font-size:18px;
    classDef lib fill:#fde68a,stroke:#b45309,color:#78350f,font-size:18px;
    classDef db fill:#fecaca,stroke:#b91c1c,color:#7f1d1d,font-size:18px;

    class A1,A2,A3 ui;
    class R1,R2,R3,R4,R5 api;
    class F1,F2,E1,W1 svc;
    class C1,C2,C3,C4 core;
    class L1,L2,L3,L4 lib;
    class D1,D2 db;
```

---

## 6. `backend/api/agents/deep_agents.py` 是什么？

它是 **DeepAgents 的 REST API 路由（控制器）**——在 `main.py` 中注册为"DeepAgents 配置与
导出"路由。它**不**构建智能体、也**不**自行导出；它负责：

| 端点组 | 职责 | 委托给 |
| ------- | ------ | ------ |
| `POST/GET /api/deepagents/`、`GET /api/deepagents/{id}`、`GET /templates` | DeepAgent CRUD + 内置模板 | `models.deep_agent`（数据库） |
| `POST /api/deepagents/prompt-preview` | 系统提示词组装预览 | deepagents 装配层档案（`_harness_profile_for_model`） |
| `/export`、`/code` | 导出 `.py` CLI / langconfig 包 | `api/agents/deep_agents.py`（代码生成）+ `services/agent_bundle.py` |

真正的构建器是 `core/agents/factory/`（普通智能体）与 `services/deepagent_factory/`
（深度智能体）——`deep_agents.py` 只是通过 HTTP 暴露它们。

**`use_deepagents` 标志是事实来源。** 它位于智能体存储的 JSON `config` 中，在运行时决定
一行记录被当作普通智能体还是 DeepAgent：

- `api/agents/deep_agents.py` 读取 `config.get("use_deepagents", False)` 来区分两个列表。
- `api/workflows/crud.py` 在工作流节点包含智能体时检查同一标志（外加节点类型 /
  `deepAgentId`），以便在执行时使用正确的工厂。

---

## 7. 前端层深入（`src/`）

UI 是一个**IDE 外壳**（Obsidian/VS Code 风格），最大化画布空间以进行可视化工作流设计。

### IDE 外壳 — `src/components/layout2/`

| 组件 | 用途 |
| ------- | ----- |
| `AgentEditor` / `AgentHomePage` | 普通智能体的四段式结构编辑器（总览 · 提示词 · 工具 · JSON） |
| `DeepAgentEditor` / `DeepAgentCreator` / `DeepAgentHomePage` | 同样的四段式编辑器，用于 DeepAgents，带导出按钮 |
| `WorkflowEditor` / `WorkflowStudioPage` | 可视化工作流构建器 |
| `NodeSidebar` | 所选画布节点的右侧配置面板 |
| `SkillEditorTab` / `SkillBrowserSidebar` | 技能编写 + 浏览 |
| `ToolEditor` | 自定义工具构建器 |
| `ModelHomePage` / `SearchProvidersSidebar` | 模型默认值 + 搜索供应商 API 密钥 |
| `KnowledgeView` / `NotebookViewer` | RAG 知识 + 笔记本 |
| `PromptBrowserSidebar` | 提示词库 |
| `editorChatToolbar` / `chatStore.ts` / `useLayout.tsx` | 编辑器内聊天 + 布局状态 |

### 功能模块 — `src/features/`

| 模块 | 用途 |
| ------ | ---- |
| `workflows/` | 完整 ReactFlow 画布（节点、边、节点配置、工具栏、结果、执行、设置） |
| `agents/ui/PromptCanvas.tsx` | 可视化提示词编辑 |
| `deepagent-studio-v2/` | 现代 DeepAgent 工作室：`ModernStudioCanvas`、智能体选择器、能力栏、主/子智能体节点、工具节点、自动布局 |
| `chat/` | 带 SSE 流式的聊天 UI（`useChatController`、`useChatStreaming`、`streamChatEvents.ts`）、会话、文件、指标、HITL 中断、思考块、分析面板 |
| `graph-studio/` | 图工程活动：助手 + 数据库侧栏、ReactFlow 画布（自动布局、条件边、运行路径、点击节点查看详情弹窗）、测试运行控制台、检视器、带中断的聊天输入 — 见 §13 |
| `tools/ui/` | `CustomToolBuilder` + `ToolTemplateGallery` |
| `knowledge/`、`memory/`、`settings/ui/`、`projects/AgentsMdEditor.tsx` | 支撑视图 |

### 类型化 API 客户端 — `src/lib/api/`

`agents.ts`、`chat.ts`、`workflows.ts`、`tools.ts`、`skills.ts`、`documents.ts`、`files.ts`、
`projects.ts`、`schedules.ts`、`settings.ts`、`triggers.ts`、`backgroundTasks.ts` — 每个
后端领域一个轻量 fetch 封装。**没有组件直接与后端通信**；一切经由这些客户端，这让 API
表面可测试且保持一致。

```mermaid
flowchart LR
    subgraph Pages["pages/"]
        P1["HomePage"] --> P2["PlaygroundPage"]
        P3["SettingsPage"] --> P4["ProjectsPage"]
        P5["AnalysisPage"] --> P6["PromptAssemblyPage"]
    end
    subgraph Shell["components/layout2/（IDE 外壳）"]
        SH1["活动栏 + 侧栏"] --> SH2["标签式工作区"]
        SH2 --> SH3["NodeSidebar（配置）"]
        SH2 --> SH4["底部面板（聊天/日志）"]
    end
    subgraph Clients["lib/api/（类型化客户端）"]
        C1["agents.ts · chat.ts · workflows.ts"]
        C2["tools.ts · skills.ts · files.ts · settings.ts"]
    end
    Shell --> Clients
    Pages --> Shell
    Clients -->|"HTTP / SSE :8765"| API["FastAPI 后端"]
```

---

## 8. 后端 API 层 — 41 个路由

`backend/main.py` 在 FastAPI 应用上注册了 **41 个路由**。它们是薄控制器：解析请求、
委托给服务/工厂，并流式返回结果。

| 分组 | 路由（按 `main.py` 顺序） | 用途 |
| ----- | ------ | ----- |
| 健康与调试 | `health`、`debug` | 存活探测 + 仅开发用的诊断 |
| 智能体 | `agents`（模板）、`agent_generator`、`action_presets`、`images` | 普通智能体 CRUD、AI 智能体生成、动作预设、图片存储 |
| DeepAgents | `deepagents`、`chat` | DeepAgent CRUD/导出 + DeepAgent 聊天测试 |
| 工作流 | `workflows`、`orchestration`、`hitl`、`checkpoints` | 工作流 CRUD/执行、简化编排、人在回路审批、检查点恢复 |
| 图工程 | `graph_studio` | 代码定义的图托管（`backend/langgraph/*.py`）：内省、线程、SSE 运行、目标数据库切换、运行中断 — 见 §13 |
| 聊天与记忆 | `memory`、`store`、`agents_md_router`、`chat_skill_review` | 智能体记忆、长期存储、AGENTS.md（MemoryMiddleware）、数据技能审查 |
| 知识 / RAG | `rag`、`graphindex_chat`、`doc_chat`、`kv`、`analysis` | RAG 摄取/检索、图索引聊天、基于文件夹的文档聊天、KV 存储、CSV→SQLite→图表 |
| 工具与技能 | `custom_tools`、`tool_registry`、`skills` | 用户工具、原生工具注册表（唯一事实来源）、技能系统 |
| 工作区与项目 | `projects`、`tasks`、`workspace`、`background_tasks` | 项目、任务工作区、文件树、后台任务队列 |
| 模型与设置 | `settings`、`search_providers`、`local_models`、`model_capabilities`、`model_routes`、`schemas` | 配置、搜索供应商密钥、本地模型、能力画像、模型调用（Playground）、结构化输出 schema |
| 自动化与扩展 | `schedules`、`triggers`、`webhooks`、`notebooks`、`presentations`、`google_auth` | Cron 定时、文件监听触发、webhook 接收、笔记本、演示文稿生成 + OAuth |

```mermaid
flowchart LR
    subgraph Routers["FastAPI 应用 (main.py)"]
        RA["agents + deepagents + chat"]
        RW["workflows + orchestration + hitl + checkpoints"]
        RG["graph_studio<br/>代码定义的 langgraph 模块"]
        RK["rag + doc_chat + graphindex_chat + kv + analysis"]
        RT["custom_tools + tool_registry + skills"]
        RM["memory + store + agents_md"]
        RX["schedules + triggers + webhooks + notebooks"]
    end
    Routers --> SVC["服务 / 工厂层"]
    SVC --> CORE["核心引擎"]
    SVC --> DB[("PostgreSQL")]
    RG --> CORE
```

---

## 9. 服务层深入（`backend/services/`）

这是大脑：**构建器**把持久化的配置变成可运行的图；**管理器**负责文件系统、工作区和副作用。

### 构建器（编译配置 → LangGraph）

| 服务 | 入口点 | 产物 |
| ------ | ----- | ----- |
| `core/agents/factory/assembly.py` | `AgentFactory.create_agent()`（L29） | 通过 langchain V1 `create_agent` 构建的普通智能体 |
| `services/deepagent_factory/assembly.py` | `DeepAgentFactory.create_deep_agent()`（L29） | 通过 `deepagents.create_deep_agent` 构建的 DeepAgent |
| `services/deepagent_factory/{preflight,shared,support}.py` | 辅助函数 | 配置校验、共享接线、SDK 兼容性防护 |
| `api/agents/deep_agents.py`（代码生成） | `export_deepagent()` / `download_agent_code()` | 独立 `.py` CLI 或导入/导出包（`services/agent_bundle.py`） |

### 管理器与支撑服务

| 服务 | 职责 |
| ---- | ---- |
| `workspace_manager.py` | 项目/任务工作区目录；沙箱与文件系统后端在此限定作用域 |
| `chat_session_manager.py` | 聊天会话生命周期（开始/结束/恢复/续接） |
| `conversation_context.py`、`context_window_manager.py`、`context_retrieval.py`、`context_document_indexer.py` | 上下文打包、token 窗口管理、检索 |
| `mcp_manager.py` | MCP 服务器/工具加载 |
| `scheduler_service.py`、`triggers/file_watcher.py` | Cron + 文件监听触发 |
| `presentation_service.py`、`dashboard_generator.py`、`data_dashboard.py`、`data_skill_generator.py`、`csv_to_sqlite.py` | 数据分析 → 演示文稿/看板 |
| `notebook_kernel_manager.py` | 笔记本用 Python 内核 |
| `event_bus.py`、`audit_service.py`、`deepagents_instrumentation.py` | 可观测性、审计日志、Langfuse 回调 |
| `local_model_service.py`、`llama_config.py` | 本地模型配置 |
| `oauth_service.py`、`encryption.py` | Google OAuth + 密钥加密 |
| `diff_service.py`、`file_storage.py`、`image_storage.py`、`storage_estimator.py` | Diff/版本化 + 存储 |
| `agents_md_service.py` | 面向 MemoryMiddleware 的项目 `AGENTS.md` |
| `token_counter.py`、`output_formatter.py` | Token 计数、响应格式化 |
| `agent_generator_service.py`、`agent_utils.py` | AI 智能体生成、模型解析（`resolve_model`） |
| `workflow_config_service.py` | 工作流配置辅助 |

### 看板 —— **Analysis** 活动

Analysis 活动（ActivityBar 中的柱状图图标 → `/analysis` → `src/pages/AnalysisPage.tsx`）
是「**静态 HTML 加载器 + 由 meta 驱动的聊天**」：通过 `GET /api/analysis/dashboards`
列出 `data/analysis_dbs/` 下的 `*.html`（解析每个文件头部的
`LangConfig Dashboard Meta` 注释，取出 `db:`、`skills:`、`entry:`），再用 iframe 通过
`GET /api/files/<name>` 渲染页面（该接口会把 Plotly 的 CDN 地址改写为
`/static/plotly.min.js`，从而支持离线使用），并把 Chat 面板接到
`/api/analysis/chat`，使用看板声明的数据库与技能。

喂给它的生成方式有三种：

| 方式 | 代码 | 是否用 LLM | 示例 |
|---|---|---|---|
| **上传 / 演示** | `services/dashboard_generator.py`（`generate_dashboard`）＋ `api/analysis/routes.py` 中的提示词（`_auto_generate_dashboard` → `_run_analysis_agent`） | ✅ 是（可选 companion `.skill.md`） | `business_dashboard`、`sales_dashboard*`、`dashboard_<hash>` |
| **ERP 研究案例** | `backend/skills/erp-analyst/9_erp_dashboard.py` | ❌ 确定性（`Mode: static-embed`） | `erp_dashboard_*.html` |
| **Sun Hing 研究案例** | `data/analysis_dbs/gen_sunhing_kpi_dashboard.py` —— 一个脚本生成 hub + 5 个因子子看板（外加 gantt/data），并复制 ERD/intro/employees/liability 母版 | ❌ 确定性（除时间戳外逐字节稳定） | `sunhing_dashboard*.html` |

详见 **[docs/reference/sunhing-dashboards.md](reference/sunhing-dashboards.md)**：Sun Hing 的生产者映射、
28 个 KPI 的覆盖证明、确定性验证，以及已知的漂移风险（两份分叉的数据库副本；
复制传播的静态页面）。

---

## 10. 核心引擎深入（`backend/core/`）

两类智能体与工作流共享的可复用引擎。

### `core/agents/`

- `factory/` — `assembly.py`（`AgentFactory.create_agent` 构建器）、`llm.py`（LLM 接线 +
  子智能体构建）、`prompting.py`、`validation.py`、`shared.py`
- `specialized/` — `json_agent.py`、`pandas_agent.py`、`sql_agent.py`（类型化专业智能体）
- `delegation.py`、`memory.py`、`model_profiles.py`、`multimodal.py`、`templates.py`、`templates_specialized.py`、`tool_loader.py`（`ToolLoader.load_native`）

### `core/workflows/` — 执行引擎（见 §12）

`executor/builder.py` · `executor/execution.py` · `executor/nodes.py` · `executor/shared.py` ·
`checkpointing/manager.py`（Postgres 检查点）· `events/emitter/`（进度、回调）·
`graph.py`、`graph_state.py`、`nodes.py`、`runner.py`、`state.py` ·
`supervisor.py`、`swarm.py`、`official_patterns.py`（可复用的图拓扑）

### `core/codegen/`

`langgraph.py`、`workflow_exporter.py` 和 `generators/` — `api_server.py`、`custom_tools.py`、
`nodes.py`、`nodes_configurable.py`、`routing.py`、`streamlit_app.py`、`streamlit_configurable.py`、
`templates.py`、`tools.py` — 把工作流变成可运行的代码工件（Streamlit 应用、API 服务器）。

### `core/context/` — `compactor.py`、`content_blocks.py`、`runtime.py`、`synthesis.py`

### `core/middleware/` — `core.py`、`advanced.py`、`deep.py`、`dynamic_tools.py`、`presets.py`、

`question_detection.py`、`routing.py`、`tool_selection.py`

### `core/skills/` — `registry.py`、`sync.py`、`matcher.py`、`loader.py`

### `core/tools/` — `factory/`（基础、构建器、模型）、`adapters/llamaindex.py`、

`templates/`（api/cms/data/database/image/notification/python/social/video）、`bigtool_registry.py`、
`execution_wrapper.py`、`seed.py`

### `core/models/` — `registry.py`、`router.py`、`selector.py`、`hooks.py`（模型路由/能力）

---

## 11. 智能体构建流水线（运行时）

两类智能体都在每次聊天/执行时从其存储的 JSON 配置编译而来。

### 普通智能体路径

`AgentFactory.create_agent()`（`core/agents/factory/assembly.py:29`）→ langchain V1
`create_agent`（与导出代码使用的同一 API）。子智能体在 `core/agents/factory/llm.py:281`
中用 `create_agent` 递归构建。

### DeepAgent 路径

`DeepAgentFactory.create_deep_agent()`（`services/deepagent_factory/assembly.py:29`）按顺序执行：

1. **导入防护** — 若未安装 `deepagents`，则回退为普通智能体（`_fallback_to_regular_agent`）。
2. **配置校验** — 只告警，不硬失败。
3. **可观测性** — Langfuse 回调（`_setup_callbacks`）。
4. **加载基础工具** — 原生 + 自定义 + MCP + 向量库（`_load_base_tools`）。
5. **中间件工具** — 来自已配置的中间件类型（`DeepAgentsMiddlewareFactory.create_all_tools`）。
6. **子智能体** — 用工作区上下文单独编译，以支持文件写入工具。
7. **中间件实例** — MemoryMiddleware（通过 FilesystemBackend 的 AGENTS.md）、
   FilesystemMiddleware（限定在任务工作区）、SummarizationMiddleware（token 触发）、
   SubAgentMiddleware（添加 `task` 工具）。
8. **检查点** — PostgreSQL 会话持久化（`get_checkpointer()`）。
9. **技能暂存** — 通过把已配置技能复制到 `<workspace>/skills/` 并用 `FilesystemBackend`
   指向它们，为 SkillsMiddleware 配备技能。
10. **沙箱** — 可选的 `LocalShellBackend`，提供 `execute` Shell 工具。
11. **`deepagents.create_deep_agent(...)`** → 编译好的 `LangGraph CompiledStateGraph`，
    随时可流式运行。

### 完整流水线

```mermaid
flowchart LR
    P1["API 调用：<br/>POST /api/deepagents/{id}/chat<br/>或工作流节点"] --> P2["DeepAgentFactory.create_deep_agent()"]
    P2 --> P3["加载工具<br/>原生 + 自定义 + MCP<br/>（设置磁盘后端时工具去重）"]
    P3 --> P4["将技能暂存到<br/><workspace>/skills/<br/>+ FilesystemBackend"]
    P4 --> P5["deepagents.create_deep_agent<br/>（技能、中间件、子智能体）"]
    P5 --> P6["CompiledStateGraph<br/>（Postgres 检查点）"]
    P6 --> P7["SSE 流：<br/>工具调用 + 最终答案"]
    P7 --> P8["会话持久化<br/>到 PostgreSQL"]

    style P5 fill:#fef3c7,stroke:#d97706,color:#111
    style P6 fill:#fee2e2,stroke:#dc2626,color:#111
```

*普通智能体走同一路径：`AgentFactory.create_agent()` → langchain V1 `create_agent`
（无技能/沙箱步骤）。*

### 工具去重说明

deepagents 库总会注入自己的 **FilesystemMiddleware**（必需中间件），其中的
`ls / read_file / write_file / edit_file / glob / grep` 工具限定在 `backend` 根目录。
当**磁盘后端**（技能/沙箱/文件系统）生效时，装配会丢弃我们原生的文件系统工具，让智能体
只暴露一套文件工具——后端限定的那一套胜出。

---

## 12. 工作流执行引擎（`core/workflows/`）

工作流是**可视化图**（前端 ReactFlow），以 JSON 节点/边持久化，然后由该引擎执行。

```mermaid
flowchart TB
    subgraph HTTP["API (api/workflows/)"]
        H1["POST /api/workflows/{id}/execute"]
        H2["POST /api/workflows/execute<br/>（execution.py）"]
        H3["GET /api/workflows/{id}/stream<br/>（SSE）"]
        H4["GET /api/workflows/{id}/events<br/>GET /tasks/{id}/events"]
    end

    subgraph ENGINE["core/workflows/"]
        E1["graph.py · graph_state.py<br/>从存储的节点构建 StateGraph"]
        E2["executor/execution.py<br/>运行 + 持久化执行状态"]
        E3["checkpointing/manager.py<br/>PostgresSaver 检查点"]
        E4["events/emitter/<br/>进度 + 回调事件"]
        E5["supervisor.py · swarm.py<br/>多智能体拓扑"]
        E6["runner.py · nodes.py<br/>节点分发（agent / tool / deepagent / llm）"]
    end

    H1 --> E1
    H2 --> E2
    E1 --> E6
    E6 --> E4
    E2 --> E3
    E3 --> DB[("PostgreSQL<br/>executions · events")]
    E4 --> H3
    E4 --> H4

    style E2 fill:#dcfce7,stroke:#16a34a,color:#111
    style E3 fill:#fee2e2,stroke:#dc2626,color:#111
```

关键机制：

- **节点分发** — 每个工作流节点可以是 LLM 调用、工具、普通智能体、DeepAgent 节点
  （由 `use_deepagents` 标志解析，`crud.py:285-334`），或 supervisor/swarm 模式。
- **检查点** — 每个执行步骤都检查点到 Postgres，因此执行可以暂停、恢复和还原
  （`api/workflows/checkpoints.py`）。
- **事件流式输出** — 事件发射器通过 SSE 推送进度 + 回调事件；UI 通过 `useWorkflowStream`
  订阅，实时更新画布。
- **编排与 HITL** — `orchestration` 路由驱动多步运行；`hitl` 路由在运行中途提供人工审批
  中断。

---

## 13. 图工程工作室（`api/graph_studio/`）

**图工程**活动是工作流引擎在 IDE 侧的伴侣：它直接在 FastAPI 进程内托管*代码定义*的
LangGraph 智能体（`backend/langgraph/*.py`）——无需独立的 `langgraph dev` 服务器。用户在
侧栏选择一个智能体，在画布上看到其图结构，创建线程，并通过实时 SSE 流式运行测试。

### 后端 — 原生图托管

`backend/api/graph_studio/routes.py` 注册一个路由（`/api/graph-studio`，挂载于
`main.py`），暴露 11 个端点：

| 端点 | 用途 |
| ----- | ---- |
| `POST /assistants/search` | 列出代码定义的助手（注册表） |
| `GET /assistants/{id}/graph` | 为画布内省节点 + 边（`compiled.get_graph()`） |
| `GET /assistants/{id}/schemas` | input / state / output jsonschema（`get_*_jsonschema()`） |
| `POST /threads/search` | 列出内存中的线程（按 `graph_id` 过滤） |
| `POST /threads` | 创建线程（uuid-hex id，状态 `idle`） |
| `GET /threads/{id}/state` | 通过 `compiled.aget_state(config)` 读取检查点状态 |
| `GET /threads/{id}/runs` | 某线程的运行历史 |
| `POST /threads/{id}/runs/stream` | SSE 运行 — `messages/partial` · `values` · `updates` |
| `GET /databases` | 列出 SQL 工具可指向的 Postgres 数据库 + 当前激活库 |
| `POST /databases/select` | 运行时切换 SQL 工具的目标数据库（无需改 `.env`） |
| `POST /threads/{id}/runs/cancel` | 中断正在进行的运行（在下一个 SSE 事件边界停止） |

关键机制：

- **注册表 → 惰性导入。** `_ASSISTANT_REGISTRY` 列出每个助手（`sql_agent`、
  `sql_agent_hitl`）；`_load_compiled()` 通过 `importlib.util.spec_from_file_location`
  一次性导入模块并缓存编译好的图。图模块之间按普通名称相互导入（例如 `sql_setup_db`），
  因此 `backend/langgraph/` 会被加入 `sys.path`。注册一个新条目是让新代码定义图浮现的
  唯一步骤。
- **无服务层。** 工作室端点直接调用 LangGraph SDK（`get_graph`、`get_*_jsonschema`、
  `astream`、`aget_state`）——图是*代码*，不是持久化的 JSON 配置，因此请求时无需编译。
- **内存线程。** `_THREADS` / `_RUNS` 是进程生命周期的字典（工作室是草稿工作区）。
  编译好的图自带线程级检查点（`InMemorySaver`）+ 跨线程记忆存储，因此会话状态在进程内
  存活——借助记忆，追问可跳过 schema 开场白。
- **SSE 形态。** 使用*列表*形式的流模式时，`compiled.astream(...)` 产生 `(mode, payload)`
  元组。部分 AIMessage 块按消息 id 累积（内容拼接 + 按索引合并 `tool_call_chunks`），
  空壳的 provider 消息被剥离，`values` / `updates` 快照原样透传。
- **用于弹窗的节点内省。** `GET /assistants/{id}/graph` 通过 `_graph_node_info` /
  `_source_info`（`inspect.getsource`，尽力而为/None 安全）丰富每个节点：`kind`
  （`start` / `end` / `function` / `tool` / `subgraph` / `unknown`）、模块、文件、行号范围 +
  原始源码、`node.metadata`，以及工具运行节点所绑定的工具（名称、描述、各自源码——
  `ToolNode.tools` 或更新的 `tools_by_name` 字典）。点击画布节点会打开一个浮动弹窗显示
  这些详情，刻意区别于经典 LangChain Studio 的检视器停靠栏。
- **运行中断。** `_CANCEL_EVENTS` 把 `thread_id → asyncio.Event` 映射起来；SSE 生成器
  在事件之间检查标志，当用户点击 Stop 时抛出 `_RunCancelled`，发出干净的
  `Run cancelled by user` 错误事件——图检查点保持一致状态。
- **目标数据库切换。** `sql_setup_db.py` 中的 SQL 工具在调用时解析数据库：运行时
  `_DB_OVERRIDE`（由 `POST /databases/select` 设置）优先于 `SQL_*` 环境配置，
  因此切换无需重新导入图。
- **SQL 智能体查询 Postgres。** `backend/langgraph/sql_setup_db.py` 连接 Postgres
  `chinook` 数据库（只读 psycopg2 会话；`information_schema` 内省产出 Postgres 风格的 DDL）。
  目标数据库通过根 `.env` 中的 `SQL_*` 环境块配置（或 `SQL_DATABASE_URL` 覆盖），
  并可在运行时从工作室的数据库下拉框中更改。
  `backend/db/setup_target_db.py` 会预置任意目标数据库（创建 + pgvector + 全部表），
  并打印要使用的 `DATABASE_URL`。

```mermaid
flowchart LR
    U1["图活动<br/>src/features/graph-studio/"] -->|"POST /runs/stream (SSE)"| A1["api/graph_studio/routes.py"]
    U2["助手 + 线程<br/>侧栏"] -->|"search · create · state"| A1
    A1 -->|"_load_compiled<br/>（importlib · 缓存）"| G1["backend/langgraph/*.py<br/>sql_agent · sql_agent_hitl"]
    G1 --> L2["LangGraph SDK<br/>StateGraph · astream · InMemorySaver"]
    A1 --> L2
    L2 -->|"检查点 + 记忆存储"| M1["内存线程状态"]

    style A1 fill:#dcfce7,stroke:#16a34a,color:#111
    style G1 fill:#fee2e2,stroke:#dc2626,color:#111
```

### 前端 — 图活动

`src/features/graph-studio/` 以活动 id `graph` 接入 IDE 外壳（工作流图标，位于
`useLayout.tsx` / `ActivityBar.tsx` 中 **Workflows** 之后，路由为 `App.tsx` 中的
`/#/graph`）：

| 模块 | 用途 |
| ------ | ----- |
| `GraphStudioPage.tsx` | 布局外壳：画布 + 可调宽度的右侧栏（两者之间有拖拽手柄） |
| `GraphStudioSidebar.tsx` | 助手选择器 + **数据库选择器** + 线程列表（+ 新建线程按钮） |
| `GraphCanvas.tsx` | ReactFlow 画布：BFS 分层自动布局、条件边（`#e8a33d`）、运行路径高亮、方向切换、**点击节点查看详情弹窗** |
| `RunConsole.tsx` | "测试运行"提示 → SSE 流 |
| `Inspector.tsx` | messages / state / raw 标签页 + 追问聊天输入（线程感知） |
| `ChatInput.tsx` | 追问输入——运行中发送按钮变为**停止**（中断） |
| `studioStore.ts` | `useSyncExternalStore` 存储（助手、线程、实时消息、运行路径、方向、激活节点、数据库选择） |
| `stream.ts` / `api.ts` | SSE 解析器 + 功能本地类型化客户端（`hasMessagesInput` schema 检测） |

画布是**通用的**：任何被内省的图都用同样的分层布局渲染（从 `__start__` 做 BFS），
因此 React 端无需为每个智能体编写代码。

---

## 14. 技能与中间件流水线

**技能**给智能体提供模块化、上下文感知的能力。流水线采用**渐进式披露**：智能体拿到一份
*目录*（名称 + 描述 + 路径），并通过其 `read_file` 工具按需读取每个 `SKILL.md` 正文——
因此在真正需要某个技能之前，上下文窗口始终很小。

```mermaid
flowchart LR
    S1["技能路由 (api/skills)<br/>CRUD + 预检"] --> S2["core/skills/registry.py<br/>+ matcher.py + sync.py"]
    S2 --> S3["暂存：<br/>把已配置技能复制到<br/><workspace>/skills/"]
    S3 --> S4["SkillsMiddleware<br/>（deepagents，目录在提示词中）"]
    S4 --> S5["智能体按需读取 SKILL.md<br/>通过 read_file（FilesystemBackend）"]
```

**DeepAgent 内部的中间件栈**（按装配顺序）：

| 中间件 | 来源 | 效果 |
| ------ | ---- | ---- |
| MemoryMiddleware | deepagents SDK | 把项目 `AGENTS.md` 载入系统提示词（对 Anthropic 做缓存控制） |
| FilesystemMiddleware | deepagents SDK | 文件读写限定在任务工作区 |
| SummarizationMiddleware | deepagents SDK | 超过 token 阈值后自动压缩历史（langchain ≥1.3.14 把 kind `"token"` 改名为 `"tokens"`） |
| SubAgentMiddleware | 装配时添加 | 提供 `task` 工具，让主智能体可以委派给子智能体 |
| 自定义中间件 | `core/middleware/deep.py` | 自包含的 TodoListMiddleware 等（带守卫的导入保持 SDK 兼容） |
| 沙箱 | 可选 `LocalShellBackend` | 在工作区内通过 `execute` 工具执行 shell/python |

---

## 15. 导出子系统（发布）

这就是"在 IDE 中开发、随处运行"的故事。导出逻辑位于两处：**独立代码生成**端点 `download_agent_code()`（在 `api/agents/deep_agents.py` 中，将工具源码、技能与 LLM 初始化内联为单个可运行 `.py`），以及 **`.langconfig` 包**端点（`/export`、`services/agent_bundle.py` 中的 `build_agent_bundle`/`import_agent_bundle`），用于导入到另一个 LangConfig 实例。

### `download_agent_code()` — 可运行的仓库

生成一个**包含完整独立智能体项目的 zip**：

```
deepagent_export/
├── README.md               # 说明 + 如何运行
├── requirements.txt        # 固定版本的依赖
├── env_example             # API 密钥
├── agent_config.json       # JSON 配置快照
├── main.py                 # CLI 聊天界面：python main.py "query"
├── api_server.py           # 可选 FastAPI 服务器
├── agent/
│   ├── agent.py            # DeepAgent 初始化（create_deep_agent / create_agent）
│   ├── prompts/system_prompt.txt
│   └── tools/custom_tools.py
├── tests/test_agent.py
├── Dockerfile / docker-compose.yml   # 可选
└── ui/ (index.html, chat.js, styles.css)  # 可选聊天 UI
```

### `build_agent_bundle()` — 互换包

导出一个**langconfig bundle**（JSON + 资源），可重新导入到另一个 LangConfig 实例——即
"打包复用"格式。

### 导出路径

```mermaid
flowchart LR
    U1["DeepAgentStudio → 导出 .py"] --> U2["POST /api/deepagents/{id}/export<br/>(或 /code)"]
    U2 --> U3["download_agent_code()<br/>(api/agents/deep_agents.py)"]
    U3 --> U4["生成独立项目<br/>(langchain create_agent + PostgresSaver)"]
    U4 --> U5["下载 zip / backend/outputs/exports/*.py"]
    U5 --> U6["CLI 运行：<br/>uv run python demo2.py \"query\""]

    style U3 fill:#dcfce7,stroke:#16a34a,color:#111
```

生成的 `main.py` 使用与实时后端**相同**的 langchain V1 `create_agent` API——因此你导出的
内容与你之前在 IDE 中测试的行为完全一致。

---

## 16. 数据层 — PostgreSQL 表

`backend/models/` 中的 SQLAlchemy 模型映射到以下表：

| 模型（文件） | 表的用途 |
| ---- | ---- |
| `deep_agent.py`（`DeepAgentTemplate` / `DeepAgentConfig`） | **`deep_agent_templates`** — 普通智能体*和*深度智能体都在这，用 `config.use_deepagents` 区分 |
| `custom_tool.py` | **`custom_tools`** — 用户工具 + 内置种子（`is_builtin=True`） |
| `skill.py` | **`skills`** — 技能目录 |
| `workflow.py`、`workflow_schedule.py`、`workflow_trigger.py` | 工作流 + cron 调度 + 事件触发器 |
| `agent_memory.py` | 长期智能体记忆（pgvector） |
| `conversation_archive.py` | 聊天会话存档 |
| `execution_event.py` | 流式执行事件 |
| `background_task.py` | 后台任务队列 |
| `workspace_file.py`、`file_version.py` | 工作区文件 + 版本历史 |
| `local_model.py`、`model.py`、`search_provider.py`、`settings.py` | 模型/本地模型/搜索供应商/设置配置 |

### 16.1 统一的 `models` 表 — 云模型与本地 LLM 合一

`models` 表是应用可调用的每个模型的单一事实来源。它取代了遗留的硬编码枚举（`constants/models.py`）以及现已移除的 `local_models` 拆分。受管云条目与用户添加的本地条目共享同一套 schema，用 `source` 区分。

**Schema**（`backend/models/model.py`）：

| 列 | 类型 | 说明 |
|--------|------|-------|
| `id` | SERIAL PK | 自增 |
| `model_id` | VARCHAR UNIQUE | 稳定 id，用于 API 调用（如 `deepseek-chat`、`gpt-4o`、`local-ollama-llama3`） |
| `display_name` | VARCHAR | UI 中显示的人类可读名称 |
| `provider` | VARCHAR（有索引） | `openai`、`anthropic`、`google`、`deepseek`、`glm`、`minimax`、`qwen`、`kimi`、`agnes`、`ollama`、`lmstudio`、`vllm`、`litellm`、`custom` |
| `source` | VARCHAR | `'cloud'`（受管）或 `'local'`（用户） |
| `capabilities` | JSONB | `{streaming, tools, structured_output, vision, audio, video, thinking, max_context, ...}` |
| `is_active` | BOOL | 软删除标记 |
| `base_url` | VARCHAR NULL | 仅本地：端点 URL |
| `api_model_name` | VARCHAR NULL | 仅本地：供应商内部名称（如 `llama3.2:latest`） |
| `api_key` | VARCHAR NULL | 仅本地：可选的每模型密钥（很少用——全局密钥在 `settings.api_keys` 中） |
| `is_validated`、`last_validated_at`、`validation_error` | bool/tz/varchar | 仅本地：连接测试结果 |
| `usage_count`、`last_used_at` | int/tz | 用量跟踪 |
| `tags` | JSONB | 分类 |
| `created_at`、`updated_at` | timestamptz | 审计 |

**初始种子流程**（安装后 / 删表之后）：

1. **删表**（彻底重置）：
   ```sql
   DROP TABLE IF EXISTS models CASCADE;
   ```
2. **从 `models/model.py` 重建** — schema 定义在 SQLAlchemy `Model` 类中，以下任选其一：
   - 运行 Alembic 到 head（`alembic upgrade head`）— 迁移首选，
   - 或在 Python shell 中执行 `Base.metadata.create_all(bind=engine, tables=[Model.__table__])`，
   - 或应用 `/tmp/create_models.sql` 中的独立 SQL（与模型保持同步）。
3. **从规范 CSV 播种** — `/tmp/models_with_url.csv` 是由 `/tmp/export_models.py` 写出的
   "初始查询"。种子脚本读取它：
   ```bash
   cd backend && DATABASE_URL="postgresql://langconfig:langconfig_dev@localhost:5432/langconfig" \
       .venv/bin/python scripts/seeds/in/seed_models.py
   ```
   这会插入约 28 行云模型（跳过 CSV 中 4 行 ollama 本地条目），`is_active=true` 并附带
   每供应商的默认 `capabilities` JSON。
4. **本地条目**（`source='local'`）**不由脚本播种** — 用户通过 设置 > 本地模型 添加。

**为什么用 CSV 而非硬编码枚举**：模型目录的任何变更（新版 Gemini、新增供应商、价格更新）
只需重新生成 CSV 并重新运行种子即可，无需改动代码。

**读取**走 `GET /api/settings/models`，返回云模型与已验证的本地模型及完整元数据。聊天与
工作流引擎在启动时调用一次。

**供应商→密钥映射**独立于 `models`：云供应商的 API 密钥存放在
`settings.api_keys.{provider}_api_key`（静态加密），解析顺序是 DB 优先、`.env` 兜底。
参见 §16.2。

---
| `user_profile.py` | 用户资料 |
| `audit_log.py` | 审计轨迹 |
| `oauth_token.py`、`presentation_job.py` | OAuth 令牌 + 演示任务 |
| `analysis_chat.py`、`custom_schema.py` | 分析聊天 + 结构化输出 schema |
| `storage_object.py` | **`storage_objects`** — 持久化构件 blob（BYTEA），即"以 DB 为存储"的接缝（阶段 1，§19） |

```mermaid
flowchart TB
    subgraph PG["PostgreSQL 16 + pgvector (:5432)"]
        T1["deep_agent_templates<br/>(普通 + 深度智能体，use_deepagents 标记)"]
        T2["custom_tools · skills"]
        T3["workflows + schedules + triggers"]
        T4["agent_memories (pgvector) · conversation_archives"]
        T5["execution_events · background_tasks · audit_logs"]
        T6["workspace_files · file_versions · local_models · settings · storage_objects"]
    end
    T1 --> T2
    T1 --> T3
    T1 --> T4
    T3 --> T5
    T4 --> T5
```

### 16.4 种子数据原则 — 一次性引导，此后以数据库为准

**不变量：** 种子数据只执行 **一次**（首次安装 / 显式 `--replace`）。此后
PostgreSQL 数据库是用户状态的唯一真源 —— 智能体、工具、API 密钥、设置 ——
运行时全部从数据库实时读取。种子数据是 **安装/迁移工具，绝不进入运行时路径**。

**一次性种子数据：**

| 种子 | 入口 | 行为 |
|------|------|------|
| 设置文档 | `core/settings/seed.py::ensure_settings_seeded()`（每次启动执行） | 仅对 **没有行的命名空间** 写入默认文档（`row_exists`）；已存在的文档绝不被改动 |
| 内置工具 | `scripts/seeds/in/seed_builtin_tools.py`（仅安装时） | 创建缺失的 `custom_tools` 行；已存在的内置行 **仅在显式 `--refresh` 时更新**；同 id 的用户工具行绝不动 |
| 智能体 / 工具 dump | `scripts/seeds/in/seed_all.py`（仅安装时，`--replace` 可选） | 仅当表 **为空**（`count == 0`）时播种；`--replace` 会先清空再恢复 dump —— 已注明为破坏性操作 |

`main.py` 启动时**只**运行 `ensure_settings_seeded()`（幂等）—— 运行时不做
任何智能体/工具播种。

**首次安装后，数据库为准，运行时实时读取：**

- **智能体** — `deep_agent_templates.config` JSON 为真源；每次对话都从
  存储的配置重建智能体（提示词、工具、技能、子智能体、中间件、插件）。
  用户修改持久化；无需再播种。
- **API 密钥** — 单表：`models` 设置文档的 `api_keys` 字段（Fernet 加密，
  §16.2）。工具每次调用都通过 `config.get_api_key_from_db` **实时读取**
  （`tavily_search`、`web_search` 的 provider 路径、LLM `resolve_model`）。
  设置里临时保存的改动下一次调用即生效 —— 无需重播种、无需重启。
  密钥从不属于种子数据。
- **内置工具** — **优先从数据库加载**（`ToolLoader._load_builtin_from_db`）：
  行内自包含代码为准；种子源（`tools/native_impl.py`）只在播种/刷新时提供。
  工具代码运行时从数据库读密钥，因此用户改密钥无需刷新工具。

```
首次安装  =  seed_all / seed_builtin_tools / ensure_settings_seeded  （一次）
此后      =  数据库为准
运行时    =  智能体从 deep_agent_templates.config 构建
             工具从 custom_tools 行加载（DB 优先）
             API 密钥每次调用从 models.api_keys 实时读取
             设置按命名空间从 settings_documents 读取
```

**运维注意：**

- `seed_all.py --replace` 会清空 `deep_agent_templates` / `custom_tools` ——
  这是刻意的强制重载，不要随意运行；它会丢弃用户修改。
- `step_deep_agents` 的补全分支在表内行数 **少于 dump** 时会重载智能体 dump
  （部分安装场景）。若你有意删除智能体，再次运行 `seed_all` 时需注意该分支
  可能把标准集合加回来；要完全贯彻“用户修改优先”，该分支应仅在表为空时触发
  （见 `scripts/seeds/in/seed_all.py`）。
- 要把 `tools/native_impl.py` 的代码修复传播到已有内置行，请一次性运行
  `seed_builtin_tools.py --refresh`（安装步骤）—— 运行时永不重播种。

---

## 17. 请求生命周期 — 时序图

### DeepAgent 聊天（SSE）

```mermaid
sequenceDiagram
    participant UI as React 聊天页
    participant API as api/chat/messages.py<br/>POST /api/chat/message/stream
    participant F as DeepAgentFactory
    participant DA as deepagents SDK
    participant LG as LangGraph graph
    participant DB as PostgreSQL

    UI->>API: POST /message/stream (agent_id, message)
    API->>F: create_deep_agent(config, project_id, task_id)
    F->>DA: create_deep_agent(...) with middleware/skills
    DA->>LG: 编译后的 CompiledStateGraph
    API->>LG: astream_events(input)
    loop 工具调用 / tokens
        LG-->>API: 智能体事件 (tool_call, tool_result, tokens)
        API-->>UI: SSE 分块
    end
    LG-->>DB: 检查点保存 (state + messages)
    LG-->>API: 最终回答
    API-->>UI: SSE [done]
```

### 工作流执行

```mermaid
sequenceDiagram
    participant UI as 工作流画布
    participant API as api/workflows/execution.py
    participant ENG as core/workflows/executor
    participant CP as checkpointing/manager
    participant DB as PostgreSQL

    UI->>API: POST /workflows/{id}/execute
    API->>ENG: 从存储的 nodes + edges 构建图
    ENG->>ENG: 分发节点（agent / deepagent / tool / llm）
    ENG->>CP: 每步保存检查点
    CP->>DB: upsert 执行状态
    ENG-->>API: 进度事件
    API-->>UI: SSE /workflows/{id}/events
    UI->>API: GET /workflows/{id}/stream（轮询/流式获取结果）
```

---

## 18. 开发拓扑

两个常驻进程 + 一个数据库，全部由根目录 `.env` 驱动（FastAPI 通过
`backend/config.py` 加载它，因此端口与 API 密钥处处一致）。

```mermaid
flowchart LR
    subgraph FRONT["Vite 开发服务器 (:1421)"]
        F["React 19 应用<br/>npm run dev"]
    end
    subgraph BACK["uvicorn (:8765, reload)"]
        B["FastAPI 应用<br/>uv run python main.py"]
    end
    subgraph DATA["PostgreSQL 16 (:5432)"]
        P[("pgvector + Alembic 迁移")]
    end
    F -->|"HTTP / SSE<br/>localhost:8765"| B
    B -->|"SQLAlchemy<br/>DATABASE_URL（根 .env）"| P

    style B fill:#dcfce7,stroke:#16a34a,color:#111
    style P fill:#fee2e2,stroke:#dc2626,color:#111
```

**坑：** 可能存在陈旧的第二个 Postgres 容器（`langconfig-postgres`）——应用
总是加载根 `.env`（→ `:5432`，已完全迁移）。独立脚本必须在导入
`db.database` **之前**加载根 `.env`——从 `backend/` 目录看是 `load_dotenv("../.env")`，
更好的做法是从 `__file__` 推导路径（参见 `tools/seed_builtin_tools.py`）——否则会漏掉
`.env` 并报出幽灵般的 `UndefinedColumn` 错误。

**坑（图工程工作室）：** `backend/langgraph/*.py` 模块用 `init_chat_model(...)` 构建聊天
模型，它会在导入时校验 `DEEPSEEK_API_KEY`。`start.sh` 会取消 shell 导出的供应商密钥，
因此该密钥必须存在于根 `.env` 中——否则 `/api/graph-studio` 内省端点会以 pydantic
`ValidationError`（HTTP 500）失败。

---

## 19. 存储策略：以数据库作为永久存储（面向企业）

> **状态（2026-08-03）：** 存储策略的四个阶段已全部交付——阶段 1（抽象层，提交 `3aa794d`）、
> 阶段 2（写穿接线）、阶段 3（deepagents `DbBackend`，`STORAGE_MODE=db` 下技能 100% 由 DB
> 管理）、阶段 4（FS→DB 迁移工具）。`storage_objects`、`services/storage/` 与 `STORAGE_MODE`
> 均已上线；在运行 `uv run python -m tools.migrate_storage` 之后切换 `STORAGE_MODE=db`。

### 愿景

文件系统是*个人/本地开发*的默认。对**企业**而言，所有构件——技能、工作区文件、上传的
文档、输出、版本——的持久家园是**数据库**，大 blob 用**对象存储**（S3 / MinIO /
腾讯 COS / 阿里 OSS / R2）。文件系统只保留真正**瞬态**的内容：任务临时文件、暂存目录、
导出 zip、本地沙箱。

**规则：数据库保存持久构件；文件系统保存瞬时工作文件。**

### Blob 存储 vs 对象存储 — 如何抉择

并非二选一——而是按大小阈值 + `STORAGE_MODE` 选择的**混合**方案：

| 存储 | 最适合 | 权衡 |
| ---- | ---- | ---- |
| Postgres BYTEA（`storage_objects`） | 技能、配置、小构件（< ~1 MB） | 事务性、零基础设施、同一份备份——会让 DB 膨胀，不适合大文件/媒体 |
| 对象存储（S3 / MinIO / COS / OSS / R2） | 上传的 RAG 文档、图片、大输出、导出 | 专为大 blob + 流式而生，便宜、多节点——需要一个服务/供应商 |

**企业模式：** DB 行 = *元数据 + 对象键*；*blob* 存于对象存储。`StorageBackend` 接口让
物理存储选择由配置驱动，因此同一批调用方在每个模式下都不需要改动。

### 单一接缝：`StorageBackend`

平台中的每个写入方都只面对一个以对象寻址的接口，因此物理后端可随部署切换
（`local` / `db` / `s3`）而无需触碰任何调用方。

```mermaid
flowchart LR
    subgraph Callers["写入方"]
        W1["FileStorage<br/>上传的 RAG 文档"]
        W2["WorkspaceManager<br/>智能体输出"]
        W3["技能<br/>SKILL.md 内容"]
    end
    W1 --> IF["StorageBackend<br/>save(key, content) · read(key)<br/>exists · delete · list · stat"]
    W2 --> IF
    W3 --> IF
    IF --> L1["LocalStorageBackend<br/>磁盘（个人默认）"]
    IF --> L2["DbStorageBackend<br/>Postgres BYTEA · 小负载"]
    IF --> L3["ObjectStorageBackend<br/>S3 / COS / OSS · 大 blob"]
    L1 --> T1["STORAGE_MODE=local"]
    L2 --> T2["STORAGE_MODE=db"]
    L3 --> T3["STORAGE_MODE=s3"]
```

### 现已具备的基础

| 资产 | 今日的 DB 基础 | 本设计补上的缺口 |
| ---- | ---- | ---- |
| 工作区文件 | `workspace_files`（元数据、标签、agent/workflow/task 上下文）+ `file_versions` | 内容在磁盘上，DB 里只有路径 → `storage_objects` BYTEA 行 / 对象存储 |
| 技能 | `skills` 表已把 SKILL.md 正文放在 `instructions` 中 | `backend/skills/**/SKILL.md` 的 git 镜像变为可选 |
| 上传的文档 | `FileStorage` 服务 | 硬编码指向 `./data/documents/` → 改走后端 |
| 智能体文件工具 | deepagents `BackendProtocol` 可插拔（`ls/read/write/glob/grep/download_files`） | 一个 `DbBackend` 把 `/skills/<name>/SKILL.md` 映射为 DB 行 |
| 运行时开关 | `config.py` pydantic 设置（根 `.env`） | 新增 `STORAGE_MODE` 环境键（`local` \| `db` \| `s3`） |

### 为什么这与 deepagents 天然契合

`SkillsMiddleware` 只调用 `BackendProtocol` 上的 `backend.ls()` + `backend.download_files()`——
它从不自己碰磁盘。因此该协议的一个 DB 实现就能做到**技能 100% 在 DB 中**，同时保留渐进式
披露（系统提示词中的元数据目录、按需读取 SKILL.md 正文），而智能体的 `read_file` 工具也能
透明地对着 DB 工作。

### 分阶段落地与当前状态

1. **阶段 1 — 抽象层 ✅ 已完成（提交 `3aa794d`）**
   - `backend/services/storage/` — `base.py`（`StorageBackend` ABC + `StorageStat`）、
     `local.py`（`LocalStorageBackend`，键清理）、`db.py`（`DbStorageBackend`，BYTEA）、
     `__init__.py`（`get_storage()` 工厂，带缓存）
   - `backend/models/storage_object.py` — `storage_objects` 表（唯一 `key`、BYTEA
     `content`、`size_bytes`、`mime_type`、时间戳）
   - Alembic `018_add_storage_objects`（幂等的存在性检查）— **仅 schema，不动数据**
   - `config.py` — `storage_mode`（默认 `local`）+ `storage_base_dir`（`./data/storage`）
   - 测试：`backend/tests/test_storage.py` — 5 项通过（两个后端往返、不安全键拒绝、
     缺失键抛错、单行 upsert）
   - 实机验证：工厂返回 `LocalStorageBackend`；`DbStorageBackend` 在 Postgres `:5432` 上
     save/read/stat/list/delete 往返成功
2. **阶段 2 — 接线 ✅ 已完成** — 把 `FileStorage`（上传的文档）、`WorkspaceManager`
   （智能体输出）和技能同步（`db_row_to_fs`）都改走 `get_storage()`；保持 `local` 为默认，
   因此在 `STORAGE_MODE=db` 之前行为不变。实现为**写穿**：在 `STORAGE_MODE=db` 下每个写入方
   额外持久化到 `storage_objects` — 键为 `documents/<rel>`（`FileStorage.save_file`/
   `delete_file`）、`outputs/<rel>`（`WorkspaceManager.persist_output`，由智能体 write/edit
   文件工具调用）、`skills/<type>/<id>/SKILL.md`（`db_row_to_fs`）。磁盘副本仍是消费者
   （RAG、工作区读取方）的操作存储；存储失败仅记录日志且不致命（只是持久性副本）。
   `local` 模式严格无操作。
3. **阶段 3 — deepagents `DbBackend` ✅ 已完成** — `services/storage/db_backend.py`
   以 `get_storage()` 为底层实现 `BackendProtocol`（`ls`/`read`/`write`/`edit`/`delete`/
   `glob`/`grep`/`download_files`/`upload_files`）；虚拟路径 `/skills/<type>/<id>/SKILL.md`
   与存储键 1:1 映射（可选的 `storage_prefix` 在路由到 `CompositeBackend` 之后重新挂上命名空间）。
   在 `STORAGE_MODE=db` 下，`DeepAgentFactory` 现在把每个已装备的技能持久化到其规范键下，
   并通过 `DbBackend` 提供服务（技能 100% 由 DB 管理，无需 FS 暂存），保留渐进式披露
   （目录 + 按需 `read`）。沙箱启用时，`CompositeBackend` 把 `/skills/` 路由到存储并让
   `execute` 留在沙箱内。`local` 模式保持遗留磁盘暂存不变。测试：
   `backend/tests/test_db_backend.py`（10 个用例，含递归删除、glob `**`、grep 截断、
   遍历拒绝、前缀映射）。
4. **阶段 4 — 迁移工具 ✅ 已完成** — `backend/tools/migrate_storage.py`，一个一次性作业，
   用于切换：把现有 FS 构件复制进 `storage_objects`，键与阶段 2 写穿一致
   （`documents/<rel>` 来自 `FileStorage`、`outputs/<rel>` 来自 `WorkspaceManager`、
   `skills/<type>/<id>/SKILL.md` 从 `skills` 表规范渲染）。幂等（已存在的键跳过；
   `--force` 覆盖）、`--dry-run` 预览、强制 `STORAGE_MODE=db`，并在导入 `db.database`
   之前加载根 `.env`（§18 的坑）。已在 `:5432` 上实机验证：1,301 个构件完成迁移并通过
   内容一致抽查，重跑时全部 1,301 个跳过。运行：`uv run python -m tools.migrate_storage [--force] [--dry-run]`

---

## 快速参考 — 各处所在

| 问题 | 答案 |
| ---- | ---- |
| 谁构建普通智能体？ | `core/agents/factory/assembly.py` → `AgentFactory.create_agent` |
| 谁构建 DeepAgent？ | `services/deepagent_factory/assembly.py` → `DeepAgentFactory.create_deep_agent` |
| `deep_agents.py` 是什么？ | REST 控制器（CRUD + 提示词预览 + 导出）— 不是构建器 |
| 导出代码在哪？ | `api/agents/deep_agents.py`（`download_agent_code`/`export_deepagent`）+ `services/agent_bundle.py` |
| 智能体持久化在哪？ | `deep_agent_templates` 表（标记 `config.use_deepagents`） |
| 聊天如何流式？ | `POST /api/chat/message/stream` → 经 `useChatStreaming` / `streamChatEvents.ts` 走 SSE |
| 工作流如何运行？ | `core/workflows/` 执行器 + Postgres 检查点，经 SSE 流式 |
| 图工程工作室如何工作？ | 图活动（`/#/graph`）→ `api/graph_studio/` 原生托管 `backend/langgraph/*.py`（无需 `langgraph dev` 服务器）；线程与运行在内存中 |
| 代码图在哪？ | `backend/langgraph/*.py` — 由 `api/graph_studio/routes.py` 惰性导入（`_load_compiled`） |
| 如何切换智能体的数据库？ | 工作室数据库下拉 → `POST /databases/select`（运行时 `_DB_OVERRIDE`）；或 `.env` 中的 `SQL_*` 环境变量 / `SQL_DATABASE_URL` + 重启 |
| 如何停止一次运行？ | 聊天**停止**按钮 → `POST /threads/{id}/runs/cancel`（下一个 SSE 事件边界生效） |
| 导出文件落在哪？ | `backend/outputs/exports/*.py`（或从 `/export` 下载 zip） |
| 构件持久化在哪？ | `services/storage/` 的 `StorageBackend` 接缝 — `local`（磁盘）\| `db`（Postgres BYTEA）\| `s3`（对象存储） |