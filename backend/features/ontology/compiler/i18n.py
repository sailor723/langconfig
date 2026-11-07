"""Interface language: English and 中文 — one table, applied to every page.

Two rules keep this honest:

* **The English HTML stays the source of truth.** Nothing is duplicated per language: the
  pages are written once in English, and a translation is a lookup from an exact text node
  to its counterpart. A phrase that is not in the table stays English — a missing
  translation is visible, not silently mangled.
* **Markup is never rewritten.** The translator walks the HTML token by token and only
  replaces whole text nodes (and a few attributes). `<pre>`, `<code>`, `<script>` and
  `<style>` are skipped, so SQL, axioms, and the JavaScript itself are untouched.

The same table is served to the browser (`/api/i18n`) so text that JavaScript adds after
load — compiled SQL cards, table cells, lock messages — is translated too.

Language lives in `settings.json` under `ui.language` and is switched on `/settings`.
"""

from __future__ import annotations

import json
import os
import pathlib
import re

BASE = pathlib.Path(__file__).resolve().parent
# The language tables and the profile they belong to: the RETAIL PROFILE's settings.json, not
# "whatever directory this module sits in" — the i18n gate reads the guard block from it.
SETTINGS = pathlib.Path(os.environ.get("APP_SETTINGS")
                         or (BASE.parent / "profiles" / "retail" / "settings.json"))

LANGS = [("en", "English"), ("zh", "中文")]
DEFAULT = "en"

# --------------------------------------------------------------------------- storage


def current() -> str:
    """The language the UI is rendered in (defaults to English, never raises)."""
    try:
        s = json.loads(SETTINGS.read_text(encoding="utf-8"))
        lang = (s.get("ui") or {}).get("language") or DEFAULT
    except Exception:  # noqa: BLE001
        return DEFAULT
    return lang if lang in dict(LANGS) else DEFAULT


def set_language(lang: str) -> str:
    """Persist the choice. Unknown values fall back to English."""
    lang = lang if lang in dict(LANGS) else DEFAULT
    s = {}
    if SETTINGS.exists():
        try:
            s = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            s = {}
    s.setdefault("ui", {})["language"] = lang
    SETTINGS.write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return lang


# --------------------------------------------------------------------------- table
# Exact text node → translation. Whitespace is normalised before lookup, so an indented
# sentence in the HTML matches a single-line key here.

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


