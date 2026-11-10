---
name: "generate-mock-dataset（生成模拟数据集）"
lang: zh
translated: machine
source: backend/skills/en-originals/generate-mock-dataset/SKILL.md
description: >-
  当一段业务故事（一通客户电话、一份书面简报、一页幻灯片）必须变成一个可以拿来演示的 PostgreSQL 数据集时使用：
  确定性、体量与故事一致，把失败点栽在故事所说它们来自的地方，并有意带上数据病理（恒定列、未判定行、一条缺失记录）；
  它做出的每一条断言都是规格文件里的一条查询，而规格就是那道门禁。
tags: [mock-data, synthetic-data, postgres, dataset, demo, gating]
triggers:
  - "被要求根据描述出来的业务创建 mock / 合成 / 演示数据时"
  - "演示需要痛点**在数字里看得见**，而不是在幻灯片里被断言时"
  - "本体构建需要一个能证明自己故事的数据库时"
  - "「随便编点数据」否则就会产出回答另一些问题的那批数据时"
version: 1.0
author: weiping

# 数据集的用途决定它的形状：本体构建要维度与病理，演示要痛点，基准测试要体量。说清是哪一种，因为它会改变设计。
params:
  dataset_name:
    label: 数据集（建议名）
    description: >-
      一个**建议**，不是命令：数据最终落到的那个数据库。创建任何东西之前先跟用户确认最终名字（步骤 0c）。
      正是智能体手里的这一份参数，让它去提议一个名字，而不是悄悄发明一个。
  generator:
    label: 生成器路径
    description: 确定性生成器脚本所在的位置（例如 backend/skills/builtin/generate-mock-dataset/scripts/gen_abc.py）
    required: false
    default: "backend/skills/builtin/generate-mock-dataset/scripts/gen_{dataset_name}.py"
---

# 从一段业务故事生成模拟数据集

模拟数据与模拟**数据集**的区别：模拟数据把表填满，模拟数据集让故事的断言成真、而且**可核查**。每条断言都变成
`<dataset>.dataset.json` 里的一条查询，于是一次绿的运行意味着「数据仍然说着简报说过的话」，一次红的运行则点名那条
烂掉的断言。

## 0a. 读简报——用对的读取器

- **`.md` / `.txt` / `.json` / `.csv`** → `read_file`。
- **`.pdf` / `.docx` / `.pptx` / `.xlsx`** → `read_any_file`。它返回**文本**：标题、表格、幻灯片文字，一个 sheet
  一个 sheet 地返回。扫描件 PDF 或图片也走那里的 OCR。
- **如果一次读取回来的是 `<w:p>`、`<a:tbl>`、`PK\x03\x04` 或 base64，那你读到的是裸字节，不是文本。** 停下，不要
  拿 `unzip`/`cat`/`strings` 去撬那份文档，不要手工解它的 XML，**也绝不**把文档原样粘回去当回答。改用
  `read_any_file` 重读一遍。

这个失败是实测出来的，不是假设：一个智能体拿到 16 KB 的 Word 简报，拿到的是裸 OOXML，用 `unzip … word/document.xml`
绕过去，最后把 143 KB 的标签汤当成「交付物」返回——没有生成器，没有表，没有数据集。读输入是第零步；它之后的每一步
都依赖那份文本。

**文档不等于 schema。** 简报给出实体、粒度、体量与关系；列是你的设计。绝不要用复述简报来回答一个数据生成请求。

## 0b. 从故事里读结构，不读形容词

从简报里只抽取会变成一列、一个行数或一条关系的东西：

| 简报里的句子 | 变成 |
|---|---|
| 「约60台司机自有的冷藏车队（12吨3台、10吨5台、8吨35台、5吨6台、3吨11台）」 | `vehicles(60)`，`tonnage` 分布与所述**完全**一致（这是客户会去核对的事实） |
| 「一车一人，司机按月扣还购车贷款」 | `drivers.vehicle_id` 1:1，而缺失的 `loan_*` 列本身就是一条发现 |
| 「把原本每天约50条固定配送路线强行压缩至40条」 | `routes.version` v1/v2 + `effective_from` → 一个数据可以被切开的**制度（regime）** |
| 「几乎每趟车都在挑战超载极限」 | 发车时刻的 `load_*` 对 `*_capacity_snapshot`（是快照，不是连到今日载重的那次 join） |
| 「日结临时工，几乎每天都在换新面孔」 | `handlers(first_day, days_worked, agency)` → 人员流失变得可测量 |
| 「司机和日结工互相推诿」 | `complaints.liability` 带一个大 NULL 组——即判定缺口 |
| 「调度凭同情心排轻松线」 | **今天无法表示** → 数据集**不得**假装：记录结果（trips），让本体去拒绝这个意图 |

