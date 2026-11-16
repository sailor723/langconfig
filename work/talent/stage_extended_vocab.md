# 扩展词表进入 `talent_v1`（已 apply，commit `63b88363`）

> 执行 2026-11-16。走的是仓库自己的规矩：`services/ontology_publish.stage()` → `apply(confirmed=True)`。
> 中间经历 4 次 `refused`（每次都是门禁抓出一个真问题），第 5 次 `gates_ok=true` 才 apply。
> **staged id `1794815488-7a83f6`，git commit `63b88363`，4 个文件 +811/−185。**
> 审计记录：`ontology_publishes`，`key='talent_v1'`，`status='applied'`。

---

## 1. 改了四个文件

| 文件 | 改了什么 |
|---|---|
| `abox.ttl` | 用 `build_abox.build()` 重生成：并入 `skill_patterns_ext.py` 的 26 条扩展技能（548 条新 `hasSkill` 断言）；**role 段原样接回** |
| `reasoning.ttl` | 追加 6 个类别类：`QualityMethod` `HarnessCraft` `WireEquipment` `GeneralCapability` `HRAdmin` `Compliance` |
| `ontology/01-structure.ttl` | 补登 6 个引擎对象（5 台账 + 1 分歧视图）、26 列、4 个对象属性 |
| `reasoning.json` | `excluded` 按决定 C 的新语义重写：保留 2、移出 19（后者改由闸门披露） |

**公理按决定 C 降为必要条件**：删掉 13 个 `∃yearsExperience` / `∃educationRank` facet，
保留 `:Candidate ⊓ ∃hasSkill.(该岗位类别 OR)`。`yearsExperience`/`educationRank` 作为属性声明仍在
（0 处 restriction），只是不再参与成员判定——这是 D10 的直接落实。

## 2. 前后对比

| | 装着的 `talent_v1` | 暂存候选 |
|---|---|---|
| 技能个体 | 28 | **54**（+26） |
| ABox 行数 | 3,224 | ~3,900 |
| `hasSkill` 断言 | 1,001 | **1,549**（+548） |
| 至少 1 个技能的候选人 | 259 | **274** |
| TBox 类别 | 16 | **22** |
| 指标编译 | 11 / 11 | **11 / 11，0 refused** ✓ |

## 3. 门禁收敛过程：每一步都是门禁抓出来的

`stage()` 跑了 `gates.json` 声明的 6 个家族。收敛过程（每一步都是门禁抓出来的，不是我看出来的）：

| 轮次 | 失败 | 原因与修复 |
|---|---|---|
| 1 | `check_structure`：5 张表未声明 | 我加的 `requirement` / `requirement_skill` / `candidate_skill_evidence` / `fit_component` / `v_shortlist` 没登记 → 补登 |
| 2 | `check_structure`：26 列未声明 | 结构文件的规矩是"每条 `:physicalColumn` 对应一列真实存在的列" → 逐列登记 |
| 3 | `check_structure`：`:fitCandidate` 属于两个类 | 该名字已被 `CandidateRoleFit` 占用 → 改名 `:fcCandidate` / `:fcRole` / `:slCandidate` / `:slRole` |
| 4 | `check_structure`：对象属性缺 `:references` | 仓库风格要求 `:physicalColumn` + `:references` 成对出现 → 补齐 |
| 5 | 仅剩 `check_abox_sync` 2 项 | 见 §5：这是 apply 前的预期状态 |

**结论：结构层（表、列、属性、命名冲突）现在全部合规。**

## 4. 抓到一个我自己制造的回归

第一版重生成把 **10 个 role 个体连同 28 条 `requiresSkill` 一起丢了**——因为
`build_abox.build()` 只写候选人、技能和 `:appliedFor`，而 role 个体
（`:requiredYears` / `:requiredEducationRank` / `:requiresSkill`）是另一支脚本追加进 `abox.ttl` 的。

实测后果，在库副本上重算时打出来：

```
candidates 277 · skills 53 · roles 0 · matches 204 · ranked 0     ← 丢了
candidates 277 · skills 53 · roles 10 · matches 204 · ranked 192  ← 接回后
```

