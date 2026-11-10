---
name: "document-deliverables（文档交付物）"
lang: zh
translated: machine
source: backend/skills/en-originals/document-deliverables/SKILL.md
description: >-
  借助宿主智能体的文件工具，把交付物做成真实文件：写 Markdown，由平台按扩展名渲染出
  .docx / .pdf / .html，用内置的文本抽取回读文档，长任务先规划好。用户要报告、文档、简报，
  或任何需要存成文件的产物时使用。
version: 1.0.0
author: User
tags: [deliverables, documents, docx, pdf, html, file-output, write-file]
triggers:
  - "用户要报告、文档、简报或文件形式的交付物"
  - "输出必须存成 .docx、.pdf、.html 或 .md"
  - "交付物应该落在工作区或 Files 面板里"
  - "在把任何生成的文档写入工作区之前"
compatibility: >-
  需要宿主智能体带着 write_file 与 read_file（filesystem 中间件），需要基于调研的交付物时还要有
  web_search / web_fetch。本技能本身不启用任何工具。
---

这个技能是方法，不是能力。它不授予任何工具——宿主智能体必须已经带着 write_file 与 read_file（filesystem 中间件），需要基于调研的交付物时还要有 web_search / web_fetch。

## 输出契约
用 write_file 写交付物。后端按扩展名渲染，所以写 Markdown，用文件名挑格式：
- .md / .txt / .csv / .json / .py → 原样写入
- .html → 由你的 Markdown 渲染成带样式的 HTML 页面
- .pdf  → 由你的 Markdown 渲染成 PDF
- .docx → 由你的 Markdown 渲染成 Word 文档
标题与各节用 Markdown 标题（#、##、###）——渲染器会把它们变成 Word/PDF 里的真标题。

## 回读文档
上传的文件和之前的交付物都用 read_file 读。.pdf、.docx 与 .pptx 的文本会自动抽取。绝不要起 shell 或自己写解析器。

## 不要做的事
- 不要用代码生成文档（python_execute、bash、python-docx）：那会绕过平台渲染器和 Files 面板。
- 不要拿 save_document 顶替 write_file。
- 不要为了填满文档编造数据——先拿到真实结果；拿不到就说明拿不到。
- 不要写到工作区之外：交付物放 generated/，草稿放 other/，上传目录 upload/ 只读。

## 长任务
多步工作（调研 → 起草 → 导出）先用 write_todos 规划。

## 格式选择
团队要编辑/评审 → .docx · 阅读、打印、对外发送 → .pdf · 发布/嵌入 → .html · 给智能体或流水线消费 → .md。没有指定时，产出 .md 并提供导出选项。

## 要求（由智能体提供，本技能不提供）
write_file、read_file（filesystem 中间件）· web_search/web_fetch（原生工具，需要来源时用）· write_todos（待办中间件）。工具是在智能体上选的，所以同一个技能可以原样挂在调研智能体、报告智能体或文档智能体上。

## Examples（示例）

USER: 生成一份关于 2026 企业 AI Agent 采用情况的简短报告，保存为 .docx
ASST: [调用 write_file(file_path="generated/enterprise-ai-agents-2026.docx", content="# 2026 企业 AI Agent 采用情况\n\n## 摘要\n…")]
      已生成 generated/enterprise-ai-agents-2026.docx（Word）。需要我再导出 PDF 或 HTML 吗？

---

*已对照 LangConfig 的 **origin_research_writer** 智能体（id 210）复核。它自己写的提示词只有
178 个字符，没有带来新东西：技能声明、"用 `write_file`、让扩展名决定格式"、"绝不用 `python_execute` /
`python-docx`" 这几条，这里都已经覆盖了（最后那条属于智能体，不属于技能）。没有替换任何内容。
留在智能体那一侧的：角色、语言偏好、工作区，以及智能体带的是哪个文件工具（这里是 `write_file`，
别处是 `save_document`）。*