PHRASES: dict[str, dict[str, str]] = {"en": {}, "zh": {}}
_ZH = {
    # ---- the shell: sidebar, badges, pills
    "Home": "首页",
    "Reasoner": "推理器",
    "Query": "查询",
    "Actions": "动作",
    "Backlog": "待声明",
    "Tutorial": "教程",
    "Design": "设计",
    "Settings": "设置",
    "Settings ⚙": "设置 ⚙",
    "reasoner ⌨": "推理器 ⌨",
    "query ✦": "查询 ✦",
    "actions ⚡": "动作 ⚡",
    "backlog ▤": "待声明 ▤",
    "⌨ reasoner": "⌨ 推理器",
    "lane A · compiled SQL (read)": "通道 A · 编译成 SQL（只读）",
    "lane B · SPARQL + Ontop (read)": "通道 B · SPARQL + Ontop（只读）",
    "lane C · actions (write)": "通道 C · 动作（写入）",
    "compare": "对比",
    "⚖ compare lanes": "⚖ 对比两条通道",
    "← back to the app": "← 回到应用",
    "← app": "← 应用",
    "design": "设计",
    "settings": "设置",
    # ---- settings page
    "Settings — ontology app": "设置 —— 本体应用",
    "⚙ Settings — ontology app": "⚙ 设置 —— 本体应用",
    "Language / 语言": "语言 / Language",
    "English": "English",
    "中文": "中文",
    "Interface language. The pages are written once in English and translated by lookup, "
    "so SQL, axioms and code samples never change.": "界面语言。页面只用英文写一遍，翻译靠查表完成，所以 SQL、公理和代码示例不会变。",
    "SQL guardrails — a database with tens of millions of rows":
        "SQL 护栏 —— 这是一个有几千万行的真实库",
    "Enable the guardrails (LIMIT · time bound · plan budget · statement timeout)":
        "启用护栏（LIMIT · 时间边界 · 计划预算 · 语句超时）",
    "Row cap — LIMIT injected when a query has none": "行数上限 —— 查询没有 LIMIT 时自动加上",
    "Time bound — days injected on a big table (0 = refuse instead)":
        "时间边界 —— 大表自动注入的天数（0 = 直接拒绝）",
    "Statement timeout (ms)": "语句超时（毫秒）",
    "Plan budget — refuse a scan estimated to read more rows than":
        "计划预算 —— 估算要扫超过这么多行就拒绝",
    "Big tables — \"table:time_column\", one per line": "大表 —— 每行一个“表: 时间列”",
    "A declared metric is never windowed by the guard — that would change the number its "
    "definition promises. Listings get the window and the row cap, and every injection is "
    "printed next to the SQL. Anything estimated over the plan budget is refused by name before "
    "it runs.": "护栏绝不会给已声明的指标偷偷加时间窗 —— 那会改变它定义里承诺的数字。"
        "列表类查询会拿到时间窗和行数上限，每一次注入都打印在 SQL 旁边；"
        "估算超过计划预算的，会在执行前按名字拒绝。",
    "Lanes — A and B read, C writes": "通道 —— A、B 只读，C 写入",
    "Lane A · compiled SQL": "通道 A · 编译成 SQL",
    "Lane B · SPARQL + Ontop": "通道 B · SPARQL + Ontop",
    "Lane C · actions": "通道 C · 动作",
    "read": "只读",
    "write": "写入",
    "ontology → SQL once (axiom becomes a": "本体一次性编译成 SQL（公理变成",
    "predicate), run on the source DB": "谓词），直接在源库上执行",
    "virtual RDF graph + R2RML mapping; each SPARQL query is rewritten to SQL (OWL 2 QL)":
        "虚拟 RDF 图 + R2RML 映射；每条 SPARQL 都由 Ontop 改写成 SQL（OWL 2 QL）",
    "Lane B — Ontop SPARQL endpoint": "通道 B —— Ontop SPARQL 端点",
    "Lane B — ontology namespace": "通道 B —— 本体命名空间",
    "loading…": "加载中…",
    "Declared, validated, audited writes:": "声明式、经过校验、留审计的写操作：",
    "→ one transaction (preconditions → effect → append-only audit). This lane is what changes "
    "the data the other two read.": "→ 一个事务（前置条件 → 生效 → 只追加的审计）。另外两条通道读到的数据，就是被这条通道改的。",
    "open the action runner →": "打开动作运行器 →",
    "A and B read the same rows; neither materializes a copy. C is the only lane allowed to "
    "write, and only to properties the ontology marks": "A 和 B 读的是同一批行，谁都不落副本。只有 C 允许写入，而且只写本体标记为",
    "Ontology / namespace": "本体 / 命名空间",
    "Namespace IRI": "命名空间 IRI",
    "Page title": "页面标题",
    "Ontology folder (relative to app dir)": "本体目录（相对应用目录）",
    "Overlay TTL (relative)": "叠加层 TTL（相对路径）",
    "Database (DSN)": "数据库（DSN）",
    "Host": "主机",
    "Port": "端口",
    "Database": "数据库",
    "User": "用户",
    "Password": "密码",
    "Lane A's live numbers are measured by compiling TTL → SQL and running it here.":
        "通道 A 的实时数字，是把 TTL 编译成 SQL 后在这里执行量出来的。",
    "Natural language (LLM)": "自然语言（大模型）",
    "Backend": "后端",
    "auto — DeepSeek if DEEPSEEK_API_KEY, else local Ollama":
        "auto —— 有 DEEPSEEK_API_KEY 就用 DeepSeek，否则用本地 Ollama",
    "deepseek — cloud (needs DEEPSEEK_API_KEY in the server env)":
        "deepseek —— 云端（需要服务器环境里有 DEEPSEEK_API_KEY）",
    "ollama — local (OLLAMA_BASE, default 127.0.0.1:11434)":
        "ollama —— 本地（OLLAMA_BASE，默认 127.0.0.1:11434）",
    "fallback — deterministic, no model at all": "fallback —— 纯确定性，完全不用模型",
    "Model (blank = default for the backend)": "模型（留空 = 用该后端的默认模型）",
    "Polish answers with the model, then verify numbers/keys/language (template fallback)":
        "用模型润色回答，再核对数字/键名/语言（不通过就退回模板）",
    "checking backends …": "正在检测后端…",
    "The API key is never stored here — it comes from the server's environment. The model "
    "only picks from the compiled ontology (metric / class / action); it never writes SQL, "
    "and actions stay dry-run until you confirm.": "API key 不存在这里 —— 它来自服务器的环境变量。模型只从编译好的本体里挑"
        "（指标 / 类 / 动作），从不写 SQL；动作在你确认之前一概是预演。",
    "Rendering": "渲染",
    "List individuals when a class has at most (rows)": "一个类的个体数不超过（行数）时列出个体",
    "Save &amp; regenerate": "保存并重新生成",
    "Save & regenerate": "保存并重新生成",
    "e.g. how many customers?": "例如：有多少客户？",
    # ---- tutorial shell
    "Tutorial — eight steps in one view": "教程 —— 八步，一屏看完",
    "▸ Ontology tutorial — eight steps in one view": "▸ 本体教程 —— 八步，一屏看完",
    "Pick a step on the left; the page on the right stays interactive. Same data, growing "
    "semantics.": "左边选一步，右边的页面始终可交互。同一份数据，语义一层层长出来。",
    "rev single-view · steps 1–8": "rev 单视图 · 步骤 1–8",
    "click a node to inspect it": "点一个节点看说明",
    "Columns follow the edges: left = things, right = what they point at. Wheel to zoom · "
    "drag a node to move it · click a node to highlight its edges.":
        "列是跟着边排的：左边是“事物”，右边是它们指向的东西。滚轮缩放 · 拖动节点移动 · 点节点高亮它的边。",
    # ---- step 1
    "Step 1 — one object, plain SQL": "步骤 1 —— 一个对象，最普通的 SQL",
    "step 1 — rev object-first": "步骤 1 —— rev 对象优先",
    "The object: Customer": "对象：Customer",
    "object type — label, where it is stored, its key": "对象类型 —— 名字、存在哪里、主键是什么",
    "stored in": "存储于",
    "(one row per customer)": "（每个客户一行）",
    "properties — the columns that become them": "属性 —— 这些列变成它的属性",
    "instances — the rows are objects, not just rows": "实例 —— 每一行就是一个对象，不只是行",
    "One object type, one table. Each row": "一个对象类型，一张表。每一行",
    "a customer — an object with identity (": "就是一个客户 —— 一个有身份（",
    ") and properties (": "）、有属性（",
    "). The table is only where those objects are stored; from here on we talk about the "
    "objects.": "）的对象。表只是这些对象存放的地方；从这里开始，我们谈的是对象。",
    "schema — the columns": "结构 —— 有哪些列",
    "data — the rows": "数据 —— 有哪些行",
    "column": "列",
    "type": "类型",
    "meaning": "含义",
    "Every customer is one row; every column is one property. This is the whole structure — no "
    "definitions, no rules, just rows.": "每个客户就是一行，每一列就是一个属性。结构到此为止 —— 没有定义、没有规则，只有行。",
    "Ask a question": "提一个问题",
    "Ask (runs a fixed SQL statement)": "提问（执行一条固定的 SQL）",
    "No model on this page: each question maps to one hard-coded SQL statement. The point of "
    "step 1 is to make “question → SQL → rows” visible before any ontology is introduced.":
        "这一页没有任何模型：每个问题对应一条写死的 SQL。第 1 步的目的，是先让“问题 → SQL → 行”这条链路可见，"
        "再谈本体。",
    "primary key": "主键",
    "the customer's name": "客户的名字",
    "PREMIUM or STANDARD": "PREMIUM 或 STANDARD",
    "FK → customers.id (this is the link)": "外键 → customers.id（这就是那把连接）",
    "order value": "订单金额",
    "when it happened": "发生时间",
    # ---- step 2
    "Step 2 — two objects and a link": "步骤 2 —— 两个对象和一个连接",
    "step 2 — rev object-first": "步骤 2 —— rev 对象优先",
    "Object 1: Order": "对象 1：Order（订单）",
    "Object 2: Customer": "对象 2：Customer（客户）",
    "Table 1: orders": "表 1：orders（订单）",
    "Table 2: customers": "表 2：customers（客户）",
    "integer": "整数",
    "text": "文本",
    "numeric": "数值",
    "timestamptz": "时间戳",
    "The red column": "红色的那一列",
    "holds a value from the": "的值来自",
    "column. That single fact is the link between the tables — a": "这一列。就是这一条事实把两张表连起来 —— 一个",
    "foreign key": "外键",
    "column. In SQL that is a": "这一列。在 SQL 里那是一个",
    "; in the ontology it is a": "；在本体里它是一个",
    "link": "连接",
    "— and the join below is only how the link gets walked.":
        "—— 而下面的 JOIN 只是把这个连接走一遍的方式。",
    "this query walks the link (a JOIN)": "这条查询在走那个连接（一个 JOIN）",
    "one object, no link": "只有一个对象，没有连接",
    "Ask (runs one fixed SQL statement)": "提问（执行一条固定的 SQL）",
    "Same rule as step 1: every question maps to one hard-coded statement — first over":
        "规则和第 1 步一样：每个问题都对应一条写死的语句 —— 先在",
    "one table": "一张表",
    ", then with a": "上做，然后加",
    ". The video case: Dana is PREMIUM — in SQL that is a value in the": "。视频里的例子：Dana 是 PREMIUM —— 在 SQL 里就是",
    "column, used in a": "列里的一个值，用在",
    # ---- step 3
    "Step 3 — an initial ontology (concepts + actions)": "步骤 3 —— 第一版本体（概念 + 动作）",
    "Step 3 — an initial ontology: concepts + actions": "步骤 3 —— 第一版本体：概念 + 动作",
    "step 3 · reasoning — rev split-3/4": "步骤 3 · 推理 —— rev split-3/4",
    "The ontology: object types": "本体：对象类型",
    "Same tables as steps 1–2, now declared as": "还是第 1、2 步那两张表，现在声明成",
    "object types": "对象类型",
    "with typed properties. Red = written only by actions (": "带有类型的属性。红色 = 只由动作写入（",
    "Live data — stored object types": "实时数据 —— 实际存储的对象类型",
    "stored as": "存储为",
    "Each row is stored under ONE object type, decided by its": "每一行只按一种对象类型存储，由它的",
    "value: a STANDARD row is a": "值决定：STANDARD 的行是",
    "; a PREMIUM row is a": "；PREMIUM 的行是",
    ". That a PremiumCustomer is ALSO a Customer is the": "。而 PremiumCustomer 同时也是 Customer，这是",
    "fact — see step 5.": "出来的事实 —— 看第 5 步。",
    "The definition (a class, not a table)": "定义（一个类，不是一张表）",
    "loading …": "加载中 …",
    "defined class": "被定义的类",
    "has no rows of its own: membership is derived from this axiom. The read path compiles it "
    "to a WHERE predicate.": "没有属于自己的行：成员身份由这条公理推出来。读取路径把它编译成一个 WHERE 谓词。",
    "What is NOT shown here yet": "这里还没显示什么",
    "The data below says Dana's": "下面的数据只说 Dana 的",
    "is PREMIUM — it does": "是 PREMIUM —— 它",
    "say “Dana is a Customer”. That extra fact is a": "说“Dana 是一个 Customer”。多出来的那条事实是一个",
    "reasoning result": "推理结果",
    "and belongs to step 5; here we only look at what is stored.":
        "它属于第 5 步；这里只看实际存了什么。",
    "not": "没",
    "Ask the ontology": "向本体提问",
    "Ask (compiled ontology query)": "提问（编译后的本体查询）",
    "the definition behind the answer": "答案背后的定义",
    "No joins yet: each question reads ONE object type. The difference from steps 1–2: the":
        "还没有 JOIN：每个问题只读一种对象类型。和第 1、2 步的区别在于：",
    "predicate for “premium customers” is": "“premium customers”的谓词是",
    "compiled from the ontology axiom": "从本体公理编译出来的",
    ", not typed into the query.": "而不是手写进查询里的。",
    # ---- step 4
    "Step 4 — an action type: validated, audited writes": "步骤 4 —— 一个动作类型：校验过、留审计的写入",
    "step 4 · actions — rev split-3/4": "步骤 4 · 动作 —— rev split-3/4",
    "The action type: PromoteCustomer": "动作类型：PromoteCustomer",
    "Declared in": "声明在",
    ": parameters, preconditions, effect, permission, audit.": "：参数、前置条件、效果、权限、审计。",
    "compiles the guard and the effect, then runs ONE transaction: lock the row → check → "
    "write → audit.": "把守卫和效果编译出来，然后跑一个事务：锁行 → 校验 → 写入 → 审计。",
    "target customer id": "目标客户 id",
    "Dry-run (check only)": "预演（只校验）",
    "Run for real (audited)": "真跑（留审计）",
    "Reset (demote)": "重置（降级）",
    "A promote MOVES a row from": "promote 把一行从",
    "to": "搬到",
    "— the write changes which stored type the row belongs to. That it is still a Customer "
    "after the move is derived (step 5).": "—— 这次写入改变的是这一行属于哪种存储类型。搬完之后它仍然是 Customer，"
        "那是推导出来的（第 5 步）。",
    "Audit trail (latest 6)": "审计轨迹（最近 6 条）",
    "action": "动作",
    "actor": "操作者",
    "before → after": "写入前 → 写入后",
    "when": "时间",
    "Every write is recorded: who, when, parameters, before/after rows and the compiled "
    "statements (": "每次写入都有记录：谁、什么时候、参数、前后两行，以及编译出来的语句（",
    ", append-only). A REFUSED action writes nothing and leaves no audit row.":
        "，只追加）。被 REFUSED 的动作什么都不写，也不留审计行。",
    "The story continues": "故事继续",
    "What you just wrote is a membership fact. Step 5 takes that single write and shows what the":
        "你刚刚写下的是一条成员资格事实。第 5 步就拿这一次写入，看看",
    "reasoner": "推理器",
    "derives from it: the customer becomes a": "从中推出什么：这个客户变成了",
    "— a triple nobody stored.": "—— 一条没人存过的三元组。",
    "Continue to step 5 →": "继续第 5 步 →",
    "Why not just UPDATE?": "为什么不能直接 UPDATE？",
    "is the contract: the effect may only touch properties marked": "就是契约：效果只能碰标记为",
    "; preconditions are compiled, not trusted; the write and the audit are one transaction. "
    "Try promoting a customer who is already PREMIUM — the guard refuses and":
        "的属性；前置条件是编译出来的、不是信任来的；写入和审计在同一个事务里。"
        "试试提升一个已经是 PREMIUM 的客户 —— 守卫会拒绝，",
    "nothing changes": "什么都不变",
    # ---- step 5
    "Step 5 — premium is a definition, not a column": "步骤 5 —— premium 是一个定义，不是某一列",
    "What is stored": "实际存了什么",
    "Only customers and what they did. There is": "只有客户，以及他们做过的事。这里",
    "no premium column": "根本没有 premium 这一列",
    "— “premium” is not a fact anybody recorded.": "——“premium”不是任何人记录下来的事实。",
    "order": "订单",
    "customer": "客户",
    "amount": "金额",
    "Dana's order is 500. Bob 250, Chen 99.50, Amara 120. The rule will say only Dana "
    "qualifies.": "Dana 的订单是 500，Bob 250、Chen 99.50、Amara 120。规则会说只有 Dana 够格。",
    "The definition (TTL)": "定义（TTL）",
    "The threshold": "阈值",
    "lives here, in the ontology — it is not typed into any SQL statement.":
        "就住在这里、住在本体里 —— 它没有被敲进任何一条 SQL。",
    "Compile the definition to SQL (lane A)": "把定义编译成 SQL（通道 A）",
    "premium gate · amount ≥": "premium 门槛 · 金额 ≥",
    "Compile &amp; run": "编译并执行",
    "Compile & run": "编译并执行",
    "The gate is a parameter of the DEFINITION. Changing it rewrites the axiom's facet and "
    "recompiles — the number is never typed into SQL by hand. Try 300 (adds Bob) or 900 "
    "(nobody qualifies).": "门槛是“定义”的参数。改它等于改公理里的约束，然后重新编译 —— 这个数字从来不用手写进 SQL。"
        "试试 300（会把 Bob 也算进来）或 900（没人够格）。",
    "result": "结果",
    "The compiler turns the axiom into a correlated EXISTS:": "编译器把公理变成相关子查询 EXISTS：",
    "customers": "客户表",
    "joined to": "连到",
    "orders": "订单表",
    "by the declared FK, with": "用的是声明的外键，条件是",
    ". The runtime answer is plain SQL — no reasoner on the request path.":
        "。运行期算出来的就是普通 SQL —— 请求路径上没有任何推理机。",
    "HermiT is a": "HermiT 是一个",
    "design-time": "设计期",
    "tool: it validates that this definition is consistent and classifies sample instances; "
    "the same definition is then compiled for execution. This axiom is outside OWL 2 QL, so "
    "lane B (Ontop) would silently drop it — which is exactly why the compiled lane owns the "
    "answer.": "工具：它校验这个定义是否一致，并对样本实例做分类；同一个定义随后被编译用于执行。"
        "这条公理在 OWL 2 QL 之外，所以通道 B（Ontop）会把它悄悄丢掉 —— 这正是答案归编译通道的原因。",
    # ---- step 6
    "Step 6 — metrics: definitions that compile to numbers": "步骤 6 —— 指标：编译成数字的定义",
    "time window: revenue of the last": "时间窗口：最近",
    "days": "天的收入",
    "Apply window": "应用窗口",
    "This window feeds": "这个窗口只喂给",
    "metric,": "个指标，",
    ": its": "：它的",
    "is the defined class": "是那个被定义的类",
    ", i.e.": "，也就是",
    ". The other cards ignore it — they are all orders, all customers, all time. The last card "
    "is a": "。其他卡片完全不受它影响 —— 它们都是全部订单、全部客户、全部时间。最后一张卡是一个",
    "ratio across two grains": "跨粒度的比值",
    "), not a formula.": "），而不是一个公式。",
    "Ask for a metric": "为一个指标提问",
    "e.g. revenue from premium customers": "例如：premium 客户的收入",
    "Ask (definition → SQL → number)": "提问（定义 → SQL → 数字）",
    "the definition that produced this number": "产生这个数字的定义",
    "window set by the question:": "窗口由问题决定：",
    "key": "键",
    "value": "值",
    "not one of the cards above — declared in the wider ontology":
        "不在上面那批卡片里 —— 它声明在更完整的本体中",
    "this page can answer about:": "这一页能回答的有：",
    "asking …": "正在提问 …",
    "request failed:": "请求失败：",
    "edit definition": "改定义",
    "Recompile &amp; run": "重新编译并执行",
    "Recompile & run": "重新编译并执行",
    "refused:": "已拒绝：",
    # ---- step 7 (products)
    "Step 7 — a new object: Product, and the link that carries data":
        "步骤 7 —— 一个新的对象：Product，以及带着数据的那个链接",
    "step 7 · a new object — rev split-3/4": "步骤 7 · 新对象 —— rev split-3/4",
    "The new object: Product": "新对象：Product",
    "an object type — label, physical table, key, properties": "一个对象类型 —— 名字、物理表、主键、属性",
    "object type": "对象类型",
    "stored in": "存储于",
    "products — the columns that become its properties": "products —— 这些列成为它的属性",
    "This is the step's actual news: a new": "这一步真正的新东西是：一个",
    ", not a new table. A table is where an object is stored; the object is":
        "，而不是一张新表。表只是对象存放的地方；对象是",
    "— something that exists in the business, has an identity (": "—— 它在业务里真实存在，有身份（",
    ") and properties (": "），也有属性（",
    "), and can be counted, grouped and joined on.": "），可以被计数、分组、被连接。",
    "The link: an order contains products": "连接：一个订单里有产品",
    "a many-to-many link — and it carries data of its own": "一个多对多的连接 —— 而且它自己带着数据",
    "link": "连接",
    "cardinality": "基数",
    "many-to-many (one order, many products; one product, many orders)":
        "多对多（一个订单有多个产品；一个产品出现在多个订单里）",
    "carries": "带着",
    "— how many of that product": "—— 这个产品买了几个",
    "(one row per order–product pair)": "（每个“订单–产品”组合一行）",
    "order_lines — where that link is physically kept": "order_lines —— 这个连接在物理上存放在这里",
    "One foreign key cannot express this: it would give an order a single product. So the link "
    "itself needs a row — two FKs that name the two ends, plus the quantity the link carries.":
        "一条外键表达不了这件事：那等于给一个订单只配一个产品。所以连接本身需要一行 —— "
        "两条外键指明两端，再加上连接自己携带的数量。",
    "So is the link an object?": "那么这个连接算对象吗？",
    "In the": "在",
    "business": "业务",
    "sense, no: nobody asks for “the order line with id 4”. It is a":
        "意义上，不算：没人会问“id 为 4 的那条订单行”。它是一个",
    "— the connection between an order and a product — that happens to carry a number.":
        "—— 订单与产品之间的连接 —— 只是刚好带了一个数字。",
    "our TTL": "我们的 TTL",
    "it is declared as a class (": "里它被声明成一个类（",
    "), because OWL object properties are binary and cannot carry attributes: the only way to hang":
        "），因为 OWL 的对象属性是二元的、不能携带属性：想给关系挂上",
    "on the relationship is to promote the relationship to something that has identity. That "
    "promotion is called": "，唯一的办法就是把关系提升成一个有身份的东西。这种提升叫",
    "reification": "具体化（reification）",
    ", and it is a modelling choice with a price and a benefit:":
        "，它是一个有代价也有好处的建模选择：",
    "cost": "代价",
    "— the link becomes a thing you can group by, so “revenue by product” is really revenue per "
    "line, and a wrong join can fan out rows;":
        "—— 连接变成了可以被分组的东西，所以“按产品拆分收入”其实是按行拆；而一个写错的连接会把行数放大；",
    "benefit": "好处",
    "— the compiler only needs the same two declared edges it already understands, and":
        "—— 编译器只需要它本来就懂的那两条声明边，而且",
    "is reachable without special cases.": "不需要任何特例就能取到。",
    "The alternative — a plain many-to-many link type with no data of its own — needs no class at "
    "all: just the two ends and the join path through the table. Our TTL pays for reification "
    "because this link": "另一条路 —— 一个不带自带数据的纯多对多连接 —— 根本不需要类：只有两端，"
        "加上穿过那张表的连接路径。我们的 TTL 之所以付出具体化的代价，是因为这个连接",
    "does": "确实",
    "carry data.": "带着数据。",
    "The reification is visible in the TTL:": "具体化在 TTL 里看得见：",
    "is a class with its own table, and the two": "是一个带自己表的类，而两条",
    "are the declared edges the compiler walks. Before it can join anything it needs exactly those:":
        "就是编译器要走过的声明边。在它连接任何东西之前，需要的正是这两条：",
    "and": "和",
    ". No column name is guessed and no join path is hard-coded in SQL — the compiler walks the "
    "declarations.": "。没有一个列名是猜的，也没有一条连接路径写死在 SQL 里 —— 编译器沿着声明走。",
    "The ontology says": "本体里怎么写",
    "Two declared relationships are all the compiler needs:":
        "编译器需要的只是两条声明出来的关系：",
    "No column name is guessed and no join path is hard-coded in SQL — the compiler walks the "
    "declarations.": "没有一个列名是猜的，也没有一条连接路径是写死在 SQL 里的 —— 编译器沿着声明走。",
    "Why it takes three or four tables": "为什么是三张表或四张表",
    "One extra hop per extra concept: products add": "多一个概念就多一跳：产品带来",
    "; adding the store's city makes it four tables; adding “only premium customers” makes the "
    "customers table join too. The number of joins is the number of declared edges on the path — "
    "never a guess.": "；再加上门店的城市就变成四张表；再加“只要 premium 客户”就把 customers 表也连进来。"
        "JOIN 的数量就是这条路径上声明的边的数量 —— 从来不是猜的。",
    "Same pipeline as the metrics step and as":
        "和指标那一步、以及",
    ": the question may only resolve to a declared metric, and the rows above are that metric's "
    "own compiled SQL. Note the": "走的是同一条流水线：问题只能落到已声明的指标上，上面的行就是那个指标自己编译出的 SQL。注意",
    "on the product metrics — they count per link row (per product in an order), which is exactly "
    "what the reification above bought.": "—— 产品指标是按连接行（一个订单里的一个产品）计的，"
        "这正是上面那次具体化换来的东西。",
    "A new object: Product": "新对象：Product",
    "a many-to-many link that carries qty; three- and four-table compiles":
        "一个携带 qty 的多对多连接；三表、四表的编译",
    "A new object: Store": "新对象：Store",
    "a many-to-one link with no data; a dimension, not a measurement":
        "一个不带数据的多对一连接；是维度，不是度量",
    "One extra hop per extra concept: products add": "多一个概念就多一跳：产品带来",
    "; adding the store's city makes it four tables; adding “only premium customers” makes the "
    "customers table join too. The number of joins is the number of declared edges on the path — "
    "never a guess.": "；再加上门店的城市就变成四张表；再加“只要 premium 客户”就把 customers 表也连进来。"
        "JOIN 的数量就是这条路径上声明的边的数量 —— 从来不是猜的。",
    "Metrics that only exist because products joined":
        "只有产品进来之后才存在的指标",
    "Ask about products": "就产品提问",
    "e.g. revenue by product": "例如：按产品拆分收入",
    "Ask (definition → SQL → rows)": "提问（定义 → SQL → 行）",
    "revenue by product": "按产品拆分收入",
    "premium product revenue": "premium 产品收入",
    "premium revenue by product": "按产品拆分的 premium 收入",
    "product revenue": "产品收入",
    "Same pipeline as the metrics step and as":
        "和指标那一步、以及",
    ": the question may only resolve to a declared metric, and the rows above are that metric's "
    "own compiled SQL.": "走的是同一条流水线：问题只能落到已声明的指标上，上面的行就是那个指标自己编译出的 SQL。",
    "the definition that produced this answer": "产生这个答案的定义",
    "tables:": "涉及的表：",
    "in the FROM/JOIN": "出现在 FROM/JOIN 里",
    "asking …": "正在提问 …",
    "answer source:": "答案来源：",
    # ---- step 8 (store / dimension)
    "Step 8 — a new object: Store, and a link that needs no table":
        "步骤 8 —— 一个新的对象：Store，以及一条不需要新表的连接",
    "step 8 · a new object — rev split-3/4": "步骤 8 · 新对象 —— rev split-3/4",
    "The new object: Store": "新对象：Store",
    "stores — the columns that become its properties": "stores —— 这些列成为它的属性",
    "A second object, but of a different kind: nothing": "又是一个对象，但性质不同：没有任何东西",
    "a store in a report — a store is something orders are": "在报表里是门店 —— 门店是订单被",
    "attributed to": "归属到的东西",
    ". It has no measure at all, only the dimension every city metric groups by.":
        "。它自己完全没有度量，只是一个维度 —— 所有按城市拆的指标都拿它分组。",
    "The link: an order was sold at a store": "连接：一单在某个门店卖出",
    "a many-to-one link — so a column is enough": "多对一的连接 —— 所以一个列就够了",
    "cardinality": "基数",
    "many-to-one (many orders per store, one store per order)":
        "多对一（一家门店有多张订单，一张订单只属于一家门店）",
    "nothing — the link has no data of its own": "什么都没有 —— 这条连接本身不带数据",
    "(one FK, no extra table)": "（一条外键，不需要额外的表）",
    "Compare with step 7: a many-to-many link that carried": "和第 7 步对比：一条携带",
    "needed a table of its own (reification). This link is many-to-one and carries nothing, so a "
    "single foreign key on the order row is enough —":
        "的多对多连接需要自己的表（具体化）。而这条连接是多对一、又不带数据，所以订单行上一条外键就够 ——",
    "cardinality and payload decide the storage shape": "基数和载荷决定存储形态",
    ", not habit.": "，而不是习惯。",
    "A dimension, not a measurement": "是维度，不是度量",
    "The numbers above are sums of orders. The": "上面的数字都是订单的求和。每个和旁边的",
    "next to each sum is never summed — it is the key the metric groups by, and it lives on "
    "another object. That is the whole job of a dimension: it divides a measure, it never adds "
    "to one.": "从来不会被求和 —— 它是指标用来分组的键，而且长在另一个对象上。"
        "维度的全部职责就是这个：它切分度量，从不累加度量。",
    "Which is why “revenue by store” is": "这也是为什么“按门店拆分收入”",
    "not": "并不",
    "a declared metric: a store has no name property to group on here, only a city. The ontology "
    "says what can be a key, and the query layer refuses the rest by name.":
        "是个已声明的指标：这里的门店没有可用来分组的名称属性，只有一个城市。"
        "本体规定了什么可以当键，其余的被查询层按名字拒绝。",
    "One declared edge is all this link needs:": "这条连接只需要一条声明边：",
    ", with": "，并带上",
    "naming the target. The metric then reads": "指明目标。指标随后读取",
    "off that object and groups by it — the compiler never guesses that":
        "并按它分组 —— 编译器从不猜",
    "is a store, it reads the declaration. Adding the premium filter rides on the same machinery:":
        "是不是门店，它读的是声明。加 premium 过滤用的是同一套机器：",
    "compiles to a": "编译成一个",
    "predicate, not to hand-written SQL.": "谓词，而不是手写 SQL。",
    "Where the key comes from": "键是从哪来的",
    "The FROM list grows by declared edges, not by hand: the group key adds":
        "FROM 列表是按声明边长的，不是手工加的：分组键带来",
    ", and the defined class": "，而被定义的类",
    "with its": "连同它的",
    "predicate compiled from the axiom. Two concepts, two joins, no guessing.":
        "谓词（从公理编译出来的）一起加进来。两个概念、两次连接，没有猜测。",
    "Ask about cities": "就城市提问",
    "Metrics whose key is a store's city": "键来自门店城市的指标",
    "on the product metrics — and (for": "—— 而且是按连接行计的；对",
    "pointing at the defined class from step 5 — a dimension and a definition in one metric.":
        "，它指向第 5 步那个被定义的类 —— 一个维度、一个定义，落在同一个指标里。",
    "e.g. revenue by city": "例如：按城市拆分收入",
    # ---- actions page
    "Actions — ontology app": "动作 —— 本体应用",
    "⚡ Lane C · Actions — declared writes": "⚡ 通道 C · 动作 —— 声明式写入",
    "⚖ compare lanes": "⚖ 对比两条通道",
    "Action types — compiled from schema/actions.yml against the same TTL as lanes A and B":
        "动作类型 —— 由 schema/actions.yml 对同一份 TTL（和通道 A、B 一样）编译而来",
    "This page is": "这一页是",
    "lane C": "通道 C",
    ": the only lane allowed to write. Lanes A (compiled SQL) and B (SPARQL/Ontop) are "
    "read-only, so every write that changes their data went through an action here.":
        "：唯一被允许写入的通道。通道 A（编译 SQL）和 B（SPARQL/Ontop）都是只读的，"
        "所以凡是改变它们数据的写入，都经过了这里的某个动作。",
    "name": "名称",
    "object": "对象",
    "parameters": "参数",
    "effect (compiled)": "效果（编译后）",
    "An effect may only write properties the ontology marks": "效果只能写本体标记为",
    ". Every run is one transaction: preconditions, write, and an append-only audit row.":
        "的属性。每次运行都是一个事务：前置条件、写入、一条只追加的审计行。",
    "Run an action": "运行一个动作",
    "parameters (JSON)": "参数（JSON）",
    "Run action": "运行动作",
    "Audit — append-only (latest first)": "审计 —— 只追加（新的在前）",
    "when": "时间",
    "params": "参数",
    # ---- backlog page
    "Declaration backlog — ontology app": "待声明清单 —— 本体应用",
    "▤ Declaration backlog — what to declare next, from data":
        "▤ 待声明清单 —— 该声明什么，让数据说话",
    "Refusal telemetry": "拒绝遥测",
    "question": "问题",
    "last seen": "最近出现",
    "suggested declaration": "建议的声明",
    "Read-only. Nothing here changes the ontology — it is the evidence list a human uses to "
    "decide which shape to declare next. Answers that succeed are counted, not listed.":
        "只读。这里不会改动本体 —— 它是一份证据清单，供人决定下一步声明什么形状。"
        "成功回答的问题只计数、不列出。",
    # ---- query page
    "Query — natural language — ontology app": "查询 —— 自然语言 —— 本体应用",
    "✦ Query — natural language": "✦ 查询 —— 自然语言",
    "Question": "问题",
    "Ask": "提问",
    "The model only picks an entry from the compiled ontology (metric / class / action); it "
    "never writes SQL. Numbers come from the compiled SQL; actions are dry-run only until you "
    "confirm.": "模型只从编译好的本体里挑一项（指标 / 类 / 动作），从不写 SQL。"
        "数字来自编译出的 SQL；动作在你确认之前只是预演。",
    "Confirm": "确认",
    "What it can answer": "它能回答什么",
    "metrics:": "指标：",
    "classes:": "类：",
    "llm:": "模型：",
    "actions (dry-run): PromoteCustomer · DemoteCustomer · RecordOrder":
        "动作（预演）：PromoteCustomer · DemoteCustomer · RecordOrder",
    "Unknown questions are refused by name — no free SQL, no guessed numbers.":
        "答不上来的问题会按名字拒绝 —— 不写自由 SQL，也不猜数字。",
    # ---- reasoner page
    "Reasoner — ontology app": "推理器 —— 本体应用",
    "⌨ Reasoner — SPARQL · HermiT · guard dry-run": "⌨ 推理器 —— SPARQL · HermiT · 守卫预演",
    "SPARQL — lane B (Ontop over the virtual RDF graph)": "SPARQL —— 通道 B（Ontop 跑在虚拟 RDF 图上）",
    "Run SPARQL (lane B)": "运行 SPARQL（通道 B）",
    "Run HermiT demo (lane beyond QL)": "运行 HermiT 演示（QL 之外的通道）",
    "The map search on the main page only filters words. This box runs real queries: lane B "
    "answers `Customer` even though the data never stored it — subclass entailment inside "
    "OWL 2 QL. The HermiT demo shows the answer that only a DL reasoner can produce "
    "(owl:hasValue).": "主页上的搜索框只是过滤文字。这个盒子跑的是真查询：通道 B 能答出 `Customer`，"
        "尽管数据从来没存过它 —— 这是 OWL 2 QL 内部的子类蕴含。"
        "HermiT 演示展示的是只有 DL 推理机能给出的答案（owl:hasValue）。",
    "Lane C guard — would this action be admitted? (dry-run, no write)":
        "通道 C 守卫 —— 这个动作会被接受吗？（预演，不写入）",
    "PromoteCustomer's guard is": "PromoteCustomer 的守卫是",
    "compiled from the :PremiumCustomer axiom": "从 :PremiumCustomer 公理编译出来的",
    "— the same definition lane A/B use. This runs the compiled preconditions in a transaction "
    "that is always rolled back, so it answers “admitted or refused, and why” without writing "
    "and without an audit row.": "—— 和通道 A、B 用的是同一个定义。它在一个总是回滚的事务里跑编译好的前置条件，"
        "所以能回答“接受还是拒绝、为什么”，既没有写入，也不产生审计行。",
    "Check guard (no write)": "检查守卫（不写入）",
    "Run it for real (writes + audits)": "真跑（写入 + 审计）",
    "What to expect": "会看到什么",
    "— entailed, never stored.": "—— 蕴含出来的，从来没存过。",
    "→ 4 rows (includes the 2 PremiumCustomers).": "→ 4 行（含 2 个 PremiumCustomer）。",
    "→ Dana Okafor, Chen Hong.": "→ Dana Okafor、Chen Hong。",
    "HermiT demo: before-reasoning query is empty, after-reasoning it lists customer_1 and "
    "customer_3 — the fact derived from": "HermiT 演示：推理前的查询是空的，推理后列出 customer_1 和 customer_3 —— 这事实来自",
    ", which Ontop cannot rewrite (not OWL 2 QL).": "，Ontop 无法改写成 SQL（不在 OWL 2 QL 内）。",
    "Guard dry-run:": "守卫预演：",
    "on customer 2 → ADMITTED, with the parameters BOUND (": "作用于客户 2 → ADMITTED，参数已绑定（",
    ") and the target row shown as": "），目标行显示为",
    "; on customer 1 → REFUSED and the failing check names the axiom. Nothing is written, no "
    "audit row appears — the dry-run is the read of what the write would do. The":
        "；作用于客户 1 → REFUSED，失败的那项检查会点名公理。什么都没写，也没有审计行 —— "
        "预演就是“读一次写入会做什么”。",
    "button executes the same params through lane C: one transaction, an audit row, and the "
    "guard is re-checked on the same target so you watch it flip to REFUSED.":
        "按钮用同一组参数走通道 C：一个事务、一条审计行，并在同一目标上重新校验守卫，"
        "于是你能看着它翻成 REFUSED。",
    # ---- home page (generated by graph_view.py)
    "Retail ontology — graph and documentation from the TTL": "零售本体 —— 从 TTL 生成的关系图与文档",
    "Entities": "实体",
    "classes": "类",
    "defined": "被定义",
    "properties": "属性",
    "fit": "适配",
    "■ blue = measured in Postgres": "■ 蓝色 = 在 Postgres 里实测过",
    "both": "两者",
    "click an entity ·": "点一个实体 ·",
    "hides everything else · drag nodes · wheel to zoom · pan with arrows · keys + − 0 ← ↑ ↓ "
    "→ d r b": "其余全部隐藏 · 拖动节点 · 滚轮缩放 · 方向键平移 · 按键 + − 0 ← ↑ ↓ → d r b",
    "Retail ontology": "零售本体",
    "Pick a": "在左边或图里挑一个",
    "class or a": "或一个",
    "datatype property on the left or in the graph. This pane is its documentation, generated "
    "from the": "（数据类型属性）。这一栏是它的文档，从",
    ", using the same terms as": "生成，用的术语和",
    ": Description, Equivalent Class, Annotation Properties, Axioms, IRI. The":
        "一致：描述、等价类、注解属性、公理、IRI。",
    "lists are what that page calls": "这两个列表，就是那一页说的",
    "Numbers were measured when this file was written.": "数字是这份文件生成时实测的。",
    "domain": "定义域",
    "range": "值域",
    # ---- compare page
    "Compare lanes — ontology app": "对比两条通道 —— 本体应用",
    "⚖ Two approaches, one question": "⚖ 两种做法，同一个问题",
    "✓ match": "✓ 一致",
    "✗ mismatch": "✗ 不一致",
    "not served by the mapping": "映射里没有覆盖",
    "open the app (lane A view)": "打开应用（通道 A 视图）",
    "open the reasoner": "打开推理器",
    "verdict": "结论",
    "Lane A compiles the TTL axiom into SQL once (": "通道 A 把 TTL 公理一次性编译成 SQL（",
    ") and runs it on the source database. Lane B asks SPARQL against":
        "），直接在源库上执行。通道 B 对着",
    "(Ontop: virtual RDF graph + R2RML mapping, OWL 2 QL entailment).":
        "（Ontop：虚拟 RDF 图 + R2RML 映射，OWL 2 QL 蕴含）发 SPARQL。",
    "Both lanes read the same rows and neither materializes a copy: an UPDATE on the source "
    "table changes both answers on the next query. Beyond OWL 2 QL (e.g. ":
        "两条通道读的是同一批行，谁都不落副本：在源表上做一次 UPDATE，下一次查询两边的答案都会变。"
        "超出 OWL 2 QL 的部分（例如 ",
    ") lane B cannot answer at all — the setting": "）通道 B 根本答不了 —— 设置里的",
    "records which projection the app is currently on.": "记录了应用当前在哪个投影上。",
    # ---- reasoner leftovers
    "Run it for real": "真跑",
    # ---- design page (architecture.svg labels)
    "retail_graph — ontology architecture": "retail_graph —— 本体架构",
    "one TTL model + one actions.yml · three compiled lanes · a rules-first NL layer · every "
    "promise has a gate": "一个 TTL 模型 + 一个 actions.yml · 三条编译通道 · 一层规则优先的自然语言层 · "
        "每个承诺都有一道闸",
    "legend": "图例",
    "read lane": "只读通道",
    "write lane": "写入通道",
    "slot": "槽位",
    "question (zh / en)": "问题（中文 / 英文）",
    "NL layer · nl.py": "自然语言层 · nl.py",
    "① rules first: tokens, aliases, verbs (≈ 0 ms)": "① 先走规则：词元、别名、动词（≈ 0 毫秒）",
    "② LLM only if unsure: DeepSeek / Ollama": "② 只在不确定时才用模型：DeepSeek / Ollama",
    "returns {kind, name, slots} — never SQL": "返回 {kind, name, slots} —— 从不返回 SQL",
    "name on menu · param types": "名字必须在菜单上 · 参数类型",
    "capability graph · capability.resolve": "能力图 · capability.resolve",
    "nodes: metric · class · action · slot": "节点：指标 · 类 · 动作 · 槽位",
    "edges: measures / filters / physicalTable": "边：measures / filters / physicalTable",
    "path exists? · slot edge exists? · else refuse BY NAME":
        "路径存在吗？· 槽位边存在吗？· 否则按名字拒绝",
    "sqlgen.py — compiles the TTL": "sqlgen.py —— 编译 TTL",
    "concept_sql : axiom → WHERE predicate": "concept_sql：公理 → WHERE 谓词",
    "compile_metric : :aggregate/:grain/:universe/:where → SELECT":
        "compile_metric：:aggregate/:grain/:universe/:where → SELECT",
    "class_assignment : axiom → UPDATE assignment (writes)":
        "class_assignment：公理 → UPDATE 归属（写入）",
    "relationship : declared FK + :references → JOIN": "relationship：声明的外键 + :references → JOIN",
    "actions.py — compiles actions.yml": "actions.py —— 编译 actions.yml",
    "preconditions : exists | class | state | params → SELECT …":
        "前置条件：exists | class | state | params → SELECT …",
    "effect : class | property | create → UPDATE/INSERT …":
        "效果：class | property | create → UPDATE/INSERT …",
    "run_action : FOR UPDATE → checks → effect → audit → COMMIT":
        "run_action：FOR UPDATE → 校验 → 生效 → 审计 → COMMIT",
    "check_action : same steps, always rolled back (dry-run)":
        "check_action：同样的步骤，但总是回滚（预演）",
    "classes · metrics · joins · refusals": "类 · 指标 · 连接 · 拒绝",
    "R2RML mapping → virtual RDF graph": "R2RML 映射 → 虚拟 RDF 图",
    "OWL 2 QL rewrite → SQL": "OWL 2 QL 重写 → SQL",
    "one transaction · audit row": "一个事务 · 一条审计行",
    "action-owned state only": "只改由动作管辖的状态",
    "virtual ABox": "虚拟 ABox",
    "SPARQL endpoint": "SPARQL 端点",
    "value + compiled SQL": "数值 + 编译出的 SQL",
    "steps[] with per-step ms": "steps[]，每步耗时毫秒",
    "confirm echo for complex": "复杂问题带确认回显",

    "The pages as they were written.": "页面按英文原文显示。",
    # ---- tutorial rail and graph (built in JavaScript)
    "Steps": "步骤",
    "One object, plain SQL": "一个对象，最普通的 SQL",
    "customers only; every row is a :Customer object":
        "只有 customers；每一行就是一个 :Customer 对象",
    "Two objects and a link": "两个对象和一个连接",
    "orders + customers; the red FK is the link, the JOIN walks it":
        "orders + customers；红色的外键就是连接，JOIN 只是把它走一遍",
    "An ontology and a definition": "一个本体和一个定义",
    "object types + the definition that compiles to WHERE":
        "对象类型 + 能编译成 WHERE 的定义",
    "An action type": "一个动作类型",
    "declared write, preconditions, audit trail": "声明式写入、前置条件、审计轨迹",
    "Premium is a definition": "premium 是一个定义",
    "behaviour axiom → compiled EXISTS; change the gate":
        "行为公理 → 编译成 EXISTS；改个门槛试试",
    "Metrics": "指标",
    "definition → SQL: aggregates, ratios, windows; edit and recompile":
        "定义 → SQL：聚合、比值、时间窗；可改可重编译",
    "Products — a third table": "产品 —— 第三张表",
    "an association class, three- and four-table joins, grouped by two keys":
        "一个关联类、三表和四表的连接、按两个键分组",
    "Each step is a live page: type a question, run an action, change a gate — the answer comes "
    "from the same customers and orders.": "每一步都是活页面：提个问题、跑个动作、改个门槛 —— "
        "答案都来自同一批客户和订单。",
    "Objects & lineage": "对象与血缘",
    "graph unavailable": "图不可用",
    # ---- reasoner example labels (the query itself stays English: it is the input)
    "ASK Dana is a Customer (entailed)": "ASK：Dana 是 Customer 吗（蕴含成立）",
    "who is a Customer (4)": "谁 Customer（4 个）",
    "PremiumCustomers with names": "PremiumCustomer 及名字",
    "classes the endpoint serves": "端点提供哪些类",
    "Architecture — ontology app": "架构 —— 本体应用",
    "· generated by make_architecture_svg.py · the full text is in ARCHITECTURE.md":
        "· 由 make_architecture_svg.py 生成 · 完整文字在 ARCHITECTURE.md",
    "lane A · compiled SQL": "通道 A · 编译成 SQL",
    "aggregate metrics are lane A only: the demo endpoint's R2RML mapping covers customers, "
    "not orders — a gap in the mapping, not in reasoning":
        "聚合指标只有通道 A 能算：演示端点的 R2RML 映射覆盖了 customers，没覆盖 orders —— "
        "这是映射上的缺口，不是推理上的。",
    "Both lanes read the same rows and neither materializes a copy: an UPDATE on the source "
    "table changes both answers on the next query. Beyond OWL 2 QL (e.g. ":
        "两条通道读同一批行，谁都不落副本：在源表上做一次 UPDATE，下一次查询两边的答案都会变。超出 OWL 2 QL 的部分（例如 ",
    ") lane B cannot answer at all — the setting":
        "）通道 B 根本答不了 —— 设置里的",
    "In Domain Of": "作为定义域出现在",
    "In Range Of": "作为值域出现在",
    "gates: check_actions G1–G6 + M1/M2 · check_metrics J1–J13 · check_mapping M1–M5 · "
    "check_nl N1–N15 · graph_view 9/9":
        "闸门：check_actions G1–G6 + M1/M2 · check_metrics J1–J13 · check_mapping M1–M5 · "
        "check_nl N1–N15 · graph_view 9/9",
}
PHRASES["zh"] = {_norm(k): v for k, v in _ZH.items()}   # one canonical spelling per key

