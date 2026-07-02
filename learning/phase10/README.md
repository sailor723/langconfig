# Phase 10: DeepAgent — Mother→Child Agent Generation Architecture

> *"Compile-time agent generation vs runtime delegation: why purpose-built child agents beat monolithic prompts."*

## 🧠 Core Philosophy

The key insight of DeepAgent is the **Mother Agent → Child Agent** pattern:

```
Agent Creator (Mother)                     Child Agent (Generated)
┌──────────────────────┐                  ┌──────────────────────┐
│ Role: "Agent Designer"│                  │ Role: "A股分析师"     │
│ Prompt: ~4000 chars  │    generate      │ Prompt: ~800 chars   │
│ Tools: 40+ (full set)│ ──────────────▶  │ Tools: 6 (web, db)   │
│ Cost: High           │                  │ Cost: Low            │
│ Use: Once (design)   │                  │ Use: Many (runtime)  │
└──────────────────────┘                  └──────────────────────┘
```

### Why This Matters

| Approach | Token Cost (per task) | Control | Reliability | Reusability |
|----------|----------------------|---------|-------------|-------------|
| **Single agent (OpenClaw/Harness)** | All tokens + delegation overhead | Black box | One bug breaks all | None |
| **DeepAgent (Mother→Child)** | One-time design cost + lean child runtime | User edits child config | Isolated per child | Save + reuse in DB |

## 🔬 Key Insight: Compile vs Runtime

The fundamental difference is analogous to **compiled vs interpreted** languages:

**OpenClaw/Harness (Runtime Delegation)** — One agent with a long prompt delegates sub-tasks dynamically:

```
User → [Master Agent] → thinks → calls web_search → thinks → calls analysis → thinks → writes report
         ↑                                                                                ↑
         └────────────────── Each step pays full reasoning cost ──────────────────────────┘
```

- Every invocation burns tokens on *how* to do things, not *what* to do
- The agent re-discovers its approach each session
- No persistence of successful patterns
- Hard to audit or intervene mid-flow

**DeepAgent (Compile-time Generation)** — Mother agent designs + saves a purpose-built child:

```
                 ┌─── Agent Creator (one-time cost) ───┐
                 │  analyze needs → select tools →      │
                 │  write prompt → save to DB            │
                 └──────────────────┬───────────────────┘
                                    │ generates
                                    ▼
                 ┌───────────────────────────────────────┐
                 │  Child Agent (saved in PostgreSQL)    │
                 │  - Tight system prompt                │
                 │  - Curated tool list                  │
                 │  - Known capabilities                 │
                 └───────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
                Task A           Task B           Task C
              (lean cost)     (lean cost)     (lean cost)
```

- Child agent's prompt is focused — no "how to design agents" boilerplate
- Tools are pre-selected — no tool-discovery overhead
- The child can be inspected, edited, versioned
- Multiple instances of the same child can run in parallel

## 🏗 Architecture

### DeepAgent Data Model

```python
class DeepAgent:
    id: int               # Primary key
    name: str             # "A股市场深度研究分析师"
    description: str      # Human-readable summary
    config: {             # Core configuration
        system_prompt: str,   # ~800 chars, task-specific
        native_tools: [...],  # Pre-selected tools
        skills: [...],        # Attached skills
        model: str,           # LLM model
        temperature: float,
    }
    middleware_config: [...]  # Routing, tool selection
    subagents_config: [...]   # Child agents (nested)
    category: str             # "research", "coding", etc.
    is_public: bool           # Shareable
    version: str              # Semver
```

### Agent Creator (Mother Agent, id=112)

The Agent Creator is itself a `DeepAgent` with:

- **System prompt**: 6-step workflow (understand → requirements → create → test → evaluate → deliver)
- **Tools**: Full set of 40+ tools + `create_deepagent` + `pg_list_tools` + `pg_list_skills` + `pg_list_documents`
- **Skills**: `skill-generator`, `debugging`, `code-review`, `data-analysis`
- **Output**: Calls `create_deepagent()` tool that saves the new agent to PostgreSQL

### Child Agent Runtime

When a child agent runs:

1. Load config from PostgreSQL
2. Initialize LLM with its system prompt
3. Load only its pre-selected tools
4. Execute task independently
5. Full session history stored for audit

## 📊 Practical Validation: 东山精密 Research Report

We proved the full flow end-to-end:

### Step 1: Generate Child Agent

```
User → Agent Creator: "创建A股市场深度研究分析师"
  → Agent Creator analyzes requirements
  → Writes system prompt + selects tools
  → Calls create_deepagent()
  → ✅ Child saved as id=123
```