如果某个痛点没有对应的列，那条发现就该留着：本体将按名字拒绝它，看板会显出那个洞。不要为了把演示做得看起来完整
而发明一个代理列。

## 0c. 先起草数据集 MANIFEST——名字、单位、注意事项——并确认它

库名只是数据集身份的一个字段，不是问题的全部。先把 manifest 写出来，才让其余问题变得可回答：本体构建器读
`schema`、`units` 和 `nulls` 去写它的 profile 和公理，看板读 `units` 写标签，运维者读 `checks` 来判断眼前的数字
是不是被验证过的那批数字。

在创建任何东西之前，按下面这个形状写 `generated/<slug>/manifest.json`——简报能回答的填上，其余留 `null` 并配一条
`questions` 条目，并**把状态标成 `proposed`**：

```json
{
  "dataset":  {"name": "<proposed name>", "schema": "nass", "status": "proposed",
               "purpose": "one sentence: what this dataset exists for",
               "confirmed_by": null, "confirmed_at": null},
  "source":   {"system": "the exporting system the brief names (or 'synthesised')",
               "files": [{"name": "upload/x.docx", "sha256": "…"}],
               "generator": "generated/<slug>/gen.py", "seed": 20260101, "spec": "…dataset.json"},
  "time":     {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "days": 0, "timezone": "…",
               "relative_window": false, "as_of": "YYYY-MM-DD",
               "regimes": [{"date": "YYYY-MM-DD", "change": "what changed in the rules"}]},
  "units":    {"<column>": "boxes|kg|t|m3|HKD|%|count"},
  "nulls":    {"<table.column>": "unknown|not_judged|not_recorded|not_applicable (why)"},
  "pii":      [{"column": "<table.column>", "kind": "person_name|plate|phone", "handling": "synthetic|masked"}],
  "decisions": [{"id": "Q23", "text": "…", "source": "brief §… | chat YYYY-MM-DD", "status": "confirmed|proposed"}],
  "refused":  [{"name": "what the ontology must refuse", "why": "…", "missing": "the declaration it lacks"}],
  "handoff":  {"ontology_key": "<key>", "profile": "<key>/<key>_settings.json",
               "guard": {"default_window_days": 0, "big_tables": {"<schema.table>": "<time column>"}}},
  "checks":   {"invariants": 0, "result": null, "deterministic": null, "mutation_turns_red": null},
  "rows":     {"<schema.table>": 0},
  "questions": [{"id": "Q1", "ask": "the question, in the user's words", "blocks": "what cannot be decided without it"}]
}
```

**只有用户能定的四件事**——在确认回合里用业务语言问，并把答案写进 manifest（不要只留在对话里）：

1. **币种**——在有人说出 HKD / RMB / 其他之前，金额列只是数字。
2. **单位**——`tonnage` 用 t、`load_weight` 用 kg、`load_volume` 用 m3、`box_capacity` 用 boxes：确认或纠正。
3. **PII**——司机姓名与车牌：打码，还是因为数据是合成的而保留可读的名字？
4. **时间**——时区，以及窗口长度（它决定了一个相对 `now()` 的护栏窗口到底还有没有意义；固定的历史窗口意味着
   `default_window_days: 0`）。

然后，也只有到那时：

1. `psql -l`——说出这台服务器上已经有什么。
2. 用一行问：**「数据集库名用 `<name>` 可以吗？」** 并说明你接下来会做什么：
   - 不存在 → 你 `CREATE DATABASE` 建它，并在那里构建；
   - 存在但**不是**你的 → 说清里面有什么，没有明确的同意就**不要**覆盖；
   - 存在且是你之前构建的 → 提供 `--reset`（重建）或换一个新名字。
3. **在拿到回答之前不创建任何东西**：没有库、没有 schema、没有表。同一个回合里读完简报、写出 `ANALYSIS.md` 加
   manifest 草稿是被期待的——用户就是这样在数据库还不存在的时候看见你确实读懂了。
4. 拿到回答之后：设 `dataset.status = "confirmed"`、`confirmed_by`、`confirmed_at`，填好 `units`/`nulls`/`pii`/`time`，
   然后构建。结束时更新 manifest（`status: "built"`、`checks`、`rows`）。

这一步为什么存在：名字过去被焊死在智能体配置里，于是第二份简报会落到第一份简报的库里，而没人同意过这件事；单位和
币种从来没写下来过，于是下游每一个标签都只能靠猜。