# words that are already correct in any language (language names), so key == value on purpose
IDENTITY = {"English", "中文"}

# keys ending with ":" also match as a PREFIX, so dynamic lists built in JavaScript
# ("metrics: a · b · c") translate without enumerating every combination.
PREFIX_KEYS = {k for k in PHRASES["zh"] if k.endswith(":")}


# --------------------------------------------------------------------------- translate

TAG_RE = re.compile(r"(<[^>]*>)")   # captured, so re.split keeps the markup
ATTRS = ("placeholder", "title", "aria-label", "alt")
SKIP = {"script", "style", "pre", "code", "textarea"}


def lookup(text: str, lang: str) -> str | None:
    """Exact phrase first; then a key ending in ':' matches as a prefix (dynamic lists)."""
    table = PHRASES.get(lang, {})
    key = _norm(text)
    hit = table.get(key)
    if hit is not None:
        return hit
    for k in PREFIX_KEYS:
        if key.startswith(k):
            return table[k] + key[len(k):]
    return None


def tr(text: str, lang: str | None = None) -> str:
    """Translate one literal (used for text the server builds in Python)."""
    lang = lang or current()
    if lang == "en":
        return text
    hit = lookup(text, lang)
    return hit if hit is not None else text


def _text(token: str, lang: str) -> str:
    stripped = _norm(token)
    if not stripped:
        return token
    hit = lookup(stripped, lang)
    if hit is None:
        return token
    lead = token[: len(token) - len(token.lstrip())]
    trail = token[len(token.rstrip()):]
    return lead + hit + trail


