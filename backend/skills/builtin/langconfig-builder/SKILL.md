---
name: "langconfig-builder（LangConfig 构建器）"
lang: zh
translated: machine
source: backend/skills/en-originals/langconfig-builder/SKILL.md
description: >-
  在 LangConfig 里构建智能体与工作流的完整指南。当用户需要配置节点、连接智能体、设置工具，或在
  LangConfig 内设计多智能体系统时使用。
tags: [langconfig, builder, configuration, deep-agents, workflows, tools]
triggers:
  - "当用户提到 LangConfig 时"
  - "当用户想构建一个工作流时"
  - "当用户需要配置方面的帮助时"
  - "当用户提到 deep agent 时"
  - "当设计智能体系统时"
allowed-tools: [filesystem, shell, python]
author: LangConfig
---

你是 LangConfig 的资深架构师，帮用户搭出成套的 AI 智能体系统。LangConfig 是一个可视化平台，用来构建
LangChain 智能体与 LangGraph 工作流，每条配置都在你手上。

### LangConfig 平台概览

LangConfig 提供：
- **可视化工作流构建器** - 拖拽式的 LangGraph 画布
- **智能体配置** - 完全掌控模型、提示词、工具
- **Deep Agents** - 带子智能体的嵌套智能体层级
- **原生工具** - 内置文件系统、网络、代码执行工具
- **RAG 集成** - 由 pgvector 驱动的知识库
- **实时监控** - 执行过程的实时跟踪与调试

### 构建智能体

#### 智能体配置字段

| 字段 | 类型 | 说明 |
|-------|------|-------------|
| `name` | string | 智能体的显示名称 |
| `model` | string | LLM 模型 ID（见支持的模型） |
| `temperature` | float | 0.0-2.0，控制输出的随机程度 |
| `max_tokens` | int | 回复的最大长度 |
| `system_prompt` | string | 智能体的指令与人设 |
| `native_tools` | string[] | 要启用的工具名列表 |
| `enable_memory` | bool | 开启跨会话记忆 |
| `enable_rag` | bool | 开启文档检索 |
| `timeout_seconds` | int | 最长执行时间 |
| `max_retries` | int | 失败时的重试次数 |

#### 完整的智能体配置示例

```json
{
  "name": "Research Assistant",
  "model": "claude-sonnet-4-5-20250929",
  "temperature": 0.5,
  "max_tokens": 8192,
  "system_prompt": "You are a thorough research assistant. When given a topic:\n1. Search for relevant information\n2. Verify facts from multiple sources\n3. Synthesize findings into clear summaries\n\nAlways cite your sources.",
  "native_tools": ["web_search", "web_fetch", "filesystem"],
  "enable_memory": true,
  "enable_rag": false,
  "timeout_seconds": 300,
  "max_retries": 3,
  "recursion_limit": 50
}
```

### Deep Agents（进阶）

Deep Agents 支持带专职子智能体的层级式智能体结构：

#### Deep Agent 配置

```json
{
  "name": "Project Manager",
  "model": "claude-opus-4-5-20250514",
  "use_deepagents": true,
  "subagents": [
    {
      "name": "researcher",
      "type": "dictionary",
      "description": "Handles research tasks",
      "model": "claude-sonnet-4-5-20250929",
      "system_prompt": "You are a research specialist.",
      "tools": ["web_search", "web_fetch"]
    },
    {
      "name": "coder",
      "type": "dictionary",
      "description": "Handles coding tasks",
      "model": "claude-sonnet-4-5-20250929",
      "system_prompt": "You are a coding specialist.",
      "tools": ["filesystem", "python", "shell"]
    },
    {
      "name": "writer",
      "type": "dictionary",
      "description": "Handles writing tasks",
      "model": "claude-haiku-4-5-20251015",
      "system_prompt": "You are a writing specialist.",
      "tools": ["filesystem"]
    }
  ]
}
```

#### 子智能体类型

1. **Dictionary 子智能体** - 带工具的简单智能体
   ```json
   {
     "type": "dictionary",
     "name": "specialist",
     "tools": ["tool1", "tool2"]
   }
   ```

2. **Compiled 子智能体** - 引用已有工作流
   ```json
   {
     "type": "compiled",
     "name": "complex_task",
     "workflow_id": 42
   }
   ```

### 构建工作流

#### 节点类型参考

##### AGENT_NODE
带 LLM 智能体的标准处理节点：
- 拥有完整的智能体配置
- 可以使用工具
- 输出写入消息历史

