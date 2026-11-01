# T5 · 研究流水线（deep agent + 文件交付）

> 提炼自：案例 10（327）· 事实见 `references/facts/case-facts.md`
> 这是 12 个案例里唯一带**完整交付契约**的结构，也是最容易被写坏的一个。

## 1 适用场景

用：开放研究类任务——给题目不给步骤，产出是**一份带引用的文件**而不是一段回答。
**不要用**：答案一两句就能说完（→ T1）；需要并行处理互不相干的子问题（→ T2）。

判据一句话：**用户要的是"报告"，不是"答案"**。

## 2 配置骨架

```json
{
  "name": "{{slug}}",
  "kind": "deep",
  "category": "Research",
  "description": "{{一句话：给题目 → 自己查 → 写报告}}",
  "temperature": 0.2,
  "native_tools": ["tavily_search", "web_fetch", "think_tool", "write_todos", "read_todos"],
  "skills": [],
  "subagents": [
    {
      "name": "research-agent",
      "description": "子问题研究者：给一个问题 + 保存路径，读完原文写一份带引用的笔记",
      "system_prompt": "{{见第 3 段「子代理」}}",
      "tools": ["tavily_search", "web_fetch", "think_tool"],
      "middleware": [],
      "interrupt_on": {}
    }
  ],
  "middleware": [{"type": "todo_list", "enabled": true, "config": {"auto_track": true}}],
  "system_prompt": "{{见第 3 段「主 agent」}}"
}
```

`kind: deep` 是必要的：harness 自带 `ls/read_file/write_file/glob/grep`，
报告落盘和自查都靠它。`todo_list` 是进度条，不是装饰。

## 3 提示词骨架

主 agent：

```
你是研究主管。用户只给题目，你自己拆、自己查、自己写。

## 流程
1. write_todos 列出 3–5 个子问题
2. 每个子问题派一次 task 给 research-agent，**描述里写清保存路径**
3. 每次搜索后 think_tool 一次：够了吗？还缺什么？
4. 汇总写 generated/{{目录}}/final_report.md
5. 回答用户：只给结论 ≤{{N}} 行 + 报告路径

## 硬契约
- 报告写进文件，**不要复制到聊天里**
- 引用编号 [1][2] 连续，末尾 `### Sources` 列 URL
- 证据不足的部分标"证据不足"，不要补猜测
- 子代理回报 ≤500 字
```

子代理：

```
你是子问题研究者。只研究给你的那一个问题。
1. 搜 2–4 次，读 1–2 篇原文（web_fetch）
2. 每次搜索后 think_tool
3. 笔记写到指定路径，含引用 URL
4. 回报 ≤500 字：结论 + 关键数字 + 来源数
```

## 4 工具与 middleware

| 项 | 必选 | 说明 |
|---|---|---|
| `todo_list` middleware | 必选 | 多步子问题的进度靠它，否则中断后无法续 |
| `think_tool` | 必选 | 每次搜索后强制收束，防止无限搜 |
| `write_todos`/`read_todos` | 必选 | 与 todo_list 配套 |
| 主 agent 搜索工具 | 可省 | 让子代理搜，主 agent 只核对；两边都搜会重复烧预算 |
| `research-agent` | 必选 | 隔离上下文，主 agent 只收摘要 |

## 5 rubric 模板

```
R1 有报告：generated/{{目录}}/final_report.md 存在，≥{{N}} 字，含 ### Sources
R2 有引用：正文出现连续编号 [1][2][3]，与 Sources 条数一致
R3 查了真资料：tool sequence 里搜索 ≥2 次，web_fetch ≥1 次
R4 交了摘要：聊天回答 ≤{{N}} 行，且不含整段报告
R5 诚实：问一个几乎查不到证据的题目，应出现"证据不足"而不是编造
```

## 6 实测基线

- 案例 10（327）：一轮 5 次 `tavily_search` + 2 次 `think_tool`，报告落 `generated/research/`
- **已知缺陷**：`web_fetch` 仍跑到 11 次（预算写在提示词里，平台没有调用上限中间件）
  → rubric 里对 `web_fetch` 断言的阈值要现实，或先把预算写得更硬

## 7 失败对照

| 症状 | 原因 | 改法 |
|---|---|---|
| 搜十几次还在搜 | 提示词没写预算，也没有 `think_tool` | 第 3 段写"最多 N 次搜索"，每搜一次 think_tool |
| 报告只在聊天里，没文件 | 交付契约没写死 | 第 3 段「硬契约」第一条 |
| 主 agent 抢子代理的活 | 主 agent 也有搜索工具 | 主 agent 去掉 `tavily_search`，只留核对用的 `web_fetch` |
| 引用编号乱 | 没要求连续编号 + Sources 段 | rubric R2 断言条数一致 |
| 结果被截断、主 agent 以为没查到 | 平台把大工具结果截成 500 字预览 | 让子代理把原文写文件，主 agent 读文件 |
