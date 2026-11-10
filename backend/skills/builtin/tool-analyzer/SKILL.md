---
name: Tool Analyzer（工具分析器）
description: >-
  分析 Python 工具文件，产出结构化文档：total_tools（不同工具函数/对象的数量）、
  tool_categories（按 web、filesystem、memory、reasoning、delegation、data_analysis、skills 分组），
  以及 common_patterns（错误处理、命名/别名、注册表、异步模式、兜底、安全、版本化）。
version: 1.0.0
author: AI Generated (Reflection Loop)
tags:
- analysis
- tools
- documentation
- python
triggers:
- 被要求分析工具结构时
- 被要求为工具编写文档时
lang: zh
translated: machine
source: backend/skills/en-originals/tool-analyzer/SKILL.md
---

## Instructions（指令）

1. 从工具目录读取目标 Python 文件。
2. 分析代码，产出一份包含以下三个部分的结果：

### total_tools（工具总数）

统计文件里每一个不同的工具函数/对象。包括：
- 所有用 @tool 装饰的异步/同步函数
- 所有用 StructuredTool.from_function() 创建的 StructuredTool 对象
- 排除纯辅助/工具性函数（例如 _init_sync_playwright、_yahoo_search_fallback、_record_file_version、_record_file_metadata、_write_file_error_handler —— 这些不是工具）
- 排除向后兼容的别名字变量（file_read、file_write、file_list）—— 它们只是引用
- 用一个纯整数给出数量

### tool_categories（工具分类）

按以下依据给工具分组：
- 文件里的小节标题（例如 "Web Search Tools"、"File System Tools"、"Memory Tools" 等）
- TOOL_REGISTRY 条目里的 'category' 字段
- 列出每个分类，含：分类名、该分类下的工具名清单、每类的数量

### common_patterns（常见模式）

识别并记录在这些工具里反复出现的结构性或设计性模式。重点看代码层面的模式，例如：
- **工具定义模式**：@tool 装饰器 vs StructuredTool.from_function()
- **命名/别名模式**：工具名如何被映射（TOOL_NAME_MAP）、向后兼容的别名
- **错误处理模式**：try/except 包装、自定义错误处理器、结构化错误消息
- **异步模式**：异步 vs 同步工具、惰性初始化、Playwright 异步处理
- **注册表模式**：TOOL_REGISTRY 作为界面元数据的唯一来源
- **兜底模式**：主方案失败时怎么办（例如 DDG 的 Yahoo 兜底、兜底用的 memory 桩）
- **安全模式**：write_file 里的路径清洗、工作区边界检查
- **版本化模式**：文件版本追踪、基于 diff 的追踪

对每个模式，给出：模式名、描述，以及它用在哪些工具里。

3. 以一份干净的类 JSON 结构返回结果。

## Output Format（输出格式）

```
{
  "total_tools": <integer>,
  "tool_categories": [
    {"category": "web", "tools": [...], "count": <int>},
    ...
  ],
  "common_patterns": [
    {"pattern": "...", "description": "...", "used_in": ["tool1", "tool2", ...]},
    ...
  ]
}
```
