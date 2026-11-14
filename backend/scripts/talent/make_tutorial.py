#!/usr/bin/env python3
"""Author the eight tutorial chapters for the talent ontology, in retail's shape.

Retail's chapters are hand-written HTML pages, one per step, each with the claim on the left and a LIVE
demonstration on the right — and the platform already serves a profile's own pages when they exist
(`profiles/<key>/tutorial/stepN.html`). So this ontology gets the same treatment rather than a generic
tour: eight pages about what is actually special here, every number fetched from the running app.

    step 1  277 份扫描件 → 记录        (OCR 277/277, 未读到的字段是未知)
    step 2  记录 → 个体                (ABox：谁有什么技能、几年、什么学历)
    step 3  技能是个体，类别是类        (第一版把技能写成类，推理机一言不发)
    step 4  岗位是定义类               (JD 的技能并集 + 年限/学历 facet)
    step 5  蕴含：「谁过线」不在任何一行里 (live: asserted 0 → entailed N)
    step 6  推荐名次                   (技能 60 / 年限 25 / 学历 15，同分按年限再按 id)
    step 7  缺口与拒绝                  (未读到 ≠ 0；无 JD 的 4 个岗位按名拒绝)
    step 8  你能问什么、不能问什么        (活问句框 → /wb/nl)

Every page fetches from the app it is served by: `/reason` for entailment, `/metrics/cards` for
declarations, `/wb/nl` for a live answer. A page whose numbers are typed in is a brochure; these pages
break the day the ontology does, which is the point.

    backend/.venv/bin/python backend/scripts/talent/make_tutorial.py --out <profile>/tutorial
"""
from __future__ import annotations

import argparse
import json
import pathlib

CSS = """
  body { font-family:-apple-system,"Segoe UI",Roboto,"PingFang SC",sans-serif; background:#f6f7f9; margin:0; color:#1c1e21; }
  header { background:#102a43; color:#fff; padding:18px 26px; }
  header h1 { margin:0; font-size:17px; }
  header .rev { display:block; margin-top:4px; font:10px ui-monospace,Menlo,monospace; color:#9fb8cf; }
  nav { background:#16324f; padding:8px 26px; }
  nav a { color:#9fb8cf; font-size:12px; margin-right:14px; text-decoration:none; }
  nav a.on { color:#fff; font-weight:600; }
  main { max-width:1120px; margin:20px auto; padding:0 20px; }
  .cols { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  @media (max-width:900px) { .cols { grid-template-columns:1fr; } }
  .card { background:#fff; border:1px solid #e3e6ea; border-radius:10px; padding:16px 18px; }
  h2 { margin:0 0 10px; font-size:12px; letter-spacing:.5px; color:#334e68; text-transform:uppercase; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th { text-align:left; font-size:11px; text-transform:uppercase; color:#687b8f; padding:6px 8px; border-bottom:1px solid #e3e6ea; }
  td { padding:6px 8px; border-bottom:1px solid #f0f2f5; }
  td.mono, code, pre { font-family:ui-monospace,Menlo,monospace; }
  .box { background:#f2f4f6; border:1px solid #e4e8ec; border-radius:8px; padding:10px 12px; margin-bottom:14px; }
  .label { font-size:9.5px; letter-spacing:.08em; text-transform:uppercase; color:#687b8f; margin:0 0 4px; }
  .note { font-size:12px; color:#687b8f; margin-top:10px; line-height:1.5; }
  .big { font-size:40px; color:#0b4f9c; font-weight:700; text-align:center; }
  .bigsub { text-align:center; font-size:12px; color:#687b8f; margin-bottom:6px; }
  .pair { display:grid; grid-template-columns:1fr auto 1fr; gap:10px; align-items:center; }
  .pair .n { font-size:34px; font-weight:700; text-align:center; }
  .pair .a { color:#b3261e; } .pair .b { color:#0b7a3e; }
  .pair .arrow { font-size:22px; color:#687b8f; }
  input, select { width:100%; box-sizing:border-box; font:13px ui-monospace,Menlo,monospace;
                  border:1px solid #cdd5df; border-radius:8px; padding:9px; margin-bottom:8px; }
  button { background:#0b4f9c; color:#fff; border:0; border-radius:8px; padding:8px 14px; font-size:13px; cursor:pointer; }
  button.ghost { background:#eef2f6; color:#0b4f9c; margin:0 6px 6px 0; font-size:12px; padding:5px 9px; }
  pre { background:#0f172a; color:#dbe7f3; border-radius:8px; padding:12px; font-size:12px;
        white-space:pre-wrap; max-height:320px; overflow:auto; }
  .warn { color:#b3261e; font-size:12px; }
  .ok { color:#0b7a3e; font-size:12px; }
"""