### Step 2: Test via Chat

```
User → Child Agent: "深度分析东山精密，中线6个月持仓"
  → Child Agent runs independently
  → Uses web_search, pg_query, neo4j_query
  → Produces 12,074-word research report
  → Saves as markdown file
```

### Step 3: Result Quality

The report included:
- **五维评分**: 基本面 8.0, 技术面 4.5, 消息面 7.5, 资金面 7.0, 政策面 8.5
- **综合结论**: Score 7.26/10 with clear risk/reward analysis
- **操作框架**: Entry/exit signals, support/resistance levels
- **风险提示**: 商誉47.69亿, 客户集中度, 技术路线博弈

All achieved without the Agent Creator's expensive prompt — the child ran lean.

## 🔄 Comparison: DeepAgent vs OpenClaw/Harness

| Dimension | OpenClaw / Harness | DeepAgent (Ours) |
|-----------|-------------------|-----------------|
| **Approach** | Single agent with delegation prompts | Mother generates purpose-built children |
| **Persistence** | Session-based, no agent DB | PostgreSQL, reusable agents |
| **Tool discovery** | Re-discovered each session | Pre-selected at generate-time |
| **Cost per task** | High (delegation overhead) | Low (focused prompt) |
| **User control** | Can only edit prompt | Can edit tools, skills, prompt, version |
| **Observability** | Chat history only | Per-agent session tracking |
| **Multi-agent** | Manual config | Generated + composed |
| **Ecosystem** | 10,700+ community skills | ~40 built-in tools + skills |

### When Each Shines

**OpenClaw/Harness** is better when:
- You need ad-hoc, one-off tasks
- The task is too novel to pre-define
- You want maximum flexibility

**DeepAgent** is better when:
- You repeat similar tasks (research, analysis, monitoring)
- You need reliability and predictability
- You want to build a library of reusable agents
- Cost control matters at scale

## 🧩 Key Components

### 1. Tools (Native → Agent)

Our tool architecture mirrors OpenClaw's first-class tools:

| Category | Tools | OpenClaw Equivalent |
|----------|-------|-------------------|
| **Web** | `web_search`, `web_fetch` | `group:web` |
| **Database (PG)** | `pg_query`, `pg_list_tables`, etc. | N/A |
| **Graph (Neo4j)** | `neo4j_query`, `neo4j_upsert_doc` | N/A |
| **Files** | `read`, `write`, `edit` | `group:fs` |
| **Code** | `python_repl`, `bash` | `group:runtime` |

### 2. Skills (Pluggable Behaviors)

Skills are `SKILL.md` files under `backend/skills/`:

```
backend/skills/
├── builtin/
│   ├── code-review/SKILL.md
│   ├── data-analysis/SKILL.md
│   ├── debugging/SKILL.md
│   ├── skill-generator/SKILL.md
│   └── ...
├── personal/
│   ├── pdf-chat/SKILL.md
│   └── ...
└── market_wizard/
    ├── SKILL.md
    └── rules.yaml
```

Each skill is a directory with `SKILL.md` containing YAML frontmatter + instructions — identical to the OpenClaw/AgentSkills spec.

### 3. Skill Registry (Future)

The next frontier: a queryable Skill Registry in PostgreSQL/Neo4j that the Agent Creator can search and compose from:

```
Agent Creator workflow with Skill Registry:
1. User request → "创建A股研究助手"
2. Agent Creator queries Skill Registry
3. Returns matching skills: ["data-analysis", "web-search", "report-generator"]
4. Agent Creator composes these into the new agent's config
5. Saves agent with selected skills
```

This would unlock the same ecosystem power as OpenClaw's ClawHub (10,700+ skills), but with the **compile-time efficiency** of DeepAgent's Mother→Child pattern.

## 🚀 Future Directions

### Near-term (Phase 10.1)
- **Skill Registry API**: CRUD for skills in PG/Neo4j, indexed by name, category, tags
- **Agent Creator skill search**: Mother agent queries registry to compose child agents
- **Agent versioning**: Track changes across child agent versions

### Medium-term (Phase 10.2)
- **Agent Marketplace**: Share/publish child agents between users
- **Runtime monitoring**: Track child agent performance, cost, success rate
- **Auto-tuning**: Mother agent analyzes child performance and suggests improvements

### Long-term (Phase 10.3)
- **Nested agent trees**: Children that can themselves generate sub-children
- **Cross-agent memory**: Shared knowledge base across agent family
- **Agent composition DSL**: Declarative YAML for describing agent hierarchies