`roles 0 / ranked 0` 意味着**名单直接空掉**。修复：`_roles_block()` 从现行 ABox 原样取 role 段接回，
判据是"有没有 `:role_X a :Role` 个体声明"——不是"有没有出现 `:role_"`
（后者在 `:appliedFor` 里天天出现，第一版判据因此失效）。

## 5. 为什么 `check_abox_sync` 在 stage 期间不可能变绿（by design）

`_run_gates()` 用 `--profile <暂存 profile>` 跑每个 gate。`check_abox_sync` 的契约是
**"表 = 对已安装本体的重新推理"**，而它读的库名来自 `dsn.dbname` —— 也就是**活库**。
所以 stage 期间它必然比对"暂存 ABox vs 活库"，而活库按定义还是旧的。

**这不是缺陷，是安装时门禁**：`apply()` 会在移入文件之后重跑同一批 gate。

### 证明 apply 会成功：在库副本上重算

| 步骤 | 结果 |
|---|---|
| `createdb -T talent_db talent_db_stage` | 副本 |
| `materialize.py --profile <暂存 profile，dsn→talent_db_stage> --dsn-db talent_db_stage` | 277 候选 / 1549 技能 / **role 10** / requiresSkill 28 / match 204 / ranked 192；HermiT 2.9s，consistent=True |
| `check_abox_sync.py --profile <同一 profile>` | **14 checks · 0 failed · green** |

逐项：7 个岗位类成员与推理一致 ✓ · 推荐表 192 行与规则推导一致 ✓ · 每条 fit 分数符合写定权重 ✓ ·
**每个 rank 符合写定的平手规则** ✓ · 技能/年限/学历列与 ABox 一致 ✓ · 加工来源与推理机符合声明 ✓ · 本体仍一致 ✓

## 6. 30 项 NOT RUN 的含义（不是失败）

- `check_dashboard` 的 D3 全是 **ABC 冷链**的指标名（`tripCount` / `stopCountByRouteVersion`…），
  跑在 `talent_v1` 上自然是空的
- `check_ontology_generic`：**无 `truth.json` 的 `_definitions` 映射**

## 7. 两个真源的问题（已由决定 C 解决）

岗位要求现在同时存在于两处：`reasoning.ttl` 的公理（决定**成员资格**）与
`requirement` 表（决定**评分与闸门**）。这次 stage 只补了词表，**没有把新要求写进公理**，
所以：**名单数字不会因为这次 stage 而改变。** 要让 QC 工具、电线设备那些要求真正参与判定，
必须改公理 —— 卡在 N1。

## 8. apply 的实际顺序（和我预判的不同，两次被迫调整）

1. **`apply` 只接受 `staged`，不接受 `refused`** —— 所以"声明成 known_failures 就能解除阻塞"是错的：
   `gates.json` 的 `known_failures` 只被 `scripts/ontology_gates.py` 在跑完后**打印**
   （"so they cannot hide as green"），不影响 `failed` 集合与退出码。**它登记事实，不解除阻塞。**
2. **`materialize` 的 `DROP ... CASCADE` 会把依赖视图一起删掉** —— `v_shortlist` 与 `v_axiom_vs_gate`
   随之消失，下一次 stage 报 "`v_axiom_vs_gate` is not a table in this database"。
   所以重算之后必须再跑 `scripts/talent/shortlist.py --build` 重建台账与视图。

**正确的完成序列**：

```bash
pg_dump … talent_db > work/talent/talent_db_before_apply.dump     # 备份
materialize.py --profile <暂存 profile> --dsn-db talent_db          # 用暂存 ABox 重算活库
python -m scripts.talent.shortlist --build                          # 重建台账 + 视图（CASCADE 删掉了）
python -m scripts.talent.stage_extended_vocab                        # 重新 stage → gates_ok=true
ontology_publish.apply(staged_id, confirmed=True)                   # 移文件 → 重跑门禁 → git commit
```

## 9. 那 30 处 rank 失配的根因（已修）

`materialize.py:352` 的平手键用的是 `r[7]` = **`years_margin`（超出年限）**，
而 `fit.py::order_key` 的文档写明规则是 *"more years first"*、实现用 `years_experience`。

后果有业务含义：**年限未知 → `years_margin` 为 None → 按 0 处理 → 与"刚好够格"同分，
于是排在年限=1 的人前面** ——把"不知道"当成了"经验正好"。这正是 §16 里修过的那个坑，
在排名里漏了同一份。改成 `r[5]` 后：`check_abox_sync` 由 30 处失配变为 **14/0 green**。

（顺带纠正本报告早期的一个无效检查：我曾用 `zip(原列表, rank_rows 返回的已排序列表)` 判定
"表与 rank_rows 自洽"，两者比的不是同一批行，那个结论不成立。）

## 10. apply 之后的状态

| 项 | 结果 |
|---|---|
| `check_abox`（安装 profile） | **54 checks · 0 failed · green** |
| `check_abox_sync`（安装 profile） | **14 checks · 0 failed · green** |
| 指标编译 | 11 / 11，**0 refused** |
| 名单（`v_shortlist`） | qualified **299** · near 60 · excluded 2411 |
| 公理 vs 闸门 | agree_qualified **143** · axiom_only 609 · gate_only 156 · agree_rejected 1862 |
| 一致率 | **13% → 48%** |

业务跟单前 3 名（年限未知的人不再插进已知年限的人中间）：

```
1  100.00  10年   cand_业务跟单_东莞_6_10K_和___10年以上
2   85.00   3年   cand_业务跟单_东莞_6_10K_黄___3年
3   80.00  10年   cand_业务跟单_东莞_6_10K_王___10年以上
```

**未解决的（都需要人或客户拍板）**：
1. 人资专员 / 工程文员 / 关务报关员 **在 TBox 里没有岗位公理**（JD 没写年限门槛，`author_tbox`
   当年跳过），因此只由闸门判定，全部落进 `gate_only`（156 行）。补公理等于替客户发明门槛。
2. **N1：技能优先级**——26 条 essential 里只有 5 条 desirable（全部来自 JD 的「优先」字样）。
   desirable 层要成为区分度来源，必须先由客户给出优先级。

## 11. 回滚

```bash
# 回到 apply 之前的库（表结构 + 数据）
pg_restore -d talent_db work/talent/talent_db_before_apply.dump
# 回到 apply 之前的文件
git revert 63b88363
```
已删除的证明用库副本：`talent_db_stage`。
