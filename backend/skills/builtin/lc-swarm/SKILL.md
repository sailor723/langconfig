---
name: "Swarm（蜂群）"
lang: zh
translated: machine
source: backend/skills/en-originals/lc-swarm/SKILL.md
description: >-
  并行分发大量彼此独立的条目：建一张表，扇出到各子智能体，再汇总结果。一行 = 一个工作单元。
tags:
  - "swarm"
  - "langchain-skills"
triggers:
  - "被要求并行处理许多彼此独立的条目时。`create` 构建一个表句柄；"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "write_file"
  - "edit_file"
  - "bash"
  - "task"
  - "skill"
author: "langchain-skills (MIT), adapted for LangConfig"
version: "1.0"
---

## Instructions（指令）

> **来源说明。** 改编自 `langchain-ai/langchain-skills → config/skills/swarm`（MIT，原样收录于 `vendor/upstream-skills/langchain-skills/skills/swarm/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


# Swarm（蜂群）

并行处理许多彼此独立的条目。`create` 建一个表句柄；`run` 把工作扇出到各行，再把结果合并回来。
一行 = 一个工作单元——分批由蜂群自动处理。

## Flow（流程）

1. **Create（建表）。** 从一个来源建表——文件、glob 模式，或预先解析好的记录。每个条目一行。
   返回一个句柄。
2. **Run（运行）。** 把一个 `instruction` 模板分发到各行。结果合并回表里。返回
   `{ completed, failed, skipped, failures }`。
3. **Aggregate（汇总）。** 用 `rows()` 加普通 JS 来计数、过滤或归纳。不要为了汇总再起子智能体。
4. **Retry（重试）。** 用 `filter: { column: "<col>", exists: false }` 重跑，只重新处理失败的行。

## Choosing a source（选择来源）

**`glob` / `filePaths`** —— 一个文件 = 一行。每个文件都是一个独立工作单元时用它。每一行拿到
`{ id, file }`；子智能体自己通过 `{file}` 占位符去读那个文件。

**`tasks`** —— 直接传预先构造好的记录。数据住在某个文件里（JSONL、CSV、JSON 数组）时用它。先在
`eval` 里读取并解析该文件，再传记录。一条记录 = 一行——不要把多个条目并进单行。

小文件（约 500 行以内）在一块里解析并建表：

```javascript
const { create } = await import("@/skills/swarm");
const raw = await tools.readFile({ file_path: "/data.jsonl" });
const records = raw.trim().split("\n").map(l => JSON.parse(l));
const table = await create({ tasks: records });
console.log(table);
```

大文件按 500 行分块读，避免被截断：

```javascript
const { create } = await import("@/skills/swarm");
let records = [];
let offset = 0;
while (true) {
  const chunk = await tools.readFile({ file_path: "/data.txt", offset, limit: 500 });
  const lines = chunk.split("\n").filter(l => l.trim());
  for (const l of lines) { records.push({ id: `r${records.length}`, text: l }); }
  if (lines.length < 500) break;
  offset += 500;
}
const table = await create({ tasks: records });
console.log(table);
```

文件大到无法在一次 `eval` 调用里解析并分发时，拆成两块。只有调用蜂群函数的那一块需要 import：

```javascript
// eval 1: parse only — no swarm import needed
const raw = await tools.readFile({ file_path: "/data.jsonl" });
globalThis.records = raw.trim().split("\n").map(l => JSON.parse(l));
console.log(`Parsed ${globalThis.records.length} records`);
```

```javascript
// eval 2: create and dispatch
const { create, run } = await import("@/skills/swarm");
const table = await create({ tasks: globalThis.records });
const result = await run(table.id, {
  instruction: "Classify {text}",
  responseSchema: {
    type: "object",
    properties: { label: { type: "string" } },
    required: ["label"],
  },
});
console.log(result);
```

传 `filePaths: ["/data.jsonl"]` 得到的是**只有一行**、指向该文件的表——而不是文件里每条记录一行。

## When to use `subagentType`（何时使用 `subagentType`）

分类、抽取、打标，以及任何一次带结构化输出的模型调用就足够的任务，都省略 `subagentType`。这是默认
做法，明显更便宜也更快——每次分发都是一次直接的模型调用，没有工具，没有迭代。

任务需要工具、文件访问或多步推理时，才设 `subagentType`。每次分发都会跑一个带着指定子智能体的完整
智能体循环。

```javascript
// Direct model call — classification, no tools needed
await run(table.id, {
  instruction: "Classify {text}",
  responseSchema: { type: "object", properties: { label: { type: "string" } }, required: ["label"] },
});

