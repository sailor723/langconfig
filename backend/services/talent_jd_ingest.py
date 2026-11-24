"""Phase 1 · 上传一份 JD → 抽成文本 → 生成「缺口 vs 标准模板」的可读 md。

## 上传后跑两件事（用户 2026-11-24 定的口径）

**a. 抽取并落盘**（`extract`）——把客户文件转成纯文本，再把"文本里明确写着的东西"抽成结构化 yaml：

    work/talent/uploads/<JD>/original.<ext>     原件，一个字节都不改（出问题回去看它）
    work/talent/jd_links/_source/<JD>.txt       抽出来的正文（**引用与行号的唯一锚点**）
    work/talent/jd_extracted/<JD>.yaml          抽取结果：转换器、行数、逐条资格/职责、以及 missing

    三份里的「原件」与「正文」是锚点，`jd_extracted` 是**派生件**（可重跑覆盖）。

**b. 对标准模板查缺口，生成给业务与 HR 看的 md**（`gap_md`）

    work/talent/jd_docs/<JD>.缺口.md            40 格逐行：状态 / 依据 / 缺谁补

## 这一档只认"原文里写着"

Phase 1 不跑 LLM、不造引用，所以状态只有四种：
`原文` / `原文·空值`（客户写了栏目没填）/ `缺` / `不适用`（条件字段不触发）。

**18 个字段靠引用才稳定**（年龄、学历、专业、年限、技能、语言、证书、薪资、到岗、通勤、
平均在职、近5年、背调、保密…）：这里先用文本规则兜一遍，兜到记 `原文`，
兜不到记 `缺` 并注明「未抽取引用，可能漏」—— 绝不写成「不满足」或「不合格」。

## 为什么 md 要能编辑

业务与 HR 看的是这份 md：他们要在旁边写"这条我们其实要求本科"“到岗 2 周内”。
所以它是**可写的**，但文件头写清楚：重跑缺口会覆盖；要长期保存的答案请落
`jd_inputs/<JD>.yaml`（那是第 2 步的正式输入）。
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib
import re
from typing import Any, Dict, List, Optional, Tuple

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
TALENT = ROOT / 'work' / 'talent'
UPLOADS = TALENT / 'uploads'
SOURCES = TALENT / 'jd_links' / '_source'
LINKS = TALENT / 'jd_links'
EXTRACTED = TALENT / 'jd_extracted'
JD_DOCS = TALENT / 'jd_docs'
TEMPLATE = TALENT / 'templates' / 'standard_jd_template.yaml'

SUPPORTED = ('.doc', '.docx', '.pdf', '.xlsx', '.xls', '.txt', '.md')


class JdIngestError(Exception):
    """抽取失败。**必须带人能看懂的原因** —— 静默成功比失败更糟。"""


# ── a. 抽取 ────────────────────────────────────────────────────────────────

def extract_text(path: pathlib.Path) -> Tuple[str, str]:
    """按扩展名转纯文本，返回 (text, how)。how 要写进 yaml —— 出问题看得出走的哪条路。"""
    suffix = path.suffix.lower()
    if suffix in ('.doc', '.ppt', '.xls'):
        from services.legacy_doc import legacy_to_text
        text, how = legacy_to_text(path)
        if not text.strip():
            raise JdIngestError(
                f'{suffix} 转换后是空的（转换器={how}）。本机没有 antiword/catdoc/textutil/soffice？'
                f'先装一个，或把文件另存为 .docx 再传。')
        return text, f'legacy:{how}'
    if suffix == '.docx':
        try:
            import docx  # python-docx
        except ImportError as exc:  # pragma: no cover
            raise JdIngestError('没装 python-docx，读不了 .docx') from exc
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        d = docx.Document(str(path))
        parts: List[str] = []
        # **按文档顺序**遍历段与表格：职务说明书里"事务表述"后面紧跟的就是那张表。
        # 之前先读全部段落再读全部表格，表格永远掉到文末，于是"事务表述"的下一行成了抬头行。
        for child in d.element.body.iterchildren():
            tag = child.tag.rsplit('}', 1)[-1]
            if tag == 'p':
                parts.append(Paragraph(child, d).text)
            elif tag == 'tbl':
                for row in Table(child, d).rows:
                    parts.append('\x07'.join(c.text.strip() for c in row.cells))
        text = '\n'.join(parts)
        if not text.strip():
            raise JdIngestError('.docx 里没读到任何文字（可能整页是图片）')
        return text, 'python-docx'
    if suffix == '.pdf':
        from core.rag.documents import load_pdf_pages
        pages = load_pdf_pages(str(path))
        text = '\n'.join(getattr(p, 'page_content', '') or '' for p in pages)
        if not text.strip():
            raise JdIngestError('.pdf 没抽出文字（扫描件需要 OCR，本机没做）')
        return text, f'rag:load_pdf_pages({len(pages)} 页)'
    if suffix in ('.xlsx', '.xls'):
        if suffix == '.xls':
            raise JdIngestError('.xls（老 Excel）请另存为 .xlsx 再传')
        import openpyxl
        wb = openpyxl.load_workbook(str(path), data_only=True)
        lines: List[str] = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                if cells:
                    lines.append('\x07'.join(cells))
        text = '\n'.join(lines)
        if not text.strip():
            raise JdIngestError('.xlsx 里没读到任何内容')
        return text, f'openpyxl({len(wb.worksheets)} sheet)'
    # 纯文本
    for enc in ('utf-8', 'gbk', 'gb18030'):
        try:
            return path.read_text(encoding=enc), f'text:{enc}'
        except UnicodeDecodeError:
            continue
    raise JdIngestError(f'读不出文本编码（{suffix}），请存成 UTF-8')


_CTRL = re.compile(r'[\x00-\x08\x0b-\x1f\x7f]')


def _norm(x: str) -> str:
    """去空白与控制字符后再比 —— Word 表格抽平后单元格之间是 \\x07（BEL）与全角空格。"""
    return _CTRL.sub('', x).replace('\u3000', '').replace(' ', '')


def _line_of(text: str, needle: str) -> Optional[int]:
    head = _norm(needle)[:8]
    if not head:
        return None
    for i, line in enumerate(text.splitlines(), 1):
        if head in _norm(line):
            return i
    return None


_QUAL_BLOCK = re.compile(r'(任职资格|岗位要求|任职要求|资格条件|录用条件)')
_DUTY_BLOCK = re.compile(r'(岗位职责|工作职责|主要职责|职责范围|工作内容)')
_TABLE_HEAD = re.compile(r'(事务表述|作业明细)')


#: 客户稿里的小标题（只有这些才算"下一节开始了"）。
#  之前用"短行就算标题"的启发式，结果遇到第一条内容「年龄：28 ~ 45岁；」就断掉，
#  任职资格抽出来是空的 —— 短行不等于小标题，得看它是不是这些词之一。
_HEADINGS = re.compile(
    r'(任职资格|岗位要求|任职要求|资格条件|录用条件|岗位职责|工作职责|主要职责|职责范围|'
    r'工作内容|事务表述|作业明细|岗位目的|职务目的|工作目标|关键指标|考核指标|KPI|'
    r'工作条件|工作环境|任职条件|其他要求|修改履历|核准|审核|制订|文件名称|职务名称|隶属部门)')


def _section_lines(text: str, start_pat: re.Pattern) -> List[str]:
    """取某个小标题之后、下一个**已知小标题**之前的非空行（客户稿的编号条目）。"""
    out: List[str] = []
    inside = False
    for ln in text.splitlines():
        t = ln.strip().lstrip('*').strip()
        if not t:
            continue
        if not inside:
            if start_pat.search(_norm(t)) and len(t) <= 20:
                inside = True
            continue
        if _HEADINGS.search(_norm(t)) and len(t) <= 24 and not re.match(r'^[0-9０-９（(]', t):
            break
        out.append(t)
    return out[:30]


def _role_type(supervises: Optional[str]) -> str:
    """岗位类别只认原文「直接下属」这一处判据；判不出就留空，不猜。

    名字带「经理/主管」不作数（本仓库实测：品质经理原文写着「直接下属　无」）。
    """
    v = _norm(supervises or '')
    if v in ('无', '0', '00'):
        return '员工岗'
    if re.search(r'[0-9一二三四五六七八九十]\s*(人|名)|主管|组长|员', v):
        return '经理岗'        # 有下属 → 倾向经理岗，但仍要人工确认
    return ''


def _role_basis(supervises: Optional[str]) -> str:
    v = (supervises or '').strip()
    if not v:
        return '原文没有「直接下属」栏 → 岗位类别未定，需人工确认'
    if _norm(v) == '无':
        return '原文「直接下属：无」→ 员工岗（名字带「经理」不作数）'
    return f'原文「直接下属：{v}」→ 有下属，倾向经理岗；待人工确认'


def extract_fields(text: str) -> Dict[str, Any]:
    """把"文本里明确写着的东西"抽出来。抽不到就写 missing，不猜。"""
    from scripts.talent.jd_parse import requirements_from_text, role_from_filename  # noqa: F401

    quals = _section_lines(text, _QUAL_BLOCK)
    duties = _section_lines(text, _DUTY_BLOCK)
    role = ''
    m = re.search(r'职务名称[\x07:：\s]*([^\x07\n]{2,20})', text)
    if m:
        role = m.group(1).strip()
    dept = ''
    m = re.search(r'隶属部门[\x07:：\s]*([^\x07\n]{2,20})', text)
    if m:
        dept = m.group(1).strip()
    reports_to = ''
    m = re.search(r'直接上司[\x07:：\s]*([^\x07\n]{0,20})', text)
    if m:
        reports_to = m.group(1).strip()
    supervises = ''
    m = re.search(r'直接下属[\x07:：\s]*([^\x07\n]{0,20})', text)
    if m:
        supervises = m.group(1).strip()

    missing: List[str] = []
    parsed = requirements_from_text(role or 'JD', text)
    for k in ('education_floor', 'min_years', 'skills'):
        if not parsed.get(k):
            missing.append(k)

    return {
        'title': role or None,
        'department': dept or None,
        'reports_to': reports_to or None,
        'supervises': supervises or None,
        'qualifications': quals,
        'duties': duties,
        'education_floor': parsed.get('education_floor'),
        'min_years': parsed.get('min_years'),
        'skills': parsed.get('skills') or [],
        'missing': missing,
        'line_index': {
            'title': _line_of(text, '职务名称'),
            'department': _line_of(text, '隶属部门'),
            'supervises': _line_of(text, '直接下属'),
            'qualifications': _line_of(text, '任职资格'),
            'duties': _line_of(text, '岗位职责'),
        },
    }


def ingest(filename: str, data: bytes) -> Dict[str, Any]:
    """上传 → 落原件 → 抽文本 → 写抽取件 → 写引用骨架 → 算缺口 → 写缺口 md。"""
    from scripts.talent.jd_parse import role_from_filename

    name = pathlib.Path(filename or 'upload')
    suffix = name.suffix.lower()
    if suffix not in SUPPORTED:
        raise JdIngestError(f'不支持的文件类型 {suffix or "（无扩展名）"}；支持：{", ".join(SUPPORTED)}')
    jd = role_from_filename(name.stem) or '未命名岗位'
    if jd in {p.stem for p in LINKS.glob('*.yaml')}:
        raise JdIngestError(f'已经有一份叫「{jd}」的 JD 了 —— 换名再传，或先把旧的归档（同名会让两套缺口并存）')

    up_dir = UPLOADS / jd
    up_dir.mkdir(parents=True, exist_ok=True)
    original = up_dir / f'original{suffix}'
    original.write_bytes(data)

    text, how = extract_text(original)
    SOURCES.mkdir(parents=True, exist_ok=True)
    text_path = SOURCES / f'{jd}.txt'
    text_path.write_text(text, encoding='utf-8')

    fields = extract_fields(text)
    EXTRACTED.mkdir(parents=True, exist_ok=True)
    ex_path = EXTRACTED / f'{jd}.yaml'
    ex_path.write_text(yaml.safe_dump({
        '_doc': ('抽取件（派生）：从上传的原件转出的正文与逐条内容。'
                 '原件与正文才是锚点；重跑会覆盖本文件。'),
        'jd': jd,
        'stage': 'phase1-extracted',
        'original': str(original.relative_to(ROOT)),
        'source_text': str(text_path.relative_to(ROOT)),
        'extracted_with': how,
        'source_lines': len(text.splitlines()),
        'extracted_at': _dt.datetime.now().isoformat(timespec='seconds'),
        **fields,
    }, allow_unicode=True, sort_keys=False), encoding='utf-8')

    # 不写 jd_links/<JD>.yaml：那是"逐字引用复核过"的产物，上传件还没抽引用。
    # 伪造一份空 citations 的骨架，会让引用门禁的"读到 0 条"既报不出问题也查不出问题。
    # 侧栏列 JD 用 union(jd_links/*.yaml, uploads/*)（见 api/talent/routes._jds）。
    links_path = None

    from services.talent_gap import text_gap_for

    gap = text_gap_for(jd)
    md_path = gap_md(jd, gap)
    return {'jd': jd, 'original': str(original.relative_to(ROOT)),
            'source_text': str(text_path.relative_to(ROOT)),
            'extracted': str(ex_path.relative_to(ROOT)),
            'links': str(links_path.relative_to(ROOT)) if links_path else '',
            'md': str(md_path.relative_to(ROOT)),
            'gap': {k: gap[k] for k in ('source', 'source_label', 'template_fields',
                                        'tally', 'in_judging', 'note')}}


# ── b. 缺口 md（给业务与 HR 看的那一份）───────────────────────────────────

WHO_FILLS = {
    '缺': '客户补（客户稿没写这一项）',
    '原文·空值': '客户补（栏目在、值是空的）',
}


def gap_md(jd: str, gap: Dict[str, Any]) -> pathlib.Path:
    rows = gap['fields']
    t = gap['tally']
    total = gap['template_fields']
    need_cites = [r for r in rows if r['state'] == '缺' and r.get('needs_citation')]
    L: List[str] = []
    A = L.append
    A(f'# {jd} · 按标准模板查缺口（{total} 格）')
    A('')
    A(f'> 口径：**{gap["source_label"]}** —— 只认客户原文里写着的东西，不做推断、不填我方建议。')
    A(f'> 生成：`services/talent_jd_ingest.py`（上传即生成）。**重跑会覆盖本文件**；'
      '要长期保留的答案请写进 `jd_inputs/'
      f'{jd}.yaml`（第 2 步的正式输入）。')
    A('')
    A('## 业务与 HR 先看这四行')
    A('')
    A('| 状态 | 格数 | 含义 | 谁处理 |')
    A('|---|---|---|---|')
    A(f'| 原文 | **{t.get("原文", 0)}** | 客户写了，读得到 | —（已可判） |')
    A(f'| 原文·空值 | **{t.get("原文·空值", 0)}** | **客户写了栏目却没填** | 客户补（最优先） |')
    A(f'| 缺 | **{t.get("缺", 0)}** | 客户稿没有这一项 | 客户补 / 我方按标准定 |')
    A(f'| 不适用 | **{t.get("不适用", 0)}** | 条件字段，本岗位类别不触发 | — |')
    A('')
    A(f'**能判 {gap["in_judging"]}/{total} 格。** ' +
      (f'其中 **{len(need_cites)}** 格是靠"文本兜底"读到的（年龄/学历/年限/技能这类），'
       '严格确认需要第 1 步的逐字引用；引用抽完后这 {n} 格可能变成「缺」。'.replace('{n}', str(len(need_cites)))
       if need_cites else ''))
    A('')
    A('## 40 格逐行')
    A('')
    A('| 段 | 字段 | 名称 | 层级 | 状态 | 依据 | 谁补 / 缺什么 |')
    A('|---|---|---|---|---|---|---|')
    for r in rows:
        ev = '；'.join(r.get('evidence') or []) or (r.get('why') or '—')
        ev = ev.replace('|', '/')[:120]
        who = r.get('needs') or WHO_FILLS.get(r['state'], '—')
        if r['state'] == '缺' and r.get('needs_citation'):
            who = '客户补；或抽引用后确认'
        A(f"| {r['section']} | `{r['code']}` | {r['label']} | {r['level']} | "
          f"**{r['state']}** | {ev} | {who.replace('|', '/')} |")
    A('')
    gaps = [r for r in rows if r['state'] in ('缺', '原文·空值')]
    if gaps:
        A('## 需要客户补的（按段）')
        A('')
        for sec in sorted({r['section'] for r in gaps}):
            group = [r for r in gaps if r['section'] == sec]
            A(f'- **{sec}**：' + '、'.join(f"{r['label']}(`{r['code']}`)" for r in group))
        A('')
    JD_DOCS.mkdir(parents=True, exist_ok=True)
    p = JD_DOCS / f'{jd}.缺口.md'
    p.write_text('\n'.join(L), encoding='utf-8')
    return p
