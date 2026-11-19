# team-4 CV↔JD 推荐系统 · 总审阅

> 审阅日期 2026-11-19 · 语料 277 份简历 × 10 份职务说明书
> 方法:每个数字都在本机重跑过一遍,命令写在第 8 节。本文不引用记忆,只引用可复现的结果。
> 分级:**P0** = 会给出错误答案且不报错 · **P1** = 答案对但会误导 · **P2** = 工程债

---

## 一页结论

1. **管道是通的,而且是端到端可验证的。** 277 份扫描件 → OCR → ABox → HermiT → PG 表 → 名单,两处门禁全绿(`check_abox` 54 项 / `check_abox_sync` 14 项)。
2. **结果不能用来排序,可以用来披露。** 95 条原子要求只有 16 条能机判(17%),这是所有分数的天花板。任何"匹配度 92"都只是在这 17% 上算的 92。
3. **四个岗位共用一把尺子。** 业务助理 / 副总助理 / 工程文员 / 管理课长的合格名单是**同一个 55 人集合**(集合相等性已逐对验证)。
4. **副总助理 26% 的推理结果建立在两个抽取错误上。** 137 人被蕴含,删掉两个误抽技能后剩 102 —— 那 35 人是因为"KPI"被读成薪酬绩效、"AI"被读成 Illustrator。
5. **品质经理 0 人合格,不是没人合适。** 闸门要 英语 ∧ 5S,两个人群交集为 0,且简历池里没有品保文件夹。
6. **最大的工程风险不是算法,是静默失败。** `build_abox.py` 不传 `--requirements` 时不报错,直接丢掉 JD 那一半 —— 这已经发生过一次。

---

## 1 · 语料与实测覆盖

| 项 | 实测 | 说明 |
|---|---|---|
| 简历文件 | **277** | 文件夹名写 307,实测 277 份 PDF |
| 可提取字符 | **0** | 全是扫描件:每页一个 `/Image`,无 `/Font`、无 `/ToUnicode` |
| 因此文本来源 | OCR | 200 dpi · `chi_sim+eng` · 按 sha256 缓存 |
| 简历文件夹 | 3 | `03管理科+副总室` / `04技术课` / `07业务课` |
| 职务说明书 | **10** | `.doc` ×6 · `.docx` ×1 · `.xlsx` ×2,无统一模板 |
| 重复扫描件 | 7 | 同一人多次投递,`owl:sameAs` 标记 |
| 技能个体 | 53 | `:skill_*`,分 **22 个类别**(TBox 与 DB 均为 22,一致) |
| hasSkill 断言 | **1549** | 274/277 人至少有一条 |

**字段覆盖(这是所有评分的天花板)**

| 字段 | 读到 | 覆盖率 |
|---|---|---|
| 技能 | 274 / 277 | 99% |
| 学历 | 206 / 277 | **74%** |
| 年限 | 148 / 277 | **53%** |
| 年龄 | 107 / 277 | **39%** |
| 性别 | 0 / 277 | **0%**(无该属性) |
| **三者齐备** | **1 / 277** | **0.4%** ← 这是决定 D10 的直接依据 |

> 三个维度做 AND 会塌成 1 个人。这就是"年限/学历退出成员判定、只参与计分"的原因,不是妥协而是算术。

---

## 2 · 文件地图

### 2.1 代码(17 个脚本,`backend/scripts/talent/`)

