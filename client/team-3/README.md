# 產出標工與效率計算工具

Python 命令列工具，按月讀取各部門「產出標工計算表」與全廠工時表，
算出部門產出標工與效率，輸出「匯總 / 明細 / 異常」三張表。

目前進度：**T1、T2、T4 完成並驗收；T3 於 DG 側打通；DG 2 部效率全對**
（金架九部 96.48%、金架燒焊部 73.46%，與 KPI 完全一致）。

## 支援的模板

| 模板 | 用途 | 已接入 |
|---|---|---|
| `dg_frontback` | 前後段型（前段表 A:E、後段表 F:T、新舊款 0.85） | 金架九部 |
| `dg_equivalent` | 多產量流 + 已算好等效工時，按月加總 | 金架燒焊部、CNC圈形部/生產 |

## 快速開始

```powershell
$py = 'C:\Users\j03386\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = "<workspace>\tools"

# T3 效率匯總（i + m → n，並對賬 KPI）
& $py -m stdhours --month 202610 --summary

# T1 產出標工
& $py -m stdhours --month 202610 --dept 金架九部

# T2 工時規則（輸出 工時匯總 + 工時排除）
& $py -m stdhours --month 202610 --hours

# T4 幫工工時（對賬調入/調出）
& $py -m stdhours --month 202610 --bango

# 全部部門
& $py -m stdhours --month 202610 --all
```

執行後會印出對賬結果，例如：

```
[DG] 金架九部  報數 44,962  產出標工 5,771.679 h（前段 2,317.648 / 後段 3,454.031）  異常 0 筆
                對賬 5771.679 vs 手工表 5771.679（+0.00%）
```

## 配置

所有部門與口徑都在 `config/departments.toml`，**加部門不改代碼**：

```toml
[[dept]]
factory = "DG"
name = "金架九部"
template = "dg_frontback"
file = "DG產出標工計算{ym}/金架九部2026產出標工計算表分前后段{m}月.xlsx"
golden_wh = 5771.679014476938   # 10 月手工表合計，用於對賬
```

路徑佔位符：`{ym}`=202610、`{m}`=10、`{mm}`=10、`{name}`=部門名。

## 口徑（已寫死在模板 + 可用 config 覆寫）

- 數量取 `生產報數`；只計「種類a = 架」且「時效 ≠ 不計」的行
- 前段＝描述 `SH分公司前工序`；後段＝描述 `SH分公司包裝` / `SH分公司包裝HY`
- 標工表是**左右兩塊**：`A:E` 是前段表、`F:T` 是後段表，各有自己的「款號」欄
- 款號比對**不區分大小寫**（表裡有 `m29059` 這種小寫）
- 新舊款：前綴 `M3 / T14 / H128 / H129 / T15` 一律新款；否則物料主檔查得到＝新款，查不到＝舊款
- `0.85` 係數**只對舊款生效**
- 查無標工 → 按 0 計，並進異常清單

## 效率口徑（T3，DG 側已逐部門驗證）

```
當月完成品標準工時 i  = 部門產出標工工時
考核出勤工時 m        = 工時底數 + 調整工時 − 特別調整
實際效率 n            = i ÷ m
目標定額 l            = i ÷ j
```

「工時底數」= 按分類規則計入的人員工時（排除固定/辦單/浮動）；
`調整工時`、`特別調整` 是 PIE 手工填在 KPI 表裡的調整項。

> 這條公式不是猜的：KPI 表本身有 `W級調整前出勤工時` 欄，
> 金架九部 = 6,170.206661，正是工具算出的底數；再加上 −27.9 − 160 之後
> 得到 5,982.306661，與 KPI 的考核出勤工時**到小數第六位一致**。

## 舊版 .xls 怎麼讀（已不再依賴 LibreOffice）

`tools/stdhours/xls.py`是一個自研的 **BIFF8 讀取器**：
直接解析 `.xls` 的 OLE2 容器與 BIFF8 記錄，不呼叫任何外部程式。

實測（本機）：

| 檔案 | 大小 | 開檔 | 讀一張表 |
|---|---|---|---|
| `2610全廠工時-XJ.xls` | 11.8 MB | 0.1 s | 0.1 s |
| `26年10月工時-XY.xls` | 33.8 MB | 0.1 s | 0.2 s |

對照 LibreOffice：同一個 11.8 MB 檔燒了 **575 秒 CPU 仍未產出**。

正確性驗證：`tests/test_xls.py` 把 `.xls` 直讀結果與 LibreOffice 轉出的 `.xlsx` **逐格比對**
（出勤表 6,000+ 個數值儲存格，0 處不一致）。

支援：BOUNDSHEET、SST（含 CONTINUE 跨記錄字串）、LABELSST、LABEL、RSTRING、
NUMBER、RK、MULRK、BLANK、MULBLANK、BOOLERR、FORMULA（含快取值與後續 STRING）、EOF。
不支援：加密檔（會明確報錯）、BIFF5 及更早版本。

> 若某天遇到讀不動的檔，仍可把 LibreOffice 轉出的 xlsx 放進 `cache/xlsx/`（檔名同來源、去 `.xls`），
> 工具會自動改用；`STDHOURS_ALLOW_SOFFICE=1` 可強制走 soffice。

## 測試

```powershell
& $py -m unittest discover -s tests -p 'test_*.py' -v
```

30 個測試，涵蓋三條驗收線：

| 測試檔 | 驗收內容 | 錨點 |
|---|---|---|
| `test_dg_frontback.py` | T1 標工 | 金架九部 5,771.679（前段 2,317.648 / 後段 3,454.031） |
| `test_hours.py` | T2 工時 | 膠架五部 21,529.57、脾形中心 10,794.47、配件三部/鐳射組 973.67 |
| `test_bango.py` | T4 幫工 | 調入 6 部門、調出 6 部門、浮動 27h 不入調出 |

## 目錄

```
tools/stdhours/
  converter.py    .xls → 預轉檔查詢（cache/xlsx/）
  readers.py      工作表定位、表頭索引（處理重複欄名）
  models.py       ProdRow / Issue / DeptResult
  hours.py        工時分類規則（固定/辦單/浮動/納入效率計算/非W轉W/離職）
  hours_report.py 工時匯總 + 工時排除明細
  bango.py        幫工工時（樞紐左出右入 + 明細）
  kpi.py          KPI 表讀取（效率目標 / 出勤 / 實際效率）
  report.py       匯總 / 明細 / 異常 三張表
  cli.py          命令列入口
  templates/
    dg_frontback.py   DG 前後段型模板
config/departments.toml
tests/test_dg_frontback.py  tests/test_hours.py  tests/test_bango.py
outputs/            跑出來的報表
```