// Subagent — needs to read files and reason over multiple steps
await run(table.id, {
  subagentType: "reviewer",
  instruction: "Review {file} for security issues.",
  responseSchema: { type: "object", properties: { finding: { type: "string" } }, required: ["finding"] },
});
```

## Instruction + context（指令与上下文）

`instruction` 是逐条目的模板，带 `{column}` 占位符。占位符由框架解析——你的列名会以“与列出的取值
并列的引用”的形式出现在提示词里，而绝不是原始的模板语法。活由子智能体干——不要自己在 JS 里处理
条目、再把结果写进行里。

`context` 是自由散文，前置到每一个子智能体提示词前面。用它放共享背景：领域术语、分类规则、示例等。

```javascript
const { create, run } = await import("@/skills/swarm");

const table = await create({ glob: "src/**/*.ts" });
const r = await run(table.id, {
  subagentType: "reviewer",
  instruction: "Review {file} for security issues. List findings or write 'no issues'.",
  context: "TypeScript Express backend using Prisma ORM. Focus on injection, auth bypass, path traversal.",
  responseSchema: {
    type: "object",
    properties: { review: { type: "string" } },
    required: ["review"],
  },
});
console.log(r);
// → { completed: 45, failed: 2, skipped: 0, failures: [...] }
```

## Structured output（结构化输出）

`responseSchema` 是必填的。schema 的属性会成为每一行的顶层列，并约束子智能体能返回什么。

```javascript
const { run } = await import("@/skills/swarm");
await run(table.id, {
  instruction: "Classify: {text}",
  responseSchema: {
    type: "object",
    properties: {
      sentiment: { type: "string", enum: ["positive", "negative", "neutral"] },
    },
    required: ["sentiment"],
  },
});
// Row after: { id: "r1", text: "...", sentiment: "positive" }
```

## Batching（分批）

默认情况下，蜂群自动分批，把总分发数压在 10 以内。小表（≤10 行）每行各拿一次子智能体调用。更大的
表，行会被自动分组。

用 `batchSize` 控制分组：

- **数字** —— 所有行用统一的批大小。`batchSize: 1` 强制逐行分发；`batchSize: 20` 每二十个一组。
- **函数** —— `(row, rowCount) => number`。为每一行返回想要的批大小。批大小相同的行先聚在一起，
  再切块。这样允许混发：有的行单跑，有的行成批。

```javascript
const { create, run } = await import("@/skills/swarm");
const table = await create({ tasks: items });