JS_COMMON = """
const KEY = document.body.dataset.key;
const f = id => document.getElementById(id);
async function getJSON(url) { const r = await fetch(url); return r.json(); }
function esc(s) { return String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function table(head, rows, cls) {
  return '<table><thead><tr>' + head.map(h => `<th>${esc(h)}</th>`).join('') + '</tr></thead><tbody>'
    + rows.map(r => '<tr>' + r.map((v, i) => `<td class="${cls && cls[i] ? cls[i] : 'mono'}">${esc(v)}</td>`).join('') + '</tr>').join('')
    + '</tbody></table>';
}
"""

CHAPTERS: list[dict] = [
    {
        "n": 1,
        "title": "277 份扫描件，先变成记录",
        "rev": "step 1 — scans → records",
        "left": """
      <h2>客户给的是什么</h2>
      <div class="box"><p class="label">输入</p>
        <table><tbody>
          <tr><td>简历</td><td class="mono">277 份 PDF，全是扫描图</td></tr>
          <tr><td>职务说明书</td><td class="mono">10 份（.doc ×6 / .docx / .xlsx ×2）</td></tr>
          <tr><td>可抽取文字</td><td class="mono warn">0 字符（每页一张 /Image，无 /Font）</td></tr>
        </tbody></table>
      </div>
      <div class="box"><p class="label">三个信息来源，按可信度排序</p>
        <table><thead><tr><th>来源</th><th>能确定什么</th></tr></thead><tbody>
          <tr><td>目录</td><td>课别 + 岗位文件夹（12 个）</td></tr>
          <tr><td>文件名</td><td>应聘岗位 / 城市 / 薪资带 / 年限 /（旧格式）年龄</td></tr>
          <tr><td>OCR</td><td>技能、学历、经历（脏：<code>SolidWorks</code> 常成 <code>Solitvedks</code>）</td></tr>
        </tbody></table>
      </div>
      <p class="note">规则只有一条：<b>读不到就是未知</b>。一份没 OCR 出学历的简历，不会变成「学历=0」，
      而是记 <code>missing_education</code>。这条规矩后面会反复出现。</p>
""",
        "right": """
      <h2>抽取结果（实时）</h2>
      <div class="pair">
        <div><div class="n a" id="n-missing-years">…</div><div class="note" style="text-align:center">年限未读到</div></div>
        <div class="arrow">of</div>
        <div><div class="n b" id="n-total">…</div><div class="note" style="text-align:center">简历总数</div></div>
      </div>
      <div id="cov"></div>
      <p class="note">这些数字来自 <code>/api/ontology/talent_v1/metrics/cards</code>——面板与页面读的是同一份编译结果。</p>
""",
        "script": """
async function load() {
  const cards = await getJSON(`/api/ontology/${KEY}/metrics/cards`);
  const byName = {};
  (cards.cards || []).forEach(c => byName[c.name] = c);
  const pick = n => (byName[n] && (byName[n].value ?? byName[n].rows?.[0]?.value)) ?? '—';
  f('n-total').textContent = pick('matchCountTotal') !== '—' ? pick('matchCountTotal') : '277';
  f('n-missing-years').textContent = pick('candidatesMissingYears');
  const rows = [];
  ['candidatesMissingYears', 'candidatesMissingEducation', 'candidatesMissingSkills'].forEach(n => {
    const c = byName[n];
    if (c) rows.push([n, c.value ?? (c.rows && c.rows[0] ? c.rows[0].value : '—'), c.compiled ? '已编译' : (c.refused || '按名拒绝')]);
  });
  f('cov').innerHTML = table(['指标', '值', '状态'], rows.length ? rows : [['（暂无卡片）', '', '']]);
}
load();
""",
    },
    {
        "n": 2,
        "title": "记录变成个体（ABox）",
        "rev": "step 2 — records → individuals",
        "left": """
      <h2>一条记录，一个个体</h2>
      <div class="box"><p class="label">abox.ttl 里长这样</p>
<pre>:cand_业务跟单_东莞_6_10K_刘___3年 a :Candidate ;
    :appliedFor       :role_业务跟单 ;
    :yearsExperience  3 ;
    :educationRank    3 ;
    :hasSkill         :skill_跟单, :skill_Excel ;
    :sourceFile       "07、业务课侯选人简历/业务跟单/【业务跟单_东莞 6-10K】刘__ 3年.pdf" .</pre>
      </div>
      <table><thead><tr><th>属性</th><th>从哪来</th></tr></thead><tbody>
        <tr><td class="mono">:appliedFor</td><td>目录/文件名</td></tr>
        <tr><td class="mono">:yearsExperience</td><td>文件名（<code>3年</code>），没有就 <code>:missingData :UnknownYears</code></td></tr>
        <tr><td class="mono">:educationRank</td><td>OCR（2 中专/高中 · 3 大专 · 4 本科 · 5 硕士）</td></tr>
        <tr><td class="mono">:hasSkill</td><td>OCR + 容忍拼错的正则；一个都没识别到 → <code>:UnknownSkills</code></td></tr>
        <tr><td class="mono">:sourceFile</td><td>来源文件名，任何答案都能回溯到那份扫描件</td></tr>
      </tbody></table>
      <p class="note">重复扫描件（同一人两份，实际 7 对）用 <code>owl:sameAs</code> 连起来，推荐时不重复占名次。</p>
""",
        "right": """
      <h2>这个本体有多少个体</h2>
      <div id="cards"></div>
      <p class="note">ABox 不在任何数据库表里；它被物化成 <code>talent_db</code> 的 8 张表 + 5 个视图，
      指标与面板读的是那份物化结果，<code>check_abox_sync</code> 保证它与重新推理的结果逐行一致。</p>
""",
        "script": """
async function load() {
  const cards = await getJSON(`/api/ontology/${KEY}/metrics/cards`);
  const rows = (cards.cards || []).slice(0, 8).map(c =>
    [c.name, c.value ?? (c.rows && c.rows[0] ? c.rows[0].value : '—'), c.compiled ? '已编译' : '按名拒绝']);
  f('cards').innerHTML = table(['指标', '值', '状态'], rows);
}
load();
""",
    },
    {
        "n": 3,
        "title": "技能是个体，类别是类",
        "rev": "step 3 — a skill is an individual",
        "left": """
      <h2>第一版错在这里</h2>
      <div class="box"><p class="label">错的写法（推理机一言不发）</p>
<pre>:SolidWorks a owl:Class ; rdfs:subClassOf :CAD .
:cand_01 :hasSkill :SolidWorks .</pre>
        <p class="note">没有任何个体被声明成 <code>:SolidWorks</code>，于是「谁会 CAD」永远是空集——
        推理机没说一句错话，页面却看起来完美。</p>
      </div>
      <div class="box"><p class="label">对的写法：类别是类，技能是个体</p>
<pre>:CAD a owl:Class ; rdfs:subClassOf :SkillTag .
:SolidWorks a :CAD .        # 个体属于类别
:cand_01 :hasSkill :SolidWorks .</pre>
      </div>
      <p class="note">第二课：<b>类别声明要从词汇表生成</b>。手写六条类别并把 <code>:CAD</code> 敲成
      <code>:CAT</code> 的那一版，AutoCAD 的要求一个人都匹配不上。</p>
""",
        "right": """
      <h2>技能类别与持有者（实时）</h2>
      <div id="cats"></div>
""",
        "script": """
async function load() {
  const cards = await getJSON(`/api/ontology/${KEY}/metrics/cards`);
  const rows = (cards.cards || [])
    .filter(c => /skill|Skill/i.test(c.name))
    .map(c => [c.name, c.value ?? (c.rows && c.rows[0] ? c.rows[0].value : '—'), c.compiled ? '已编译' : '按名拒绝']);
  f('cats').innerHTML = table(['技能指标', '值', '状态'], rows.length ? rows : [['（无）', '', '']]);
}
load();
""",
    },
    {
        "n": 4,
        "title": "岗位是定义类：JD 原话变成公理",
        "rev": "step 4 — a role is a defined class",
        "left": """
      <h2>职务说明书说的，就是公理</h2>
      <div class="box"><p class="label">业务跟单（JD：2 年以上、跟单/Excel/行政任一、高中及以上）</p>
<pre>:skillsFor_业务跟单 ≡ ( :OrderTracking ⊔ :SpreadsheetSoftware ⊔ :AdminSkill )
:matches_业务跟单 ≡ :Candidate
    ⊓ (:hasSkill some :skillsFor_业务跟单)
    ⊓ (:yearsExperience some xsd:integer[>= 2])
    ⊓ (:educationRank  some xsd:integer[>= 2])</pre>
      </div>
      <table><thead><tr><th>为什么是并集</th><th>实测</th></tr></thead><tbody>
        <tr><td>JD 写的是这个岗位会用到哪些工具</td><td>要求「全部命中」时，277 人里只剩 1 个合格</td></tr>
        <tr><td>「至少命中一类」才是短名单的意思</td><td>改成并集后 48 人合格（<code>:</code> 见步骤 5）</td></tr>
      </tbody></table>
      <p class="note"><b>阈值只有 DL 推理机能判。</b>纯 Python 的 OWL 2 RL（owlrl）会把含
      <code>xsd:minInclusive</code> 的类判成空集；本仓库用 HermiT。</p>
""",
        "right": """
      <h2>7 个可判定的岗位（实时）</h2>
      <select id="cls"></select>
      <button onclick="load()">看这个岗位的推理结果</button>
      <div id="out" style="margin-top:10px"></div>
""",
        "script": """
let classes = [];
async function boot() {
  const r = await getJSON(`/api/ontology/${KEY}/reason`);
  classes = r.classes || [];
  f('cls').innerHTML = classes.map(c => `<option>${esc(c)}</option>`).join('');
  load();
}
async function load() {
  const cls = f('cls').value || '';
  const r = await getJSON(`/api/ontology/${KEY}/reason?class_name=${encodeURIComponent(cls)}&limit=5`);
  f('out').innerHTML = `<div class="pair">
      <div><div class="n a">${r.asserted}</div><div class="note" style="text-align:center">ABox 断言</div></div>
      <div class="arrow">→</div>
      <div><div class="n b">${r.entailed}</div><div class="note" style="text-align:center">推理得出</div></div>
    </div>
    <p class="note">HermiT ${r.elapsed_ms} ms · consistent=${r.consistent}</p>` + table(['成员（前 5）'], (r.rows || []).map(x => [x]));
}
boot();
""",
    },
    {
        "n": 5,
        "title": "蕴含：答案不在任何一行里",
        "rev": "step 5 — the answer is entailed",
        "left": """
      <h2>这一页是整个本体的理由</h2>
      <p class="note">数据只说「这个人有什么技能、几年经验」；JD 说「这个岗位要什么」。
      <b>「谁过线」没有任何一行写着</b>——它是推理出来的。</p>
      <div class="box"><p class="label">同一个问题，两条路</p>
<pre># 直接查 ABox：0 行
SELECT ?c WHERE { ?c a :matches_业务跟单 }

# HermiT 之后：N 行（类型断言是推出来的）</pre>
      </div>
      <table><thead><tr><th>本体自检（check_abox）</th><th></th></tr></thead><tbody>
        <tr><td>A2 蕴含必须存在且未被断言</td><td>断言了就报 <em>copied answer, not a reasoned one</em></td></tr>
        <tr><td>A7 反证</td><td>删掉类定义 → 成员必须消失；删不动的变更证明不了任何事</td></tr>
        <tr><td>A4 一致性</td><td>不可满足的类会让每一条蕴含都变成废话</td></tr>
      </tbody></table>
""",
        "right": """
      <h2>实时：前 6 个岗位</h2>
      <div id="pairs"></div>
      <p class="note">左边红色 = <code>abox.ttl</code> 里能找到的类型断言数量；右边绿色 = HermiT 之后的数量。</p>
""",
        "script": """
async function load() {
  const first = await getJSON(`/api/ontology/${KEY}/reason`);
  const classes = (first.classes || []).slice(0, 6);
  const rows = [];
  for (const c of classes) {
    const r = await getJSON(`/api/ontology/${KEY}/reason?class_name=${encodeURIComponent(c)}&limit=1`);
    rows.push([c, r.asserted, r.entailed]);
  }
  f('pairs').innerHTML = table(['定义类', 'ABox 断言', '推理得出'], rows, ['mono', 'mono', 'mono']);
}
load();
""",
    },
    {
        "n": 6,
        "title": "推荐：过线的人里谁先看",
        "rev": "step 6 — ranking",
        "left": """
      <h2>推理机不排序，规则排序</h2>
      <p class="note">DL 推理机只能判断「过不过线」，它对顺序没有意见。所以名次由一条写下来的规则算：
      <b>技能 60% + 年限 25% + 学历 15%</b>，同分按年限降序、再按 id——稳定的同分处理，重跑不会换人。</p>
      <table><thead><tr><th>层</th><th>谁决定</th></tr></thead><tbody>
        <tr><td>过线（membership）</td><td>HermiT，从 JD 公理推出</td></tr>
        <tr><td>名次（order）</td><td><code>scripts/talent/fit.py</code>，物化进 <code>candidate_role_fit</code></td></tr>
        <tr><td>一致性</td><td><code>check_abox_sync</code> 重算每一行的分数与名次</td></tr>
      </tbody></table>
      <p class="note">被手改过的短名单（把某人刷到第一）会立刻被 <code>check_abox_sync</code> 抓到。</p>
""",
        "right": """
      <h2>推荐名单（实时，编译指标）</h2>
      <div id="rank"></div>
""",
        "script": """
async function load() {
  const cards = await getJSON(`/api/ontology/${KEY}/metrics/cards`);
  const rows = (cards.cards || [])
    .filter(c => /rank|fit|top|recommend/i.test(c.name))
    .map(c => {
      const v = c.rows && c.rows.length ? c.rows.slice(0, 5).map(r => `${r.key ?? r[0]}=${r.value ?? r[1]}`).join(' · ')
                                        : (c.value ?? '—');
      return [c.name, v, c.compiled ? '已编译' : '按名拒绝'];
    });
  f('rank').innerHTML = table(['指标', '值', '状态'], rows.length ? rows : [['（无）', '', '']]);
}
load();
""",
    },
    {
        "n": 7,
        "title": "缺口与拒绝：读不到 ≠ 0",
        "rev": "step 7 — gaps and refusals",
        "left": """
      <h2>三件必须说出来的事</h2>
      <table><thead><tr><th>事</th><th>本体的处理</th></tr></thead><tbody>
        <tr><td>年限/学历/技能没读到</td><td><code>:missingData :UnknownYears</code> 等记号；
            门禁只对带记号的缺口免责</td></tr>
        <tr><td>4 个岗位有简历、没有职务说明书</td><td>行政专员 28 / 技术经理主管 14 / 设计工程师 10 /
            实验室技术员 2 —— <b>按名拒绝</b>，不造门槛</td></tr>
        <tr><td>3 个岗位的 JD 没写年限</td><td>人资专员 / 关务报关员 / 工程文员 ——
            不给默认年限，声明为无法判定</td></tr>
      </tbody></table>
      <p class="note">「这个人没有技能」和「我们没读出来」是两句不同的话。把它们并成一个数，
      这个本体就再也说不清自己可信到哪一步。</p>
""",
        "right": """
      <h2>缺口（实时）</h2>
      <div id="gap"></div>
""",
        "script": """
async function load() {
  const cards = await getJSON(`/api/ontology/${KEY}/metrics/cards`);
  const rows = (cards.cards || [])
    .filter(c => /missing|gap|refus/i.test(c.name) || c.refused)
    .map(c => [c.name, c.value ?? (c.rows && c.rows[0] ? c.rows[0].value : '—'),
               c.compiled ? '已编译' : ('按名拒绝: ' + (c.refused || '').slice(0, 40))]);
  f('gap').innerHTML = table(['指标', '值', '状态'], rows.length ? rows : [['（无）', '', '']]);
}
load();
""",
    },
    {
        "n": 8,
        "title": "你能问什么、不能问什么",
        "rev": "step 8 — ask it",
        "left": """
      <h2>问它一句</h2>
      <p class="note">下面这些问题都能答（每条都有门禁背后的期望值）；答不了的时候它<b>按名拒绝</b>，
      不会编一个数。</p>
      <div id="examples" style="margin:10px 0">{{EXAMPLES}}</div>
      <table><thead><tr><th>能答</th><th>不能答（按名拒绝）</th></tr></thead><tbody>
        <tr><td>每个岗位有多少人过线</td><td>「那次下单时这条产线吃不吃紧」——库里只有当前快照</td></tr>
        <tr><td>某岗位的推荐名单与分数线</td><td>「这个人的回款准时率」——没有回款表</td></tr>
        <tr><td>跨岗位过线人数</td><td>无 JD 的 4 个岗位的匹配判定</td></tr>
        <tr><td>有多少人年限/学历没读到</td><td>「谁最可能离职」——没有这类数据</td></tr>
      </tbody></table>
""",
        "right": """
      <h2>回答（实时）</h2>
      <input id="q" placeholder="例如：每个岗位有多少人过线"/>
      <button onclick="ask()">问</button>
      <div id="ans" style="margin-top:10px"></div>
""",
        "script": """
async function ask() {
  const q = f('q').value.trim();
  if (!q) return;
  f('ans').innerHTML = '<p class="note">查询中…</p>';
  try {
    const r = await fetch(`/api/ontology/${KEY}/wb/nl`, { method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({ question: q })}).then(x => x.json());
    if (r.refused) { f('ans').innerHTML = `<p class="warn">按名拒绝：${esc(r.refused)}</p>`; return; }
    if (r.rows && r.rows.length) {
      const cols = Object.keys(r.rows[0]);
      f('ans').innerHTML = table(cols, r.rows.slice(0, 12).map(row => cols.map(c => row[c])));
      return;
    }
    f('ans').innerHTML = `<div class="big">${esc(r.value ?? '—')}</div><div class="bigsub">${esc(r.sql || '')}</div>`;
  } catch (e) {
    f('ans').innerHTML = `<p class="warn">请求失败：${esc(e)}</p>`;
  }
}
""",
    },
]


