---
name: reviewer
description: 当需要评审 PRD 草稿、澄清问题、最终 PRD 或系统提示词时，使用此技能输出标准化评审结果与 pass/revise/blocked 状态。
---

# Phase 1 评审技能

## 目标

对 Phase 1 的关键输出进行标准化评审，确保：

- 输出完整
- 输出正确
- 输出一致
- 输出具体
- 输出安全
- 输出可审查

## 可评审对象

你可以评审以下内容：

1. PRD 草稿
2. 澄清问题
3. 最终 PRD
4. 系统提示词

## 输出文件建议

根据评审对象不同，写入以下文件之一：

```text
artifacts/prd_draft_review.md
artifacts/question_review.md
artifacts/review.md
artifacts/system_prompt_review.md
```

## 输出格式

评审输出必须包含以下部分：

```markdown
# 评审结果

## 评审对象
## 总结
## 评分维度
- 维度名：X/5

## 发现的问题
- ...

## 修改建议
- ...

## 最终状态
pass / revise / blocked
```

## 状态定义

- `pass`
  - 当前结果可以进入下一步
- `revise`
  - 当前结果需要修改后重试
- `blocked`
  - 当前阶段不能继续，必须先由用户补充信息或确认

## 关键规则

- 不要只给笼统表扬，必须指出具体问题
- 不要把“看起来不错”当成通过标准
- 如果存在关键缺失，不允许给出 `pass`
- 必须优先保护准确性与边界安全

## 完成标准

在以下条件满足前，不视为完成：

- [ ] 已明确评审对象
- [ ] 已按固定结构输出评审结果
- [ ] 已给出具体问题与建议
- [ ] 已明确最终状态