// Complex items get individual attention; simple ones batch together
await run(table.id, {
  instruction: "Analyze {text}",
  responseSchema: {
    type: "object",
    properties: { analysis: { type: "string" } },
    required: ["analysis"],
  },
  batchSize: (row) => (row.token_count > 1000 ? 1 : 10),
});
```

批大小在求值之后会被夹到 [1, 50]。

## Aggregation（汇总）

`run()` 之后，用 `rows()` 加普通 JS——不需要额外的子智能体。

```javascript
const { rows } = await import("@/skills/swarm");
const data = await rows(table.id, { columns: ["sentiment"] });
const counts = {};
data.forEach(r => { counts[r.sentiment] = (counts[r.sentiment] || 0) + 1 });
console.log(counts);
// → { positive: 120, negative: 45, neutral: 35 }
```

## Chaining passes（串联多趟）

`run` 就地更新表——串联调用即可累积列。

```javascript
const { create, run } = await import("@/skills/swarm");
const table = await create({ tasks: interviews });
await run(table.id, {
  instruction: "Classify sentiment of {text}",
  responseSchema: {
    type: "object",
    properties: { sentiment: { type: "string", enum: ["positive", "negative", "neutral"] } },
    required: ["sentiment"],
  },
});
await run(table.id, {
  filter: { column: "sentiment", equals: "negative" },
  instruction: "Summarize why {text} had negative sentiment.",
  responseSchema: {
    type: "object",
    properties: { summary: { type: "string" } },
    required: ["summary"],
  },
});
```

## Action-only tasks（只出动作的任务）

当子智能体做的是动作（写文件、打补丁）而不是返回数据时，用一个带状态或标记字段的简单 schema。
`exists: false` 过滤器照样能用于重试。

```javascript
const { create, run } = await import("@/skills/swarm");
const fixedSchema = {
  type: "object",
  properties: { fixed: { type: "string" } },
  required: ["fixed"],
};
const table = await create({ glob: "src/**/*.ts" });
await run(table.id, {
  subagentType: "fixer",
  instruction: "Add missing JSDoc to all exported functions in {file}.",
  responseSchema: fixedSchema,
});
// retry any that failed
await run(table.id, {
  subagentType: "fixer",
  instruction: "Add missing JSDoc to all exported functions in {file}.",
  responseSchema: fixedSchema,
  filter: { column: "fixed", exists: false },
});
```

## Filtering（过滤）

```javascript
{ column: "status", equals: "done" }
{ column: "status", notEquals: "done" }
{ column: "category", in: ["A", "B"] }
{ column: "result", exists: false }      // not yet processed
{ and: [filter1, filter2] }
{ or: [filter1, filter2] }
```

## Technical notes（技术备注）

- **只在调用蜂群函数的块里 import `@/skills/swarm`。** 数据准备（读文件、解析、存进
  `globalThis`）不需要这个 import。只解构你要用的：`{ create }`、`{ run }`、`{ create, run }` 等。
- **控制台输出上限约 5 KB。** 绝不打印原始文件内容——只打印计数和短样本。
- **`eval` 里的 `readFile` 返回原始内容——没有行号前缀。** 每次调用最多请求 500 行。超过 500 行的
  文件，用递增的 `offset` 循环。
- **从文件建表时，在 `eval` 里读它。** 在沙箱里读到的数据留在沙箱里；它从不进入智能体的上下文窗口。
- **绝不直接写 `.swarm/`。** 始终用 `create()`。
- **子智能体需要的一切都必须在 `instruction` + `context` 里。** 子智能体看不见智能体的上下文。
- **行 id 必须唯一。** `create()` 会拒绝产生重复 id 的来源。对 `tasks` 而言这是调用方的责任；
  对 `glob` / `filePaths` 而言，id 由父目录自动区分开。
- **未知列立即失败。** 如果 `instruction` 引用了 `{foo}`，而没有任何匹配的行提供 `foo`，
  `run()` 会在分发任何子智能体之前抛出错误。

## API Reference（API 参考）

### `create(source)`

建表。返回句柄 `{ id, count, columns }`。

| 来源 | 说明 |
|--------|------------|
| `{ glob: "src/**/*.ts" }` 或 `{ glob: ["src/**/*.ts", "lib/**/*.ts"] }` | 按一个或多个模式匹配文件。列：`id`、`file` |
| `{ filePaths: ["a.ts", "b.ts"] }` | 显式的文件清单。列：`id`、`file` |
| `{ tasks: [{ id: "t1", text: "..." }] }` | 自定义行。每一行都必须带 `id` |

### `run(tableId, options)`

把工作分发到各行。返回 `{ completed, failed, skipped, failures }`。

| 选项 | 默认 | 说明 |
|--------|---------|------------|
| `instruction` | （必填） | 带 `{column}` 占位符的模板 |
| `responseSchema` | （必填） | JSON Schema（`type: "object"`）——属性成为行的列 |
| `context` | — | 前置到每个子智能体提示词前的散文 |
| `filter` | — | 只分发匹配的行 |
| `subagentType` | — | 要分发到的子智能体名。设置时跑完整智能体循环；省略时跑一次直接的模型调用 |
| `batchSize` | 自动 | 数字，或 `(row, rowCount) => number`。自动模式把分发数压到 10；`1` = 逐行；函数 = 逐行定量 |
| `concurrency` | `10` | 最大并发子智能体分发数（夹到 1–10） |

### `rows(tableId, options?)`

取回行。用于检视，以及基于 JS 的汇总。

| 选项 | 说明 |
|--------|------------|
| `filter` | 只返回匹配的行 |
| `columns` | 只投影到指定列 |
| `limit` | 返回的最大行数 |

## This repository's floor（本仓库的底线）

- **用真实命令验证**，不要靠眼看：`./scripts/housekeeping_verify.sh`（守卫 + `tsc` + `vite build` +
  一份文档库报告）。后端测试套件加 `--full-suite`。
- **后端套件有 20 个既有的失败。**“不比那个基线更差”是诚实的判据；“测试是绿的”在这里不是一个你能
  做出的宣称。用
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`
  对照，并把 `FAILED` 行与记录的基线做 diff。
- **规格、工单和笔记活在文件里**：`docs/specs/<slug>.md`、`docs/tickets/NNN-<slug>.md`、`work/<scope>/`。
  写在聊天消息里的一句判词，下一轮就丢了。
- **生态层**：智能体代码是 LangGraph 运行时里的 LangChain（`create_agent`），通常由 Deep Agents 框架
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `ecosystem-primer` 规则——并优先
  选能胜任的最高一层。
