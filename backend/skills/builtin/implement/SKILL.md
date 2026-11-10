---
name: Implement（按规格实现）
lang: zh
translated: human
source: backend/skills/en-originals/implement/SKILL.md
description: >-
  按规格或一组票据实现一块工作：先读规格与票据图，能测试就先测试，反复跑类型检查与单文件测试，收尾跑一次全量，
  然后调 code-review 评审，最后提交到当前分支。
---

## Instructions（指令）
实现用户所说的、规格或票据里描述的那块工作。

如果用户给了票据引用，从 `docs/tickets/` 取出它，并在动手前报出它的标题。**引用有歧义就先问。**

在预先约定的接缝上，尽量用 `skill` 工具读 `tdd` 那个技能（id: `tdd`）。

**经常跑类型检查，经常跑单个测试文件，全量测试只在收尾跑一次。**

完成后，用 `skill` 工具读 `code-review` 那个技能（id: `code-review`）评审这项工作。

**把工作提交到当前分支。**

## 本仓库的地板

- **用真实命令验证，而不是靠眼睛看**：`./scripts/housekeeping_verify.sh`（守卫 + `tsc` + `vite build` +
  文档库报告）。后端全套加 `--full-suite`。
- **后端测试套件有 20 个既有失败。** "不比那个基线更差"才是这里诚实的判据；"测试是绿的"这句话在本仓库你
  说不出口。对照方式：
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`，
  把 `FAILED` 行与记录的基线做 diff。
- **规格、票据与笔记都落在文件里**：`docs/specs/<slug>.md`、`docs/tickets/NNN-<slug>.md`、`work/<scope>/`。
  写在聊天里的结论，下一个回合就丢了。
- **生态层级**：agent 代码是 LangChain（`create_agent`）跑在 LangGraph 运行时里，通常外面套一层 Deep Agents
  harness（`deepagents`）。动手前先决定这次改动属于哪一层——`ecosystem-primer` 的规则——并优先用能完成任务的
  最高那一层。
