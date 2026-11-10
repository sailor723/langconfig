---
name: "langchain-agents（LangChain 智能体）"
lang: zh
translated: machine
source: backend/skills/en-originals/langchain-agents/SKILL.md
description: >-
  搭建 LangChain 智能体的专家指南：工具绑定、记忆与配置都要摆对。在 LangConfig 里创建智能体、配置模型、
  或接好工具集成时使用。
tags: [langchain, agents, llm, tools, memory, rag]
triggers:
  - "用户提到 LangChain 时"
  - "用户提到智能体时"
  - "用户提到 LLM 配置时"
  - "用户提到工具绑定时"
  - "创建新智能体时"
allowed-tools: [filesystem, shell, python]
author: LangConfig
---

你是 LangChain 开发专家，帮助用户在 LangConfig 里搭建智能体。以下准则来自 LangChain 官方文档与 LangConfig 的既有模式。

### LangChain 核心概念

LangChain 是构建 LLM 应用的框架，关键组件如下：

1. **模型** —— 语言模型（ChatOpenAI、ChatAnthropic、ChatGoogleGenerativeAI）
2. **消息** —— 结构化的对话数据（HumanMessage、AIMessage、SystemMessage）
3. **工具** —— 智能体可调用、用于与外部系统交互的函数
4. **记忆** —— 在单次对话内与跨对话持久保存的上下文
5. **检索器** —— 访问外部知识的 RAG 系统

### LangConfig 中的智能体配置

#### 支持的模型（2025 年 12 月）

```python
# OpenAI
"gpt-5.1"              # Latest GPT-5 series
"gpt-4o", "gpt-4o-mini" # GPT-4o series

# Anthropic Claude 4.5
"claude-opus-4-5-20250514"    # Most capable
"claude-sonnet-4-5-20250929"  # Balanced
"claude-haiku-4-5-20251015"   # Fast/cheap (default)

# Google Gemini
"gemini-3-pro-preview"  # Gemini 3
"gemini-2.5-flash"      # Gemini 2.5
```

#### 智能体配置结构

```json
{
  "name": "Research Agent",
  "model": "claude-sonnet-4-5-20250929",
  "temperature": 0.7,
  "max_tokens": 8192,
  "system_prompt": "You are a research assistant...",
  "native_tools": ["web_search", "web_fetch", "filesystem"],
  "enable_memory": true,
  "enable_rag": false,
  "timeout_seconds": 300,
  "max_retries": 3
}
```

#### 温度取值指南

| 场景 | 温度 | 理由 |
|----------|-------------|-----------|
| 代码生成 | 0.0 - 0.3 | 确定、精确 |
| 分析 / 研究 | 0.3 - 0.5 | 准确度均衡 |
| 创意写作 | 0.7 - 1.0 | 更多变化 |
| 头脑风暴 | 1.0 - 1.5 | 创造力拉满 |

### 系统提示词最佳实践

#### 结构
```
# Role Definition
You are [specific role] specialized in [domain].

# Core Responsibilities
Your main tasks are:
1. [Primary task]
2. [Secondary task]
3. [Supporting task]

# Constraints
- [Limitation 1]
- [Limitation 2]

# Output Format
When responding, always:
- [Format requirement 1]
- [Format requirement 2]
```

#### 示例：代码评审智能体
```
You are an expert code reviewer specializing in Python and TypeScript.

Your responsibilities:
1. Identify bugs, security issues, and performance problems
2. Suggest improvements following best practices
3. Ensure code follows project style guidelines

Constraints:
- Focus only on the code provided
- Don't rewrite entire files unless asked
- Prioritize critical issues over style nits

Output format:
- List issues by severity (Critical, Warning, Info)
- Include line numbers for each issue
- Provide specific fix suggestions
```

### 工具配置

#### LangConfig 里可用的原生工具

```python
# File System Tools
"filesystem"           # Read, write, list files
"grep"                 # Search file contents

# Web Tools
"web_search"           # Search the internet
"web_fetch"            # Fetch and parse web pages

# Code Execution
"python"               # Execute Python code
"shell"                # Run shell commands (sandboxed)

# Data Tools
"calculator"           # Mathematical operations
"json_parser"          # Parse and query JSON
```

#### 工具选择指南

| 智能体用途 | 推荐工具 |
|---------------|-------------------|
| 研究 | web_search, web_fetch, filesystem |
| 编码助手 | filesystem, python, shell, grep |
| 数据分析 | python, calculator, filesystem |
| 内容写作 | web_search, filesystem |
| DevOps | shell, filesystem, web_fetch |

### 记忆配置

#### 短期记忆（会话内）
- 由 LangGraph 的检查点机制自动管理
- 在一次工作流执行期间持续存在
- 消息窗口可配置

#### 长期记忆（跨会话）
```json
{
  "enable_memory": true,
  "memory_config": {
    "type": "vector",
    "namespace": "agent_memories",
    "top_k": 5
  }
}
```

### RAG 集成

`enable_rag` 为 true 时，智能体可以访问项目文档：

```json
{
  "enable_rag": true,
  "rag_config": {
    "similarity_threshold": 0.7,
    "max_documents": 5,
    "rerank": true
  }
}
```

### 智能体模式

#### 1. 单一用途智能体
最适合聚焦的任务：
```json
{
  "name": "SQL Generator",
  "model": "claude-haiku-4-5-20251015",
  "temperature": 0.2,
  "system_prompt": "You are a SQL expert. Generate only valid SQL queries.",
  "native_tools": []
}
```

#### 2. 使用工具的智能体
适合需要外部数据的任务：
```json
{
  "name": "Research Agent",
  "model": "claude-sonnet-4-5-20250929",
  "temperature": 0.5,
  "system_prompt": "Research topics thoroughly using available tools.",
  "native_tools": ["web_search", "web_fetch", "filesystem"]
}
```

#### 3. 编码智能体
适合开发任务：
```json
{
  "name": "Code Assistant",
  "model": "claude-sonnet-4-5-20250929",
  "temperature": 0.3,
  "system_prompt": "Help with coding tasks. Write clean, tested code.",
  "native_tools": ["filesystem", "python", "shell", "grep"]
}
```

### 调试智能体问题

#### 常见问题

1. **智能体无限循环**
   - 在系统提示词里补上停止条件
   - 设置 `max_retries` 与 `recursion_limit`
   - 检查工具是否返回了有用的结果

2. **智能体不调用工具**
   - 确认工具已在 `native_tools` 列表里
   - 在系统提示词里明确写出该用哪些工具
   - 检查工具权限

3. **回答前后不一致**
   - 调低温度，换取更多确定性
   - 系统提示词写得更具体
   - 改用结构化输出格式

4. **智能体太慢**
   - 换更快的模型（用 haiku 而不是 opus）
   - 降低 `max_tokens`
   - 精简系统提示词
