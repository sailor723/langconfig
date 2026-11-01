# T3 · handoff 状态机

> 提炼自：案例 5（325）、案例 7（314）· 事实见 `facts/case-facts.md`

## 1 适用场景

用：**同一段对话里流程有几步**，每步"该做什么、不许做什么"不一样，用户不该重开对话
（售后、审批、开户、售前转技术）。
**不要用**：几件事可以并行做（→ T2）；只要一个 agent 干一件事（→ T1）。

判据一句话：**同一时刻只有一个角色说话，而角色会变**。

## 2 配置骨架

```json
{
  "name": "{{slug}}",
  "kind": "normal",
  "category": "{{category}}",
  "description": "{{一句话：几个阶段，各自干什么}}",
  "temperature": 0.0,
  "native_tools": ["{{最后一步才需要的工具，如 write_file}}"],
  "skills": [],
  "subagents": [],
  "middleware": [
    {
      "type": "handoff",
      "enabled": true,
      "config": {
        "state_field": "handoff_to",
        "default_step": "{{step_1}}",
        "steps": {
          "{{step_1}}": {
            "label": "{{阶段显示名}}",
            "description": "{{这一步的判断标准}}",
            "system_prompt": "你是…当前阶段：{{阶段}}。{{这一步只做什么}}。做完调用 transfer_to_{{step_2}}。",
            "tools": [],
            "transfers": [{"to": "{{step_2}}", "description": "{{什么条件下进下一步}}"}]
          },
          "{{step_2}}": {
            "label": "{{阶段显示名}}",
            "system_prompt": "…",
            "tools": ["{{这一步才解锁的工具}}"],
            "transfers": [{"to": "{{step_3}}", "description": "…"}]
          },
          "{{step_3}}": {
            "label": "{{阶段显示名}}",
            "system_prompt": "…",
            "tools": ["write_file"],
            "transfers": [{"to": "{{step_1}}", "description": "用户说信息有误 → 回去改"}]
          }
        }
      }
    }
  ],
  "system_prompt": "你是 {{入口角色}}，从 {{step_1}} 开始。"
}
```

**主提示词只写一句**。案例 5 是 17 字、案例 7 是 18 字——真正的提示词在每步的
`system_prompt` 里。把阶段规则写进主提示词会覆盖掉步骤定义，是最常见的错法。

## 3 提示词骨架

每步一个，三段式：

```
你是 {{角色}}，当前阶段：{{阶段名}}。
1) {{这一步先问/先做什么}}
2) {{这一步的判断}}
3) 做完必须调用 transfer_to_{{下一步}}（这就是把"{{事实}}"记下来）
阶段事实在对话历史里，自己回看，不要重复问。
```

最后一步额外写**产出契约**：

```
回答最多 {{N}} 行，细节写进 generated/{{目录}}/<时间戳>-<类型>.md
文件名不要用客户名（会让第二个客户覆盖第一个）
```

## 4 工具与 middleware

| 项 | 必选 | 说明 |
|---|---|---|
| middleware | `handoff`（唯一） | 它自动生成 `transfer_to_<step>`，**不用另外配工具** |
| 每步 `tools` | 按需 | **工具集就是闸门**：第一步手里没有"进下一步"之外的写工具，顺序就乱不了 |
| 主 agent 工具 | 通常空或仅最后一步的 | 案例 5 只有 `write_file`（其实那一步已单独声明） |
| 子代理 | 无 | 状态机是单 agent，加子代理会让阶段判断漏掉上下文 |

## 5 rubric 模板

```
R1 顺序：第一轮回答只做第一步（问 {{保修/身份}}），不跳到方案
R2 推进：回答后 tool sequence 出现 transfer_to_{{step_2}}
R3 闸门：{{step_1}} 执行期间，{{写类工具}} 不可用（tool 列表里没有）
R4 回退：用户说"{{信息有误}}"，出现 transfer_to_{{step_1}} 而不是重新开始
R5 产出：最后一步写出 generated/{{目录}}/…md，文件名不含客户名
```

## 6 实测基线

- 案例 5（325）：3 步 `warranty_collector → issue_classifier → resolution_specialist`，
  每次跳转都落 `handoff_from`/`handoff_to`，验收脚本记到 3/3
- 案例 7（314）：3 角色 `sales → support → finance`，主提示词 18 字

## 7 失败对照

| 症状 | 原因 | 改法 |
|---|---|---|
| 一步到位，不问保修 | 提示词没锁第一步；或第一步就有写工具 | 第一步 `tools: []`，提示词写"不要一次问多个问题" |
| 跳步/回退成新对话 | 忘了 `transfers` 回边 | 最后一步加 `to: {{step_1}}` 并写清触发条件 |
| 阶段事实丢失 | 把状态写进 prompt 插值（平台没有可编辑 state） | 事实留在**对话历史**，提示词写"自己回看" |
| 主提示词很长 | 把三步规则都写进主提示词 | 拆回 steps，主提示词只留一句入口 |
