---
name: tool-analyzer
description: >-
  Analyze Python tool files and produce structured documentation including total_tools (count of distinct tool functions/objects), tool_categories (grouped by web, filesystem, memory, reasoning, delegat
tags: [analysis, tools, documentation, python]
triggers:
  - "when asked to analyze tool structure"
  - "when asked to document tools"
author: AI Generated (Reflection Loop)
---

1. Read the target Python file(s) from the tools directory.
2. Analyze the code to produce a result with these three sections:

### total_tools
Count every distinct tool function/object in the file. Include:
- All @tool-decorated async/sync functions
- All StructuredTool objects created with StructuredTool.from_function()
- Exclude pure helper/utility functions (e.g., _init_sync_playwright, _yahoo_search_fallback, _record_file_version, _record_file_metadata, _write_file_error_handler — these are not tools)
- Exclude backward-compatibility alias vars (file_read, file_write, file_list) — they are just references
- Give the count as a plain integer

### tool_categories
Group the tools by category based on:
- Section headers in the file (e.g., "Web Search Tools", "File System Tools", "Memory Tools", etc.)
- The 'category' field in TOOL_REGISTRY entries
- List each category with: category name, list of tool names in it, count per category

### common_patterns
Identify and document recurring structural or design patterns visible across the tools. Focus on code-level patterns such as:
- **Tool definition patterns**: @tool decorator vs StructuredTool.from_function()
- **Naming/alias patterns**: How tool names get mapped (TOOL_NAME_MAP), backwards compatibility aliases
- **Error handling patterns**: try/except wrappers, custom error handlers, structured error messages
- **Async patterns**: async vs sync tools, lazy initialization, Playwright async handling
- **Registry pattern**: TOOL_REGISTRY as single source of truth for UI metadata
- **Fallback patterns**: When primary approaches fail (e.g., Yahoo fallback for DDG, fallback memory stubs)
- **Security patterns**: Path sanitization in write_file, workspace boundary checks
- **Versioning patterns**: File version tracking, diff-based tracking

For each pattern, provide: pattern name, description, and the tool(s) where it's used.

3. Return the result formatted as a clean JSON-like structure.

## Output Format
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