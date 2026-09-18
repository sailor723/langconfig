---
name: web-search
description: Search the web for the latest news, current events, and recent information.
  Use when the user asks about today's news, current events, breaking news, recent
  updates, latest developments, or any external facts not in their training data.
version: 1.0.0
author: User
tags:
- web-search
- news
- current-events
- research
- search
triggers:
- when user asks about the latest news
- when user asks about current events or breaking news
- when user asks what's new or what's happening today
- when user needs the most recent information on a topic
- when user asks about recent events or current news
- when user needs external facts not in their training data
- when user asks to search the web for information
- when user wants to find URLs related to a specific topic
- when user asks to look up something online
- when user asks to verify a fact or claim
allowed_tools:
- '['
- '"'
- w
- e
- b
- _
- s
- e
- a
- r
- c
- h
- '"'
- ','
- ' '
- '"'
- f
- e
- t
- c
- h
- _
- u
- r
- l
- '"'
- ','
- ' '
- '"'
- w
- r
- i
- t
- e
- _
- f
- i
- l
- e
- '"'
- ','
- ' '
- '"'
- r
- e
- a
- d
- _
- f
- i
- l
- e
- '"'
- ']'
---

## Instructions

---
name: web-research
description: Searches multiple web sources, synthesizes findings, and produces cited research reports using delegated subagents. Use when the user asks to research a topic online, search the web, look something up, find current information, compare options, or produce a research report.
---

# Web Research Skill

## Research Process

### Step 1: Create and Save Research Plan

Before delegating to subagents, you MUST:

1. **Create a research folder** - Organize all research files in a dedicated folder relative to the current working directory:
   ```
   mkdir research_[topic_name]
   ```
   This keeps files organized and prevents clutter in the working directory.

2. **Analyze the research question** - Break it down into distinct, non-overlapping subtopics

3. **Write a research plan file** - Use the `write_file` tool to create `research_[topic_name]/research_plan.md` containing:
   - The main research question
   - 2-5 specific subtopics to investigate
   - Expected information from each subtopic
   - How results will be synthesized

**Planning Guidelines:**
- **Simple fact-finding**: 1-2 subtopics
- **Comparative analysis**: 1 subtopic per comparison element (max 3)
- **Complex investigations**: 3-5 subtopics

### Step 2: Delegate to Research Subagents

For each subtopic in your plan:

1. **Use the `task` tool** to spawn a research subagent with:
   - Clear, specific research question (no acronyms)
   - Instructions to write findings to a file: `research_[topic_name]/findings_[subtopic].md`
   - Budget: 3-5 web searches maximum

2. **Run up to 3 subagents in parallel** for efficient research

**Subagent Instructions Template:**
```
Research [SPECIFIC TOPIC]. Use the web_search tool to gather information.
After completing your research, use write_file to save your findings to research_[topic_name]/findings_[subtopic].md.
Include key facts, relevant quotes, and source URLs.
Use 3-5 web searches maximum.
```

### Step 3: Synthesize Findings

After all subagents complete:

1. **Review the findings files** that were saved locally:
   - First run `list_files research_[topic_name]` to see what files were created
   - Then use `read_file` with the **file paths** (e.g., `research_[topic_name]/findings_*.md`)
   - **Important**: Use `read_file` for LOCAL files only, not URLs

2. **Synthesize the information** - Create a comprehensive response that:
   - Directly answers the original question
   - Integrates insights from all subtopics
   - Cites specific sources with URLs (from the findings files)
   - Identifies any gaps or limitations

3. **Write final report** (optional) - Use `write_file` to create `research_[topic_name]/research_report.md` if requested

**Note**: If you need to fetch additional information from URLs, use the `fetch_url` tool, not `read_file`.

## Best Practices

- **Plan before delegating** - Always write research_plan.md first
- **Clear subtopics** - Ensure each subagent has distinct, non-overlapping scope
- **File-based communication** - Have subagents save findings to files, not return them directly
- **Systematic synthesis** - Read all findings files before creating final response
- **Stop appropriately** - Don't over-research; 3-5 searches per subtopic is usually sufficient