| 文件 | 作用 | CLI | 提交 |
|---|---|---|---|
| `extract.py` | 277 份扫描件 → `candidates.jsonl` | ✓ 9 参数 | ✓ |
| `extract_jd.py` | 10 份职务说明书 → `requirements.json` | ✓ 3 参数 | ✓ |
| `parse.py` | **库**:CV 侧词表与正则 | — | ✓ |
| `jd_parse.py` | **库**:JD 侧正则(无 CLI,常被误认成脚本) | — | ✓ |
| `build_abox.py` | jsonl(+requirements)→ `abox.ttl` | ✓ 5 参数 | ✓ |
| `author_tbox.py` | jsonl+requirements → `reasoning.ttl` + `reasoning.json` | ✓ 5 参数 | ✓ |
| `materialize.py` | 两个 TTL → HermiT → PG 表 | ✓ 3 参数 | ✓ |
| `fit.py` | **库**:权重与排序键(v1 / v2 两套) | — | ✓ |
| `shortlist.py` | 建 `fit_component` + `v_shortlist` + `v_axiom_vs_gate` | ✓ 4 参数 | ✓ |
| `skill_patterns_ext.py` | **库**:扩展词表,26 个模式带 JD 原文证据 | — | ✓ |
| `extract_probe.py` | 用扩展词表在已 OCR 文本上再抽一遍(探针) | ✓ 5 参数 | ✓ |
| `stage_extended_vocab.py` | 把扩展词表装进 ABox,**staged 不 apply** | ✓ 2 参数 | ✓ |
| `gen_from_ontology.py` | 从 `:Requirement` 类生成表行(TTL→表) | ✓ 2 参数 | **✗ 未提交** |
| `ask_reasoner.py` | 同一问题跑两遍:断言 vs 蕴含 | ✓ 6 参数 | ✓ |
| `make_tutorial.py` | 生成 8 章教学章节 | ✓ 2 参数 | ✓ |
| `check_score_models.py` | 分数目录的结构校验 + 9 条门禁实跑 | ✓ 1 参数 | ✓ |
| `__init__.py` | 包说明 | — | ✓ |

**注:`materialize.py` 同时干"推理"和"投影"两件事**,第 ③④ 层在文件层面不是分开的。

### 2.2 本体产物(`backend/features/ontology/profiles/talent_v1/`)

| 文件 | 大小 | 内容 | 生成者 |
|---|---|---|---|
| `abox.ttl` | 141K | 277 人 · 53 技能 · 1549 hasSkill · 10 个 `:role_*` | `build_abox.py` **+ 手工补的 role 块** |
| `reasoning.ttl` | 7.0K | 7 个 `:matches_*` 定义类 + 7 个 `:skillsFor_*` 类别并集 | `author_tbox.py` |
| `reasoning.json` | 8.5K | 推理**预期**(纯 Python 第二路线算的) | `author_tbox.py` |
| `ontology/01-structure.ttl` | 40K | Palantir 式物理映射(`:physicalTable` / `:primaryKey` / `:references`) | 手写 |
| `metrics_ext.ttl` | 16K | 指标声明 | 手写 |
| `talent_v1_settings.json` | 11K | profile 声明(`ns` / `abox` / `reasoning` / 门禁) | 手写 |
| `dashboard.json` · `samples.json` · `steps.json` · `truth.json` · `tutorial.json` | — | 看板与教学 | 编译器 |
| `ontology.html` | 162K | 渲染出的看板 | 编译器 |

### 2.3 文档(`work/talent/`)

| 文件 | 提交 | 内容 |
|---|---|---|
| `score_models.yaml` | ✓ | **6 个分数的目录**:名字/分母/闸门/可比范围 + 9 条可执行门禁 |
| `skill_map.yaml` | ✓ | 技能词表(被 `skill_patterns_ext.py` 读取) |
| `D11_two_sources_of_truth.md` | ✓ | 决定 D11:权威在公理还是表,选 C 的理由与边界条件 |
| `B_experiment.md` | ✓ | 复合要求为什么是"副总助理 0 人"的病因 |
| `grill.md` | ✓ | 已定决定清单 |
| `stage_extended_vocab.md` | ✓ | 扩展词表 apply 前后对比 |
| `jd_schema.yaml` | **✗** | L1/L2/L3 分类 + 宣称的 G1–G7 门禁(**无执行者**) |
| `jd_requirements_all10.md` | **✗** | 95 条原子要求逐条清单(唯一的全量来源) |
| `jd_taxonomy_L1_L2_L3.md` | **✗** | 三层分类:8 分区 42 字段 / 9 维度 / 5 族 6 级 |
| `requirement_taxonomy.md` | **✗** | 要求分类方案 |
| `jd_standard_副总助理.md` | **✗** | 单岗标准说明书 |
| `talent_db_before_*.dump` | 忽略 | 3 份库快照,253K,`.gitignore` 排除 |