## 📖 Running the Demo

```bash
# Start backend
cd backend && uv run python main.py --port 8765

# Open Studio
# http://localhost:1420/modern-studio

# Click "Generate with AI" → Agent Creator (id=112)
# Propose an agent → Agent Creator generates + saves
# Click "Test" → Chat with your new agent
```

### API Quick Test

```bash
# Start a session with Agent Creator
curl -s -X POST http://localhost:8765/api/chat/start \
  -H "Content-Type: application/json" \
  -d '{"agent_id":112}'

# Propose an agent
curl -s -X POST http://localhost:8765/api/chat/message \
  -H "Content-Type: application/json" \
  -d '{"session_id":"<sid>","message":"创建一个人工智能新闻监控助手"}'
```

## 🏁 Conclusion

DeepAgent's Mother→Child generation offers a fundamentally different trade-off from the OpenClaw/Harness approach:

- **DeepAgent** optimizes for **reusability, control, and efficiency at scale**
- **OpenClaw/Harness** optimizes for **flexibility and ad-hoc adaptability**

Neither is universally better. But for teams building production agent systems where tasks are repeatable and cost predictability matters, the **compile-time generation** approach of DeepAgent provides a powerful alternative to runtime delegation.

**The key insight**: A mother agent's expensive reasoning is amortized across every invocation of the children it creates. The more a child runs, the more valuable the generation step becomes.

---

## 🏗 Architecture V2: Orchestrator + SkillsMiddleware (DeepAgent Official Pattern)

After Phase 10, the architecture evolved from "Mother → Child" generation to a **Skill Registry** with a routing **Orchestrator** agent that follows the official DeepAgent **SkillsMiddleware** pattern:

```
                    ┌──────────────────────────────────────────┐
                    │            Orchestrator (id=124)          │
                    │     "规划 → 执行 → 跟进"                  │
                    │                                           │
                    │  Middleware:                               │
                    │  ├── SkillsMiddleware → 技能目录注入       │
                    │  ├── TodoListMiddleware → 进度追踪         │
                    │  └── SubAgentMiddleware → task() 委托      │
                    └──────────────┬────────────────────────────┘
                                   │
                  ┌────────────────┼────────────────────┐
                  │                │                    │
                  ▼                ▼                    ▼
          ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
          │ SKILL.md     │ │ SKILL.md     │ │ ... 31 skills    │
          │ a-share-     │ │ global-      │ │ (DB + disk)      │
          │ research     │ │ equity-      │ │                  │
          │              │ │ research     │ │                  │
          │ 6-step SOP   │ │ 4-dimension  │ │                  │
          │ 五维评分     │ │ Multi-market │ │                  │
          └──────────────┘ └──────────────┘ └──────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                              │
                    ▼                              ▼
          ┌──────────────────┐        ┌──────────────────────┐
          │ general-purpose  │        │ (more subagents in   │
          │ subagent         │        │  future)             │
          │ [auto-created]   │        │                      │
          │ task() only      │        │                      │
          └──────────────────┘        └──────────────────────┘
```

### Three-Layer Architecture

| Layer | Component | Responsibility |
|-------|-----------|---------------|
| **Router** | Orchestrator (id=124) | SkillsMiddleware Match → Read → Execute |
| **Skills** | SKILL.md on disk (31 skills) | Domain-specific instructions + metadata |
| **Subagent** | general-purpose (auto) | task() delegation for heavy/fallback tasks |

### SkillsMiddleware 3-Step Flow (DeepAgent Official)

DeepAgent's SkillsMiddleware follows a documented 3-step pattern:

```
Step 1: Match  ─── SkillsMiddleware injects "Skills System" catalog into prompt
                    Agent checks skill descriptions against user request
                   
Step 2: Read   ─── read_file("backend/skills/{name}/SKILL.md")
                    Agent loads full instructions + tools + SOP

Step 3: Execute ── Agent follows skill instructions
                    TodoListMiddleware tracks progress
                    Tools called within same session
```

### Skills vs Subagents (Two Separate Tracks)

| Track | Trigger | Executor | Use task()? |
|-------|---------|----------|-------------|
| **Skill** | User request matches skill description | Orchestrator itself | No |
| **Subagent** | No skill match / context too heavy | general-purpose subagent | Yes |

**Key insight**: Skills and subagents are independent. SkillsMiddleware loads SKILL.md metadata into the agent's context. SubAgentMiddleware provides the `task()` tool. The agent decides which to use.

### When task() Delegation Happens

