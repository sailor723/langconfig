---
name: build-ontology-from-db（从数据库搭建本体）
lang: zh
translated: machine
source: backend/skills/en-originals/build-ontology-from-db/SKILL.md
description: 在已有 PostgreSQL 数据库之上搭建本体（或语义层，或"从数据库编译指标"）时使用——这是一架台阶梯，每一级都是一个产 物加一道会失败的门禁，所以"完成"意味着全绿，而绝不意味着"看起来做完了"；它拒绝猜测只有业务方才能决定的事，也拒绝
  发明一个数据支撑不了的数字
tags:
- ontology
- semantic-layer
- postgres
- metrics
- data-modeling
- sql
- gated-build
triggers:
- 被要求为一个数据库搭建或扩展本体 / 语义层时
- 某个 KPI 或指标必须只定义一次并编译出来、而不是每张报表手写一遍时
- '"同一个指标给出两个不同数字"，而定义必须定下来时'
version: 3.2
author: weiping
params:
  datasource:
    label: 数据库
    description: 本体从哪个数据库搭建（即智能体的 `datasource`）
    required: true
    default_from: agent.datasource
  ontology_key:
    label: 本体
    description: 这个智能体写入的文件夹（例如 new_coldchain）
    required: true
  profile_file:
    label: profile 文件名
    description: 该文件夹里的 profile
    required: false
    default: '{ontology_key}_settings.json'
---

# 从数据库搭建本体——一架每一步都带门禁的台阶梯

本体不是一张 schema 图。它是一组**声明**，每一个数字都由它们编译出来：改声明，数字就跟着动；什么都不改，就没有任何
报表会漂移。一个不会拒绝的本体，是一个多绕了几步的仪表盘。

**让本技能成立的那条规则：一步的完成，看的是它的门禁全绿——不是它看起来做完了。** 下面每一步都有一个产物、一条命令
和一行"绿"的定义。没有门禁的步骤是 `ungated`，而没有门禁的步骤永远不许被报告为完成。

**写 TTL 之前先读 [references/rules.md](references/rules.md)**（二十八条编号规则，每一条都声明了强制它的那道 GATE，
或者干脆说出 `Ungated`）。[references/pitfalls.md](references/pitfalls.md) 是真实失败案例的目录；
[references/tuning-log.md](references/tuning-log.md) 记的是智能体*自身*行为的同类账本；
[references/gates.md](references/gates.md) 是门禁矩阵，以及怎么证明每道门禁真的咬得住；
[references/assets.md](references/assets.md) 索引了 `examples/` 里四个完整本体与 `scripts/` 里三个辅助脚本，并标出
打开每一个的是哪一级台阶。

**在需要它的那一步读它，别把它当作业。** 实测：一个搭建者在一次搭建里把这份 SKILL.md 读了八遍，却没打开过任何一份
参考——所以它破坏的正是那些只写在正文里的规则。下面的台阶梯标出了在哪一步读哪一节。

## 0. 一步怎样结束（动别的东西之前先读这里）

每一步都要往 `work/<key>/steps.json` 写一条记录：

```json
{"id":"S1","skill_section":"3. structure","status":"green",
 "artifacts":[{"path":"work/<key>/ontology/01-structure.ttl","bytes":21424,"sha256":"ab12…"}],
 "gate":{"cmd":"gates/check_structure.py --profile work/<key>/<key>_settings.json",
         "exit":0,"summary":"88 checks · 0 failed · green"},
 "at":"2026-11-08T00:10:00","by":"agent"}
```

- `status: green` 只有在 `gate.exit == 0` **且**失败检查为零时才合法。
- `status: red` 要原样带上失败的那一行。绝不许把一道红门禁概括成"基本做完了"。
- 任何改动之后，**重跑那一步的门禁**。没有重跑的改动等于没验证。

### 四条让一步不至于卡死的纪律（全部实测，不是文风）

当一轮要求模型既大量读、又大量写时，模型会沉默。下面每一条都是某个下午搭一个本体时测出来的数字：

- **用 shell heredoc 追加——绝不对一个已经很大的文件用 `edit_file`。** 这是目前发现的最大卡死原因。同样 11 个属性，
  对一个 24 KB 的文件走 `edit_file` 花了 **5.5 分钟且零输出**，走 `cat >> file <<'TTL'` 只花 **30–40 秒**。
  （`edit_file` 需要 `old_string`/`new_string`，所以它的参数随文件一起变大；heredoc 只发送新文本。）

  ```bash
  cat >> ontology/01-structure.ttl <<'TTL'
  :stopOnTime a owl:DatatypeProperty ; rdfs:domain :Stop ; :physicalColumn "on_time" ;
      :businessDescription "该门店是否在收货窗口内到货" .
  TTL
  ```

- **把列清单放进提示词里。** 一轮要先读 40 KB 的 `brief.json`（或 42 KB 的 TTL）才知道 20 个列名，既慢又会卡；
  那次搭建里最快的两轮，正是把列名直接粘进指令的两轮（2–3 个类，41 秒和 97 秒）。不知道列名就问数据库**一个**紧凑的
  问题——不是要一份 40 KB 的内省转储。
- **一轮 = 1–3 个类。** 实测：6 个类卡死了两次（5 分钟以上）；2–3 个类 30–120 秒完成。追加；绝不重写一个已经完成的
  文件。
- **一个聚合，一条语句。** 绝不要给同一条查询再加一个子句重发一遍——那个循环十轮也出不来一个数字。连续两次工具调用有
  ≥80 % 相同时，停下来换方法。
- **门禁是唯一的权威，引擎不是。** 一个文件的格式不清楚时，打开将要审判它的**门禁**——它的 docstring 里就有完整
  示例。实测：一轮被要求写 `samples.json`，却跑去 `compiler/*.py` 里找 schema，发了 **78** 次 `grep`，每次往文件
  列表里再加一个文件名（`… f1 f2 … fN 2>/dev/null | head -20`），直到撞上递归上限，而文件其实已经写好了。这个
  形状——*同一条命令再加一个参数*——正是平台循环守卫现在要找的东西（剥掉共同的尾巴之后再比，所以命令**中间**变长也
  算），第三次重复时触发。一旦发现自己正往同一条命令上再加一项，停下来去读真相源头。

如果一轮以空回答或链路超时结束：已经在磁盘上的产物才是真相。说清哪一步是绿的、哪一步是红的，然后从红的那一步继续。

