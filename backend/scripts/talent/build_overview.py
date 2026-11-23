#!/usr/bin/env python3
"""生成**总览文档** `work/talent/OVERVIEW.md` —— 拿去给用户演示的那一页。

## 为什么要有它

`PROCESS.md` 是流程的**权威说明**（规则、判据、每条为什么），`STATUS.md` 是**按日期堆的流水账**。
演示时两样都不合适：一个太重，一个太散。这个脚本产出的是一页
"**从客户原文到最终 5 个人**"的全景 —— 每一步谁做、产出什么、门禁卡什么、现在是什么数。

## 数字从哪来

- 漏斗数字：`jd_links/`、`shortlist/`、`picks/` 现场扫出来的，**不手写**；
- 教程类数字：复用 `tutorial_facts.collect()`（同一份 facts，避免两处各算一遍）；
- 门禁汇总行：现场跑一次 `check_component_catalog` 取最后一行（`--skip-gate` 可跳过）。

用法:
    python -m scripts.talent.build_overview            # 生成 OVERVIEW.md
    python -m scripts.talent.build_overview --skip-gate # 不跑门禁（快）
    python -m scripts.talent.build_overview --check     # 只校验文件是否最新
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

from scripts.talent import tutorial_facts as TF  # noqa: E402

TALENT = ROOT / 'work' / 'talent'
DEST = TALENT / 'OVERVIEW.md'

STEP_NAMES = ('1 出初始 JD', '2 定稿', '3 初筛', '4 一面', '5a 短名单', '5b 最终名单')


def jds() -> list[str]:
    return sorted(p.stem for p in (TALENT / 'jd_links').glob('*.yaml'))


def _n(v) -> int:
    """count.excluded 是数字,旧产物里是列表 —— 两种都要能读。"""
    return int(v) if isinstance(v, (int, float)) else len(v or [])


def funnel() -> list[dict]:
    out = []
    for jd in jds():
        sl = yaml.safe_load((TALENT / 'shortlist' / f'{jd}.yaml').read_text(encoding='utf-8')) or {}
        lst = (TALENT / 'shortlist' / f'{jd}.面试名单.yaml')
        tgt = (TALENT / 'shortlist' / f'{jd}.目标名单.yaml')
        picks = (TALENT / 'picks' / f'{jd}.yaml')
        lst_d = yaml.safe_load(lst.read_text(encoding='utf-8')) if lst.is_file() else {}
        tgt_d = yaml.safe_load(tgt.read_text(encoding='utf-8')) if tgt.is_file() else {}
        pk_d = yaml.safe_load(picks.read_text(encoding='utf-8')) if picks.is_file() else {}
        fin = (tgt_d.get('final') or {})
        out.append({
            'jd': jd,
            'kept': len(sl.get('kept') or []),
            'excluded': _n((sl.get('count') or {}).get('excluded')
                           if (sl.get('count') or {}).get('excluded') is not None
                           else len(sl.get('excluded') or [])),
            'interview': len(lst_d.get('selected') or []),
            'shortlist': len(tgt_d.get('selected') or []),
            'final': int(fin.get('count') or 0),
            'judgeable': (pk_d.get('count') or {}).get('judgeable_requirements'),
            'total_req': (pk_d.get('count') or {}).get('total_requirements'),
            'tie_band': (tgt_d.get('cut') or {}).get('tie_band'),
        })
    return out


def gate_line() -> str:
    try:
        proc = subprocess.run([sys.executable, '-m', 'scripts.talent.check_component_catalog'],
                              cwd=str(BACKEND), capture_output=True, text=True, timeout=600)
        out = (proc.stdout or '') + (proc.stderr or '')
        for ln in reversed(out.splitlines()):
            if 'checks ·' in ln:
                return ln.strip()
    except Exception:                                             # noqa: BLE001
        pass
    return '（未跑）'


def render(facts: dict, rows: list[dict], gate: str) -> str:
    s5, s7, s8, s13 = facts['step5_gates'], facts['step7_states'], facts['step8_evidence'], facts['step13_replay']
    s10, s12, s2 = facts['step10_two_sources'], facts['step12_refusals'], facts['step2_individuals']
    pt = facts['pipeline_truth']
    lib = s5['library_size']
    cites = sum(v['citations'] for v in s5['per_jd'].values())
    client = sum(v['client'] for v in s5['per_jd'].values())
    hr = sum(v['hr'] for v in s5['per_jd'].values())
    L: list[str] = []
    A = L.append

    A('# 招聘流水线 · 总览（演示用）')
    A('')
    A('> 一页讲完：**怎么走完一次招聘**、**每一步业务做什么、技术怎么实现**、**凭什么信结论**。')
    A('> 数字由 `scripts/talent/build_overview.py` 从产物现算，不手写（`--check` 可校验是否过期）。')
    A('')
    A('## 一句话')
    A('')
    A('**客户原文 → 可回查的闸门 → 决定谁值得面 → 电话补数据 → 两道闸筛出 5 个人 → 每人一份可追到行号的判定说明。**')
    A('')
    A('## 全流程图')
    A('')
    A('```')
    A('  ① 客户给 JD          ② HR + 业务定稿         ③ 初筛（决定谁值得面）')
    A('  ────────────         ─────────────          ──────────────────')
    A('  原文一字不改    →    拆成要求 + 阈值    →   只剔"简历上明确不合格"的')
    A('  逐字可回查            每条落到客户行号       读不到的一律留 + 进待核清单')
    A('        │                    │                       │')
    A('        ▼                    ▼                       ▼')
    A('  client 原文.txt      jd_links/<JD>.yaml        shortlist/<JD>.yaml')
    A('                       要求库 + 决策账本          面试名单 + 待核清单')
    A('                                                     │')
    A('  ⑤b 最终名单 ≤5   ←   ⑤a 短名单 ≤10     ←        ④ 一面（补数据）')
    A('  ──────────────       ──────────────             ──────────────────')
    A('  没有硬伤的人          按九层证据阶梯排序           一次电话两份产物：')
    A('  门槛 0 不满足        切线并列数写进产物           ① JD 要的字段问齐')
    A('  硬证据 ≥1                                       ② 能力要能举例')
    A('  未知 ≤3                      │                  答案落回"哪条要求"')
    A('        │                      │                        │')
    A('        └──────→ ⑥ 选人 + 逐人判定说明 ←────────────────┘')
    A('                  （客户原文 / 行号 / 值来源 / 四态）')
    A('```')
    A('')
    A('**交接关系**：业务交原文 → HR+业务交闸门 → HR 交面试名单 → HR 交一面记录 → HR 交短名单 → 业务+HR 交最终 5 人 → 用人部门面这 5 人。')
    A('每一步都落成文件；下一步只读上一步的产物，不靠人转述。')
    A('')
    A('## 现在跑出来的漏斗（五条线）')
    A('')
    A('| JD | 初筛保留 | 排除 | 面试 | 短名单 | 最终 | 可判要求 | 切线并列 |')
    A('|---|---|---|---|---|---|---|---|')
    for r in rows:
        A(f"| {r['jd']} | {r['kept']} | {r['excluded']} | {r['interview']} | {r['shortlist']} | "
          f"**{r['final']}** | {r['judgeable']}/{r['total_req']} | {r['tie_band']} |")
    A('')
    A(f'> 判定说明 **{s7["docs"]}** 份 · 判定格 **{s7["total_cells"]}** 个 · 引用 **{cites}** 条'
      f'（客户 {client} + 我方 HR 侧 {hr}）· 要求库 {lib} 条。')
    A('')
    A('---')
    A('')
    A('## 第 ① 步 · 出初始 JD')
    A('')
    A('### 业务视角')
    A('')
    A('- **谁**：业务（招聘需求方）。**什么时候**：岗位一开就做。')
    A('- **做什么**：把客户给的职务说明书**原样**交上来。不解释、不润色、不改错别字、不合并同类项。')
    A('- **判断标准**：客户到底写了什么。业务不做"意思大概是这样"的翻译 —— 那一步是第 ② 步、而且要签字。')
    A('- **交付**：一份原始文件 + 一句"这份是哪个岗位"。')
    A('')
    A('### 技术视角')
    A('')
    A('| 项 | 内容 |')
    A('|---|---|')
    A('| 落盘 | `work/talent/jd_links/_source/<JD>.txt`（.doc/.docx/.xlsx 抽平成文本，每行带行号） |')
    A('| 为什么保留原文 | 后面每一条要求都要能**逐字回查**到这里的某一行；原文动了，所有引用立刻作废 |')
    A('| 工具 | `extract_jd` / `llm_draft_jd` 起草引用；`jd_links/_source` 是只读锚点 |')
    A('| 门禁 | 逐字回查：`verbatim` 必须在原文里且 `txt_line` 真的指向那一行（改一个字就红） |')
    A('')
    A('## 第 ② 步 · 定稿（把原文变成闸门）')
    A('')
    A('### 业务视角')
    A('')
    A('- **谁**：HR + 业务一起。**什么时候**：初筛之前，必须定稿。')
    A('- **做什么**：逐条确认"这句是客户的意思吗"；把客户没写清的地方列成待确认；我方要补的要求（例如到岗周期）必须标明**我方提出**并写依据。')
    A('- **判断标准**：客户原文优先。客户说"优先"就是优先，不许写成"必须"；客户没说阈值，就记"没法判"，**不许替客户定一个数**。')
    A('- **交付**：一张要求清单（每条带客户原话和行号）+ 一份决策账本（谁定了什么、哪天、为什么还没签）。')
    A('')
    A('### 技术视角')
    A('')
    A('| 项 | 内容 |')
    A('|---|---|')
    A(f'| 引用文件 | `jd_links/<JD>.yaml`：{cites} 条引用（客户 {client} + 我方 HR 侧 {hr}），每条带 `verbatim` / `txt_line` / `origin` / `tier` / 阈值 `value` |')
    A(f'| 要求库 | `requirement_library.yaml`（{lib} 条）：阈值算子、数据项、可判性（`assessable`）、阈值口径 |')
    A('| 转正脚本 | `promote_jd`：草稿逐条复核 verbatim 与行号，**任一条对不上就整体拒绝、一个文件都不写** |')
    A('| 决策账本 | `jd_reviews/<JD>.yaml`：粒度/阈值/覆盖三类决定，一律 `signoff: pending` 等业务签字 |')
    A('| 回填参数 | `jd_inputs/<JD>.yaml`：面试人数、短名单区间、`final_max`、业务优先条件 |')
    A('| 门禁 | 引用逐字性、行号真实、HR 侧不许冒充客户原话、带拆分信号的引用必须有粒度决定且账本里有对应条目 |')
    A('')
    A('## 第 ③ 步 · 初筛（决定谁值得面，不是判合格）')
    A('')
    A('### 业务视角')
    A('')
    A('- **谁**：HR。**什么时候**：定稿之后、打电话之前。')
    A('- **做什么**：从简历池里**只**剔除"简历上明确写着不合格"的人（例如客户写 25~40 岁、简历写 45 岁）。')
    A('- **判断标准**：读不到 ≠ 不合格。凡是拿不准的，一律留在池子里，进**待核清单**，等电话里问。')
    A('- **交付**：一份面试名单（HR 真能打完电话的数量）+ 一份待核清单（按谁问、怎么问写清楚）。')
    A('')
    A('### 技术视角')
    A('')
    A('| 项 | 内容 |')
    A('|---|---|')
    A('| 初筛 | `screen_cv`：只对"简历直接写着"的属性阈值判；算子不是阈值的、推导出来的量、白名单带"等/类"的**都不拿来排除人** |')
    A('| 账要平 | `kept + excluded = pool`，门禁断言；差一个人就说明有人被静默丢掉 |')
    A('| 面试名单 | `pick_interview_list`：九层证据阶梯排序 + 切线 `tie_band`（并列几个人写进产物，名次可读不可读由它决定） |')
    A('| 待核清单 | `open_questions`：按人 × 按条款生成；每条写清谁问、给什么问法 |')
    A('| 门禁 | **排除必须有硬证据**；待核的人必须还在池里；每条排除都能追到值 |')
    A('')
    A('## 第 ④ 步 · 一面（把 JD 要的数据补齐）')
    A('')
    A('### 业务视角')
    A('')
    A('- **谁**：HR 打电话（采集），业务判能力。**什么时候**：面试名单出来之后。')
    A('- **做什么**：一次电话两份产物：① 按待核清单把 JD 要的数据问齐（到岗、薪资、通勤、在职时长…）② 对能力项要"能举出具体一段做法"。')
    A('- **判断标准**：**不问"你觉得他行不行"**，也不打分。只记录：问了什么、他怎么答、能不能举例。')
    A('- **交付**：每人一份问答记录；简历里读不到的字段，靠这场对话补齐。')
    A('')
    A('### 技术视角')
    A('')
    A('| 项 | 内容 |')
    A('|---|---|')
    A(f'| 记录 | `cv_interview/<候选人>.yaml`：`answers[]` 每条带 `basis`（`interview` 真访谈 / `simulated` 代拟）、`establishes`（坐实了哪条要求的能力项） |')
    A('| 采信规则 | 规则是**数据**：`interview_policy.yaml` 的 `mode`。默认 `real_only` —— 代拟答案不进判定 |')
    A('| 档案 | `render_cv_final` 产出 `cv_docs/<候选人>.定稿.md`：字段全集 + 每格标来源（`resume` / `代拟(模拟)` / `interview`），并写明填充度 |')
    A('| 演练模式 | `simulate_hr_round`：按待核清单 + JD 能力项生成答案，**坐实/否认跟着简历证据走**，不按哈希随机 |')
    A('| 门禁 | 每条答案 `basis` 必须诚实；`establishes` 必须落回某条要求；能力「满足」必须标证据强度 |')
    A('')
    A('## 第 ⑤a 步 · 短名单（谁排前面）')
    A('')
    A('### 业务视角')
    A('')
    A('- **谁**：HR。**什么时候**：一面做完。')
    A('- **做什么**：把面过的人排一个"够格进下一轮评估"的名单，人数按 HR 定的上限（当前 ≤10）。')
    A('- **判断标准**：**证据多的排前面**（有载体/能核实的证据优先于只有自述），然后才看业务偏好、客户写的"优先"条款、年限、稳定性。')
    A('- **交付**：一份有顺序的名单 + 切线说明（切在第几名、那里是否并列）。')
    A('')
    A('### 技术视角')
    A('')
    A('| 项 | 内容 |')
    A('|---|---|')
    A('| 脚本 | `shortlist_after_interview` → `shortlist/<JD>.目标名单.yaml` 的 `selected` |')
    A('| 证据 | 简历抽到的能力项 ∪ 一面坐实的；按 `component_catalog` 的 `evidence_role` 分硬/软 |')
    A('| 排序 | 九层阶梯：硬证据 → 软证据 → 业务优先条件 → 客户「优先」条款 → 年限 → 稳定性 → 待核项 → 品质岗经历 → 哈希兜底 |')
    A('| 门槛口径 | `REQ-B-MAJOR`（专业）**不进硬门槛**：客户写的是"…等"开区间，且口径未定（DEF-04） |')
    A('| 门禁 | 进名单的人必须面过且在本 JD 面试名单内；人数 ≤ 上限；切线 `tie_band` 必须交代 |')
    A('')
    A('## 第 ⑤b 步 · 最终名单（谁没有硬伤）')
    A('')
    A('### 业务视角')
    A('')
    A('- **谁**：HR + 业务。**什么时候**：短名单之后，送去用人部门面之前。')
    A('- **做什么**：从短名单里取出**送去面试的那 5 个人**。')
    A('- **判断标准**：三条硬条件 —— 客户硬门槛 **0 条不满足**、至少 **1 项硬证据**、未知 **≤3 条**；上限 5 人。**不够 5 个就如实说不够，不硬凑。**')
    A('- **交付**：5 人名单 + 每人一段"为什么是他"。')
    A('')
    A('### 技术视角')
    A('')
    A('| 项 | 内容 |')
    A('|---|---|')
    A('| 产物 | 同文件的 `final`（含 `unknown_max` / `min_hard` / `max`，门禁照产物复核，不写死数字） |')
    A('| 选人 | `pick_final`：**不重排**，直接按名单顺序取；只补逐人理由与判定说明 |')
    A('| 判定说明 | `explain_rejection` → `verdicts/<JD>/<人>.md|yaml`：每条判定带客户原文、行号、数据项、他的值、阈值、值来源、四态 |')
    A('| 门禁 | 最终名单 ⊂ 短名单、人数 ≤ 上限、**人数明显更少**、每人真的过三条硬条件（从 `rows` 复算，不信自报）、说明不得过期 |')
    A('')
    A('---')
    A('')
    A('## 四个设计决定（演示时最该讲的四句）')
    A('')
    A(f'**① 四种判定状态永不合并。** 满足 / 不满足 / **未知**（材料里读不到）/ **不可判**（这条要求没有数据项）。')
    A(f'当前 {s7["total_cells"]} 格：满足 {s7["counts"]["满足"]}、不满足 {s7["counts"]["不满足"]}、'
      f'**未知 {s7["counts"]["未知"]}**、不可判 {s7["counts"]["不可判"]}。把「未知」当「不满足」= 把"我们没读到"判成"他不行"。')
    A('')
    A(f'**② 能力「满足」要标证据档次。** 组件目录 {s8["components"]} 个，已标 {s8["roles"]["hard"]} 硬 / '
      f'{s8["roles"]["soft"]} 软；**还有 {s8["roles"]["未声明"]} 个没标**（待办，演示时如实说）。')
    A('')
    A('**③ 本体给事实、LLM 给判定，冲突分四类。** A 数据值 / B 阈值 / D 不可判 → 跟本体；**C 判定 → 不进结论、进复议**。')
    A('依据：只看本体 7/31，本体给料 + LLM 判 15/31（31 格人工核对过的基准）。')
    A('')
    A(f'**④ 「可复算」= 重放，不是重调。** {s13["run_pairs"]} 对存档里 {s13["same_verdicts"]} 对结论一致'
      f'（按格 {s13["cells_same"]}/{s13["cells_compared"]}）；再问一次模型会漂移，那不叫可复算。')
    A('')
    A('## 凭什么信它（机器检查）')
    A('')
    A('| 检查 | 挡什么 | 在哪 |')
    A('|---|---|---|')
    A('| 逐字回查 | 客户原文改一个字，引用立刻对不上行 | 门禁 / `verify_jd_report` |')
    A('| 排除必须有硬证据 | 不许拿"读不到"排除人 | 门禁 |')
    A('| 两道闸 | 最终名单必须是短名单真子集且明显更少 | 门禁 |')
    A('| 判定说明不过期 | 输入一变（JD/阈值/简历事实/一面记录），旧说明立刻红 | 门禁 |')
    A('| 教程数字不过期 | 教程里每个数字都由脚本现算，手改一个数就红 | `check_tutorial` |')
    A('')
    A(f'当前门禁：**{gate}**')
    A('')
    A('## 现在的状态（演示时必须同时说的部分）')
    A('')
    A(f'- **一面数据全是代拟**：{pt["interview_docs"]} 份记录里真访谈 **{pt["real_interview_docs"]}** 份 —— '
      '所以每份名单只能当演练看，不能当录用依据。')
    A(f'- **一个数两个来源还没定真源**：{s10["candidates"]} 人里 {s10["differ"]} 人技能集合两边不一致'
      f'（ABox 独有 {s10["only_abox"]}、LLM 独有 {s10["only_llm"]}）。')
    A(f'- **三种按名拒绝**：没 JD 的岗位 {s12["roles_without_jd_candidates"]} 人、没数据项的要求 '
      f'{len(s12["requirements_without_data_item"])} 条、全库无人命中的组件 {len(s12["components_zero_holder"])} 个。')
    A('- **还有 5 个 JD 停在客户原文**（业务助理 / 人资专员 / 工程文员 / 招聘专员 / 管理课长），有草稿未转正。')
    A(f'- **本体 ABox 是 {s2["candidates"]} 人的快照**，当前可用 OCR 文本 {facts["step1_records"]["source_files"]} 份，差的那几份是后来的清洗。')
    A('')
    A('## 在哪里看、怎么复算')
    A('')
    A('| 想看什么 | 打开哪里 |')
    A('|---|---|')
    A('| 一个 JD 的全部产物 | Talent 侧栏选 JD → 按层展开 1 → 5 |')
    A('| 名单 + 每人的证据 | `5 目标名单 · 人读` → 表格每行「看 CV」读完整档案 |')
    A('| 判定说明 | `5 判定总览` → 点人，每条带客户原文/行号/值来源 |')
    A('| 这套流程怎么来的 | `教程 v2 · 从记录到判定`（14 步，每步一个真数字 + 一个能变红的反证） |')
    A('| 跑第 5 步 | 文档页右上角「跑第 5 步」（白名单端点 + 跨进程锁，跑完自动重读） |')
    A('')
    A('```bash')
    A('cd backend && set -a && source ../.env; set +a')
    A('env -u PGPORT .venv/bin/python -m scripts.talent.build_overview          # 重新生成本页')
    A('env -u PGPORT .venv/bin/python -m scripts.talent.build_overview --check  # 是否过期')
    A('env -u PGPORT .venv/bin/python -m scripts.talent.check_component_catalog # 门禁')
    A('```')
    A('')
    return '\n'.join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--skip-gate', action='store_true')
    ap.add_argument('--check', action='store_true', help='只校验是否最新')
    args = ap.parse_args()

    facts = json.loads(json.dumps(TF.collect(), ensure_ascii=False))
    rows = funnel()
    gate = '（本次未跑；见 STATUS 最近一次记录）' if args.skip_gate else gate_line()
    md = render(facts, rows, gate)

    if args.check:
        old = DEST.read_text(encoding='utf-8') if DEST.is_file() else ''
        same = old.strip() == md.strip() or (args.skip_gate and old.strip().split('\n当前门禁：')[0]
                                            == md.strip().split('\n当前门禁：')[0])
        print('OVERVIEW.md 是最新的' if same else 'OVERVIEW.md 已过期 —— 重跑 build_overview')
        return 0 if same else 1
    DEST.write_text(md, encoding='utf-8')
    print(f'写出 {DEST.relative_to(ROOT)} · {len(md.splitlines())} 行 · 门禁 {gate}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
