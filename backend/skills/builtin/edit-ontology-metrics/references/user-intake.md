# User intake — the user speaks business, you speak declarations

A user asking for a metric does **not** know what a `:grain` is, cannot write TTL, and must never be
asked for a column name, a table name or a JOIN. They know the business: what the number is called,
what question it answers, how it is worked out in words, what one row of the business is, what is in
scope, and what they want to look at it by.

Your job is the translation. This file is the contract for that translation, and the form the panel
puts in front of the user is built from it.

## The intake form (what the user fills in, in their own words)

| # | field | what it means | example (business words) | required |
|---|---|---|---|---|
| 1 | **它叫什么** | the phrase the user types when asking | 每千公里破损箱数 | yes |
| 2 | **回答什么问题** | one sentence, as a person would ask it | 每跑一千公里会破多少箱？ | yes |
| 3 | **怎么算** | the arithmetic in business language | 一共破了多少箱 ÷ 一共跑了多少公里，再乘 1000 | yes |
| 4 | **一行代表什么** | the grain, named as a business object | 一次配送（一个站点） | yes |
| 5 | **算哪些 / 不算哪些** | the scope, in business terms | 全部；不含测试门店 | yes, or "全部" |
| 6 | **要分维度看吗** | the dimensions, business nouns, multi-select | 按线路版本、按车辆 | optional |
| 7 | **单位 / 量级** | boxes, yuan, times, %, per thousand | 箱 | optional |
| 8 | **大概多少** | a sanity number, not a target | 三十几箱 | optional |
| 9 | **谁用它做什么决定** | who acts on the number | 调度决定要不要加车 | optional |
| 10 | **其他约定** | anything else about the definition | 只算客户已签收的 | optional |

The form asks **nothing** about tables, columns, joins, `:grain`/`:universe`/`:where` TTL names,
aggregates or files. Those are yours to derive from the ontology that is already declared.

## What each answer becomes (your side of the table)

| field | you derive | from where | if the user left it blank |
|---|---|---|---|
| 1 name | `rdfs:label` + the metric's local name | their words, verbatim | you cannot guess a phrase: ask |
| 2 question | `:askedAs` | their sentence | optional; derive from label |
| 3 arithmetic | `:aggregate`, `:formula` / `:numerator`+`:denominator`+`:scale`, or a `:where` | the *declared* properties and classes; the compiler derives joins from `:references` | ask — the arithmetic IS the definition |
| 4 one row | `:grain` (+ `:universe`) | the object they named must exist as a class; if it does not, that is a finding, not a guess | **ask** — a wrong grain changes every number |
| 5 scope | `:where` on a declared definition class, or nothing | an existing `owl:equivalentClass` axiom; **never invent a threshold** | treat "全部" only if they said it; otherwise ask |
| 6 dimensions | `:groupBy` | properties reachable through declared relationships (2 hops is fine) | none — do not add dimensions they did not ask for |
| 7 unit | `:unit` | their word; use the ontology's existing units | best guess from the arithmetic |
| 8 expected | **your verification target** | you compute it with an independent route | not needed, but if given it must match |
| 9 decision | `:businessDescription` (one line on why it exists) | their answer | optional |
| 10 conventions | `:businessDescription` | their words | optional |

Two rules that keep the translation honest:

1. **A blank is a question, not a default.** Grain, scope and thresholds decide what the number
   *means*; if the user did not say, ask them in business words — "这个数是按*每一趟车*算，还是按
   *每一家门店*算？" — never pick one because it is convenient.
2. **Do not answer with TTL.** Never paste declarations at a user. Report: what the number now is, the
   sentence it answers, which tables/objects it had to touch (called that, not `JOIN`), the value, the
   independent route that proved it, and what a person must still decide.

## How the panel asks: one question at a time, then a summary, then an interpretation

A nine-field form gets nine half-answers. The panel is a **stepper**: it asks one business question at
a time (with an example and one line saying what that answer changes), and the last step is not a
question — it is the **summary**, the same answers restated as sentences the user can disagree with,
each with a way back to the step that produced it. Skipping an optional step means "you will ask me",
never "pick a default".

