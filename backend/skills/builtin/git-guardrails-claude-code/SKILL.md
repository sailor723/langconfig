---
name: "Git Guardrails Claude Code（Git 安全护栏 · Claude Code）"
lang: zh
translated: machine
source: backend/skills/en-originals/git-guardrails-claude-code/SKILL.md
description: >-
  在 Claude Code 里配好 hooks，让危险的 git 命令（push、reset --hard、clean、branch -D 等）在执行之前就被拦住。
  当用户想禁止破坏性的 git 操作、想加一层 git 安全 hook、或想在 Claude Code 里挡住 git push / reset 时使用。
tags:
  - "git"
  - "guardrails"
  - "claude"
  - "code"
  - "mattpocock"
triggers:
  - "用户想禁止破坏性的 git 操作时"
  - "想在 Claude Code 里加一层 git 安全 hook 时"
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

> **来源说明。** 改编自 `mattpocock/skills → skills/misc/git-guardrails-claude-code`（MIT，原样收录于 `vendor/upstream-skills/mattpocock/skills/misc/git-guardrails-claude-code/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


# 配置 Git 安全护栏

配一个 PreToolUse hook，在 Claude 真正执行之前拦下并阻断危险的 git 命令。

## 会被拦下的命令

- `git push`（所有变体，含 `--force`）
- `git reset --hard`
- `git clean -f` / `git clean -fd`
- `git branch -D`
- `git checkout .` / `git restore .`

被拦下时，Claude 会看到一条消息，告诉它无权访问这些命令。

## 步骤

### 1. 询问作用范围

问用户：只给**本项目**装（`.claude/settings.json`），还是给**所有项目**装（`~/.claude/settings.json`）？

### 2. 复制 hook 脚本

随本技能附带的脚本在：[scripts/block-dangerous-git.sh](scripts/block-dangerous-git.sh)

按作用范围把它复制到目标位置：

- **项目**：`.claude/hooks/block-dangerous-git.sh`
- **全局**：`~/.claude/hooks/block-dangerous-git.sh`

用 `chmod +x` 给它加上可执行权限。

### 3. 把 hook 写进配置

加到对应的配置文件里：

**项目**（`.claude/settings.json`）：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/block-dangerous-git.sh"
          }
        ]
      }
    ]
  }
}
```

**全局**（`~/.claude/settings.json`）：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/block-dangerous-git.sh"
          }
        ]
      }
    ]
  }
}
```

如果配置文件已经存在，就把这个 hook 合并进现有的 `hooks.PreToolUse` 数组。不要覆盖其它配置。

### 4. 询问是否定制

问用户是否要在禁用清单上增删某些模式。按他的回答改那份复制过去的脚本。

### 5. 验证

跑一个快速测试：

```bash
echo '{"tool_input":{"command":"git push origin main"}}' | <path-to-script>
```

它应当以退出码 2 结束，并向 stderr 打印一条 BLOCKED 消息。

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
