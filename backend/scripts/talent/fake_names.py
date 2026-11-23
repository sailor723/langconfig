#!/usr/bin/env python3
"""给每个候选人编一个**完整的中文姓名**（演示用），写进 `work/talent/fake_names.yaml`。

## 为什么要这个

简历原文是脱敏的：`廖____`、`徐*`、`lizw`。做演练时满屏都是这种名字，
看名单、看档案都要不停"这是谁"——**看起来像数据坏了**。
所以给每个人编一个完整姓名，一处在 `fake_names.yaml` 生成，所有产物都读它。

## 三条规矩

1. **确定性**:同一个 candidate id 永远得到同一个名字(按 sha256 播种),
   重跑不会换人。已存在的映射**只增不改**。
2. **不重名**:270 个人必须 270 个不同姓名 —— 重名会让"这是谁"重新变成问题。
3. **每个名字都标来源**:文书里写的是 `编造(演示)`,不是 `resume`。
   **这些名字与真实简历无关**,任何对外场合都要换回真实的脱敏写法或真名。

## 名字怎么编

姓:沿用 id 里那个汉字(脱敏后留下的姓,`胡___` → 胡),没有就按哈希取常见姓。
名:两字,从常见字池按哈希挑;撞名就换一个字,直到不重复。

用法:
    python -m scripts.talent.fake_names            # 补齐缺失的,不改已有的
    python -m scripts.talent.fake_names --rebuild  # 全部重编(会换名,慎用)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

OUT = ROOT / 'work' / 'talent' / 'fake_names.yaml'
CV_FACTS = ROOT / 'work' / 'talent' / 'cv_facts.json'
INTERVIEW = ROOT / 'work' / 'talent' / 'cv_interview'
SHORTLIST = ROOT / 'work' / 'talent' / 'shortlist'

#: 常见姓。id 里带汉字姓时优先沿用,保证"还是那个人"的感觉。
SURNAMES = list(
    "王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤")

#: 名用字(避开生僻字,读起来像个真人)。男女通用为主,单字组合足够 270 人不撞。
GIVEN = list(
    "伟芳娜敏静秀丽强磊洋勇艳杰娟涛明超秀霞平刚桂英华建国志强晓东海燕文轩子墨思远雨晨佳怡嘉诚宇轩浩宁若曦子涵天佑振华国强立新永强春梅冬梅雪梅志明家豪家乐俊杰秀兰玉兰素芬桂芳")

#: 用于保证唯一性的备用字(撞名时换)
EXTRA = list("安宁博超晨成诚川春秋丹道德登东帆飞峰刚歌根光广国海涵航豪浩禾红宏洪华辉慧吉嘉佳家建江杰金锦晶静娟军君俊凯康可坤兰岚乐雷蕾莉丽莲良林玲龙璐梅美萌梦苗敏明铭娜楠宁暖欧鹏平萍琪琦芊倩强乔钦青清庆秋群然荣瑞睿山珊善尚少申生胜诗士世守书帅双顺思松素堂涛桃腾天铁婷彤婉万旺威伟炜卫文雯武西希晰霞贤香湘翔向晓肖心欣新星雄秀旭轩雪雅亚妍岩艳燕阳洋瑶耀业叶一伊仪怡艺易奕毅音银英瑛颖映勇友余宇羽雨玉元园源远月悦云芸蕴泽增展章昭哲珍振正芝知智中忠舟洲珠竹卓子梓")
SUPPORT_SURNAMES = SURNAMES[:40]


def _h(cid: str, salt: str = '') -> int:
    return int(hashlib.sha256(f'{cid}|{salt}'.encode()).hexdigest()[:12], 16)


def _orig_surname(cid: str) -> str:
    """id 里脱敏后留下的那个**姓**。

    id 有两种写法,姓的位置不同 —— 所以不能"取最后一个汉字"
    (那样会取到「1年以内」的「内」,编出「内佳俊」这种名字):
        平台导出:cand_<JD>_<城市>_<薪低>_<薪高>_<姓>__<年限>
        文件名派生:cand_<姓>___<岗位>_<岗位>
    规则:按 _ 切开后,第一个"1~2 个汉字且首字是常见姓"的片段就是姓。
    """
    toks = [t for t in cid.replace('cand_', '').split('_') if t]
    cjk = lambda t: all('\u4e00' <= ch <= '\u9fa5' for ch in t)
    # ① 常见姓(1~2 字,如「徐」「欧阳」)
    for t in toks:
        if 1 <= len(t) <= 2 and cjk(t) and t[0] in SURNAMES:
            return t
    # ② 单字汉字 —— 「华」「伍」这类不在词表里的姓,也该沿用
    for t in toks:
        if len(t) == 1 and cjk(t):
            return t
    # ③ 「Jessie郭」这种**中英混写**才取结尾的汉字。
    #    这里必须要求"含拉丁字母":否则「业务跟单」也满足"以汉字结尾",
    #    于是把岗位名的最后一个字当成姓(实测编出了「单素思」)。
    for t in toks:
        if (len(t) <= 10 and t and '\u4e00' <= t[-1] <= '\u9fa5'
                and any(ch.isascii() and ch.isalpha() for ch in t)):
            return t[-1]
    return ''


def make_name(cid: str, k: int = 0) -> str:
    """第 k 个候选名(k>0 时换字,用来避开重名)。"""
    sur = _orig_surname(cid) or SURNAMES[_h(cid, 'sur') % len(SURNAMES)]
    if k == 0:
        a = GIVEN[_h(cid, 'g1') % len(GIVEN)]
        b = GIVEN[_h(cid, 'g2') % len(GIVEN)]
    else:
        a = GIVEN[_h(cid, f'g1-{k}') % len(GIVEN)]
        b = EXTRA[_h(cid, f'x{k}') % len(EXTRA)]
    return f'{sur}{a}{b}'


def all_ids() -> list[str]:
    ids: list[str] = []
    if CV_FACTS.is_file():
        ids += list((json.loads(CV_FACTS.read_text(encoding='utf-8')) or {}).keys())
    ids += [f'cand_{p.stem}' for p in INTERVIEW.glob('*.yaml')]
    for f in SHORTLIST.glob('*.yaml'):
        try:
            doc = yaml.safe_load(f.read_text(encoding='utf-8')) or {}
        except yaml.YAMLError:
            continue
        for key in ('kept', 'selected'):
            ids += [c for c in (doc.get(key) or []) if isinstance(c, str)]
    return sorted(set(ids))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--rebuild', action='store_true', help='全部重编(会换名)')
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()

    existing = {}
    if OUT.is_file() and not args.rebuild:
        doc = yaml.safe_load(OUT.read_text(encoding='utf-8')) or {}
        existing = {k: v for k, v in (doc.get('names') or {}).items() if isinstance(v, dict)}

    used = {v.get('name') for v in existing.values()}
    ids = all_ids()
    added = 0
    for cid in ids:
        if cid in existing:
            continue
        for k in range(200):
            name = make_name(cid, k)
            if name not in used:
                break
        used.add(name)
        existing[cid] = {
            'name': name,
            'basis': 'fabricated',
            'why': '原文姓名是脱敏的(廖____ / 徐*),这是为演练编的完整姓名,与真实简历无关',
            'surname_kept': _orig_surname(cid) == name[0],
        }
        added += 1

    print(f'共 {len(ids)} 人 · 新增 {added} 个姓名 · 已有 {len(ids) - added} 个(不改)')
    if not args.dry:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(yaml.safe_dump({
            'note': ('演练用姓名映射:candidate id → 完整姓名。**编造的**,与真实简历无关。'
                     '所有产物(名单/档案/选人)都读这一份,不要各写各的。'),
            'count': len(existing),
            'names': existing,
        }, allow_unicode=True, sort_keys=True, width=100), encoding='utf-8')
        print(f'写出 {OUT.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
