# 品质经理 · 第 1–2 步产物(2026-11-20 整体退出)

按 admin 要求「从第 1 步重来,换新的口径重拆」,把这份 JD 的第 1 步与第 2 步产物整体撤出流水线目录。
**没有删除** —— 全部原样保存在这里,包括路径结构,可以直接照下面恢复。

```
jd_links/品质经理.yaml              10772 B   步1 产物:15 条原子要求(10 客户原话 + 5 HR 侧)
jd_links/_source/品质经理.txt        1477 B   步1 产物:客户原文锚点(48 行,逐字回查的基准)
jd_docs/品质经理.定稿.md             9857 B   步2 产物:正文 + 附录 F(我方建议 4 项)
jd_docs/品质经理.fields.json         7934 B   步2 产物:机器可读版(tally 有值 8 / 未写 34)
jd_docs/品质经理.待补清单.md         5766 B   步2 产物:A/B/C 三级回填表(A 8 · B 16 · C 10)
jd_reviews/品质经理.yaml             3921 B   人定的决策账本(3 条粒度 + 1 条排除)
```

## 为什么整体退出,而不是只退一半

`jd_docs/` 的三份是**从 `jd_links/` 算出来的**。只退引用、留着定稿,目录里就会出现一份
"没有出处的定稿"—— 它长得像产物,但已经无法回查。所以第 1 步和第 2 步必须一起退。

## ⚠️ 还没退、但现在**已经过期**的东西

下面这些是第 3 步及之后的产物,它们当初是**按旧的引用文件**算出来的。引用一撤,它们就失去依据:

```
collection/品质经理.yaml · 品质经理.采集清单.md · 品质经理.廖___.一面脚本.md
shortlist/品质经理.yaml                 (32 KB,保留 169 / 排除 101 是旧口径的结果)
picks/品质经理.md · 品质经理.yaml        (选人结果)
cv_docs/ · cv_draft/ · cv_interview/ · cv_text/  (廖 一个人的,绑定旧的 15 条要求)
```

**不要拿它们当依据。** 重新跑完第 1–2 步之后,要么按新引用重算,要么把它们也移到这里 ——
但那是另一步的决定,本轮没动。

## 决策账本里的决定,不会自动跟过来

`jd_reviews/品质经理.yaml` 里记着 admin 当时定过的 4 条:

- C-04(第 17 行「英语口语熟练及独立书写英文8D报告」)**不拆** —— 代价:永远只能判 partial
- C-07(第 19 行「分析、改善」)**不拆**
- C-10(第 20 行「沟通、协调」)**不拆** —— 代价:这条本身判不了,只能留给面试
- X-01(IATF16949)**不作为任职资格** —— 它只出现在岗位职责段,是公司要做的事,不是候选人必须具备的条件

新的抽取如果又把第 17/19/20 行拆开或合并成别的样子,这些决定要**重新确认一次**,
在新账本里重新签。旧账本留着就是为了让这件事有据可依,而不是被忘掉。

## 恢复办法

```bash
cd <repo>
mv work/talent/_retired/品质经理-redo-2026-11-20/jd_links/品质经理.yaml          work/talent/jd_links/
mv work/talent/_retired/品质经理-redo-2026-11-20/jd_links/_source/品质经理.txt  work/talent/jd_links/_source/
mv work/talent/_retired/品质经理-redo-2026-11-20/jd_docs/*                        work/talent/jd_docs/
mv work/talent/_retired/品质经理-redo-2026-11-20/jd_reviews/品质经理.yaml        work/talent/jd_reviews/
```

恢复后必须重跑门禁与回检(**改了产物就该重跑,不是"看起来没坏"就算**):

```bash
cd backend && set -a && source ../.env; set +a
env -u PGPORT .venv/bin/python -m scripts.talent.check_component_catalog
env -u PGPORT .venv/bin/python -m scripts.talent.verify_jd_report --jd 品质经理
```