### 2.4 测试(57 个断言)

| 文件 | 断言数 |
|---|---|
| `test_talent_parse.py` | 12 |
| `test_talent_fit.py` | 10 |
| `test_talent_score_models.py` | 10 |
| `test_talent_abox.py` | 9 |
| `test_abox_gate.py` | 9 |
| `test_abox_reasoning.py` | 7 |
| **合计** | **57** |

### 2.5 已丢失的中间产物(2 个)

| 文件 | 原路径 | 状态 | 重建成本 |
|---|---|---|---|
| `candidates.jsonl` | `/tmp/team4/` | **没了** | **高** —— 277 份扫描件 OCR,`ocr-cache` 也没了 |
| `requirements.json` | `/tmp/team4/` | **没了** | **低** —— 10 份文档,纯文本抽取,秒级 |

**但内容没有真的丢:**
- `candidates.jsonl` 的全部字段(技能/年限/学历/投递岗/来源文件/缺失标记)都已固化在 `abox.ttl`;
- `requirements.json` 的学历·年限·技能·缺失项已固化在 `abox.ttl` 的 10 个 `:role_*` 个体(含 4 条 `:notStated`)。

**真正不可恢复的只有一件事:原始 OCR 文本。** 想改进抽取(比如修掉 `skill_Illustrator`)必须重跑 OCR。这是唯一的硬损失。

---

## 3 · 代码链路

```
① 抽取      extract.py ──→ candidates.jsonl        (277 份 PDF,OCR)
            extract_jd.py ─→ requirements.json     (10 份 Word/Excel,无 OCR)
                 ↑ 两侧共用 parse.py / jd_parse.py 的词表
② 生成      build_abox.py ──→ abox.ttl            (事实)
            author_tbox.py ─→ reasoning.ttl        (规则) + reasoning.json(预期)
③ 推理      materialize.py → reasoner.py(HermiT)
④ 投影      materialize.py ──→ candidate / candidate_skill / candidate_match
                                / candidate_role_fit / reasoning_run
⑤ 闸门      check_abox.py      HermiT ↔ reasoning.json(纯 Python 第二路线)+ 变异测试
            check_abox_sync.py HermiT ↔ PG 表(逐行)
```

第 ⑤ 层是**两道不同的比对**,不能混成一句:

| 门禁 | 拿什么跟什么比 | 防止什么 |
|---|---|---|
| `check_abox.py` | 重跑 HermiT ↔ `reasoning.json` | 用一个推导验证它自己 |
| | 蕴含成员**不许**在 ABox 里被断言 | "推理结果"其实是手写进去的 |
| | 删一条断言再推,蕴含必须消失 | 公理根本没起作用 |
| `check_abox_sync.py` | 重跑 HermiT ↔ `candidate_match` / `candidate_role_fit` / `reasoning_run` | 表是旧的、手改的、或被等价 SQL 重写过 |

**当前状态:54 项 / 0 失败,14 项 / 0 失败。**

---

## 4 · 结果(实测)

### 4.1 推理 —— 只有推理机能回答的部分

```
reasoning_run: 2026-11-16 07:51 · 719 ms · hermit · consistent = true · 277 candidates
candidate_match: 752 行 / 7 个岗(10 岗中 7 岗有公理)
```

| 岗 | 蕴含人数 | 备注 |
|---|---|---|
| 业务跟单 | 175 | |
| 副总助理 | 137 | 其中 26% 靠两个误抽技能,见 P0-2 |
| 品质经理 | 114 | |
| 招聘专员 | 97 | |
| 管理课长 | 97 | |
| 专案工程师 | 78 | |
| 业务助理 | 54 | |
| 人资专员 / 工程文员 / 关务报关员 | — | **无公理**(JD 未写年限门槛) |

> 关键:这 752 行**不在任何文件里**。搜 `abox.ttl` 找不到"谁匹配",因为那是蕴含出来的。删掉 `:matches_*` 的定义,立刻回到 0。

### 4.2 闸门与评分 —— 表侧

