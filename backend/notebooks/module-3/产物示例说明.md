# Phase 1 产物示例说明

本文件用于说明 Phase 1 Agent 运行后，建议生成哪些产物，以及这些产物应该具备什么特征。

## 1. `artifacts/prd.md`

这是 Phase 1 最重要的中间产物，建议包含：

- 项目基本信息
- 背景与问题
- 产品目标
- 使用者与场景
- Agent 定位
- 核心流程
- 功能需求
- 能力边界
- 资料与工具
- 失败与兜底
- 评估指标
- 验收标准
- 风险与依赖

同时建议在文档末尾保留：

- 缺失字段清单
- 模糊字段清单

## 2. `artifacts/prd_draft_review.md`

该文件用于说明 PRD 草稿是否正确提取了用户输入，建议包含：

- 评审总结
- 评分维度
- 发现的问题
- 修改建议
- 状态：`pass / revise / blocked`

## 3. `artifacts/question_review.md`

如果 Agent 生成了澄清问题，则建议对问题质量进行评审，重点检查：

- 是否问题太多
- 是否问题太泛
- 是否问题真的能补齐关键字段
- 是否误入 Phase 2 技术实现细节

## 4. `artifacts/system_prompt.md`

最终系统提示词建议至少包含：

- Identity
- Background
- Mission
- Success Criteria
- Knowledge And Tools
- Guardrails
- Approval Rules
- Failure And Fallback
- Workflow Steps

## 5. `artifacts/system_prompt_review.md`

该文件用于评审系统提示词，建议重点检查：

- 是否完全对齐最终 PRD
- 是否存在无依据扩展
- 是否足够具体
- 是否具备安全边界与审批规则
- 是否便于业务方评审

## 理想运行结果

一个理想的 Phase 1 流程，不应该只是“生成一段漂亮文字”，而应该做到：

1. 先整理
2. 再评审
3. 再提问
4. 再补齐
5. 再生成系统提示词
6. 最后再评审系统提示词
