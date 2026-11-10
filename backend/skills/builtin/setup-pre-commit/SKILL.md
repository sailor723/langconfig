---
name: "Setup Pre Commit（配置 pre-commit 钩子）"
lang: zh
translated: machine
source: backend/skills/en-originals/setup-pre-commit/SKILL.md
description: >-
  在当前仓库里配好 Husky pre-commit 钩子：lint-staged（Prettier）、类型检查与测试。当用户想加 pre-commit 钩子、
  想装 Husky、想配 lint-staged、或想在提交时自动格式化 / 类型检查 / 跑测试时使用。
tags:
  - "setup"
  - "pre"
  - "commit"
  - "mattpocock"
  - "testing"
triggers:
  - "用户想加 pre-commit 钩子、装 husky 或配 lint-staged 时"
  - "想在提交时自动格式化、类型检查或跑测试时"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "write_file"
  - "edit_file"
  - "bash"
author: "mattpocock (MIT), adapted for LangConfig"
version: "1.0"
---

## Instructions（指令）

> **来源说明。** 改编自 `mattpocock/skills → skills/misc/setup-pre-commit`（MIT，原样收录于 `vendor/upstream-skills/mattpocock/skills/misc/setup-pre-commit/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


# 配置 Pre-Commit 钩子

## 这套配置会装出什么

- **Husky** pre-commit 钩子
- **lint-staged**，对所有已暂存的文件跑 Prettier
- **Prettier** 配置（若缺失）
- pre-commit 钩子里的 **typecheck** 与 **test** 脚本

## 步骤

### 1. 识别包管理器

看仓库里有哪个文件：`package-lock.json`（npm）、`pnpm-lock.yaml`（pnpm）、`yarn.lock`（yarn）、`bun.lockb`（bun）。
哪个在就用哪个。看不出来时默认 npm。

### 2. 安装依赖

作为 devDependencies 安装：

```
husky lint-staged prettier
```

### 3. 初始化 Husky

```bash
npx husky init
```

这一步会建出 `.husky/` 目录，并把 `prepare: "husky"` 写进 package.json。

### 4. 创建 `.husky/pre-commit`

写入这个文件的内容（Husky v9+ 不需要 shebang）：

```
npx lint-staged
npm run typecheck
npm run test
```

**就地适配**：把 `npm` 换成第 1 步识别出的包管理器。如果 package.json 里没有 `typecheck` 或 `test` 脚本，
就删掉对应那几行，并告知用户。

### 5. 创建 `.lintstagedrc`

```json
{
  "*": "prettier --ignore-unknown --write"
}
```

### 6. 创建 `.prettierrc`（若缺失）

只在没有任何 Prettier 配置时才创建。用这组默认值：

```json
{
  "useTabs": false,
  "tabWidth": 2,
  "printWidth": 80,
  "singleQuote": false,
  "trailingComma": "es5",
  "semi": true,
  "arrowParens": "always"
}
```

### 7. 验证

- [ ] `.husky/pre-commit` 存在且有可执行权限
- [ ] `.lintstagedrc` 存在
- [ ] package.json 里的 `prepare` 脚本是 `"husky"`
- [ ] `prettier` 配置存在
- [ ] 跑一遍 `npx lint-staged`，确认它确实能用

### 8. 提交

把所有改动过、新建过的文件暂存起来，用这条信息提交：`Add pre-commit hooks (husky + lint-staged + prettier)`

这次提交本身就会走过新装的 pre-commit 钩子：一次很好的烟火测试，证明整套东西是通的。

## 说明

- Husky v9+ 的钩子文件不需要 shebang
- `prettier --ignore-unknown` 会跳过 Prettier 解析不了的文件（图片等）
- pre-commit 先跑 lint-staged（快，只看已暂存的），再跑完整的类型检查和测试

## This repository's floor（本仓库的底线）

- **用真实命令验证**，不要靠眼看：`./scripts/housekeeping_verify.sh`（守卫 + `tsc` +
  `vite build` + 一份文档库报告）。后端测试套件加 `--full-suite`。
- **后端套件有 20 个既有的失败。**“不比那个基线更差”是诚实的判据；“测试是绿的”在这里不是一个你能做出的宣称。
  用
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`
  对照，并把 `FAILED` 行与记录的基线做 diff。
- **规格、工单和笔记活在文件里**：`docs/specs/<slug>.md`、`docs/tickets/NNN-<slug>.md`、`work/<scope>/`。
  写在聊天消息里的一句判词，下一轮就丢了。
- **生态层**：智能体代码是 LangGraph 运行时里的 LangChain（`create_agent`），通常由 Deep Agents 框架
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `lc-ecosystem-primer` 规则——并优先选
  能胜任的最高层。
