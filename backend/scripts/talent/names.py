#!/usr/bin/env python3
"""候选人的**显示姓名** —— 一处读取 `work/talent/fake_names.yaml`,别处不要自己编。

简历原文是脱敏的(`廖____`、`徐*`、`lizw`),演练时满屏都是这种名字看着像数据坏了。
`fake_names.py` 给每个 id 编了一个完整姓名并落在这份映射里;这里只负责读。

**这些姓名是编的**,文书里必须标 `编造(演示)`。id 一律不动:文件名、判定、
一面记录、名单全部照旧以 candidate id 为键,只有"显示"换成姓名。
"""
from __future__ import annotations

import functools
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
FAKE = ROOT / 'work' / 'talent' / 'fake_names.yaml'


@functools.lru_cache(maxsize=1)
def _map() -> dict:
    if not FAKE.is_file():
        return {}
    doc = yaml.safe_load(FAKE.read_text(encoding='utf-8')) or {}
    return doc.get('names') or {}


def name_of(cid: str) -> str:
    """显示姓名。映射里没有就退回 id 里的脱敏写法(不编)。"""
    rec = _map().get(cid)
    if isinstance(rec, dict) and rec.get('name'):
        return str(rec['name'])
    return str(cid).replace('cand_', '')


def label(cid: str) -> str:
    """`姓名 · 简写 id` —— 名单里既认得出人,又能对上文件。"""
    nm = name_of(cid)
    short = str(cid).replace('cand_', '')
    return nm if nm == short else f'{nm}'
