---
name: document-deliverables
description: >-
  Produce deliverables as real files through the host agent's file tools: write markdown and let the
  platform render .docx / .pdf / .html by file extension, read documents back with built-in text
  extraction, and keep long jobs planned. Use when the user asks for a report, document, brief, or
  any artifact that must be saved as a file.
version: 1.0.0
author: User
tags: [deliverables, documents, docx, pdf, html, file-output, write-file]
triggers:
  - "when the user asks for a report, document, brief or file deliverable"
  - "when output must be saved as .docx, .pdf, .html or .md"
  - "when a deliverable should end up in the workspace or Files panel"
  - "before writing any generated document to the workspace"
compatibility: >-
  Requires a host agent carrying write_file and read_file (filesystem middleware), plus web_search /
  web_fetch for research-backed deliverables. This skill itself enables no tools.
---

This skill is know-how, not capability. It grants no tools — the host agent must already carry write_file and read_file (filesystem middleware), plus web_search / web_fetch for research-backed deliverables.

## The output contract
Write deliverables with write_file. The backend renders by extension, so write Markdown and pick the format with the filename:
- .md / .txt / .csv / .json / .py → written verbatim
- .html → styled HTML page rendered from your Markdown
- .pdf  → PDF rendered from your Markdown
- .docx → Word document rendered from your Markdown
Use Markdown headings (#, ##, ###) for title and sections — the renderers turn them into real headings in Word/PDF.

## Reading documents back
Use read_file for uploads and prior deliverables. Text is extracted automatically from .pdf, .docx and .pptx. Never shell out or write your own parser.

## What not to do
- Do not generate documents with code (python_execute, bash, python-docx): it bypasses the platform renderer and the Files panel.
- Do not substitute save_document for write_file.
- Do not invent data to fill a document — gather real results first, and say so if unobtainable.
- Do not write outside the workspace: deliverables in generated/, scratch in other/, uploads read-only in upload/.

## Long jobs
Plan multi-step work (research → draft → export) with write_todos first.

## Format choice
Editable/reviewed by a team → .docx · read/printed/sent externally → .pdf · published/embedded → .html · consumed by an agent or pipeline → .md. If unspecified, produce .md and offer exports.

## Requirements (provided by the agent, not by this skill)
write_file, read_file (filesystem middleware) · web_search/web_fetch (native tools, when sources are needed) · write_todos (to-do middleware). Tools are selected on the agent, so the same skill attaches to a research agent, a reporting agent, or a document agent unchanged.

## Examples

USER: 生成一份关于 2026 企业 AI Agent 采用情况的简短报告，保存为 .docx
ASST: [calls write_file(file_path="generated/enterprise-ai-agents-2026.docx", content="# 2026 企业 AI Agent 采用情况\n\n## 摘要\n…")]
      已生成 generated/enterprise-ai-agents-2026.docx（Word）。需要我再导出 PDF 或 HTML 吗？

---

*Reconfirmed against the LangConfig **origin_research_writer** agent (id 210). Its authored prompt is only
178 chars and contributes nothing new: the skill declaration, "use `write_file` and let the extension pick
the format", "never use `python_execute` / `python-docx`" and the language rule are already covered here (the
last one belongs to the agent, not the skill). No content was replaced. Left agent-side: the role, the
language preference, the workspace, and which file tool the agent carries (`write_file` here, `save_document`
elsewhere).*