| Scenario | Example | Action |
|----------|---------|--------|
| Skill matched, simple task | "What's the PE ratio of AAPL?" | Orchestrator executes directly |
| Skill matched, heavy task | "Analyze 3000 A-share stocks" | `task()` to general-purpose subagent |
| No skill matched | "Write a poem about spring" | Orchestrator answers or `task()` |

### SKILL.md File Format

Every skill exists as a `SKILL.md` file on disk with:

```yaml
---
name: a-share-research
description: A股五维深度分析
tags: [finance, a-share, china-stock]
triggers:
  - "when user asks about A-share stock analysis"
allowed-tools: [web_search, tavily_search, web_fetch, write_file]
author: LangConfig
---
# 角色定位
你是一名专业的「A 股市场深度研究分析师」

# 工作流程（6步SOP）
第1步：明确研究需求
第2步：多源数据采集
第3步：多维度分析（权重分配）
第4步：综合判断（1-10分）
第5步：撰写报告（write_file）
第6步：后续跟踪建议

# 工具
web_search, tavily_search, web_fetch, write_file, memory_store, memory_recall, reasoning_chain
```

### Skill Generator Agent

The `agent_gen_agent` (id=69) was renamed to **`skill_gen_agent`** — a dedicated agent that creates new skills from natural language descriptions:

```
User → skill_gen_agent (id=69)
  → "创建 web-content-analyzer skill"
  → agent reads skill-generator SKILL.md
  → designs skill (name, tags, triggers, instructions, tools)
  → calls create_skill() → saves to DB + generates SKILL.md on disk
  → returns success
```

Skills created via this flow:
- `global-equity-research` — Multi-market equity research
- `a-share-research` — A-share 5-dimension analysis
- `report-generator` — Structured Markdown report generation
- `web-content-analyzer` — Web page content extraction

### Studio UI Improvements

| Feature | Description |
|---------|-------------|
| **Gen Skill with AI** button | Opens skill_gen_agent in Studio header |
| **Skill node detail panel** | Shows tags, triggers, allowed_tools, full SKILL.md, version, author |
| **Skill metadata from API** | Fetches skill details on node click |
| **Chat header fix** | Agent name now correctly reflects selected agent, not session cache |

### Key Bug Fixes

| Fix | Problem | Solution |
|-----|---------|----------|
| **Subagent tool inheritance** | Empty `tools=[]` overrode inheritance with zero tools | Only set `tools` key when tools are explicitly provided |
| **Source path sync** | DB skills had no `source_path` pointing to disk files | Generated SKILL.md files for all 31 skills + updated `source_path` |
| **TodoList middleware** | Orchestrator had no planning middleware | Added `todo_list` middleware config |
| **Model config** | Orchestrator model was empty | Set to `minimax-m3` |

## 🚀 Future Directions

### Completed ✓

| Feature | Status |
|---------|--------|
| Skill Registry (PostgreSQL) | ✅ 31 skills |
| SKILL.md files on disk | ✅ All DB skills |
| `search_skills` tool | ✅ Done |
| Orchestrator (id=124) | ✅ Renamed from Master Router |
| SkillsMiddleware inject | ✅ Skills catalog in prompt |
| TodoListMiddleware | ✅ Planning/progress tracking |
| SubAgentMiddleware | ✅ task() delegation |
| Skill Generator agent | ✅ Renamed to `skill_gen_agent` |
| Global Equity Research skill | ✅ 4-dimension analysis |
| A-Share Research skill | ✅ 5-dimension + 6-step SOP |
| Report Generator skill | ✅ 3 report templates |
| Web Content Analyzer skill | ✅ URL → structured extraction |
| Skill node detail in Studio | ✅ Tags, triggers, SKILL.md |
| Gen Skill with AI button | ✅ Studio header |
| Tool inheritance fix | ✅ No more empty tools override |

### Near-term (Phase 10.2)

| Priority | Feature | Status |
|----------|---------|--------|
| 1 | **Domain-specific subagents** — add custom subagents for heavy tasks | 🔜 Next |
| 2 | **Skill Generator from existing agents** — convert id=115/123 into skills | 🔜 |
| 3 | **Skill Registry UI** — browse/search/compose in Studio | 🔜 |
| 4 | **General assistant fallback skill** — handle unmatched queries | 🔜 |

### Medium-term (Phase 10.3)

| Feature | Description |
|---------|-------------|
| Agent Marketplace | Share/publish skills between users |
| Runtime monitoring | Track skill usage, cost, success rate |
| Cross-agent memory | Shared knowledge base across skills |
| Skill composition DSL | Declarative YAML for composing skill pipelines |
