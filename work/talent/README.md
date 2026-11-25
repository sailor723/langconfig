# work/talent — 这个目录只放**产物与数据**，叙述型文档在 `docs/talent/`

| 这里的东西 | 性质 |
|---|---|
| `OVERVIEW.md` · `flow.svg` · `CATALOG.md` · `catalog.json` | **生成物**，`--check` 校验是否最新，不要手改 |
| `STATUS.md` | 工作记录（按日期追加） |
| `field_schema.yaml` · `component_catalog.yaml` · `requirement_library.yaml` · `labels_en.yaml` | 标准定义（判定读的是这些） |
| `templates/standard_{jd,cv}_template.yaml` | 公司标准模板（`build_templates.py` 生成） |
| `company_profile.yaml` · `fake_names.yaml` · `interview_policy.yaml` · `priority_catalog.yaml` | 本仓库专有的画像/假名/策略/优先条件 |
| `jd_links/` `jd_draft/` `jd_docs/` `jd_requirements/` `shortlist/` `picks/` `verdicts/` `cv_docs/` `cv_interview/` `open_questions/` `template_fill/` `tutorial/` | 五步流程的产物（按 JD / 按人） |
| `cv_facts.json` · `hr_facts.json` · `cv_quality.json` · `ontology_facts.json` | 事实层（判定读的是这些） |
| `_retired/` | 历史快照，只读 |

**流程怎么走** → `docs/talent/PROCESS.md`；**为什么这么设计** → `docs/talent/decisions/`；
**机器怎么配** → `docs/installation/installation.md` §1.1。