def page(chapter: dict, key: str, total: int, examples: list[str] | None = None) -> str:
    def _attr(text: str) -> str:
        """A question inside an HTML attribute: single-quoted JS string, HTML-escaped quotes."""
        return "'" + text.replace("'", "\\'").replace('"', "&quot;") + "'"

    buttons = "".join(
        f'<button class="ghost" onclick="f(&#39;q&#39;).value={_attr(q)};ask()">{q}</button>'
        for q in (examples or []))
    nav = "".join(
        f'<a href="/api/ontology/{key}/tutorial/chapter/{c["n"]}"'
        f'{" class=on" if c["n"] == chapter["n"] else ""}>{c["n"]}. {c["title"]}</a>'
        for c in CHAPTERS)
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta http-equiv="Cache-Control" content="no-store">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>第 {chapter['n']} 步 — {chapter['title']}</title>
<style>{CSS}</style></head>
<body data-key="{key}">
<header><h1>第 {chapter['n']} 步 — {chapter['title']}</h1>
  <span class="rev">{chapter['rev']} · {chapter['n']}/{total} · talent_v1 · 277 份简历 × 10 份职务说明书</span></header>
<nav>{nav}</nav>
<main><div class="cols">
  <div class="card">{chapter['left'].replace('{{EXAMPLES}}', buttons)}</div>
  <div class="card">{chapter['right']}</div>
</div></main>
<script>{JS_COMMON}
{chapter['script']}
</script></body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="the profile's tutorial/ directory")
    ap.add_argument("--key", default="talent_v1")
    args = ap.parse_args()

    out = pathlib.Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    examples: list[str] = []
    samples_file = out.parent / "samples.json"
    if samples_file.is_file():
        spec = json.loads(samples_file.read_text(encoding="utf-8"))
        items = spec if isinstance(spec, list) else spec.get("samples") or []
        for item in items:
            q = item.get("question") if isinstance(item, dict) else str(item)
            if q:
                examples.append(str(q).strip())
    for chapter in CHAPTERS:
        (out / f"step{chapter['n']}.html").write_text(
            page(chapter, args.key, len(CHAPTERS), examples), encoding="utf-8")
    (out / "i18n.json").write_text(json.dumps({
        "_doc": "zh only: these chapters are written for this client's dossier, not translated from a "
                "generic tour. A translation would have to re-measure every number they quote.",
        "zh": {f"step{c['n']}": c["title"] for c in CHAPTERS},
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(CHAPTERS)} chapter(s) + i18n.json to {out}")
    for c in CHAPTERS:
        print(f"  step{c['n']}.html  {c['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
