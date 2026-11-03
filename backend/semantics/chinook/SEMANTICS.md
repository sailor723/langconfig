# Chinook — 语义层（给 SQL 图的 SEMANTICS）

> `load_semantics` 读它，只放 DDL 看不出来的东西；列名/类型来自 `get_schema`，不重复。

## 表与 join（DDL 无外键，路径只有这几条）

`artist` 275 · `album` 347 · `track` 3,503 · `genre` 25 · `customer` 59 · `invoice` 412 ·
`invoiceline` 2,240 · `playlist` 18 · `playlisttrack` 8,715 · `employee` 8 · `mediatype` 5

```
track.albumid→album   album.artistid→artist   track.genreid→genre
invoiceline.trackid→track   invoiceline.invoiceid→invoice   invoice.customerid→customer
```

## 口径规则

1. **`milliseconds` 是毫秒**：分钟 `/60000.0`，秒 `/1000.0`，报数带单位。
   "最长曲目"= 单曲最大；"平均时长最长"= `AVG()` 最大。两件事。
2. **`genre` 混着影视/有声书**（`TV Shows`、`Drama`、`Comedy`、`Sci Fi & Fantasy`、
   `Science Fiction`、`Audiobook`，均 40+ 分钟）：答"音乐流派最长"要么 `NOT IN` 排除，要么明说包含。
3. **收入只算美国开票**：`WHERE invoice.billingcountry='USA'`。不加会高估约 3 倍
   （2,328.60 → 523.06）。**这条推不出来，必须显式加。**
4. **收入口径二选一**：`SUM(invoice.total)`（存储值）vs `SUM(invoiceline.unitprice*quantity)`；
   实收用 `invoiceline.unitprice`（成交价），不是 `track.unitprice`（标价）。
5. **ARPU = 美国营收 ÷ 有美国发票的客户数（13）**，分子分母同一批发票：

   ```sql
   SELECT ROUND(SUM(total) FILTER (WHERE billingcountry='USA')
     / NULLIF(COUNT(DISTINCT customerid) FILTER (WHERE billingcountry='USA'),0), 2) FROM invoice;
   ```

   正确 **40.24**。错答：**39.47**（分子分母都用全量）、**8.87**（分母用全量客户 59）、
   当成 `AVG(total)`（那是平均发票额）。
6. **ROE 算不出，必须拒绝**：本库无资产负债表，分母（股东权益）不存在。说明缺口，
   给能算的（净利润 = 美国营收 × 12%），列出还缺什么；禁止假设权益或直接给 ROE 百分比。
7. **计数**：客户 59、艺人 275；"发过专辑的艺人"要 join 去重。

## 回答规则

- 时长带单位；金额报名（发票头/行明细/美国口径）；"最长/最多"说明是否排除影视类。
- 库里没有的字段不编：直接说没有，并给出能算的替代口径。
