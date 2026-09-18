---
name: pdf-chat
description: >-
  Search and read project documents (PDF, MD, DOCX, PPT, TXT) using GraphIndex
  vectorless RAG. Use when the user asks about a document, report, or file, or
  wants to find content in the project knowledge base.
tags: [document, pdf, chat, rag, search]
triggers:
  - "search document"
  - "find document"
  - "read pdf"
  - "what does the document say"
  - "pdf content"
  - "graphindex"
  - "upload pdf"
  - "show me the document"
  - "find report"
  - "search knowledge base"
author: User
---

# PDF Chat Assistant

When the user asks about a document, report, file, or topic they want to find:

## Workflow
1. FIRST call graphindex_search(query) with relevant keywords to search project documents
2. If results found, call graphindex_load(context_doc_id) to read full content
3. Answer based on the document content
4. ONLY if graphindex_search returns NOTHING, suggest uploading a document

## Critical Rules
- NEVER ask the user to upload a document without searching the knowledge base first
- The project already has indexed documents available via graphindex
- When uploading happens, document content appears as [PDF Content: "filename.pdf"] in the conversation — read it directly
- If the user uploads a PDF in chat, summarize it first, then answer questions

## Tools Available
- graphindex_search(query): Search project documents by keywords. Returns matching doc IDs.
- graphindex_load(context_doc_id): Load full document content by ID. Returns complete text.
