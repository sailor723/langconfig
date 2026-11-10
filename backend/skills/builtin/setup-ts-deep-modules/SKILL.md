---
name: "Setup Ts Deep Modules（把 TypeScript 包配成深模块）"
lang: zh
translated: machine
source: backend/skills/en-originals/setup-ts-deep-modules/SKILL.md
description: >-
  把 dependency-cruiser 接进一个 TypeScript 仓库，让每个包都成为深模块：实现藏在子目录里，外部只能经它的入口文件够到。
  由用户主动调用。
tags:
  - "setup"
  - "ts"
  - "deep"
  - "modules"
  - "mattpocock"
triggers:
  - "当被要求把本仓库的每一个包都做成**深模块**：在很小的接口背后藏着大量行为。"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "write_file"
  - "edit_file"
  - "bash"
  - "skill"
author: "mattpocock (MIT), adapted for LangConfig"
version: "1.0"
---

## Instructions（指令）

> **来源说明。** 改编自 `mattpocock/skills → skills/in-progress/setup-ts-deep-modules`（MIT，原样收录于 `vendor/upstream-skills/mattpocock/skills/in-progress/setup-ts-deep-modules/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


# 配置 TS 深模块

把本仓库里的每一个包都做成**深模块**：在很小的接口背后藏着大量行为。一个包的公开面就是它的**入口**（位于包根目录的那些文件），
子目录里的一切都是隐藏的。本技能装上 [dependency-cruiser](https://github.com/sverweij/dependency-cruiser)，
以及让入口成为唯一进门的那套规则，然后证明这些规则真的会咬人。

关于术语（deep module、interface、seam、depth），用 `skill` 工具读取技能（id 为 `codebase-design`），
并全程沿用它的说法。

## 这套配置强制的形状

```
src/packages/
  <name>/
    index.ts        ← an entry point (public). Import this from outside.
    client.ts       ← another entry point. Packages may expose SEVERAL.
    lib/            ← implementation: hidden from outside, free to import each other.
    tests/          ← co-located tests + fixtures (a subfolder, so private).
