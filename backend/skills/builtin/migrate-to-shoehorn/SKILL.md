---
name: "Migrate to Shoehorn（把测试迁移到 shoehorn）"
lang: zh
translated: machine
source: backend/skills/en-originals/migrate-to-shoehorn/SKILL.md
description: >-
  把测试文件里的 `as` 类型断言迁移到 @total-typescript/shoehorn。当用户提到 shoehorn、想把测试里的 `as` 换掉、
  或需要构造部分测试数据时使用。
tags:
  - "migrate"
  - "to"
  - "shoehorn"
  - "mattpocock"
  - "testing"
triggers:
  - "用户提到 shoehorn、想把测试里的 `as` 换掉，或需要部分测试数据"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "bash"
author: "mattpocock (MIT), adapted for LangConfig"
version: "1.0"
---

## Instructions（指令）

> **来源说明。** 改编自 `mattpocock/skills → skills/misc/migrate-to-shoehorn`（MIT，原样收录于 `vendor/upstream-skills/mattpocock/skills/misc/migrate-to-shoehorn/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


# 迁移到 Shoehorn

## 为什么用 shoehorn？

`shoehorn` 让你在测试里传部分数据，同时让 TypeScript 依然满意。它用类型安全的替代品取代 `as` 断言。

**只用于测试代码。** 生产代码里永远不要用 shoehorn。

测试里用 `as` 的问题：

- 早就被教过不要这么写
- 必须手工指定目标类型
- 故意写错数据时要双重 `as`（`as unknown as Type`）

## 安装

```bash
npm i @total-typescript/shoehorn
```

## 迁移模式

### 大对象，但只用得上很少几个属性

改前：

```ts
type Request = {
  body: { id: string };
  headers: Record<string, string>;
  cookies: Record<string, string>;
  // ...20 more properties
};

it("gets user by id", () => {
  // Only care about body.id but must fake entire Request
  getUser({
    body: { id: "123" },
    headers: {},
    cookies: {},
    // ...fake all 20 properties
  });
});
```

改后：

```ts
import { fromPartial } from "@total-typescript/shoehorn";

it("gets user by id", () => {
  getUser(
    fromPartial({
      body: { id: "123" },
    }),
  );
});
```

### `as Type` → `fromPartial()`

改前：

```ts
getUser({ body: { id: "123" } } as Request);
```

改后：

```ts
import { fromPartial } from "@total-typescript/shoehorn";

getUser(fromPartial({ body: { id: "123" } }));
```

### `as unknown as Type` → `fromAny()`

改前：

```ts
getUser({ body: { id: 123 } } as unknown as Request); // wrong type on purpose
```

改后：

```ts
import { fromAny } from "@total-typescript/shoehorn";

getUser(fromAny({ body: { id: 123 } }));
```

## 各用哪个

| 函数            | 适用场景                                     |
| --------------- | -------------------------------------------- |
| `fromPartial()` | 传部分数据，同时仍然能通过类型检查           |
| `fromAny()`     | 传故意写错的数据（保留自动补全）             |
| `fromExact()`   | 强制要求完整对象（之后再换成 fromPartial）   |

## 工作流

1. **摸清需求** —— 问用户：
   - 哪些测试文件里的 `as` 断言在制造麻烦？
   - 是不是那种大对象、而只有少数属性真的重要？
   - 为了测错误路径，需不需要传故意写错的数据？

2. **安装并迁移**：
   - [ ] 安装：`npm i @total-typescript/shoehorn`
   - [ ] 找出带 `as` 断言的测试文件：`grep -r " as [A-Z]" --include="*.test.ts" --include="*.spec.ts"`
   - [ ] 把 `as Type` 换成 `fromPartial()`
   - [ ] 把 `as unknown as Type` 换成 `fromAny()`
   - [ ] 补上来自 `@total-typescript/shoehorn` 的 import
   - [ ] 跑类型检查确认

## This repository's floor（本仓库的底线）

- **用真实命令验证**，不要靠眼看：`./scripts/housekeeping_verify.sh`（守卫 + `tsc` +
  `vite build` + 一份文档库报告）。后端测试套件加 `--full-suite`。
- **后端套件有 20 个既有的失败。**“不比那个基线更差”是诚实的判据；“测试是绿的”在这里不是一个你能做出的断言。
  用
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`
  对照，并把 `FAILED` 行与记录的基线做 diff。
- **规格、工单和笔记活在文件里**：`docs/specs/<slug>.md`、`docs/tickets/NNN-<slug>.md`、`work/<scope>/`。
  写在聊天消息里的一句结论，下一轮就丢了。
- **生态层**：智能体代码是 LangGraph 运行时里的 LangChain（`create_agent`），通常由 Deep Agents 脚手架
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `lc-ecosystem-primer` 规则——并优先选
  能胜任的最高层。
