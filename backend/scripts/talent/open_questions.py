#!/usr/bin/env python3
"""待核清单:把「我们不知道」变成「谁去问、问什么、答完解锁哪一条」。

为什么必须有这一步(2026-11-21 修正):

原来这套系统把**读不到**当成**不满足**。实测两处:

    ① judge_component  没抽到组件 → 判「不满足」。全库 1207 格组件类不满足里,
                        **1192 格(99%)是"一项都没抽到"** —— 这是"简历没写/词表没覆盖",
                        不是"他不会"。
    ② cv_quality       读不到品质动作 → 判「无」→ 第 3 步直接排除。270 人里 235 人
                        是这个判决,其中很多人的 `months_known=False`(连时长都没读出来)。

后果:第 3 步用一道**读不出来的信号**挡掉了 165 个人。短名单只有 4 人,
不是因为只有 4 个人合格,而是因为我们把 160 个人的"不知道"当成了"不行"。

改法不是让脚本猜,而是**把它变成工作项**:每条"不知道"都要标明
  谁去问(HR / 业务 / 客户)、问什么(可以照着念的话)、答完能解锁哪一条要求。

产出:
    work/talent/open_questions/<JD>.yaml   给流程用(4a 采集清单从这里取)
    work/talent/open_questions/<JD>.md     给人看(按"谁答"分组)

用法:
    python -m scripts.talent.open_questions --jd 品质经理
    python -m scripts.talent.open_questions --jd 品质经理 --limit 20
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

from scripts.talent import interview_policy  # noqa: E402
from scripts.talent.evaluate import (  # noqa: E402
    PROP_FIELD, load_candidates, overlay_hr, overlay_interview, overlay_llm)
from scripts.talent.pick_final import load_inputs  # noqa: E402

OUT = ROOT / 'work' / 'talent' / 'open_questions'
SHORTLIST = ROOT / 'work' / 'talent' / 'shortlist'
QUALITY = ROOT / 'work' / 'talent' / 'cv_quality.json'

#: 每个数据项缺了之后该问什么。**话要能直接照读** —— HR 不该被要求理解数据模型。
ASK = {
    'age': ('HR', '请候选人提供身份证出生日期(或出生年月),并说明是身份证还是自述',
            '解锁 C-01 年龄区间'),
    'educationRank': ('HR', '请候选人提供最高学历证书照片(毕业证/学位证),注明全日制还是在职',
                      '解锁 C-02 学历不低于'),
    'major': ('HR', '请候选人说明证书上的**专业全称**与院校(例:机电一体化技术)',
              '解锁 C-03 专业限定'),
    'yearsPlatform': ('HR', '请候选人按"起止年月"口述主要工作段,用来核对总年限',
                      '解锁 C-05 某领域年限'),
    'skill_英语': ('HR', '近 12 个月有没有一次不靠翻译、独立用英语主答客户审核会议?(是/否)',
                   '解锁 C-04 英语(口语部分;书面按能否独立写 8D 判断)'),
    'skill_8D报告': ('HR', '最近一份你独立写的英文 8D 报告是什么问题?能否发一份脱敏版?',
                     '解锁 C-04 英语(书面部分)'),
    'skill_线束行业知识': ('业务', '他做过线束/连接器产品吗?哪一段、什么产品、做了什么工序?',
                           '解锁 C-06 线束/连接器行业认知'),
    'skill_品质问题分析': ('业务', '举一个他主导的品质异常分析:什么不良、用什么方法、结果如何?',
                           '解锁 C-07 品质问题分析改善能力'),
    'skill_QC七大手法': ('业务', '现场随机问一项 QC 手法(如鱼骨图/柏拉图)让他说怎么用',
                         '解锁 C-08 品质工具(5 项之一)'),
    'skill_SPC': ('业务', '他们的 SPC 用什么控制图?CPK 多少算合格?', '解锁 C-08 品质工具(5 项之一)'),
    'skill_CPK': ('业务', '让他说清 CPK 与 PPK 的区别,以及他们厂的验收值', '解锁 C-08 品质工具(5 项之一)'),
    'skill_6S': ('业务', '他们厂 6S 由谁推、多久审一次、不合格怎么处理?', '解锁 C-08 品质工具(5 项之一)'),
    'skill_5WHY': ('业务', '给一个具体不良,让他现场连问 5 个为什么', '解锁 C-08 品质工具(5 项之一)'),
    'notice_weeks': ('HR', '如果录用,多久能到岗?是否需要办离职交接?有无竞业限制?',
                     '解锁 HR 侧「到岗时间」'),
    'salary_max_k': ('HR', '目前月薪多少?期望多少?最低可接受多少?(要具体数字)',
                     '解锁 HR 侧「薪资上限」'),
    'commute_ok': ('HR', '住哪里?到厂单程多久?能接受本岗的班制/加班/调岗吗?',
                   '解锁 HR 侧「上班地点与班制」'),
    'fullTime': ('HR', '这份学历是全日制还是在职/自考?', '解锁「是否全日制」'),
    'avg_tenure_years': ('HR', '近 5 年换过几家?每段做多久?离职原因是什么?',
                         '解锁 HR 侧「平均在职年限(稳定性)」'),
    'recent5y_segments': ('HR', '近 5 年有哪几段工作?每段起止年月与岗位?',
                          '解锁 HR 侧「近 5 年工作段数」'),
    'skill_客户验厂': ('业务', '哪家客户来验过厂?验的什么体系(ISO/客户自有标准)?他负责哪部分?',
                       '解锁 C-09 客户验厂经验'),
}


#: 采集方式。这是比"谁去问"更重要的一层:
#:   证件  = 拿材料核(身份证/毕业证/学信网),HR 在邀约阶段就该收齐,不占面试时间
#:   面谈  = 问经历(做过什么、哪一段),HR 一面能采,业务复核更准
#:   实测  = 现场做。**问不出能力**:问"你懂不懂 SPC",回答一定是"懂"。
METHOD = {
    'age': ('证件', '身份证', 'HR'),
    'educationRank': ('证件', '毕业证/学位证 + 学信网', 'HR'),
    'major': ('证件', '毕业证上的专业全称', 'HR'),
    'yearsPlatform': ('面谈', '按起止年月核对,补空档', 'HR'),
    'skill_英语': ('实测', '英文 8D 作业 + 英文面试 10 分钟', '业务'),
    'skill_8D报告': ('实测', '带一份脱敏英文 8D 让他讲', '业务'),
    'skill_线束行业知识': ('面谈', '产品/工序/客户指名道姓地问', '业务'),
    'skill_品质问题分析': ('实测', '给一个真实不良,现场让他分析并给对策', '业务'),
    'skill_QC七大手法': ('实测', '现场出题:鱼骨图/柏拉图各画一次', '业务'),
    'skill_SPC': ('实测', '拿他的控制图数据问异常判读', '业务'),
    'skill_CPK': ('实测', '给一组数据让他算 CPK 并解释', '业务'),
    'skill_6S': ('实测', '让他说上一家公司 6S 的审核与整改流程', '业务'),
    'skill_5WHY': ('实测', '给一个不良,现场连问 5 个为什么', '业务'),
    'skill_客户验厂': ('面谈', '哪家客户、什么体系、他负责哪部分', '业务'),
    'notice_weeks': ('面谈', '问清到岗时间与离职周期', 'HR'),
    'salary_max_k': ('面谈', '问清现薪、期望与底线', 'HR'),
    'commute_ok': ('面谈', '问清住址、通勤时长、能否接受班制', 'HR'),
    'fullTime': ('证件', '看毕业证上的学习形式', 'HR'),
    'avg_tenure_years': ('面谈', '问清每段时长与离职原因', 'HR'),
    'recent5y_segments': ('面谈', '按起止年月核对近 5 年工作段', 'HR'),
}


def method_of(prop: str) -> tuple[str, str, str]:
    return METHOD.get(prop, ('面谈', '确认这项信息', 'HR'))


def _ask_for(prop: str, cand_name: str) -> dict:
    who, how, unlock = ASK.get(prop, ('HR', f'确认「{prop}」这项信息', '解锁对应要求'))
    kind, material, judge = method_of(prop)
    if kind == '实测':
        # 实测类 HR 一个人做不了:要么业务在场出题,要么 HR 发作业、业务批改。
        # 把 who 改成业务,是因为**必须有人能判**,不然问出来的"会"会直接变成"满足"。
        who = '业务'
    return {'who': who, 'how': how.replace('{}', cand_name), 'unlock': unlock,
            'method': kind, 'material': material, 'judge_by': judge}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd', required=True)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--only-pending', action='store_true',
                    help='只取品质门槛待核/需复议的人(旧行为);默认按"要求级未知"取全部 kept')
    args = ap.parse_args()

    mode, _src = interview_policy.mode_for(args.jd)
    cat, lib, link, atts = load_inputs(args.jd)
    cands = load_candidates()
    overlay_llm(cands)
    overlay_hr(cands)
    overlay_interview(cands, allow_simulated=mode == interview_policy.MOCK_ALLOWED)
    by_id = {c['id']: c for c in cands}
    quality = json.loads(QUALITY.read_text(encoding='utf-8')) if QUALITY.is_file() else {}

    sl = yaml.safe_load((SHORTLIST / f'{args.jd}.yaml').read_text(encoding='utf-8')) or {}
    qg = sl.get('quality_gate') or {}
    pending = [p['candidate'] for p in (qg.get('needs_verification') or [])]
    review = [b['candidate'] for b in (qg.get('blocked_by_other_requirements') or [])]
    # 范围必须是**要求级的未知**,不是"品质门槛待核"。
    # 之前只取 pending+review:某份 JD 不套品质门槛时(如业务跟单),这个队列直接是空的,
    # 于是 34 人的学历未知、6 条能力要求全无数据,却一个待核项都没有 ——
    # 排序第④层"待核项数"对所有人都是 0,那一层等于失效。
    scope = (pending + review) if args.only_pending else list(sl.get('kept') or [])
    scope = [c for c in dict.fromkeys(scope) if c in by_id]
    if args.limit:
        scope = scope[:args.limit]

    items = []
    for cid in scope:
        cand = by_id[cid]
        q = quality.get(cid) or {}
        # ① 品质岗经历待核(第 3 步的信号)
        if q.get('verdict') in ('待核', '读不出'):
            items.append({
                'candidate': cid, 'data_item': '品质岗经历',
                'current': q.get('verdict'), 'why': q.get('why_short'),
                'who': 'HR',
                'how': ('近三年有没有做过品质相关工作(检验判定/异常处理/体系或客户审核)?'
                        '是哪一段、起止年月、具体做什么?'),
                'unlock': '第 3 步的品质岗门槛(现在卡着的人全部因此待核)',
                'method': '面谈', 'material': '按起止年月问清责任范围',
                'judge_by': '业务',
                'evidence': (q.get('quote') or '')[:120],
            })
        # ② 属性类缺值 → HR 要数据
        for c in link['citations']:
            req = lib[c['requirement']]
            attr = req.get('attribute')
            if not attr or req.get('_resolved'):
                continue
            prop = PROP_FIELD.get(attr)
            if attr in ('C.1', 'C.6'):
                prop = 'yearsPlatform'
            if not prop:
                continue
            if cand.get(prop) is None:
                a = _ask_for(prop, cid.replace('cand_', ''))
                items.append({'candidate': cid, 'data_item': f'{attr} {prop}',
                              'current': '未知', 'why': '库里没有这个值',
                              'who': a['who'], 'how': a['how'], 'unlock': a['unlock'],
                              'method': a['method'], 'material': a['material'],
                              'judge_by': a['judge_by'], 'evidence': ''})
            elif req.get('op') in ('between', '>=', 'in') and not (c.get('value') or {}):
                # JD 侧没给阈值 —— 这是业务/客户的活,不是候选人的
                items.append({'candidate': cid, 'data_item': f'{attr} 阈值',
                              'current': 'JD 侧缺阈值', 'why': '这条要求 JD 没写取值,对所有人不可判',
                              'who': '客户',
                              'how': f"请客户确认「{c.get('verbatim') or req.get('name')}」的具体标准",
                              'unlock': f"解锁 {c['id']}", 'evidence': ''})
        # ③ 组件类一条都没抽到 → 面谈确认(业务更懂技术面)
        for c in link['citations']:
            req = lib[c['requirement']]
            needed = req.get('_resolved') or []
            if not needed:
                continue
            hit = [x for x in needed if x in cand['components']]
            if hit:
                continue
            first = _ask_for(needed[0], cid.replace('cand_', ''))
            names = [x.replace('skill_', '') for x in needed]
            how = first['how']
            if len(names) > 1:
                # 同一条要求下的多项合成一次提问:电话里问"你懂哪些品质工具"比逐项点名现实
                how = (f"一次问完 {'、'.join(names)}:{first['how']}"
                       if first['who'] == '业务' else
                       f"逐个确认 {'、'.join(names)}:{first['how']}")
            kinds = {method_of(x)[0] for x in needed}
            items.append({'candidate': cid,
                          'data_item': '、'.join(names),
                          'current': '没抽到',
                          'why': f"{len(needed)} 项一项都没抽到(可能没写,也可能没做过)",
                          'who': first['who'], 'how': how,
                          'unlock': f"解锁 {c['id']} {req.get('name') or ''}".strip(),
                          'method': '实测' if '实测' in kinds else first['method'],
                          'material': first['material'], 'judge_by': first['judge_by'],
                          'evidence': ''})

    # 排序:按"答完解锁的要求数"再看影响人数 —— 这是工作队列的优先级
    per_item = collections.Counter(i2['data_item'] for i2 in items)
    per_cand = collections.Counter(i2['candidate'] for i2 in items)

    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f'{args.jd}.yaml'
    dest.write_text(yaml.safe_dump({
        'jd': args.jd, 'scope_size': len(scope), 'items': len(items),
        'by_who': dict(collections.Counter(i2['who'] for i2 in items)),
        'rule': ('待核 ≠ 不合格。未核期间这些要求一律按「未知」处理,不得用于排除;'
                 '问完把答案写回 cv_facts/cv_interview,再重跑第 3 步。'),
        'queue': items,
    }, allow_unicode=True, sort_keys=False), encoding='utf-8')

    groups = collections.defaultdict(list)
    for i2 in items:
        groups[i2['who']].append(i2)
    by_method = collections.Counter(i2.get('method') or '面谈' for i2 in items)
    md = [f'# 待核清单 · {args.jd}', '',
          f'范围 **{len(scope)}** 人 · 待核项 **{len(items)}** 条。', '',
          '> **待核 ≠ 不合格。** 未核期间这些要求一律按「未知」处理,不得用于排除。',
          '> 问完把答案写回 `cv_facts.json` / `cv_interview/`,再重跑第 3 步 —— '
          '不要在这里手改判定。', '',
          '| 谁答 | 待核项 | 说明 |', '|---|---|---|',
          f"| **HR** | {len(groups.get('HR', []))} | 打电话/要证件 —— 这些只有候选人本人能答 |",
          f"| **业务** | {len(groups.get('业务', []))} | 技术面确认 —— 这些要懂行的人判断 |",
          f"| **客户** | {len(groups.get('客户', []))} | 阈值/口径 —— 这些只有客户能定 |", '',
          '## 按采集方式分(这一层比"谁去问"更要紧)', '',
          '| 方式 | 条数 | 是什么 | 谁判 |', '|---|---|---|---|',
          f"| **证件** | {by_method.get('证件', 0)} | 拿材料核(身份证/毕业证/学信网) —— "
          f"邀约阶段就该收齐,不占面试时间 | 机器比阈值 |",
          f"| **面谈** | {by_method.get('面谈', 0)} | 问经历(做过什么、哪一段) —— HR 一面可采 | HR 采、业务复核 |",
          f"| **实测** | {by_method.get('实测', 0)} | 现场做 —— **问不出能力**:"
          f"问\"你懂不懂 SPC\",回答一定是\"懂\" | 业务 |", '',
          '> **能力类(实测)不能只靠问。** 问出来的\"会\"记进系统就是\"满足\",'
          '那比\"未知\"更糟 —— 未知至少诚实。这类要么现场做、要么给作业,并且由业务判。', '']
    for who in ('HR', '业务', '客户'):
        g = groups.get(who) or []
        if not g:
            continue
        md += [f'## {who}({len(g)} 项)', '',
               '| 候选人 | 缺什么 | 方式 | 怎么问/怎么验(可照读) | 答完解锁 |',
               '|---|---|---|---|---|']
        seen = set()
        for i2 in g:
            key = (i2['candidate'], i2['data_item'])
            if key in seen:
                continue
            seen.add(key)
            md.append(f"| {i2['candidate'].replace('cand_', '')[:26]} | {i2['data_item']} | "
                      f"{i2.get('method') or '面谈'} | {i2['how']} | {i2['unlock']} |")
        md.append('')
    md += ['## 优先做哪些', '',
           '| 缺的数据项 | 待核人次 |', '|---|---|']
    for k, v in per_item.most_common(12):
        md.append(f'| {k} | **{v}** |')
    md += ['', f'共 {len(scope)} 人,人均 {len(items)/max(1,len(scope)):.1f} 项待核。'
           '先做「待核人次」最高的那几项 —— 一次问法能解开一批人。', '',
           '> 这些不是"必须全问完"。**先问那些会改变结论的**:同一个人,问完之后'
           '从「待核」变成明确结论的那几项,优先做。', '']
    (OUT / f'{args.jd}.md').write_text('\n'.join(md), encoding='utf-8')

    print(f"范围 {len(scope)} 人 · 待核 {len(items)} 项 "
          f"({', '.join(f'{k} {v}' for k, v in collections.Counter(i['who'] for i in items).items())})")
    print(f"人均 {len(items)/max(1,len(scope)):.1f} 项 · 写出 {(OUT / (args.jd + '.md')).relative_to(ROOT)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