## 台阶梯

| # | 步骤 | 产物 | 门禁 | 绿意味着 |
|---|---|---|---|---|
| S-1 | **重建先证 delta**（仅当本体已装） | `delta.json` | 无自动门；`changed=added=removed=0` 且无 questions ⇒ 输出 `NO DELTA` 并停止 | delta 可解析、逐条对照已装声明、跳过的步骤写明理由 |
| S0 | 读材料 + 澄清 | `draft.json` `questions.json` `answers.json` | 人工确认（无自动门 → `status: human-confirmed`） | 每条声明都能引用 `answers:Qx` 或 `docx#Qn` |
| S1 | 结构层 | `ontology/01-structure.ttl` | `gates/check_structure.py --profile …` | 0 failed：类→表/主键存在、属性→本表列存在、外键带 `:references`、属性名不撞、无孤儿、**每列都被覆盖**、无空类 |
| S2 | 含义层 | `ontology/02-meaning.ttl` | `gates/check_ontology_generic.py --profile … --family R` | 每个定义可编译且选出 >0 行 |
| S3 | 计算层 | `metrics_ext.ttl` | `--family C` | 每个指标编译成功，或**按名拒绝**并进拒绝清单 |
| S4 | 护栏 | profile `guard` | `--family G` | G0–G6 全过（含 G1c：声明的窗口列必须存在） |
| S5 | 菜单/样例 | `samples.json`（格式抄 `check_samples.py` 的 docstring）+ profile `samples` 前门清单 | `gates/check_samples.py --profile …` | 每个样例答出或按名拒绝；`unresolved`/`[WARN] offered but not gated` 逐个点名 |
| S6 | 仪表盘（若声明） | `dashboard.json` | `gates/check_dashboard.py --profile …` | 每个面板引用已声明指标或声明过的洞 |
| S7 | 教程 | `tutorial.json` + 本 profile 自己的 `ontology.html` | `--family T` + 现场 `tutorial/run?metric=…` + `graph_view.py` 末行的自检 | 每个 items 名字已声明；至少一个指标步真跑出数；页面自检 PASS、标题 == profile `title` |
| S8 | 发布 | staged 报告（记 staged id 到 `gates.json` 的 `pending_install`） | `ontology_publish` → `scripts/ontology_gates.py` | stage 编译 0 新拒绝、门全过；整套 suite `0 failed`，未安装的 key 点名 NOT RUN 而不是红 |

**绝不跳过任何一步，也绝不"以后再修"。** S1 是红的，后面每一步都失去意义：编译器会因为同一个结构性理由拒绝每一个指标，
而时间要花两遍。

## 这一轮实测到了什么——以及它改掉了什么

特意留在这里：这些就是教会上面那些规则的失败，而一个丢掉了失败故事的规则会被再次跳过。每个数字都来自这台机器上对同一个
本体（v6）的一次搭建。

**成绩单：凡是有门禁的规则，它都守了；凡是没有门禁的规则，它全破了。**

| 它做了什么 | 证据 | 为什么能 |
|---|---|---|
| 在本体安装之后，编出一个 **S9"复查"** 来继续加指标 | 安装后加了 11 个指标；台阶梯里没有 S9 | 技能从没说台阶梯到哪为止（已修：下面那一节） |
| 43 个指标，**0** 个带 `:askedAs` | `grep -c askedAs` → 0；每一道门禁全绿 | 没有门禁强制它（规则 20，至今无门禁） |
| **43 个里有 11 个**指标没有 `口径来自` | 按块扫描测出 | 没有门禁强制它（规则 21，至今无门禁） |
| 发布了，然后把一套绿的 suite 读成"我的暂存是绿的" | `--key` 在 `profiles/<key>/` 存在时读的就是它；`pending_install` 从没记录 | 没有任何东西区分暂存与已安装（规则 22） |
| 从没跑过变异，把 `exit 0` 叫作"通过" | `steps.json` 里没有变异记录 | 这份记录从来不是必需的（规则 15） |
| SKILL.md 读了 **8 次**，参考读了 **0 次** | 同一次会话的工具日志 | 参考只在"写 TTL 之前"被排进日程 |
| 一个没人点名的 **TimeWindow / timeBucket** 缺口 | `grep -c` → 0 条声明；按月/按周的问题答不出来 | 没有规则说声明了 `:timeColumn` 就必须有分桶（规则 16、18） |
| 重建时写下 `skip S1 — 结构未变`，而库多了 9 张表 | 同一份 `delta.json` 的 `skip` 行 vs 当天 `check_structure` 的 9 条 uncovered | 门禁只在首建被排进日程：没有规则说重建也要先量库（规则 27） |
| **Query 页面**在笔记本上能答，在 ECS 上被拒 | `nl.py failed: [Errno 2] … '/Users/weiping/dev/Learn/ontology/.venv/bin/python'`——七个本体全一样 | 运行器 spawn 的是写死的 venv（规则 24）；没有任何东西去扫 profile 里的机器路径 |
| 物流/ABC 的问题以 `PromoteCustomer: :Customer has no :physicalTable` 死掉 | retail 的 `actions.yml` 编译到了它们的图上 | actions 路径取的是 `PROFILE / actions_file`（retail 的目录），而不是当前活动 profile 的 |

**由此得出的规则：** *智能体守住了有门禁的规则，却破了写在正文里的规则。* 这不是模型的性格缺陷，而是一个设计结果——
没有门禁的规则就是会被跳过的规则，没有人链接的文件就是没人打开的文件。因为这张表，现在有了两个机制：
`scripts/check_skill.py`（本技能自己 lint 自己：规则对门禁、死链、够不到的文件）和
`scripts/verify_skill_version.py`（每个智能体实际读的是哪个版本，以及 `--restage`）。

**至今仍无门禁的，点名而不是藏起来：** 暂存与已安装（22）、变异记录（15）、时间轴与分桶（16、18）。`:askedAs`（20）
和来源句（21）现在由 C5a/C5b 强制，规则 24（机器路径）由 family X 强制。在其余的都有门禁之前，本技能在
`references/rules.md` 里明说，且 `check_skill.py` 每次运行都把它们打印出来。

### 台阶梯止于 S8——没有 S9、S10 或 S11