```

公开面是包的**根目录文件**，而不是某个指定的 `index.ts`。按约定，实现放在 `lib/`，测试放在 `tests/`，
于是每个包都是同样的两目录形状。但规则本身是通用的：*任何*子目录里的*任何东西*都是私有的，
所以你永远不需要为了新增一个目录去改配置。

四条规则，全部是 `error` 级别：

1. **入口边界**：包外的代码（应用代码或另一个包）只能 import 那个包的入口（它的根目录文件），
   绝不能碰它子目录里的东西。
2. **包内自由**：一个包自己的文件之间可以随意互相 import。
3. **测试走入口**：`<pkg>/tests/` 下的文件可以 import 任何包的入口，以及自己 `tests/` 里的 fixture，
   但绝不能 import 任何包的子目录内部（连自己的也不行）。跨包的集成测试没问题；深度 import 不行。
4. **无环**：不允许出现依赖环。

**要入口，不要 barrel。** 因为公开面是*每一个*根目录文件，一个包可以暴露好几个小入口
（`index.ts`、`client.ts`、`server.ts`），而不必把所有东西都漏斗进一个巨大的 `index.ts`。
把整棵子树再导出一次的 barrel 文件是不鼓励的；把入口保持得小，把实现藏进子目录。

分层（哪个包可以依赖哪个包）是*另一件*事，在本仓库的配置里留成一段注释掉的存根，由本仓库自己补。

## 步骤

### 1. 探测环境

- **包管理器**：`pnpm-lock.yaml` → pnpm，`yarn.lock` → yarn，`bun.lockb` → bun，否则 npm。下面每条命令都用它
  （`pnpm` / `yarn` / `npm run` / `bunx`）。
- **包根目录**：如果存在 `src/`，用 `src/packages`，否则用 `packages`。如果仓库里已经有一套明显不同但成形的约定，
  先跟用户确认这个选择。
- **已有配置**：检查有没有 `.dependency-cruiser.*` 文件。如果已经有，**不要**覆盖它：把四条规则和选项合并进去，
  并告诉用户你加了什么。

**完成标准：** 包管理器、包根目录、已有配置的状态，三者都已明确。

### 2. 安装 dependency-cruiser

用识别出来的包管理器，把 `dependency-cruiser` 装成 devDependency。

**完成标准：** `devDependencies` 里出现了 `dependency-cruiser`。

### 3. 写配置文件

把 [`dependency-cruiser.config.cjs`](./dependency-cruiser.config.cjs) 复制到仓库根目录，命名为 `.dependency-cruiser.cjs`。
把 `PACKAGES_ROOT` 设成第 1 步识别出的根目录。这些规则是按路径深度判定的，与扩展名无关，
所以别的地方都不用改。

**完成标准：** `.dependency-cruiser.cjs` 存在、`PACKAGES_ROOT` 正确，且四条禁止规则俱全。

### 4. 接进检查流程

- 加一个 `lint:boundaries` 脚本：`depcruise <packages-root>`（或 `depcruise src`）。
- 把它并进仓库的总检查命令，也就是那个已经在跑 typecheck 的命令（例如某个 `check` / `ci` / `validate` 脚本）。
  **不要**动 `tsconfig`，也不要加路径别名。
- 如果仓库里没有总检查脚本，就单加 `lint:boundaries`，并告诉用户把它纳入 CI。

**完成标准：** `lint:boundaries` 存在，并且和 typecheck 在同一条命令里跑。

### 5. 搭一个示例包

建一个会提交进仓库的 `<packages-root>/example/`，当作“照抄我”的模板：

- `index.ts` 是一个入口。导出一个函数，让它委托给内部文件（这样这个包一眼看去是*深的*，而不是一层转发）。
- `lib/impl.ts`：放在**子目录**里的内部文件，由 `index.ts` import，从外部够不到。
- `tests/example.test.ts` **只** import `../index`（一个入口），并对那个公开函数做断言。

告诉用户这是一个供复制或删除的起手模板。

**完成标准：** 示例包存在，通过根目录的入口暴露行为，并把 `impl` 藏在子目录里。

### 6. 证明规则会咬人

这是整个技能的完成判据：一份遇到违规也不报错的配置毫无价值。

1. 跑 `lint:boundaries`。在干净的示例上它必须**通过**。
2. 临时给 `tests/example.test.ts` 加一句深度 import（例如 `import { thing } from "../lib/impl"`）。
   再跑一次 `lint:boundaries`；它必须**失败**，并报出 `tests-through-entrypoints`。
3. 撤回那句深度 import。再跑一次，必须**通过**。

**完成标准：** 你亲眼看到先通过、然后加了深度 import 就失败、撤掉后又通过。如果第 2 步没有失败，
说明规则接得不对，收工之前先修好。

### 7. 写下这套约定

在**包目录里**写一个 `README.md`（`<packages-root>/README.md`，就放在它所管的那些包旁边），涵盖：
`src/packages/<name>/` 这套布局（入口在根目录，`lib/` 放实现，`tests/` 放测试）、“只经包的入口（它的根目录文件）import”、
以及怎么跑 `lint:boundaries`。明确**不鼓励 barrel 文件**：暴露几个小入口，别把整棵子树经一个 index 再导出一次。
篇幅控制住：一段照抄片段，加四条规则各一段。

然后从仓库的智能体说明文件里加一条**上下文指针**指向它（有 `CLAUDE.md` 用它，否则用 `AGENTS.md`；
两样都没有就新建 `AGENTS.md`）。一行就够，例如
`Packages are deep modules: see [src/packages/README.md](./src/packages/README.md) before adding or importing one.`。
正是这一行让智能体能发现这条边界规则，而不是一头撞上去。

**完成标准：** `<packages-root>/README.md` 存在且不鼓励 barrel，并且仓库的 `CLAUDE.md` / `AGENTS.md` 链到了它。

## 说明

- 配置里的 `$1` 反向引用（dependency-cruiser 的分组匹配）正是既能让一个包够到自己的内部、又让外部够不到的机制。
  不要把它们摊平成一堆按包分开的规则。
- 公开还是私有由**深度**决定：包的根目录文件是入口，子目录里的任何东西都是私有的。常用子目录是 `lib/`（实现）和 `tests/`，
  但规则并不写死它们：任何子目录都是私有的，所以新增目录永远不需要改配置。新增一个入口，就是新增一个根目录文件（不需要 barrel）。
- 包是**平的**：根目录下面只有一层直接子目录。包的内部想嵌多深都行；但一个包里不能含另一个包。
- 用 `.cjs`（不是 `.js`），这样即使在 `"type": "module"` 的仓库里，配置的 `module.exports` 也照样能工作。

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