```
fit_component:      9972 行(每条要求一行:要求/实际/权重/贡献/缺什么)
v_shortlist:        2770 行 = 277 人 × 10 岗(**所有人和所有岗都算,不只看投递**)
                    qualified 299 · near 60 · excluded 2411
candidate_role_fit: 731 行(推理结果 − 7 份重复简历 = 752 − 21)
```

`752 − 731 = 21` 已查清:**全部是重复简历**,7 份重复件 × 每人约 3 个岗。排序表故意排除重复,否则真人会因重复文件被挤下一名(`materialize.py:328`)。**这不是缺陷。**

### 4.3 对撞 —— 两边的话

```
v_axiom_vs_gate:
  agree_qualified  143   两边都说合格
  axiom_only       609   推理说"会",闸门说"不够"     ← 单用任何一边会漏掉 4 倍于合格者的一批
  gate_only        156   闸门说"够",推理推不出来
  agree_rejected  1862
```

### 4.4 三个反常结果,以及它们各自的原因

**① 四个岗位的合格名单是同一个人群**

```
业务助理 55 · 副总助理 55 · 工程文员 55 · 管理课长 55
集合相等性:业务助理 == 副总助理 (true) · 工程文员 == 管理课长 (true)
```
原因是四个岗的可判定必备要求都塌成同一句「Office 三件套任取其二」,而 Office 三件套持有 ≥2 项的人恰好 55 个。
**后果:现在的分数无法区分这四个岗。**

**② 品质经理 0 人合格**

闸门要 英语 ∧ 5S 同时满足:`skill_英语` 99 人,`skill_5S` 5 人,**交集 0**。
且简历只有 3 个文件夹(管理科/技术课/业务课),**没有品保**。
**这不是"无人合格",是"闸门与投递池不相交"。**

**③ 74% 的合格者处在同分并列**

299 名合格者里 **222 人**同岗同分,69 个并列组,最大组 6 人。
**所以"按匹配度排序"不成立** —— 实际排序键是(覆盖率, 完备度, 年限)。

### 4.5 要求层只覆盖了 17% —— 天花板在这里

95 条原子要求 → 入库 31 条(33%)→ 可判定 16 条(17%)。

副总助理是极端个例:JD 写了 16 条,库里只有 2 条。其中「女性」「25-38 岁」**在 JD 原文里逐字可查,但库里没有对应行**。

> 这两条是**从未入库**,不是被删除。恢复路径是把它们入库并执行(age 已有 107/277 可读,gender 需要新属性),不是把要求删掉。见 `score_models.yaml` 的 `open.O2`。

---

## 5 · 缺陷清单

### P0 —— 会给出错误答案且不报错

| # | 缺陷 | 证据 | 后果 |
|---|---|---|---|
| **P0-1** | `build_abox.py --requirements` 是**可选**参数,不传时 `if requirements:` 整块跳过,不报错 | `build_abox.py:181` `default=""`;对照 `author_tbox.py:216` `required=True` | **已发生过一次**:重新生成时 `roles 0 / ranked 0`,JD 那一半凭空消失 |
| **P0-2** | 两个误抽技能污染 26% 的副总助理蕴含 | 137 人删掉这两项后剩 **102**(−35) | **JD 侧错了**:原文只要「Office(Word/Excel/PPT/AI)」,却解析出 `skill_Illustrator`(从 "AI")和 `skill_薪酬绩效`(从**职责**里的「督办各部门 KPI」)。候选人侧这两项真实持有 8 / 45 人,而 `:skillsFor_副总助理` 是**类别并集** —— 持任一即匹配,于是 35 人仅凭这两项被蕴含。**类别并集把 JD 侧的一个错误放大成 35 个假阳性。** |
| **P0-3** | `abox.ttl` 不是纯生成物 | 当前 role 块是重新生成丢失后**手工补回**的 | 换个环境重跑 `build_abox.py`,10 个 `:role_*` 会再次消失,而没有任何东西会报错 |

### P1 —— 答案对但会误导