被问"S1 … S11 在这个技能里吗？"，诚实的答案就是上面那张表：**S-1、S0、S1、S2、S3、S4、S5、S6、S7、S8**，S8 之后再
无其他。实测：一个搭建者被问了正好这个问题，花了 **213 次工具调用**（69 次 shell、68 次 python、29 次 psql、15 次写）
从产物里重新推导自己的历史来回答——一次没有廉价答案的自审，因为技能从没说过台阶梯到哪为止。

S8 之后发生的事不是台阶梯的一步，它们有自己的名字：

| S8 之后 | 谁 | 做什么 |
|---|---|---|
| **apply（应用）** | 一位持有 `ontology_editor` 的人 | 在**已安装**路径上重跑整套 suite，提交，失败时逐字节回滚 |
| **appears（出现）** | 没有人 | 装好的 profile 自己出现在 Ontology 活动里（存在性来自 `profiles/<key>/`，不是来自花名册） |
| **operate（运行）** | 任何人 | 页面、Query、Dashboard、教程——每个数字都在请求时编译；`scripts/ontology_gates.py --key …` 重证整个 key |
| **change again（再改一次）** | 搭建者 | 那是一次**重建**：回到 **S-1**，证明 delta，只碰 delta 点名的东西 |

所以当有人问某一步是否"在技能里"，**引用台阶梯那张表**（十行），而不是从工作区里重建你做过什么：那张表就是答案，重新
推导一次要花掉一轮。

---

## S-1. 重建在碰任何东西之前先证明自己的 DELTA

**本体已经装好时，先读这一节。** 重建不是"再做一遍"，而是"证明变了什么，然后只问变了的那部分"。本项目实测：被要求从同一批
文档重建一个已装好的本体，一轮花了 **285 秒和 188 次工具调用**去翻已安装的 TTL，什么都没写；同一件事把已安装的事实
**直接交到提示词里**，**12 秒、一次 `write_file`** 就答完，结论是 `changed=0 added=0 removed=0`。

所以重建从 `work/<key>/delta.json` 开始，别的什么都不写：

```json
{"installed": {"objects": 18, "metrics": 28, "samples": 14},
 "items": [{"id": "D1", "kind": "unchanged|changed|added|removed",
            "what": "…", "installed": "…", "document": "…",
            "action": "…", "needs_business": false, "why": "…"}],
 "questions": [{"id": "Q1", "ask": "…", "default": "…", "blocks": "…"}],
 "skip": [{"step": "S1", "why": "structure unchanged"}]}
```

### S-1 的第一个动作是量库，不是读文档

**库的当下 schema 是第四份输入，而且要先于另外三份去量。** 首建从 S0 进（先内省数据库），重建从 S-1 进（先比文档）——
**这就是盲区**：库变了、文档没变，重建这条路看不见。实测（2026-11-11 复查一个 11-08 的搭建）：账本里写着
`{"step": "S1", "why": "结构未变（无新增/删除对象与列）"}`，而当天 `check_structure` 对同一个库报

```
[FAIL] no table is silently left out — 9 uncovered:
  driver_schedule, fuel_logs, incident_tickets, maintenance_orders,
  restriction_calendar, vehicle_axles, vehicle_fixed_costs, violations, zone_permits
```

那 9 张表是后来补进库里的，本体没跟。**"结构未变"在被测出来之前不是结论，是一个假设。**

所以：

```
# 1. 先拿一份已安装本体（不要用 cp -r 拷仓库）
ontology_open(ontology_key="<key>", dest="work/<key>")
# 2. 量的这一步，读的仍是「已装声明 × 库里真实 schema」
python backend/features/ontology/gates/check_structure.py --profile work/<key>/<key>_settings.json
```

- **绿** → `"结构未变"` 这句话现在可以写进 `skip`，并且**必须附上那道门禁的最后一行**（`NNN checks · 0 failed · green`）。
- **红** → 库动了，不是文档动了：`skip: S1` 不成立，把红行点出来的表和列补进 S1，从那一级重新往上走。

这条不是"多跑一道门禁"，它决定后面所有步骤是否还有意义：结构不对时编译器会用同一个结构性理由拒绝每一个指标，时间花两遍。

规则，按顺序：

- **先量库**（上一节）：`check_structure` 的绿行是"结构未变"的**唯一**凭据；
- **对照已安装的声明，而不是对照一张白纸**——已安装的本体、已经给出的答案（`answers.json`）、新到的材料，这是三份输入；
- **`changed=added=removed=0` 且没有 `questions` → 停下，说 `NO DELTA`。** 不要重编译、不要重跑 S1..S8、不要发布。
  没有东西要建是一个结果，不是失败——为一份与声明一致的文档去重写那些已经绿的声明，正是把 12 秒的重建拖成十分钟的方式；
- **冲突 → 提一个问题，而不是做一个决定。** 文档要求的东西只要与已安装声明不同，就进 `questions`，带上默认值和它阻塞
  什么；
- **`skip` 点出你不跑的步骤和理由**（"结构未变"、"样例未变"）。有理由跳过的步骤是一个决定；悄悄跳过的步骤是一句谎话。
  **跳过 S1 而没有 `check_structure` 的绿行，就是那句谎话**（规则 27）；
- **`delta.json` 必须能解析。** 写 JSON，把摘要行放进 ANSWER，不要追加在文件里——实测：文件里多出一行
  `DELTA done=…` 让它无法解析，而一个解析不了的账本产物不算产物。

然后台阶梯**只在 delta 上**跑：变了的指标是 S2+S3，新增一列是 S1+S3，文档里新增一节但没有声明后果，那就什么都不做。

### 种子由平台拼好；别自己去找

重建种子（已安装的 objects/metrics/samples、已经给出的答案、护栏）**在第一条消息里**到达。它若缺失，那是一个值得点名的
平台 bug——不要花掉这一轮去读 `01-structure.ttl`（597 行）来重建一份平台本来就有的清单。

**编译器和门禁脚本不是你的材料。** 两次部署中的搭建恰好死在这一点上：它们把 `compiler/sqlgen.py` 读了十一次、把
`gates/check_structure.py` 读了八次（就为了学一条写在这个文件里的调用方式），两分钟内转录膨胀到 100 KB+，随后模型调用
再也没有返回——任务停在 `RUNNING`、零文件写入，直到被杀掉。读你必须改的声明、发给你的种子和答案文件。不要去读编译你的
代码：需要调用方式，它就在下面；需要知道某个东西**为什么**被拒，证据是声明，不是生成器。

**一个文件最多读一次。** 重读就是一轮悄悄变成三倍大小的方式；把需要的事实留在 `work/<key>/*.json` 里，去读那些。