**Then the agent runs in two phases, and the second one needs a second confirmation.**

- Phase 1 — **interpretation only.** The composed message ends with *"先只给我你的解读，不要改任何文件"*.
  You answer with: the declaration you intend (in business words first), which objects it lands on,
  the expected value, and the independent route you will use to check it. No file is touched.
- Phase 2 — the user answers *"解读确认，可以实施"*. Only then do you edit, verify and stage.

Why: the interpretation is where a wrong grain or a wrong denominator gets caught, and it is free —
one message, no files, no gates. A user who cannot read TTL can still read "这个数是 破损箱数 ÷ 计划里程 ×
1000，按站点数、按行程算里程" and say "不对，里程要按实际跑的".

For **generation** (the build job) the same idea applies with the skill's own stop point: the confirmed
summary is the user's sign-off on the brief, and the job stops with questions rather than guessing if
something that changes the data's meaning is still missing.

## The message the panel composes from the form

```
【新增指标】（业务口径，不含任何技术细节）

- 用户会这么叫它：{name}
- 它会回答：{question}
- 怎么算（业务语言）：{arithmetic}
- 一行代表：{grain}
- 算哪些 / 不算哪些：{scope}
- 要看的维度：{dimensions}
- 单位 / 量级：{unit}
- 大概多少（用来校验，不是目标）：{expected}
- 谁用它做什么决定：{purpose}
- 其他约定：{notes}

把它翻译成声明：对象与属性从已声明的本体里取，:aggregate / :formula（或 :numerator+:denominator+:scale）
/ :grain / :universe / :where / :groupBy 由你决定，JOIN 由编译器从 :references 推导 —— 不要向我问表名、
列名或 TTL。任何会改变这个数含义而上面没答的点（颗粒度、范围、阈值、维度），先问我，不要自己定。

做完按 edit-ontology-metrics 验证：编译；值与你自己写的第二条独立路线一致；其余指标的数字一个都不许变。
然后 ontology_publish 暂存（只带改动的文件），报告里写：值多少、独立路线是什么、哪些门禁 NOT RUN。
```

## Worked example — the seven answers that produced `damagePer1kKm`

| field | what a user would type |
|---|---|
| 1 | 每千公里破损箱数 |
| 2 | 每跑一千公里会破多少箱？ |
| 3 | 一共破了多少箱 ÷ 一共跑了多少公里，再乘 1000 |
| 4 | 一次配送的一个站点（货损是在站点上记的） |
| 5 | 全部 |
| 6 | 不分维度（先要一个总数） |
| 7 | 箱 |
| 8 | 三十几箱 |
| 9 | 判断是不是某条线路/某台车在货损上要复查 |

What that turned into, without the user seeing a single declaration: a cross-grain ratio —
`sum(stops.damaged_boxes)` over `sum(trips → routes.planned_km)` scaled by 1000 — where the
`trips ⋈ routes` join exists only because `:routeOf` is declared, and where "一行代表一次配送的一个站点"
became `:grain :Stop`, "跑了多少公里" became `:universe :Trip`. Measured: **36.0097452699625488**
(8,144 boxes / 226,161.0 km). The user's sanity answer ("三十几") matched, which is the cheapest check
there is and the reason field 8 exists.

## What the user's words do NOT let you skip

- **a link that is not declared**: if the two objects are not connected by `:references`, the join is
  refused by name. Report that as "这批数据里没有把 A 和 B 连起来的声明" and ask/propose the declaration
  — do not write a JOIN by hand.
- **a class that does not exist**: "一行代表一次配送的一个站点" is fine because `:Stop` exists. If they
  say "一行代表一次装车", check the ontology; a missing object is a modelling decision, not a translation.
- **a threshold**: "只算客户已签收的" is a definition only if the data has that column and the business
  owns the rule. Otherwise it is a refusal by name, and the refusal is the deliverable.