| # | 缺陷 | 证据 |
|---|---|---|
| **P1-4** | 4 个岗共用一把尺子 —— 要求粒度太粗,不是评分函数的问题 | 55 人集合完全相同 |
| **P1-5** | 空名单被读成"没人合适" | 品质经理 0 人 = 英语∩5S 空集 |
| **P1-6** | S2 分母在 1–2 之间,跨岗比较是错的 | 16 条可判定要求分布 2/2/2/2/2/2/1/1/1/1 |
| **P1-7** | 74% 同分并列,"排名"名不副实 | 222/299 |
| **P1-8** | 分数的天花板是 17% | 95 → 31 → 16 |
| **P1-9** | 完备度低的会出现"满分" | 合格名单里 20 人完备度仅 60%(只有技能被观测到;全表 76 人) |

### P2 —— 工程债

| # | 缺陷 | 证据 |
|---|---|---|
| **P2-10** | `gen_from_ontology.py` 未提交,且读到 **0 行** | `reasoning.ttl` 里 `:Requirement` 类 = 0 |
| **P2-11** | `jd_schema.yaml` 宣称的 G1–G7 门禁**无任何代码执行** | `grep -rl jd_schema.yaml backend/` → 空 |
| **P2-12** | 4 个岗的 `:appliedFor` 指向**未声明**的 `:Role` 个体 | 被引用 12 个、被声明 10 个:多 行政专员/技术经理主管/设计工程师/实验室技术员;少 品质经理/关务报关员(0 人投递) |
| **P2-13** | 54 人投递到**没有 JD** 的岗位 | 行政专员 28 + 技术经理主管 14 + 设计工程师 10 + 实验室技术员 2 = **19.5%** |
| **P2-14** | 没有导出层 | 结果只在 PG 里;想给 HR 只能贴 stdout 或导 dump。没有任何 xlsx/CSV/PDF |
| **P2-15** | 5 个文档 + `talent_steps` profile 未提交 | 含 95 条要求的唯一全量来源 `jd_requirements_all10.md` |

---

## 6 · 状态表

| 环节 | 状态 | 说明 |
|---|---|---|
| OCR 抽取 | ✅ 完成 | 277/277,缓存键 sha256+dpi+lang |
| JD 解析 | ✅ 完成 | 三种格式统一,缺失项报 `missing` 不填默认值 |
| ABox 生成 | ⚠️ 部分 | role 块当前是手工补的(P0-3) |
| TBox 生成 | ✅ 完成 | 7/10 岗有公理,3 岗因 JD 无年限门槛而跳过(已记录理由) |
| 推理 | ✅ 完成 | HermiT 719 ms,一致 |
| 推理投影到 PG | ✅ 完成 | `check_abox_sync` 逐行验证 |
| 闸门 + 评分 | ✅ 完成 | 299/60/2411 |
| 分数定义 | ✅ 完成 | 6 个分数,9 条门禁,6 成立 |
| 要求模型 | ⚠️ 部分 | 95 条里 31 条入库、16 条可判 |
| 要求 → TTL 单一真源 | ❌ 未开始 | `gen_from_ontology.py` 读到 0 行(P2-10) |
| 导出 | ❌ 未开始 | 无 xlsx/CSV/PDF(P2-14) |
| 界面 | ⚠️ 部分 | `ontology.html` 看板存在,但读同几张表 |

---

## 7 · 下一步(按 ROI)

| 序 | 做什么 | 解锁什么 | 成本 |
|---|---|---|---|
| **1** | 把 `build_abox.py --requirements` 改成 `required=True` | P0-1/P0-3 —— 让生成变成可信的 | 1 行 |
| **2** | 加抽取门禁:每个技能必须能在原文找到逐字依据(**G2 落地**) | P0-2 —— 挡掉"AI→Illustrator"这类错误 | 中 |
| **3** | 补 `major` 属性 | 6 条要求可判(B 维最高 ROI) | 低 |
| **4** | 把 95 条要求全部入库 | S2 分母从 1–2 升到 3–6,**打散 74% 的并列** | 中 |
| **5** | 副总助理 A 维两条入库并执行(女性 / 25–38 岁) | P2 恢复 + 兑现"保留并执行" | 低(age 已有;gender 需新属性) |
| **6** | 修 P1-4:让四个 Office 岗的尺子分开 | 4 个岗不再共用同一份 55 人名单 | 中 |
| **7** | 写 `jd.ttl`,让 `gen_from_ontology.py` 有货可读 | 要求层"一处定义两处消费" | 中 |
| **8** | 加 `--export xlsx` | 结果能交给人评审 | 低 |