---

## S0. 先读材料，再澄清（两进，三出）

输入：一份**业务文档**（用户自己的话——目标写在那里，不在数据库里）和一个已有的**数据库**；若先跑过 mock 数据智能体，
还要它的 `dataset.manifest.json`（`units / nulls / pii / decisions / refused / handoff`）。

**不要**开始写 TTL。按这个顺序产出：

1. **`draft.json`**——整幅画面，每条主张都带证据：`objects[{class, table, grain, rows, evidence}]`、
   `metrics[{name, label, status: supported|needs-decision|refused, definition, evidence, preview}]`、
   `refusals_expected[]`。`evidence` 点名列或约束；`preview` 是一个真实测出来的数字。
2. **`questions.json`**——最多 12 个，且只收答案会**改变一条声明**的问题：
   `{id, ask（业务的话，不带表名）, options[], default, blocks, evidence}`。把测出来的数字放进选项里："准点率按站点算
   94.6%、按整趟算 53.9%，你要哪个？"是可回答的；"准点率怎么定义"不是。
3. **`answers.json`**——`{id, answer, assumed: true|false, becomes}`。给了默认值的答案没问题，写明 `assumed: true`。
   留着不答不是阻塞；悄悄发明才是。

**阈值、粒度、"好线路"的定义、目标值：一个都不许发明。** 文档没说，答案要么是一个带默认值的问题（记作 assumed），要么
是一次拒绝。

### 数据支撑不了某个目标指标时：先问数据来源，再造 mock

业务要一个 schema 服务不了的指标（这天天发生——"毛利"需要的成本，那份导出从来没有）。绝不要悄悄算一个代理量。顺序是：

1. 点名缺的字段，以及它能解开什么；
2. 记下这个决定（`{"id":"D-cost","text":"向 NASS 追加成本导出","status":"confirmed"}`）；
3. **按那个来源会有的样子扩展数据集**——新表（`trip_costs`）、一个带真实 `as_of` 的新列、一张结算表——并在数据集
   spec 里声明它；
4. 仍然缺的，留成 **NULL，绝不填 0**（`other_cost` 100 % 为 NULL，意味着毛利是一个上界）；
5. 重跑数据集构建，确认**已有数字没有动**（加一张表不得移动生成器的随机流；新列在 SQL 里派生，或者用一条独立的流）。

若业务文档说某件事在范围之外（温控第二期、贷款压力不进系统），**不要为它造 mock**——记作已确认排除，让本体按名拒绝它。

---

## S1. `ontology/01-structure.ttl`——对象、键、列

一张表一个类；一列一个属性；**外键变成对象属性，而不是同时再做成数据属性**。

```ttl
@prefix : <https://example.org/onto#> .
:plate a owl:DatatypeProperty ; rdfs:domain :Vehicle ; :physicalColumn "plate" ;
    :businessDescription "脱敏后的车牌：保留省市与发牌字母，后缀是序号" .
:driverVehicle a owl:ObjectProperty ; rdfs:domain :Driver ; :physicalColumn "vehicle_id" ;
    :references :Vehicle ; :businessDescription "司机带车加盟：一台车一位司机" .
```

硬规则——每一条都是已经发生过的失败：

- **属性名在类之间唯一**：用 `:tripDate`，不用 `:date`。在 RDF 里，一个局部名就是**一个**属性；`:id` 出现在六个类上，
  就变成一个带六个 domain 的属性，编译器于是处处把它当歧义拒掉。
- **每个建模表的每一列都要有一个属性。** 一个类点名了自己的表却什么都没声明，就是空脚手架，门禁会判它失败。
- **外键列只是那条链接**——声明两次会让一段关系变成两个东西。
- `:businessDescription` 是一句业务语言；评审者读的就是它。

**复合键是一个逗号分隔的字面量**——`:primaryKey "route_id, seq"` 是本仓库已经在用的约定（clinic 的
`treatment_lines`、logistics 的 `route_stops` 和 `driver_stats`）。

分轮次搭这个文件，**每一轮之后都跑门禁**：

```
python backend/features/ontology/gates/check_structure.py --profile work/<key>/<key>_settings.json
```

它把文件与 `information_schema` 对差：类 → 表和键存在；数据属性 → 列存在于**它自己那个类的表**上；对象属性 → 列 + 一个
键存在的 `:references` 目标；没有两个类共享同一个属性名；没有孤儿属性；每张表都被建模；**每一列都被覆盖**；没有无属性
的类。绿 = `0 failed`，且 `columns_missing` 为 0。它在任何东西编译之前就跑——这正是要点。

**一次真实搭建，按轮次排成台阶**（账本逐条记录）：6 个类 → `columns_missing` 104；再加 2 个 → 77；1 个（Stop，改用
heredoc 之后）→ 66；1 → 56；2 → 46；1 → 37；2 → 0。二十分钟，该绿的地方每一轮都绿，而那两次红灯的轮次连理由一起记在
账本里。

**门禁也会错。** 这道门禁第一次跑的时候，因为 `:primaryKey "route_id, seq"` 判了两个类失败，它在找一个确实叫
`route_id, seq` 的列。复合键要按逗号拆开——当门禁和声明互相矛盾时，**先**弄清哪一个是对的，再去改 TTL，并说明当时是
哪一个错。

---

## S2. `ontology/02-meaning.ttl`——一个词是什么意思

对草稿里的每个指标，先问"用业务的话说，它到底**是什么意思**"，然后声明它：

```ttl
:LateStop owl:equivalentClass [ owl:intersectionOf ( :Stop
    [ a owl:Restriction ; owl:onProperty :onTime ; owl:hasValue false ] ) ] .
```

`owl:intersectionOf` = 与，`owl:unionOf` = 或，`owl:hasValue` = 一个编码，`:physicalPredicate` = **唯一**的逃生口
（`IS NULL`、列对列），而且必须在注释里说明。既带公理又带已声明谓词的类会被拒。

门禁 `--family R`：每个定义都能编译**且能选出行**——选不出任何行的定义，等于没有定义。

### 编译器绝不做的一件事：跨表

在这次搭建的五轮里实测下来，有四种形状每次都重现。它们是契约，不是口味：