## 1. 设计：实体 → 粒度 → 体量 → 不变量

1. **实体**——业务点名的每样东西一行，带一个真正的主键。
2. **粒度**——你要去数的那个事实：一个 stop 是一次门店拜访，一趟 trip 是一个「车-日-线路」。把它写下来；之后每个
   指标都由它决定。
3. **体量**——从故事推出来（「90 天 × 45 趟/天 = 4,050」），绝不取一个让故事变假的整数。留一个 helper，把简报
   蕴含的合计数打出来。
4. **不变量**——那些断言，写成 SQL（见 `check_dataset.py`）。客户提到的每个痛点至少一条断言，另外至少一条恒等式
   （每个父行有几个子行、必须成立的求和）。

## 2. 把失败栽在故事说它们来自的地方

随机的失败造出一个什么都证明不了的演示。在 ABC 上实测：

| 栽进去的 | 机制 | 变得可见的东西 |
|---|---|---|
| 超载 2% → 并线后 80% | 每车的载重快照固定；线路停靠点 10.2 → 15.7 | `overloadRateByRouteVersion` |
| 倒温主要发生在老车上 | 温偏概率绑定到 `age_years` | 每车的 `tempExcursionStops` |
| 破损落在入职第一周的日结工身上 | 破损绑定到 `handlers.days_worked` | 破损 4.5 对 1.7 箱 / 千次停靠 |
| 客诉跟着迟到 + 温偏来 | 每个失败停靠点生成一条客诉 | `complaintCountByLiability` |
| 路权冲突 | `emission` + `core_zone_permit` 设成让国四 36 台没有许可 | `permitCoverage` 23.3% |

## 3. 有意把数据病理放进去

干净的数据集教会错误的课。下面每一条都存在于 ABC，每一条都变成了一道本体门禁：

- **一个恒定列**（`complaints.kind` 只有 `late`）→「做不了客诉类型拆分」是一条发现，不是 bug；
- **所有行共用一个时间戳**（`opened_at` 完全相同）→ 趋势图只有**一根**柱子，而那根柱子正是时间戳被批量回填的证据；
- **一个大 NULL 组**（`liability` NULL 占 46.1%）→ 未判定的责任是一个真实的组；它的金额是 NULL，不是 0；
- **一张对这个问题来说太小的表**（3 小时的遥测）→ 温度趋势必须被拒绝；
- **计划与实际对不上**（`route_stops` 对 `stops`：51,210 个停靠点里只有 75 个共享同一门店）→ 达成率不可复现，
  继续作为一条声明出来的拒绝。

## 3b. 分块写文件，每一块都有界（一次 700 行的工具调用会卡死）

一个 `write_file` 扛下整个生成器，就是一条巨大的工具调用参数流。在这家 provider 上实测两次：请求流式发出 28 个分块，
然后静默了 **600 秒**，回合丢掉，用户只看到一个转圈。所以：

- 按**每段 ≤ ~120 行**写生成器：先骨架加 helper，然后每组表一次 `edit_file`（或追加），最后 `main()`；
- spec 同理：先写平铺的部分（`dataset`/`source`/`time`），再分两三趟写 `invariants`；
- 每次写完都对文件 `wc -l`，这样你知道它真的在变长（一次「成功」了的截断写入，正是这条要防的失败模式）；
- 一次巨大的响应不是美德：没人会一口气评审它，而 provider 可能干脆停住。

## 3c. 用一条查询量，而不是 N 条

一个数字就是一条查询，但 N 个数字不等于 N 条查询。实测（2026-11-07，`new_coldchain`）：智能体想知道并线之后每天的
趟数，于是为 X = 09-23 发出 `select count(*) … trip_date >= '2026-09-22' and trip_date < X`，然后又用第二个 `-c`
发一遍，再来第三次……每次调用都重复前面每一条查询，再加一条。十个回合之后，命令已经是几千字符的重复 SQL，一个数字
也没报出来，回合最后死于停滞的流。

规则：

- **一个聚合，一条语句**：`select trip_date, count(*) from trips group by 1 order by 1` 回答整个问题；
  `select version, avg(planned_stops), … group by 1` 回答那张信号表；
- 某个值必须量，就在**打印标签的同一条**查询里量它，并且一次全打出来；
- 永远不要重发已经发过的查询；需要再用它，就重读上一条工具结果；
- 如果连续两次工具调用有 ≥80 % 相同，停下换方法——那是循环，不是进展。

## 4. 确定性与重置