##### CONDITIONAL_NODE
按条件路由：
```
Condition syntax:
- "'keyword' in messages[-1].content"
- "state.get('score', 0) > 0.8"
- "'ERROR' not in result"
```

##### LOOP_NODE
反复迭代，直到条件满足：
- `max_iterations`：安全上限
- `exit_condition`：何时停止
- 记录迭代次数

##### OUTPUT_NODE
终止工作流：
- 格式化最终输出
- 可以转换结果

##### CHECKPOINT_NODE
保存状态以便恢复：
- 具名检查点
- 支持暂停/恢复

##### APPROVAL_NODE
人在回路：
- 暂停等待用户输入
- 批准/拒绝的路由

#### 边类型

1. **默认边** - 总是沿路径前进
2. **条件边** - 按状态路由
3. **循环边** - 返回上一个节点

### 工作流模板

#### 1. 简单问答流水线
```
[START] → [Researcher] → [Output]

Nodes:
- Researcher: web_search, web_fetch tools
- Output: Format markdown response
```

#### 2. 带评审的内容生成
```
[START] → [Writer] → [Reviewer] → [Conditional]
                                      ├── PASS → [Output]
                                      └── REVISE → [Writer]

Nodes:
- Writer: Generate content
- Reviewer: Critique and score
- Conditional: Check if score > 0.8
```

#### 3. 多专家研究
```
[START] → [Supervisor] → [Conditional]
                            ├── research → [Researcher] → [Supervisor]
                            ├── code → [Coder] → [Supervisor]
                            └── done → [Output]

Nodes:
- Supervisor: Delegate and coordinate
- Researcher: Web research specialist
- Coder: Code analysis specialist
```

#### 4. 文档处理流水线
```
[START] → [Loader] → [Analyzer] → [Loop]
                                    ├── continue → [Processor] → [Loop]
                                    └── done → [Aggregator] → [Output]

Nodes:
- Loader: Load documents into context
- Analyzer: Identify sections to process
- Processor: Process each section
- Aggregator: Combine results
```

### 工具配置

#### 可用的原生工具

| 工具 | 用途 | 用法示例 |
|------|---------|-------------|
| `web_search` | 搜索互联网 | 研究课题 |
| `web_fetch` | 抓取网页 | 阅读文档 |
| `filesystem` | 读写文件 | 代码编辑 |
| `python` | 执行 Python | 数据分析 |
| `shell` | 运行命令 | DevOps 任务 |
| `grep` | 搜索文件 | 查找代码模式 |
| `calculator` | 数学运算 | 各类计算 |

#### 工具选择指引

```
Research Agent:
  → web_search, web_fetch

Code Assistant:
  → filesystem, python, shell, grep

Data Analyst:
  → python, filesystem, calculator

Content Writer:
  → web_search, filesystem

DevOps Agent:
  → shell, filesystem, web_fetch
```

### RAG（知识库）集成

#### 为智能体启用 RAG

```json
{
  "enable_rag": true,
  "rag_config": {
    "similarity_threshold": 0.7,
    "max_documents": 5,
    "rerank_results": true
  }
}
```

#### 支持的文档类型
- PDF 文件
- Word 文档（.docx）
- 文本文件（.txt、.md）
- 代码文件（各种扩展名）
- 网页（通过 URL）

### 最佳实践

#### 1. 从简开始
- 从单个智能体起步
- 复杂度一点一点加
- 每个节点先单独测通，再连线

#### 2. 选合适的模型
- **Opus**：复杂推理，贵
- **Sonnet**：均衡，推荐的默认选择
- **Haiku**：快、便宜，适合简单任务

#### 3. 写清系统提示词
- 明确写出角色
- 列出具体职责
- 写明输出格式要求
- 补上约束与护栏

#### 4. 处理失败
- 设置合理的超时
- 配置重试逻辑
- 加错误处理节点
- 危险操作之前先打检查点

#### 5. 优化 token 用量
- 简单任务用更小的模型
- 限制上下文窗口
- 打检查点并清空历史
- 提示词写紧凑

### 调试要点

#### 工作流问题
1. 查看浏览器控制台里的报错
2. 在 Results 页签里查看执行事件
3. 确认所有边都连上了
4. 检查条件表达式

#### 智能体问题
1. 先单独测试智能体
2. 确认工具已启用
3. 检查系统提示词是否清楚
4. 复核 token/超时上限

#### 性能问题
1. 换更快的模型（haiku）
2. 减少工具数量
3. 简化提示词
4. 用检查点加缓存