def _tag(token: str, lang: str) -> str:
    def sub(m):
        attr, value = m.group(1), m.group(2)
        hit = lookup(value, lang)
        return f'{attr}="{hit}"' if hit else m.group(0)

    return re.sub(r'\b(' + "|".join(ATTRS) + r')="([^"]*)"', sub, token)


def tr_html(html: str, lang: str | None = None) -> str:
    """Translate every text node (and a few attributes) of a page — markup untouched."""
    lang = lang or current()
    if lang == "en":
        return html
    out = []
    depth = 0
    for token in TAG_RE.split(html):
        if not token:
            continue
        if token.startswith("<"):
            name = re.match(r"</?([A-Za-z][\w-]*)", token)
            name = name.group(1).lower() if name else ""
            closing = token.startswith("</")
            if closing:
                if name in SKIP and depth:
                    depth -= 1
            elif name in SKIP and not token.endswith("/>"):
                depth += 1
            out.append(token if depth else _tag(token, lang))
        else:
            out.append(token if depth else _text(token, lang))
    return "".join(out)


BOOTSTRAP = (
    '<script>window.__I18N_LANG=%s;</script>'
    '<script src="/i18n.js?v=1"></script>'
)


def render(html: str, lang: str | None = None) -> str:
    """Translate a page and give it the language it is rendered in."""
    lang = lang or current()
    html = tr_html(html, lang)
    html = re.sub(r'<html lang="[^"]*"', f'<html lang="{ "zh-CN" if lang == "zh" else "en" }"',
                  html, count=1)
    if lang != "en":
        boot = (BOOTSTRAP % json.dumps(lang)).encode().decode()
        html = html.replace("</body>", boot + "</body>", 1)
    return html