| 业务要什么 | 什么编译不过 | 什么能 |
|---|---|---|
| 跨两列的谓词（`boxes > capacity`）或 `IS NULL` | 一个包含两个属性的 restriction | 在类上写 `:physicalPredicate "load_weight > weight_capacity_snapshot"`，并且**列名不带限定**（`amount IS NULL`，绝不是 `c.amount IS NULL`——`FROM` 由编译器自己写，加了别名就变成 `missing FROM-clause entry`） |
| 只有 `:physicalPredicate` 的定义 | 任何自己去找表的写法 | 该类还要有 `:physicalTable`，而且 **C1b 需要一个在它上面声明了 `:where` 的指标**——顺序：定义 → 计数指标 → 门禁 |
| 跨到另一张表上的定义（"这一趟的站点全部准时"） | 谓词里的 `EXISTS`/子查询 | 把这个状态反规范化到事实行上（`trips.late_stop_count`、`stops.handler_days_worked`），再声明一个单表面 |
| 为行程级合计供数的 1:1 明细表（`trip_costs`） | 公式里的 `JOIN` | 把合计收敛到事实行上（`trips.cost_total`），明细留着下钻 |
| 落在另一张表上的**维度**（用 `route.version` 比较并线前后） | 任何跨表的 `:groupBy` | 把这个维度反规范化到事实行上（`trips.route_version`），再声明 `:groupBy :tripRouteVersion` |

最后一行是这一轮新增的：并线前后超载是个头条问题，它答不出来不是因为数据缺失，而是因为版本住在隔一张表的地方。反规范化
它，是在生成器里加了八行 SQL 派生列，没有改动任何已有数字（已验证：ontime 0.94596、external 0.10121、margin 0.51506
前后完全一致）。

一个**同时**带 `:physicalPredicate` 和 `:physicalTable` 的定义类，是定义，不是结构类：那张表是给 C1b 用的，让它知道
该数什么；概览页现在先判定定义（实测：它以前会报"18/21 个类列出了它们的属性"，并给一个正确的本体打红旗）。

---

## S3. `metrics_ext.ttl`——计算叠加层

含义与计算是两个文件，这是故意的。这一个装 `:aggregate`、`:grain`、`:universe`、`:where`、`:groupBy`、
`:numerator`/`:denominator`/`:scale`、`:unit`、`:askedAs`。

- 比值要声明分子/分母（绝不手打 `sum(a)/sum(b)`）；
- 阈值只存在**一处**；
- 带 `:formula` 却没有 `:grain` 的指标**必须拒绝**——那次拒绝量出来的，正是语义层以前隐含持有的东西；
- **每个指标的 `:businessDescription` 都要点出来源**：`口径来自 answers:Q2` 或 `docx#Q10`。没有来源的指标不能被声明
  ——它进拒绝清单，并点名缺的是哪个问题。

门禁 `--family C`：每个指标要么编译成功，要么**按名拒绝**，并给出一句评审者可以据此行动的话。拒绝清单是一份交付物，
最后会打印出来。

---

## S4. 护栏——针对**这一份**数据决定是拒绝还是收窄

做任何选择之前，先读 manifest 的 `time` 段：

- 数据是**近期的** → 相对 `now()` 的窗口有意义（`default_window_days: 30/90`）；
- 数据落在一个**固定的历史窗口**里 → **拒绝**而不要收窄（`default_window_days: 0`），因为相对窗口会悄悄返回空；
- 永远要有：页面上限（`max_rows`）、计划预算（`max_plan_rows`）、语句超时；
- **`big_tables` 只收自己有独立时间列的表**（`trips.trip_date`、`telemetry.ts`、`complaints.opened_at`）；
- 一个大表若**没有**自己的时间列（`stops`：它的日期是 `trips.trip_date`，隔一次 join），就放进 `large_tables`——只给
  预算，不注入窗口。若声明进了 `big_tables`，护栏会往一个不存在的列上注入窗口，**那张表的每一次读取都会死**。

门禁 `--family G`：页面上限、有窗口或拒绝、计划预算（含扇出）、语句超时、已声明的指标绝不加窗口、空窗口要被报出来，以及
**G1c**——每个 `big_tables` 的窗口列都存在。

---

## S5. 菜单、名字、样例

- 每个指标都要有一个用户语言的 `rdfs:label`，和一个问题能匹配上的 `:askedAs`；
- 为那些在不同数据集里含义不同的词提供按 profile 的别名——**以及材料引入的每一个新词**。v3 搭建实测：36 个 KPI 指标都
  声明了 `:askedAs`，问题却照样被拒，因为 违章 / 出勤 / 油耗 / 路权 / 轴荷 不在 `settings.aliases` 里；`违章多少条` 只有
  在加上 `违章 → violation` 之后才答得出来。门禁抓不到这个：它只检查你写的那些样例，而你写的恰恰是已经跑通的那几个；
- `samples.json`：8–15 个问题，一种能力一个，**至少一个必须被拒**，每个都写明它必须产出什么（`value`、`rows`、
  `refused_by_name`），数字来自**第二条 SQL 路径**；
- 本体还不能兑现的，记为 `unresolved`，**并点名缺的那条声明**；
- profile 提供的问题（`settings.samples`）是前门：提供了却没被门禁覆盖的问题会被点名
  `[WARN] offered but not gated`，因为没人检查的样例正是会烂掉的那一个。

门禁 `gates/check_samples.py --profile …`：每个样例要么答出，要么按名拒绝。一个烂样例比没有样例更糟。

### 写它的输入之前，先读那道门禁

`samples.json` 的形状就在门禁自己的 **docstring** 里——`{"samples": [{"question": …, "expect": {...}}]}`，含
`value`/`rows`/`refused_by_name`/`unresolved` 和一个 `tolerance`。凭记忆写，就是一轮花掉 **204 次工具调用**去找一个
格式，而那个格式就在它正 grep 的代码上方 15 行：

- 裸 JSON 列表 → `AttributeError: 'list' object has no attribute 'get'`；
- 键写成 `q` 而不是 `question` → 每个样例悄悄变成 `''`，门禁等于什么都没问。

所以：**打开门禁，抄它的示例，把数字填进去。** 一次阅读胜过七十次 grep，而门禁的 docstring 是唯一不会与门禁漂移的
spec。

### 门禁负责验证；13 个问题不靠你的手

数字来自**一条由手里有数据的人写的第二条 SQL 路径**——不是流水线自己的输出，也不是智能体重跑十三条查询来安慰自己。
实测：被要求"先跑每个样例的第二条路径"，搭建者花掉 204 次工具调用，最后以 `Recursion limit of 400` 死掉，磁盘上没有
`samples.json`。可行的做法是两步：

