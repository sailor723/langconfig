# T4 · 技能驱动的 agent

> 提炼自：案例 8（319）、案例 11（328）· 事实见 `facts/case-facts.md`
> 反例警告：案例 8 的 agent **自己没有挂技能**（`skills: []`），它靠读工作区 `skills/` 目录
> 演示概念。照抄它会得到一个"讲技能但没有技能"的 agent。

## 1 适用场景

用：领域知识**长、不常用、还要能单独改**（写作规范、SQL 约定、行业口径），
运行时只给目录、用到再读全文。
**不要用**：知识很短（直接写提示词）；知识需要隔离上下文执行（用子代理 → T2）。

判据一句话：**这份知识三天不用一次，但用的时候一字不能错**。

## 2 配置骨架

```json
{
  "name": "{{slug}}",
  "kind": "normal",
  "category": "{{category}}",
  "description": "{{一句话：做什么，按哪份技能做}}",
  "temperature": 0.3,
  "native_tools": ["skill", "{{产出工具：write_file 等}}"],
  "skills": ["{{skill-id-1}}", "{{skill-id-2}}"],
  "subagents": [],
  "middleware": [],
  "system_prompt": "{{见第 3 段}}"
}
```

**`skills` 必须真的填**（案例 8 的教训）。技能 id 先用 `search_skills` /
`pg_list_skills` 查，别凭名字猜。

库里没有现成的就用 `create_skill` 造一个。**技能在这平台上是两份东西**：
`skills` 表里的一行 + `backend/skills/personal/<owner>/<skill_id>/SKILL.md` 这个文件。
`create_skill` 两个都写（带 frontmatter：name/description/version/author/tags/triggers/
allowed_tools），返回磁盘路径；`update_skill` 改完会写回同一个文件。
support files（模板、参考表、脚本）放进同一文件夹，用
`skill("<id>", file="<相对路径>")` 取——它们不会随正文一起加载。

## 3 提示词骨架

```
你是 {{角色}}。{{一句话职责}}。

## 先选技能
可用的技能见目录。按用户要的产出选一个：
- {{触发词 A}} → skill("{{skill-id-1}}")
- {{触发词 B}} → skill("{{skill-id-2}}")
选完先读全文，再动笔；不要凭印象写。

## 产出
{{格式、路径、必备字段}}
回答里给结论 + 文件路径，≤{{N}} 行。

## 常量 vs 变量
- 长期不变的语气/口径 → 放 AGENTS.md（每次运行都在）
- 长而具体的规格 → 放技能（用到才读）
不要把两者混在一处。
```

## 4 工具与 middleware

| 项 | 必选 | 说明 |
|---|---|---|
| `skill` | 必选 | 按 id 取全文（progressive disclosure） |
| `skills` 字段 | 必选且非空 | 这是"已挂载"清单，空 = 技能库对它不可见 |
| 产出工具 | 按需 | `write_file`（normal agent 不自带） |
| middleware | 通常无 | 需要审批再挂 `hitl` |

## 5 rubric 模板

```
R1 选技能：探针里 tool sequence 出现 skill("{{skill-id}}")
R2 按规格：产出里出现技能规定的必备字段（{{字段}}）
R3 常量生效：输出语气符合 AGENTS.md 里的设定（{{口吻}}）
R4 不越界：技能没覆盖的请求，明说不覆盖，不自行发明规范
```

## 6 实测基线

- 案例 11（328）：deep + 2 个技能（`blog-post`、`social-media`）+ 3 子代理；技能内含
  产出路径与自检清单
- 案例 8（319）：只有 `skill` + `python_execute` 两个工具，技能清单为空（反例）

## 7 失败对照

| 症状 | 原因 | 改法 |
|---|---|---|
| 从不调用 `skill` | 提示词没说"先读全文" | 第 3 段写成硬动作 |
| 技能加载失败 | 技能 id 错，或 `skills` 字段空 | `search_skills` 查 id，填进 `skills` |
| 把技能名当子代理 | 技能 ≠ 子代理（案例 11 踩过：`blog-post` 被写成 0 工具子代理） | 技能进 `skills`，子代理只放真正要隔离执行的 |
| 规格每次都要重复讲 | 长文写在了提示词里 | 搬到 SKILL.md，提示词只留触发词 |