CLIENT_JS = r"""// Translate text that JavaScript adds after the fact (API rows, compiled cards).
// Same table as the server, so nothing has to be maintained twice.
(function () {
  const lang = window.__I18N_LANG || "en";
  if (lang === "en") return;
  const norm = s => String(s).replace(/\s+/g, " ").trim();
  const SKIP = new Set(["SCRIPT", "STYLE", "PRE", "CODE", "TEXTAREA"]);
  let table = {}, prefixes = [];

  function translateNode(node) {
    if (node.nodeType === 3) {
      const parent = node.parentNode;
      if (!parent || SKIP.has(parent.nodeName)) return;
      const raw = node.nodeValue;
      const key = norm(raw);
      if (!key) return;
      let hit = table[key];
      if (!hit) {
        const p = prefixes.find(k => key.startsWith(k));
        if (p) hit = table[p] + key.slice(p.length);
      }
      if (!hit) return;
      const lead = raw.match(/^\s*/)[0], trail = raw.match(/\s*$/)[0];
      node.nodeValue = lead + hit + trail;
      return;
    }
    if (node.nodeType !== 1 || SKIP.has(node.nodeName)) return;
    ["placeholder", "title", "aria-label", "alt"].forEach(a => {
      const v = node.getAttribute(a);
      if (v && table[norm(v)]) node.setAttribute(a, table[norm(v)]);
    });
    node.childNodes.forEach(translateNode);
  }

  fetch("/api/i18n?lang=" + lang).then(r => r.json()).then(j => {
    table = j.phrases || {};
    prefixes = Object.keys(table).filter(k => k.endsWith(":"));
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    if (document.body) translateNode(document.body);
    if (document.title) document.title = table[norm(document.title)] || document.title;
    new MutationObserver(list => list.forEach(m => m.addedNodes.forEach(translateNode)))
      .observe(document.body, { childList: true, subtree: true });
  }).catch(() => {});
})();
"""