1. 把成品内容交出来（数字已经测好），并说**写这个文件，然后跑这一道门禁**；
2. 门禁变红时，要改的是*预期*——绝不是容差。为了让门禁变绿去放宽容差，正是让样例不再是门禁的方式。

### 第二条路径必须用与声明**相同**的口径

`:OverloadedTrip` 声明为**只看重量**（`load_weight > weight_capacity_snapshot`）。把第二条路径写成"箱数 OR 重量 OR
体积"，量的是另一个词，而且是故意不一致：v1 5.5% / v2 80.1%，而声明的是 2.65% / 75.4%。两个数字都对；只有一个是被声明
的指标。**一个本体只有一个度量词**——要么改谓词并重新声明，要么就量已声明的那个。因为第二条路径漂移而变红的门禁，红在
你身上，不在本体身上。

### 分组样例：键是一个值，值是一个数字

`{"rows": {"v1": 0.02654, "v2": 0.75395}}`——键是渲染出来的分组值（`True`/`False`、`v1`/`v2`），所以必须按编译器的
渲染原样书写。而分组指标**没有单一值**：任何在它上面读 `value` 的代码，读到的都是分组键。`tutorial_api.run_metric`
现在返回 `grouped: true, rows: [[key, value], …], row_count: n`，并把 `value` 留空——这条是实测出来的，因为它以前
对一个分组超载率报 `value: "v2"`，而读者会把它当成答案。

### 答错的三种形状

`unresolved` 不只是"它拒绝"。这次搭建交付了三个答错的案例，每个都点名了缺什么：

- **用子集替整体回答**——"所有赔付成本（含未判定）"答出 543,309.02，因为 `:universe` 是 `:JudgedComplaint`；
  那 46.1% 未判定是一种状态，不是 0；
- **丢掉了一个限定词**——"司机的贷款压力分布"答出一个 Driver 的人数（60）：类匹配上了，`贷款压力` 从未被证明，也没有
  任何东西拒绝；
- **把度量当成了维度**——"按线路版本看超载"（"率"被丢掉了）答出一个 Route 列表（90）。

把这三个都记下来，并点名缺的声明。一个红灯样例会更仁慈，但在声明存在之前，`unresolved` 才是诚实的标签。

---

## S6. 仪表盘（仅当业务方要了一块板）

### 两种仪表盘物种——选一种，并说明为什么

| | **参考板**（v3、v4） | **汇报板**（v5） |
|---|---|---|
| 规模 | 19 个面板 · 17–21 张卡片 · 90–153 个指标 | **6 个面板 · 10 张卡片 · 61 个指标** |
| 给谁 | 会去盘问业务的人：每一种分解、每一种口径，按车 / 周 / 区域 / 版本 | 每周汇报六个 KPI 家族的人 |
| 形状 | `slope` + `matrix` + `ranked` + `composition` + `series` + `parallel` | 每个家族一张图：`slope`（趋势/局面）、`series`（按周）、`composition`（构成）、`parallel`（口径并排） |
| 数字 | 19 个独立面板 | 红线是被声明出来的（`policy`），用 `assumed` / `refused:` 标出业务**尚未**确认的阈值 |

两种都对，也没有哪一种算降级：**v3/v4 仍然是"这个数据库能回答什么"的参考**，而 v5 是同一个数据库裁到一个人汇报时要用的
那部分。重建不得把一块参考板压成六个面板，除非简报要的就是一块汇报板。

### 一个按百分比读的比率，就在声明里这么说

只有 `:unit "ratio"` 而没有 `:scale`，会让卡片打印 `0.9459`，而业务读的是站次准时率。实测：v5 里 19 个指标、v4 里
17 个正是这么干的，只有 v3（始终带着 `:scale "100.0"` + `:unit "percent"`）看起来是对的。

```
:stopOnTimeRate :aggregate "ratio_of_sums" ; :grain :Stop ; :universe :Stop ;
    :numerator :onTimeStopCount ; :denominator :stopCount ;
    :scale "100.0" ; :unit "percent" ; :askedAs "准时率是多少" .
```

`check_dashboard` 现在会把单位缺失、或单位只是裸 `ratio` 的 KPI 卡片判为 FAIL。合法地不是百分比的单位，就把自己说清楚：
`money_per_km`、`liter_per_100km`、`count_per_10000km`。

### 这个应用能画的种类（它不认识的 `render` 就是一张空白框）

`slope · series · composition · ranked · matrix · parallel · treemap · bubble · sankey · hole`

`bar` **不**在其中，而 `treemap` 需要**两个**维度——一维的构成是 `composition`。一个声明 `render: "bar"` 的面板会渲染成
空框，payload 里 `kind: null`，这正是"v5 的图全都看不见"那件事：数据在，渲染器从没跑起来。`kind` 和 `render` 是同一个
字段；payload 会把两者归一，`series: [{metric, label}]` 提供指标。

`dashboard.json` 点名每个面板展示哪一个**已声明**的指标、按什么切，以及缺一个的代价。答不出来的面板，以拒绝卡片的形式
交付。

门禁 `gates/check_dashboard.py --profile …`：每个被引用的指标要么已声明、要么是一个已声明的洞；每个指标具备它面板所需的
形状；独立 SQL 结果一致；分组的比率能加权回未分组的值。

### 仪表盘是交付物，不是副产品

那道门禁验证的是**存在**的面板。它不知道材料点名了哪些家族，所以**一块一个家族都没展示的板也是绿的**——v3 搭建实测：
业务要求的六个家族共 36 个 KPI 指标，每道门禁全绿，而仪表盘仍然只带着从 v1 继承的六个面板。那次搭建做完了 S1–S3 就停了。

所以 S6 的完成线是一次**覆盖检查，写进 profile 自己的话里**，靠的是样例形状的习惯，而不是运气：

1. 列出材料点名的家族（它的标题就是清单）；
2. 逐个点名展示它的指标和面板——一个家族一行，写在发布说明里；
3. 指标存在却没有面板的家族**不算完成**：一个没人看得见的数字，是业务从没要过的声明；
4. 面板的 `kind` 由指标的形状决定，不由口味决定——一个 `groupBy` → `ranked` 或 `composition`，一个时间桶 → `series`，
   两个 `groupBy` → `matrix`，同单位的多个指标 → `parallel`，一个总量中的占比 → `treemap`/`sankey`。

