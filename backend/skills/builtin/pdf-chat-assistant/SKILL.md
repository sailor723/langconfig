---
name: PDF Chat Assistant（PDF 对话助手）
description: >-
  搜索并阅读项目文档（PDF、MD、DOCX、PPT、TXT）。使用 GraphIndex 的无向量 RAG。
version: 1.0.0
author: User
tags:
- document
- pdf
- chat
- rag
- search
triggers:
- 搜索文档
- 查找文档
- 阅读 PDF
- 文档里说了什么
- PDF 内容
- graphindex
- 上传 PDF
- 给我看看这份文档
- 查找报告
- 搜索知识库
lang: zh
translated: machine
source: backend/skills/en-originals/pdf-chat-assistant/SKILL.md
---

## Instructions（指令）

# PDF 对话助手

当用户问起某份文档、报告、文件，或者想找某个主题时：

## 工作流
1. 首先调用 graphindex_search(query)，用相关关键词搜索项目文档
2. 如果找到结果，调用 graphindex_load(context_doc_id) 读取完整内容
3. 基于文档内容作答
4. 只有当 graphindex_search 返回空结果时，才建议上传文档

## 关键规则
- 绝不在搜索知识库之前就要求用户上传文档
- 项目中已经有通过 graphindex 建立索引的文档可用
- 上传发生时，文档内容会以 [PDF Content: "filename.pdf"] 的形式出现在对话中——直接读取它
- 如果用户在对话中上传了 PDF，先做摘要，再回答问题

## 可用工具
- graphindex_search(query)：按关键词搜索项目文档，返回匹配的文档 ID。
- graphindex_load(context_doc_id)：按 ID 加载完整文档内容，返回完整文本。