- **`SEED` 常量放在顶部。** 门禁或截图里的数字绝不能自己动；实测到的教训：一道拿相对 `now()` 的数字去比常量的
  门禁，会退化成误报。
- `--reset` 丢弃并重建（幂等），因为演示会被反复重跑。
- 生成的 id 跨运行稳定；任何会被查询比较的东西，都不要依赖 `serial` 的顺序。
- 时间：把数据放进一个**固定的历史窗口**并把它说出来（`2026-08-08 → 2026-11`）。这样
  `guard.default_window_days` 必须是 `0`（拒绝相对当前时间的窗口），否则每个指标都会静默地返回空。

## 4b. 交付自检——逐条过一遍，在回答之前

| 必须为真 | 怎么查 |
|---|---|
| 生成器文件在 `generated/<dataset>/gen.py` 处存在 | `ls` 它 |
| `SEED` 是顶部的常量，`--reset` 会丢弃并重建 | 两样都 `grep` |
| spec 在 `generated/<dataset>/<dataset>.dataset.json` 处存在 | `ls` 它 |
| `check_dataset.py --spec …` 打印了 **`N checks, 0 failed`** | 跑它；把那一行引出来 |
| 简报里每个硬事实都是一条断言（计数、分布、50→40 的切分） | 打开 spec 数一遍 |
| 每个栽进去的信号都用数字断言了 | 同上 |
| 每条有意为之的病理都被断言了（恒定列、NULL 组、一张太小的表） | 同上 |
| 每个没有对应列的痛点都在 `cannot_see` 里 | `grep` 它 |
| **重建不改变任何东西**：`gen.py --reset` 跑两遍给出完全相同的数字 | 比前后的总数，或对一个关键聚合取校验和 |
| **spec 能失败**：手工改掉一条期望 → 它变红，改回来 → 变绿 | 做一次，并且说出来；一份从没人见过它失败的 spec 只是装饰 |
| manifest 在 `generated/<slug>/manifest.json` 处存在，且它的 `dataset.status` 是 `built` | `cat` 它 |
| manifest 的 `rows` 等于库里实际存的行数 | 每张表 `select count(*)`，比对 |
| manifest 的 `checks` 等于 `check_dataset.py` 打印的东西 | 同一次运行，同一批数字 |
| `units`、`nulls`、`pii`、`time.timezone` 都填了——不是 `null` | 一份 units 为 null 的 manifest，就是一个没人能给它打标签的数据集 |

**一个没有这些产物却在作答的回复，不是部分交付，而是一次失败的运行。** 直说，不要把它包装起来。

## 5. 用 spec 验证，然后交接

```bash
PY=<the app's own .venv: the interpreter that runs the backend>
$PY <this skill>/scripts/check_dataset.py --spec <this skill>/fixtures/abc_coldchain.dataset.json
#   → 53 checks, 0 failed   (volume, FK, planted invariants, constant columns, NULL rates)
```

之后数据集进入正常路径：`build-ontology-from-db`（内省 → 声明 → 门禁 → 看板）。spec 文件是两个技能之间的契约：
本体的 `:businessDescription` 应当引用 spec 所断言的同一批数字。

## 反模式

- **拿文档本身当回答**——把简报（或它的 XML）复述一遍当成「结果」。交付物是一个生成器、一份 spec 和一个检查计数，
  否则就是一次带原因的失败；
- **用文本路径去读二进制文档**（`unzip`/`cat`/解析 XML）而不是 `read_any_file`；
- **构建进一个用户没有确认的库**（或问都不问就覆盖一个）：名字是业务决定，而一次安静的构建，就是第二份简报落进第一份
  简报库里的方式；
- 把故事糊在随机数据上面（什么都证明不了）；
- 一个「干净」的数据集，没有 NULL、没有恒定列（演示于是声称了一种真实数据支撑不了的能力）；
- 为了凑整而选的体量，让 `4,050` 变成 `4,000`；
- 用业务从来没有过的代理列去表示一个痛点（改为写进 `cannot_see`）；
- 在固定的历史数据集里用相对 `now()` 的日期——那样每个窗口都返回空。

## 参考资料

- `references/design-checklist.md`——清单，每一项带它的验证查询，以及漏掉它在本体上的后果。
- `references/abc-case.md`——完整的实例（schema、体量、栽进去的信号、实测数字）。
- `scripts/check_dataset.py`——spec 检查器（本技能的门禁）。
- 它提炼自的那个生成器：`<this skill>/scripts/gen_abc.py`（SEED 20251106，`--reset`）。