KPI 卡片同理：一个头条数字既属于 `kpis`，**也**属于某个面板，因为卡片说的是它今天是多少，面板说的是它从哪来。

---

## S7. 教程——没人读得懂的本体，是一个多绕了几步的数据库

**步骤种类是复数形式，而且正好五个。** v5 搭建实测：它写成 `kind: "structure" / "definition" / "metric" / "refusal"`——四个全用了单数——于是 T3/T4 在 `{'metric','refusal','definition','structure'}` 上变红，而教学内容本身
没问题。门禁比对的是字符串，所以拼写是契约的一部分：

| kind | items 点名 | 窗格显示什么 |
|---|---|---|
| `objects` | 类 | 表和列 |
| `definitions` | 类（已定义的） | 编译出的谓词 |
| `metrics` | 指标 | 编译出的 SQL **以及它的数字** |
| `refusals` | 类或指标 | 按名的拒绝 |
| `guard` | （无） | profile 的护栏表 |

`T3` 要求至少有一个 `refusals` 步骤；`T4` 要求至少有一个 `metrics` 步骤，且它的 items 既编译**又真跑**。一个所有步骤
都用单数种类的教程看起来完整，却两条都不过。


`tutorial.json` 放在 profile 旁边：6–10 个步骤，按读者提问的顺序排列，用用户的语言。每个 `items` 名字都必须**已声明**。
至少一个指标步骤必须真的跑起来（`…/tutorial/run?metric=…`），且至少一个步骤必须是**拒绝**——那是你交付的最有价值的
东西。

门禁 `--family T`，外加一次现场 `GET /api/ontology/{key}/tutorial/run?metric=…`，返回一个值和 `plan_rows`。

两个形状陷阱，都是实测的：

- **分组指标返回的是行，不是一个值**——`run_metric` 以前对一个分组超载率答 `value: "v2"`。它现在返回 `grouped` +
  `rows` + `row_count`；工作台页面打印 `v2 → 0.754 · v1 → 0.027`，而不是一个破折号。
- **拒绝步骤的 items 仍然必须是已声明的名字。** 这个本体把 28 个指标全编译了，所以没有"已声明但被拒"的指标可以拿来讲。
  于是这一步点名两个已声明的对象（`Telemetry`、`Driver`），讲那些真实存在的拒绝："温度趋势"（没有趋势指标，遥测只覆盖
  2.8 小时）和"还款压力"（没有该列，而模糊匹配器会答一个人数——把这件事说出来）。

---

## S7·5. 暂存之前的自检（四个数字，不是一种感觉）

一次跳过这一步直接走到 S8 的搭建，可能暂存 149 个指标、其中 45 个没有读者；一块看板，业务点名的某个家族没有面板；一份
教程，点名的指标在后来的一次裁剪里被删了。这些在某道门禁里全是绿的，因为门禁检查的是**形状**，不是覆盖。在
`ontology_publish` 之前把这四个数字写下来：

```
1. 指标 → 读者：每个指标都要被某个面板、KPI 卡片、样例、教程，或某个 `:numerator`/`:denominator`
   引用。其余的孤儿——删掉，或者给它一个读者。
2. 家族 → 面板：素材里点名的每个家族一行（`家族 → 指标 → 面板 id → kind`）。
   没有面板的家族是有意缺席，并且要说明为什么。
3. 消费方一致：任何一个指标被删除之后，`tutorial.json`、`samples.json` 与 `dashboard.json`
   都不能再点它的名字——实测：删掉六个孤儿就把 T2 变红了（"每一条教程条目都已声明"），而没人看过那份教程。
4. 预算：机制件（numerator/denominator）不是冗余——6 个 KPI 家族需要约 50 个，比率才算得出来。
   如果设了预算（今天：约 60 个指标），只能同时裁剪**消费方**（教程、样例、面板、卡片）来满足它；
   说出裁哪些、用数字说，而不是删掉机制件、把比率弄坏。
```

### 生成之前：清空货架

一次重建会继承那个数据库上的每一个本体，而每一个都要花一次门禁运行、一行花名册和 UI 里的一张图。部署环境实测：一个数据库
上压着六个冷链本体，其中四个已被取代。所以搭建之前：

1. 列出声明了**这个**数据库的本体（`grep dsn.dbname`）；
2. 除最近的两个之外全部归档（`mv` 到 `profiles/.archive/<key>-<ts>/`，该目录被 git 忽略），并说明是哪些、为什么；
3. 同一次编辑里把它们的 `gates.json` 条目也删掉——从 suite 里移除的 key 必须在声明里看得见，而不是被悄悄跳过；
4. 这之后才跑台阶梯，货架上只放你要扩展的那个基底，别的都不放。

## S8. 通过通道发布——本体自己落地

```
ontology_publish(ontology_key="<key>", source_dir="work/<key>", note="…")
```

它复制出一份**已安装本体的暂存副本**，在那里重跑编译 + 门禁：每个指标编译成功或按名拒绝，每道门禁。一次引入了**新拒绝**
或**失败门禁**的发布，会在暂存阶段就被拒；沿用下来的拒绝单独列出。它**绝不安装**——一位持有 `ontology_editor` 角色的
人确认 `apply`，那会在已安装路径上重跑门禁并提交。

然后记录这一步，并为这个 key 跑 suite：

```
python backend/scripts/ontology_gates.py --key <key>
```

绿 = 每个已声明的家族都通过，且每个 `NOT RUN` 都被点名。新的 key 还需要在 `gates.json` 里有它的声明——没有的话 suite
会以 "has no gate declaration" 失败，这正是设计在起作用。

### 暂存副本也会门禁**你的**页面，所以先生成它

暂存会对着那份暂存副本跑整条构建轨，其中两项检查会在一个新 profile 上真咬：

- `P2 the profile has its own generated page`——`ontology.html` 必须存在于**profile 旁边**。用工作台所用的同一套参数
  （profile 自己的 `ns`/`ontology_dir`/`overlay`/`dsn`/`title`）生成它：`graph_view.py --ns <profile ns> --ontology-dir <profile>/ontology --overlay <profile>/metrics_ext.ttl --dsn … --title "<profile title>" --out <profile>/ontology.html`。它自己的最后一行就是一道门禁——`56/56 positioned, 56/56 documented, 18/18 classes list their properties — PASS`。那一行红了，说明 TTL 里有真实缺陷，不是格式上的小毛病。
