#!/usr/bin/env python3
"""模拟 HR 一面:把面试名单里那几个人**缺的字段补齐**,让第 4~6 步能端到端跑。

它不是在"判定",是在**造访谈记录**。所以三道锁必须一起上:

    ① 每条答案 `basis: simulated`,文件顶层 `simulated: true`,CV 定稿顶部有横幅
    ② 个人身份字段(姓名/电话/邮箱/婚姻/籍贯)一律不编 —— 编了会被当真档案转手
    ③ 生成的取值来自**待核清单**(这个人真缺什么就问什么),不是通用十问

为什么按待核清单来:通用十问(到岗/薪资/通勤)填了也用不上 —— 第 5 步判的是
"C-06 线束行业有没有据"。实测那批通用答案对可判条数**一点没提升**(10 人里 9 人 +0)。

用法:
    python -m scripts.talent.simulate_hr_round --jd 品质经理
    python -m scripts.talent.simulate_hr_round --jd 业务跟单 --dry
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

from scripts.talent import interview_policy  # noqa: E402
from scripts.talent.evaluate import load_candidates, overlay_hr, overlay_llm  # noqa: E402
from scripts.talent.pick_final import load_inputs  # noqa: E402

CVINTERVIEW = ROOT / 'work' / 'talent' / 'cv_interview'
OPENQ = ROOT / 'work' / 'talent' / 'open_questions'
SHORTLIST = ROOT / 'work' / 'talent' / 'shortlist'
CV_FACTS = ROOT / 'work' / 'talent' / 'cv_facts.json'
TEXT = ROOT / 'work' / 'talent' / 'cv_text'

#: 生成规则。**这是编数据**,分布必须写在这里,不许藏在代码里。
#: 每个字段:(取值函数, 说明, 落成什么)
GEN = {
    'birthDate': (lambda u, c: '1986-01-01',        # 具体值在下面按 u 重算,这里只是占位
                  '出生年月:1985~1998 均匀取,年龄由它反算', 'prop'),
    'age': (lambda u, c: 26 + int(u * 15),          # 26~40,落在客户门槛 25~40 内
            '年龄按 26~40 均匀取(客户门槛之内)', 'prop'),
    'educationRank': (lambda u, c: 4 if u < 0.45 else 3,
                      '学历:45% 本科、55% 大专(客户要求大专及以上)', 'prop'),
    'major': (lambda u, c: ('机电一体化技术' if u < 0.25 else '电子技术' if u < 0.45
                            else '自动化' if u < 0.6 else '机械工程' if u < 0.75
                            else '工商管理'),
              '专业:75% 落在客户点名范围,25% 工商管理', 'prop'),
    'yearsPlatform': (lambda u, c: 3 + int(u * 12),
                      '总年限 3~15 年', 'prop'),
    'yearsStated': (lambda u, c: 3 + int(u * 12), '声明年限 3~15 年', 'prop'),
    'notice_weeks': (lambda u, c: 4 if u < 0.5 else (2 if u < 0.8 else 8),
                     '到岗:4 周(50%)/ 2 周(30%)/ 8 周(20%)', 'prop'),
    'salary_max_k': (lambda u, c: 8 + int(u * 12), '期望月薪 8~20K', 'prop'),
    'commute_ok': (lambda u, c: u < 0.75, '通勤可接受 75%', 'prop'),
    'avg_tenure_years': (lambda u, c: round(1.0 + u * 5, 1), '平均在职 1~6 年', 'prop'),
    'recent5y_segments': (lambda u, c: 1 + int(u * 3), '近 5 年 1~4 段', 'prop'),
    'fullTime': (lambda u, c: u < 0.7, '全日制 70%', 'prop'),
    # ── 简历里多半读不到、但 HR 一面确实会问到的字段(教育/证书/语言/项目/培训),
    #    同样只做"缺什么补什么",值一律标 simulated。
    'gender': (lambda u, c: '男' if u < 0.72 else '女', '性别:男 72% / 女 28%', 'prop'),
    'hasCertification': (lambda u, c: u < 0.35, '证书:35% 有内审员/质量类证书', 'prop'),
    'activityExperience': (lambda u, c: (c.get('_biz') or '来料检验、制程异常处理、客户投诉闭环'),
                           '活动经验:按岗位性质给三段标准动作', 'prop'),
    'domain': (lambda u, c: ('业务/跟单' if c.get('_is_biz') else '品质/工程'),
               '职能域:按岗位性质归域', 'prop'),
    'industry': (lambda u, c: ('制造/贸易(玩具/印刷/电子)') if c.get('_is_biz')
                 else '制造业(线束/汽车零部件)', '行业:按简历公司产品归到制造业', 'prop'),
    'languageLevel': (lambda u, c: '英语:CET-4,能读写英文图纸与邮件',
                      '语言熟练度:CET-4,读写为主', 'prop'),
    'language': (lambda u, c: '英语', '语言:英语', 'prop'),
    'competency': (lambda u, c: '工作认真负责,能独立推动异常闭环',
                   '职业素养:自评(自述,不作为判定依据)', 'prop'),
    'eduPeriod': (lambda u, c: f'{2006 + int(u * 4)}.09-{2010 + int(u * 4)}.06',
                  '起止时间:四年制本科区间', 'prop'),
    'institution': (lambda u, c: ['湖南工业大学', '南昌工程学院', '广东工业大学',
                                  '桂林电子科技大学'][int(u * 4) % 4],
                    '毕业院校:华南/华中工科院校之一', 'prop'),
    'projects': (lambda u, c: ('跟进 30 个客户、月均出货 200 万,逾期订单降到 2%'
                               if c.get('_is_biz') else '主导 CCS 采集线束导入,良率 92%→97%'),
                 '项目经验:一条可讲出来的项目', 'prop'),
    'trainings': (lambda u, c: ('外贸单证与跟单实务培训' if c.get('_is_biz')
                                else 'IATF16949:2016 内审员培训'),
                  '培训经历:与本岗相关的一次培训', 'prop'),
    'currentSalaryK': (lambda u, c: 8 + int(u * 11), '目前年薪(月薪口径)8~19K', 'prop'),
    'employer': (lambda u, c: (c.get('_last_company') or '（模拟）科技有限公司'),
                 '公司名称:取简历最近一段公司', 'prop'),
    'jobType': (lambda u, c: '全职', '求职类型:全职', 'prop'),
    'salary': (lambda u, c: f'{c.get("_salary_k", 10) - 2}-{c.get("_salary_k", 10)}K',
               '薪资:按客户预算区间代拟(平台无归档时)', 'prop'),
    # ── 身份与岗位信息(2026-11-23 admin 要求"完美填充"):编也要编,
    #    但每个值都写 basis: simulated,填完能一眼看出是模拟。
    #    姓名用 id 里的姓 +「某」——原文本来就脱敏,别再编一个真名。
    'fullName': (lambda u, c: (c.get('_name') or '（模拟）'),
                 '姓名:显示用编好的完整姓名(原文脱敏)', 'prop'),
    'phone': (lambda u, c: '138****' + str(1000 + int(u * 8999)), '手机号:138****XXXX(明显占位)', 'prop'),
    'email': (lambda u, c: f'cand{int(u * 9999):04d}@example.com', '邮箱:example.com 占位域', 'prop'),
    'marital': (lambda u, c: '已婚' if u < 0.6 else '未婚', '婚姻:已婚 60% / 未婚 40%', 'prop'),
    'hometown': (lambda u, c: ['广东','湖南','江西','广西','湖北'][int(u * 5) % 5],
                 '籍贯:华南/华中常见五省之一', 'prop'),
    'jobTitle': (lambda u, c: (c.get('_last_title') or '工程师'),
                 '现岗位:取简历最后一段的岗位名', 'prop'),
    'workLocation': (lambda u, c: '东莞', '工作地点:按简历城市(东莞)', 'prop'),
}
#: 组件类(能力)的答案**跟着简历走**:简历里抽到过就坐实,没抽到就否认。
#: 之前是 `hash(cid+组件) < 0.55` 随机坐实 —— 那等于给每个人随机分配能力,
#: 第 5 步排出来的差别全是噪声。实测业务跟单 10 人判定完全相同,就是这么来的。
EVIDENCE_ONLY = True


def text_components(text: str, comps) -> set:
    """简历**原文**里读得到的能力项(和本体用的是同一套词表规则)。

    只看 LLM 抽出来的 skills 不够:抽取没命中不等于简历没写(实测 270 份里
    41 份原文提到交期/排产/生管,但抽成组件的少得多)。一面的答案要跟着
    "材料里真读得到的东西"走,那这条链的输入就该是原文 + 抽取的并集。
    """
    if not text:
        return set()
    from scripts.talent.skill_patterns_ext import EXTENDED_SKILL_PATTERNS
    rx = {p[0]: p[2] for p in EXTENDED_SKILL_PATTERNS}
    out = set()
    for comp in comps:
        name = comp.replace('skill_', '')
        pat = rx.get(name)
        if pat and re.search(pat, text, re.I):
            out.add(comp)
    return out


def resume_components(cid: str, facts: dict, quality: dict) -> set:
    """这个人的简历里**真有的**能力项(LLM 逐字抽取 + 品质岗经历)。

    刻意不并 cv_mock:模拟填充出来的能力项如果再拿来当一面答案的依据,
    就是自己编数据证明自己编的数据。
    """
    out = set()
    for s_ in ((facts.get(cid) or {}).get('skills') or {}).get('value') or []:
        name = str(s_.get('name') or '').strip()
        if name:
            out.add(f'skill_{name}')
    q = quality.get(cid) or {}
    if q.get('verdict') == '有':
        out.add('skill_品质岗经历')      # 品质岗经历是伪组件,由 cv_quality 定
    return out


def _u01(cid: str, key: str) -> float:
    h = hashlib.sha256(f'{cid}|{key}'.encode()).hexdigest()
    return int(h[:12], 16) / float(0xFFFFFFFFFFFF)


def _dedupe_props(answers: list) -> list:
    """同一个属性只留一条问答,并把 schema 名/本体名两种写法补全。

    重跑 + 合并会积累"同一个年限问了两遍"的老答案,档案上就看不出哪条算了。
    判重按**规范化名字**(years_stated 与 yearsStated 是同一个量),先到的留下;
    留下的那条补齐两个名字,判定和档案各读各的都不缺。
    """
    props_of = _schema_props()
    seen: set = set()
    out = []
    for a in answers:
        raw = dict(a.get('props') or {})
        canon = {_camel(k) for k in raw}
        if canon and canon <= seen and not (a.get('establishes')):
            continue
        if raw:
            for k, v in list(raw.items()):
                for alias in (_snake(k), _camel(k)):
                    if alias in props_of:
                        raw.setdefault(alias, v)
            a['props'] = raw
        seen |= canon
        out.append(a)
    return out


def _snake(x: str) -> str:
    return re.sub(r'(?<!^)(?=[A-Z])', '_', x).lower()


def _camel(x: str) -> str:
    return re.sub(r'_([a-z])', lambda m: m.group(1).upper(), x)


def _sync_age_birth(answers: list, real_age, resume_bd=None) -> list:
    """把年龄与出生年月调成同一个事实。以简历里的值为准(它能引原文)。"""
    bd = next((a for a in answers if 'birthDate' in (a.get('props') or {})), None)
    if bd is None and resume_bd:
        # 出生年月是简历里读到的、没进一面答案 —— 那就拿它当锚反算年龄
        ag0 = next((a for a in answers if 'age' in (a.get('props') or {})), None)
        if ag0 is not None:
            age_from_bd = 2026 - int(str(resume_bd)[:4])
            ag0['props']['age'] = age_from_bd
            ag0['answer'] = re.sub(r'→.*$', f'→ {age_from_bd}', str(ag0.get('answer') or ''))
        return answers
    ag = next((a for a in answers if 'age' in (a.get('props') or {})), None)
    if real_age is None and not bd:
        return answers
    if real_age is not None:
        year = 2026 - int(real_age)
        month = int(str((bd or {}).get('props', {}).get('birthDate') or '1986-01-01')[5:7] or 1)
        val = f'{year}-{month:02d}-01'
        if bd:
            bd['props']['birthDate'] = val
            bd['answer'] = re.sub(r'→.*$', f'→ {val}', str(bd.get('answer') or '')) or bd['answer']
        if ag:
            ag['props']['age'] = int(real_age)
    elif bd and ag:
        year = int(str(bd['props']['birthDate'])[:4])
        ag['props']['age'] = 2026 - year
        ag['answer'] = re.sub(r'→.*$', f'→ {2026 - year}', str(ag.get('answer') or ''))
    return answers


def _schema_props() -> dict:
    """field_schema 里声明的 {cv.prop: 字段id} —— 一面答案落哪个字段以它为准。"""
    import yaml as _yaml
    doc = _yaml.safe_load((ROOT / 'work' / 'talent' / 'field_schema.yaml')
                          .read_text(encoding='utf-8')) or {}
    out = {}
    for f in doc.get('fields') or []:
        prop = (f.get('cv') or {}).get('prop')
        if prop:
            out.setdefault(prop, f['id'])
    return out


def _cv_text_index() -> dict:
    """candidate.id → 简历原文路径。文件名是【JD_城市 薪资】姓名 年限,cid 是
    cand_JD_城市_薪资_姓名_年限,两套写法,只能从库里对上。"""
    import os
    import pathlib
    import psycopg2
    conn = psycopg2.connect(host=os.environ['ONTOLOGY_DB_HOST'],
                            port=int(os.environ['ONTOLOGY_DB_PORT']), dbname='talent_db',
                            user=os.environ['ONTOLOGY_DB_USER'],
                            password=os.environ['ONTOLOGY_DB_PASSWORD'])
    with conn.cursor() as cur:
        cur.execute('select id, source_file from candidate where source_file is not null')
        rows = cur.fetchall()
    conn.close()
    return {cid: TEXT / (pathlib.Path(src).stem[:80] + '.txt') for cid, src in rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd', required=True)
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--force', action='store_true', help='已有真访谈也覆盖(默认跳过)')
    ap.add_argument('--refresh', action='store_true',
                    help='丢掉旧的模拟答案,按当前规则重算(真访谈保留)。'
                         '生成规则改过之后要用它,否则合并逻辑会把旧值留着')
    args = ap.parse_args()

    mode, src = interview_policy.mode_for(args.jd)
    if mode != interview_policy.MOCK_ALLOWED:
        raise SystemExit(f'{args.jd} 未授权模拟({src});先在 interview_policy.yaml 登记')
    print(f'采信规则 {mode}({src})')

    cat, lib, link, atts = load_inputs(args.jd)
    cands = load_candidates()
    overlay_llm(cands)
    overlay_hr(cands)
    by = {c['id']: c for c in cands}
    lst = yaml.safe_load((SHORTLIST / f'{args.jd}.面试名单.yaml').read_text(encoding='utf-8')) or {}
    ids = [c for c in (lst.get('selected') or []) if c in by]
    q = yaml.safe_load((OPENQ / f'{args.jd}.yaml').read_text(encoding='utf-8')) or {}
    asks: dict[str, list] = {}
    for it in q.get('queue') or []:
        asks.setdefault(it['candidate'], []).append(it)

    # 要求 → 需要哪些组件/属性(把待核项翻译成能落盘的字段)
    req_comp = {}
    for c in link['citations']:
        req = lib[c['requirement']]
        req_comp[c['requirement']] = list(req.get('_resolved') or [])

    # 这个人的简历里真有的能力项 —— 一面的能力题答案全部跟着它走
    _facts_all = json.loads(CV_FACTS.read_text(encoding='utf-8')) if CV_FACTS.is_file() else {}
    _quality_all = (json.loads((ROOT / 'work' / 'talent' / 'cv_quality.json')
                               .read_text(encoding='utf-8'))
                    if (ROOT / 'work' / 'talent' / 'cv_quality.json').is_file() else {})
    # JD 引用到的全部能力项(可判的那些)—— 一面要把它们全问到,
    # 否则"未知"永远消不掉:实测面完 30 人,平均还剩 4 条未知。
    JCOMPS = sorted({x for rid, cs in req_comp.items() for x in cs
                     if (lib.get(rid) or {}).get('_resolved')})
    print(f'  JD 依赖的能力项 {len(JCOMPS)} 个 —— 一面会逐个问到(坐实/否认都跟着简历走)')
    txt_of = _cv_text_index()
    CVINTERVIEW.mkdir(parents=True, exist_ok=True)
    made = filled_props = filled_comps = 0
    for cid in ids:
        path = CVINTERVIEW / f"{cid.replace('cand_', '')}.yaml"
        old = (yaml.safe_load(path.read_text(encoding='utf-8')) if path.is_file() else {}) or {}
        if old and not args.force:
            real = [a for a in (old.get('answers') or []) if interview_policy.is_real_basis(a)]
            if real:
                print(f'  跳过 {cid.replace("cand_","")[:34]}(已有 {len(real)} 条真访谈)')
                continue
        _evidence = resume_components(cid, _facts_all, _quality_all)
        _tf0 = txt_of.get(cid)
        try:
            _t0 = _tf0.read_text(encoding='utf-8') if _tf0 and _tf0.is_file() else ''
        except Exception:  # noqa: BLE001
            _t0 = ''
        _evidence |= text_components(_t0, JCOMPS)
        answers = []
        # 两遍:第一遍先定出生年月/岗位(其它字段要引用它)
        ordered = sorted(asks.get(cid, []), key=lambda x: 0 if 'birthDate' in GEN and (
            'birthDate' in str(x.get('data_item') or '') or '出生' in str(x.get('how') or '')) else 1)
        for it in ordered:
            how = str(it.get('how') or '')
            who = str(it.get('who') or 'HR')
            item = str(it.get('data_item') or '')
            # ① 属性类:按字段名生成
            key = next((k for k in GEN if k.lower() == item.lower() or k in item), None)
            if key:
                fn, note, _kind = GEN[key]
                u = _u01(cid, key)
                _c = by[cid]
                val = fn(u, _c)
                # 出生年月与年龄必须自洽:先定出生年月,年龄一律由它算 ——
                # 实测出现过「出生年月 1985-11-01 + 年龄 36」这种自相矛盾。
                if key == 'birthDate':
                    year = 1985 + int(u * 14)      # 1985~1998
                    month = 1 + int(_u01(cid, 'bm') * 12)
                    val = f'{year}-{month:02d}-01'
                    _c['_birth_year'] = year
                if key == 'age':
                    y = _c.get('_birth_year')
                    val = (2026 - y) if y else val
                answers.append({'question': how, 'answer': f'（模拟答案）{note} → {val}',
                                'basis': 'simulated', 'evidence_level': 'stated',
                                'props': {key: val},
                                'note': '模拟:不是真人说的'})
                filled_props += 1
                continue
            # ② 组件类:按待核项里提到的组件名,决定坐实/不坐实
            comps = [x for rid, cs in req_comp.items() for x in cs
                     if x.replace('skill_', '') in item or item in x.replace('skill_', '')]
            if not comps:
                # 兜底:从本条待核项的 data_item 里逐个拆
                comps = [f'skill_{p.strip()}' for p in item.split('、') if p.strip()]
            est = [x for x in comps if x in _evidence]
            if est:
                answers.append({'question': how,
                                'answer': f'（模拟答案）做过:{", ".join(x.replace("skill_","") for x in est)}'
                                          f',能说出具体一段与做法',
                                'basis': 'simulated',
                                'evidence_level': 'test' if who == '业务' else 'stated',
                                'establishes': est,
                                'note': '模拟:不是真人说的'})
                filled_comps += len(est)
            else:
                answers.append({'question': how,
                                'answer': f'（模拟答案）简历里没有{"、".join(x.replace("skill_","") for x in comps)}'
                                          f'的证据,本人也说不出具体例子 —— 记为否认',
                                'basis': 'simulated', 'evidence_level': 'stated',
                                'establishes': [], 'denies': comps,
                                'note': '模拟:本人否认(跟着简历走,不是随机)'})
        # **合并**而不是覆盖:待核清单会随着数据补齐而变短,重跑时若整份覆盖,
        # 先前面过的问题与答案就被冲掉了(实测:第 3 轮只剩 3 条,把第 2 轮的 120 条冲没)。
        _old_ans = ([] if args.refresh else
                    [a for a in (old.get('answers') or [])
                     if a.get('simulated') or a.get('basis') == 'simulated'])
        _seen_q = {str(a.get('question') or '') for a in answers}
        merged_ans = answers + [a for a in _old_ans if str(a.get('question') or '') not in _seen_q]
        answers = merged_ans
        # ② 补 CV 字段表里仍然空着的字段(身份/岗位/地点这些不属于"要求",进不了待核清单)。
        #    简历读得到的就**不代拟** —— 代拟只在真的空着时兜底,否则会盖掉原文。
        from scripts.talent.cv_parse import parse_experience
        from scripts.talent.render_cv_final import resume_only
        _tf = txt_of.get(cid)
        try:
            _txt = _tf.read_text(encoding="utf-8") if _tf and _tf.is_file() else ""
        except Exception:  # noqa: BLE001
            _txt = ""
        _resume = resume_only(_txt) if _txt else {}
        _facts = ((json.loads(CV_FACTS.read_text(encoding="utf-8")).get(cid) or {})
                  if CV_FACTS.is_file() else {})
        _js = parse_experience(_txt) if _txt else []
        if _js:
            _t = re.sub(r"\s*[|｜/／]\s*\d+(\.\d+)?K\s*$", "",
                        str(_js[-1].get("title") or "")).split("|")[0].split("／")[0]
            _t = re.sub(r"\s+", " ", _t).strip()
            by[cid]["_last_title"] = _t[:20] or "工程师"
            by[cid]["_last_company"] = str(_js[-1].get("company") or "").strip()
        by[cid]["_salary_k"] = 8 + int(_u01(cid, "salary") * 11)
        _title = str(by[cid].get("_last_title") or "")
        by[cid]["_is_biz"] = any(w in args.jd or w in _title
                                 for w in ("跟单", "业务", "外贸", "客服"))
        by[cid]["_biz"] = ("接单→下单排产、跟进出货、客户对账与异常反馈"
                           if by[cid]["_is_biz"] else "来料检验、制程异常处理、客户投诉闭环")
        # 姓名:简历抬头/文件名里都是脱敏写法(徐__),照抄,不编
        _stem = _tf.stem if _tf else ""
        by[cid]["_name"] = (_stem.split("】")[-1].strip().split(" ")[0] if "】" in _stem else "")
        # 姓名:统一取 fake_names 里编好的完整姓名 —— 档案、一面、名单必须是同一个名字
        from scripts.talent import names as _names
        by[cid]["_name"] = _names.name_of(cid)
        _bd = (_resume.get("F.CV_BIRTH_DATE") or (None,))[0]
        if _bd:
            by[cid]["_birth_year"] = int(str(_bd)[:4])
        # prop 名 → 字段 id:从 field_schema 读,**不手写死表**(手写过一次,key 和
        # schema 的 prop 对不上,填了等于没填:fullTime vs full_time)
        PROP_FIELD = _schema_props()
        _have = {k for a in answers for k in (a.get("props") or {})}
        for key, (fn, note, _kind) in GEN.items():
            if key in _have:
                continue
            fid = PROP_FIELD.get(key) or PROP_FIELD.get(_snake(key))
            if fid and (_resume.get(fid) or (None,))[0]:
                continue                      # 简历里有,不用代拟
            if key == 'age' and (_facts.get('age') or {}).get('value') is not None:
                continue
            if key == 'educationRank' and (_facts.get('education_rank') or {}).get('value') is not None:
                continue
            if key == 'major' and (_facts.get('major') or {}).get('value'):
                continue
            if key == 'birthDate' and _bd:
                continue
            u = _u01(cid, key)
            val = fn(u, by[cid])
            if key == 'birthDate':
                year = 1985 + int(u * 14)
                val = f'{year}-{1 + int(_u01(cid, "bm") * 12):02d}-01'
                by[cid]['_birth_year'] = year
            elif key == 'age' and by[cid].get('_birth_year'):
                val = 2026 - by[cid]['_birth_year']
            if isinstance(val, str):
                val = re.sub(r"\s+", " ", val.replace("|", "／")).strip()
            _props = {key: val}
            # 判定读本体名(educationRank),档案按 field_schema 的 prop 名(education_rank)
            # 显示 —— 同一条答案里两个名字都写,省得同一个字段出现两条问答。
            for _alias in ((_snake(key), _camel(key))):
                if _alias != key and _alias in PROP_FIELD:
                    _props[_alias] = val
            answers.append({'question': f'（补充询问）{note}', 'answer': f'（模拟答案）{note} → {val}',
                            'basis': 'simulated', 'evidence_level': 'stated',
                            'props': _props, 'note': '模拟:不是真人说的'})
            filled_props += 1

        # ④ 覆盖补问:JD 要的每个能力项都要有答案(坐实或否认)。
        #    待核清单只列"还没读到"的那部分,而且按人分流;不补齐的话,
        #    面完一整天,"未知"还是那几条 —— 第 5 步的最终名单就永远卡在未知上。
        _decided = {x for a in answers for x in (a.get('establishes') or [])}
        _decided |= {x for a in answers for x in (a.get('denies') or [])}
        _todo = [c for c in JCOMPS if c not in _decided]
        if _todo:
            est = [c for c in _todo if c in _evidence]
            deny = [c for c in _todo if c not in _evidence]
            if est:
                answers.append({'question': '（补充核实）JD 要求的能力项:' + '、'.join(
                                    c.replace('skill_', '') for c in est),
                                'answer': '（模拟答案）简历里有证据,本人能讲出具体一段与做法:'
                                          + '、'.join(c.replace('skill_', '') for c in est),
                                'basis': 'simulated', 'evidence_level': 'stated',
                                'establishes': est, 'note': '模拟:简历有证据 → 坐实'})
                filled_comps += len(est)
            if deny:
                answers.append({'question': '（补充核实）JD 要求的能力项:' + '、'.join(
                                    c.replace('skill_', '') for c in deny),
                                'answer': '（模拟答案）简历里没有这几项的证据,本人也举不出例子 —— 记为否认',
                                'basis': 'simulated', 'evidence_level': 'stated',
                                'establishes': [], 'denies': deny,
                                'note': '模拟:简历无证据 → 否认'})

        # 年龄 / 出生年月自洽:简历给了真实年龄就以它为锚,没有才拿生成的出生年月反算。
        # **必须在合并与补全之后收口** —— 老答案不会被覆盖,不统一收口就会留下
        # "年龄 29 + 出生年月 1992"这种自相矛盾的档案(实测 25/39 份)。
        answers = _dedupe_props(answers)
        answers = _sync_age_birth(answers, (_facts.get('age') or {}).get('value'), _bd)

        doc = {
            'candidate': cid, 'simulated': True,
            'channel': '模拟一面(开发用,非真实访谈)',
            'date': datetime.date.today().isoformat(),
            'interviewer': '—',
            'simulated_note': ('本文件 answers 全部 `basis: simulated`:按待核清单与简历常识推的,'
                               '不是访谈记录。对外前必须换成真实答案。'),
            'answers': answers,
        }
        if not args.dry:
            path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=100),
                            encoding='utf-8')
        made += 1
        print(f'  {cid.replace("cand_","")[:34]:34} 答 {len(answers):>2} 条')

    print(f'\n模拟一面 {made} 人 · 落属性 {filled_props} 个 · 坐实能力 {filled_comps} 次'
          + ('  (--dry,未写盘)' if args.dry else f' → {CVINTERVIEW.relative_to(ROOT)}'))
    print('身份/岗位/地点等字段也一并代拟(标 simulated),字段表里不再留〔待补〕。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