第 1 项是一行改动,却是唯一一个"已经出过事故"的点。建议先做它。

---

## 8 · 复现

```bash
cd /Users/weiping/dev/Learn/langchain-ai/langconfig/backend
set -a && source ../.env; set +a       # ONTOLOGY_DB_* 必须显式加载
unset PGPORT                           # 本机 shell 的 PGPORT=5432 会劫持默认值

# 两道门禁
env -u PGPORT .venv/bin/python features/ontology/gates/check_abox.py \
    --profile features/ontology/profiles/talent_v1/talent_v1_settings.json
env -u PGPORT .venv/bin/python features/ontology/gates/check_abox_sync.py \
    --profile features/ontology/profiles/talent_v1/talent_v1_settings.json

# 分数门禁(结构 + 9 条 SQL)
env -u PGPORT .venv/bin/python -m scripts.talent.check_score_models

# 名单
env -u PGPORT .venv/bin/python -m scripts.talent.shortlist --report
env -u PGPORT .venv/bin/python -m scripts.talent.shortlist --report --role 业务跟单 --top 10

# 重建已被清理的中间产物(便宜的那个)
env -u PGPORT .venv/bin/python -m scripts.talent.extract_jd \
    --input ../client/team-4/unzipped/职务说明书10份 --out /tmp/team4/requirements.json

# 测试
.venv/bin/python -m pytest tests/test_talent_*.py tests/test_abox_*.py -q
```

**环境陷阱(必须记住):** 本机 shell 导出过 `PGPORT=5432`,而 libpq 会静默读它 —— 于是 `os.environ.get("PGPORT", "5433")` 拿到 5432,报一个看起来像"角色不存在"的假错。所有独立脚本必须用 `ONTOLOGY_DB_*` 并 `env -u PGPORT`。

---

## 9 · 数字速查

| 数字 | 值 | 出处 |
|---|---|---|
| 简历 / JD | 277 / 10 | 实测 |
| 技能 / hasSkill | 53 / 1549 | `abox.ttl` |
| 学历 / 年限 / 年龄 覆盖 | 74% / 53% / 39% | `candidate` 表 |
| 三者齐备 | **1 / 277** | 同上 |
| 公理数 | 7(10 岗中) | `reasoning.ttl` |
| 推理耗时 | 719 ms | `reasoning_run` |
| 蕴含总数 | 752 | `candidate_match` |
| 排除重复后的排序行 | 731 | `candidate_role_fit` |
| `fit_component` | 9972 | 每条要求一行 |
| 合格 / 接近 / 排除 | 299 / 60 / 2411 | `v_shortlist` |
| 两边都合格 / 只说会 / 只说够 / 都否 | 143 / 609 / 156 / 1862 | `v_axiom_vs_gate` |
| 原子要求 → 入库 → 可判 | 95 → 31 → 16 | `jd_requirements_all10.md` / `requirement` |
| 同分并列 | 222 / 299(74%) | `v_shortlist` |
| 4 岗共用名单 | 55 人 | 集合相等性验证 |
| 副总助理蕴含受污染比例 | 35 / 137(26%) | 见 P0-2 |
| 投递到无 JD 岗位 | 54 / 277(19.5%) | `candidate` 表 |

---

## 10 · 一句话

> 这套系统**能证明自己算错了什么,不能证明自己算对了谁**。
>
> 它把 609 个"会但不够"、74% 的同分、4 个岗共用一把尺子、26% 的蕴含建立在两个错字上,全部标了出来 —— 这是它的价值。而它的天花板(17% 的要求可判)不在算法里,在**要求本身还没被结构化**这件事里。
>
> 所以下一步不是加更多评分模型,是把 95 条要求真正变成数据。