- `P2 the page's title is this profile's title`——页面标题必须等于 `settings.title`。一个 `title` 就是自己 key 的
  profile（`"new_coldchain"`）会得到一张标题为 `new_coldchain` 的页面；给它一个业务标题。

### 卡住的搭建必须失败，而不是坐在那里

平台会给一次搭建轮次设上界（`ONTOLOGY_BUILD_TURN_TIMEOUT`，默认 1200 秒），并用这个数字把任务判失败，而不是让它永远
`RUNNING`。这不会让卡住变便宜——它让卡住变得可见。重跑一次卡住过的搭建时，去改让它变大的那个东西（更短的简报、更少的
阅读、跳过已经绿的步骤），而不是再按一次开始。

### 你读到的数字可能是缓存里的数字——加 `refresh=true`

在你的搭建和你读回来的东西之间，坐着两个缓存：

| 什么 | 缓存在什么上 | 多久 |
|---|---|---|
| 编译后的文档（`/api/ontology/{key}/document`） | **声明**文件的一个签名（路径、mtime、大小）——重写 TTL 自己就会让它失效 | 直到某个文件改变 |
| 指标卡片（`/metrics/cards`）——每个值一条查询 | 同一个签名 | 30 秒 |

所以重写完 TTL 之后马上验证是安全的；而在改完**数据**（或跑过一次 mock 刷新）之后马上验证，可能读到一个最多 30 秒前的
值，对着一个你以为刚修好的数字显得一脸绿。任何在数据变更之后跑的检查，都追加 `?refresh=true`；它就是浏览器刷新按钮发出
的那个开关。单个 worker 实测：`document` 冷 0.88 秒 → 热 0.005 秒，`cards` 0.84 秒 → 0.003 秒——缓存正是重开一个
本体免费的原因，也正是读到陈旧值之所以可能的原因。

### 暂存不等于已安装

暂存只写 `<profile>/.staging/<id>/`，别的什么都不写，所以这个 key **没有 profile 文件**，它自己的门禁还跑不了。那是一个
被点名的 `NOT RUN`，既不是通过也不是失败：把 staged id 记进 `gates.json`（`"pending_install": "staged <id>: compile 28/28, gates PASS, 1 NOT RUN (R2)"`），这样 suite 会把理由打印出来，而不是因为缺 profile 而失败。一次实测出来的假红：
在那之前，`check_chapters` 把暂存目录当成一个 profile 枚举，要了五个页面，拿到五个 404，让整套 suite 为一个谁都没安装的
本体变红——枚举器必须要求存在 profile 文件，而一个只暂存的 key 是待安装，不是坏的。

---

## 改动本技能

本技能是一个基底，所以改它就是改未来每一次搭建：

1. 改，并**升 `version:`**（一个你无法标注日期的基底不是基底）；
2. `python backend/scripts/check_skill.py --skill build-ontology-from-db`——每条规则都必须点名一道门禁，或者说出
   `Ungated`；每个链接都必须解析得开；每个文件都必须够得到；每份参考都必须在某一步被排进日程；
3. commit + push + deploy，然后 `systemctl restart`（应用在启动时把 FS 同步到 DB）和
   `python backend/scripts/verify_skill_version.py --restage`（每个智能体的工作区副本只在会话开始时刷新）——再跑一次
   审计，并要求 `every copy the agents read matches the repo file`；
4. 你无法加门禁的规则，写成 `**Ungated (MUST)**`，绝不要写得像它已经被强制。

---

## 拒绝清单就是交付物

```
REFUSED  temperatureTrend : 遥测只覆盖 2.8 小时/1,030 趟 → 画不出趋势（docx Q3/Q19 范围外）
REFUSED  loanPressureRanking : 无该列，docx Q14 明确不纳入系统；不造代理列
REFUSED  fullCompensationCost : 46.1% 未判定是状态，不是 0；只能报已判定部分
```

连数字一起交付。它就是待办清单，也是与业务方的那场谈判。

**一道不会失败的门禁是装饰。** 对每个家族都要知道把它变红的那个变异（改一个预期、删一个 `:references`、去掉一个
`:grain`、把一个属性指向一个不存在的列），并说明你跑过它。没见过门禁失败，你就不知道它有用。

## 本技能不会做的事

- 发明一个阈值、一个粒度、一个维度、一个目标，或一个"可接受"的比率——要么问，要么拒绝
- 把一个数字写进 SQL、一份报告或一个测试
- 接受调用方送来的 SQL（编译器是 SQL 的唯一来源）
- 因为指标跑起来了就断言它是对的——真相标准是第二条独立的查询
- 交付一个没有门禁的 profile，或一道不会变红的门禁
- 把拒绝当成失败：拒绝就是契约
- 为业务明确排除的数据来源造 mock——范围之外就一直是范围之外

## 前提要求（由智能体/宿主提供，不由本技能提供）

| 能力 | 为什么 |
|---|---|
| **shell 执行**（`execute` / `bash`） | 步骤脚本和每一道门禁都要对着真实数据库跑 |
| **文件读 + 写** | TTL、profile、样例、教程和 `steps.json` 都是文件 |
| **一个 PostgreSQL 连接** | 内省和每一道门禁用的都是真实数据，绝不是对数据的描述 |
| **一个带 `psycopg2` + `rdflib` 的 Python** | 脚本和门禁会 import 它们；宿主应用的 venv 两个都有 |
| **`ontology_publish` 工具** | 搭建要经由经过验证的通道落地；没有它，就说发布是 NOT RUN |

## 不是本技能的职责

| 交给谁 | 为什么 |
|---|---|
| 宿主应用的 UI（profile、标签页、页面） | 技能止步于 本体 + profile + 门禁 |
| 写数据库（actions、审计） | 那是已声明动作的关切，有它自己的评审；这里只用 `:state "action"` 标出一次写入可以拥有什么 |
| 决定一个阈值、一个粒度、一条业务规则 | S0 的澄清循环；猜它们正是本技能存在要防止的那种失败 |
| 给 SPARQL 通道用的 R2RML / OBDA 映射 | 那是另一套映射纪律，而且需要它自己的门禁 |

## 与人协作

按这个顺序问：（1）草稿，（2）定义，（3）拒绝——每一份都带来自真实数据库的真实数字，并直白说明哪些数字尚未验证。搭建
过程中发现编译器或门禁的 bug，就修掉并说出来：bug 是证据，不是难堪。
