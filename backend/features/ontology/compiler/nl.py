#!/usr/bin/env python3
"""nl.py — natural-language interface over the compiled ontology (menu-constrained).

The LLM never writes SQL. It receives a MENU built from the compiled ontology
(metrics, classes, actions) and must return a structured intent that NAMES an entry.
The server then executes the compiled query through the existing lanes:

    metric  -> sqlgen.compile_metric(...).sql        (lane A, read)
    class   -> sqlgen.concept_sql(...)               (lane A, read)
    action  -> actions.check_action(...)             (lane C, DRY-RUN only)

Numbers come from SQL; the LLM only verbalizes. Anything not on the menu is refused
BY NAME, same rule as the rest of the track. Without DEEPSEEK_API_KEY the deterministic
keyword fallback runs instead, so the gates work offline.

Entry points:
    menu(graph) -> dict                    what the ontology can answer
    interpret(question, menu) -> intent    LLM or fallback, validated
    execute(intent, cur, graph) -> result  run the compiled query (read-only)
    answer(question, intent, result) -> str  LLM or template
    ask(question) -> dict                  end-to-end (used by /api/nl)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

import pathlib

import psycopg2
from rdflib import OWL, RDF, RDFS, URIRef

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import guard  # noqa: E402  (SQL guardrails: no unbounded page, no unbounded scan)

# the demo never needs hosted tracing; override (not setdefault) because an inherited
# LANGCHAIN_TRACING_V2=true would make every local run phone LangSmith and warn
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGSMITH_TRACING_V2"] = "false"   # langchain-core 1.x reads THIS one
os.environ["LANGCHAIN_TRACING"] = "false"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import actions  # noqa: E402
import capability  # noqa: E402
import sqlgen   # noqa: E402

P = sqlgen.P

MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://127.0.0.1:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")


class NlRefusal(Exception):
    """A result, not an error: the question or intent is outside the menu."""

    def __init__(self, message: str, polished: str | None = None):
        super().__init__(message)
        self.polished = polished or message


NL_DDL = """
CREATE TABLE IF NOT EXISTS nl_events (
    id           bigserial PRIMARY KEY,
    ts           timestamptz NOT NULL DEFAULT now(),
    question     text NOT NULL,
    ok           boolean NOT NULL,
    refused      text,
    refusal_kind text,
    intent       jsonb,
    backend      text
);
"""

REFUSAL_KINDS = (
    ("off_menu", ("not on the menu", "not on the capability graph", "no metric :",
                  "unknown action", "can answer about")),
    ("unsupported_slot", ("does not support the ", "slot (declared slots")),
    ("multi_dimension", ("no declared metric groups by",)),
    ("no_capability_path", ("reaches no physical table", "no declared relationship",
                            "declared but refused")),
    ("type_error", ("must be integer", "must be number", "must be string",
                    "must be boolean", "missing parameter")),
    ("ambiguous", ("ambiguous", "MORE THAN ONE")),
)


def _refusal_kind(message: str) -> str:
    low = (message or "").lower()
    if "slot (declared slots" in low or "does not support the " in low:
        return "unsupported_slot"
    if "no declared metric groups by" in low:
        return "multi_dimension"
    if "ambiguous" in low or "more than one" in low:
        return "ambiguous"
    for kind, needles in REFUSAL_KINDS:
        if any(n.lower() in low for n in needles):
            return kind
    return "other"


REFUSAL_RULES = """You are the ontology app's friendly explainer. The system could not
answer the user's question, and you must explain WHY in plain language.

- Write in the user's language (Chinese if the question is Chinese).
- State what could not be answered and name the missing piece from the reason.
- One or two sentences; no apologies, no "as an AI"; do not invent data or numbers.
- If the reason names available options (metrics/classes/actions), you may mention one or two."""


def _polish_refusal(question: str, reason: str) -> str:
    """Any result is polished — refusals too. Falls back to the raw reason."""
    llm = _llm()
    if llm is None or os.getenv("NL_ANSWER_LLM", "1") == "0":
        return reason
    zh = any("\u4e00" <= ch <= "\u9fff" for ch in question)
    language = "Chinese" if zh else "English"
    prompt = (REFUSAL_RULES + f"\nLANGUAGE: {language}.\nQUESTION: {question}\n"
              f"REFUSAL REASON: {reason}")
    try:
        text = llm.invoke(prompt).content.strip()
        if text and not _language_mismatch(question, text):
            return text
    except Exception:  # noqa: BLE001
        pass
    return reason


def _polish_understanding(question: str, text: str) -> str:
    """Polish the confirmation echo too: same facts, friendlier prose."""
    llm = _llm()
    if llm is None or os.getenv("NL_ANSWER_LLM", "1") == "0":
        return text
    zh = any("\u4e00" <= ch <= "\u9fff" for ch in question)
    language = "Chinese" if zh else "English"
    prompt = ("Rewrite this system understanding for the user: same facts, same numbers, "
              "the same SQL and the same keys. One short paragraph plus the SQL line. "
              f"LANGUAGE: {language}.\nUNDERSTANDING:\n{text}")
    try:
        out = llm.invoke(prompt).content.strip()
        sql = (text.split("I will run: ")[-1].split("\n")[0]
               if "I will run: " in text else
               text.split("将执行：")[-1].split("\n")[0] if "将执行：" in text else None)
        if out and (not sql or sql.strip() in out):
            return out
    except Exception:  # noqa: BLE001
        pass
    return text


def _record(question: str, ok: bool, refused: str | None = None,
            kind: str | None = None, intent: dict | None = None,
            backend: str | None = None) -> None:
    """Append the question outcome to `nl_events` — the refusal telemetry the backlog reads.

    Best-effort by design: telemetry must never break an answer.
    """
    import os as _os
    if _os.getenv("NL_TELEMETRY", "1") == "0":
        return
    try:
        conn = psycopg2.connect(**actions.dsn())
        try:
            cur = conn.cursor()
            cur.execute(NL_DDL)
            cur.execute(
                "INSERT INTO nl_events(question, ok, refused, refusal_kind, intent, backend) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, %s)",
                (question, ok, refused, kind,
                 json.dumps(intent or {}, ensure_ascii=False, default=str),
                 backend or _backend_name()))
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — telemetry is a courtesy, never a failure
        pass


SUGGESTIONS = {
    "unsupported_slot": "declare :supportsSlot <slot> on a metric (or add a metric that supports it)",
    "multi_dimension": "declare a metric with :groupBy <dims> (one :groupBy per dimension)",
    "off_menu": "declare a metric/class/action (or extend ALIASES) for the asked term",
    "no_capability_path": "declare the missing relationship (:physicalColumn + :references) or :physicalTable",
    "type_error": "no declaration needed — the question's parameter is invalid (type gate)",
    "ambiguous": "disambiguate the declaration (two classes own the same column)",
    "other": "inspect the refused message",
}


def backlog(limit: int = 50) -> dict:
    """Aggregate refusals into a declaration backlog: what to declare next, from data."""
    conn = psycopg2.connect(**actions.dsn())
    try:
        cur = conn.cursor()
        cur.execute(NL_DDL)
        cur.execute(
            "SELECT refusal_kind, question, count(*) AS n, max(ts) AS last_seen "
            "FROM nl_events WHERE ok = false "
            "GROUP BY refusal_kind, question ORDER BY n DESC, last_seen DESC LIMIT %s",
            (limit,))
        rows = [{"kind": r[0], "question": r[1], "count": r[2], "last_seen": r[3].isoformat()
                 if hasattr(r[3], "isoformat") else str(r[3])} for r in cur.fetchall()]
        cur.execute("SELECT count(*) FILTER (WHERE ok), count(*) FILTER (WHERE NOT ok) "
                    "FROM nl_events")
        ok_n, bad_n = cur.fetchone()
        cur.execute("SELECT refusal_kind, count(*) FROM nl_events WHERE ok = false "
                    "GROUP BY refusal_kind ORDER BY 2 DESC")
        by_kind = {k: n for k, n in cur.fetchall()}
    finally:
        conn.close()
    for r in rows:
        r["suggestion"] = SUGGESTIONS.get(r["kind"], SUGGESTIONS["other"])
    return {"ok": True, "answered": ok_n, "refused": bad_n,
            "by_kind": by_kind, "items": rows}


def _ollama_alive() -> bool:
    """Is a local Ollama serving the OpenAI-compatible API?"""
    import urllib.request
    base = OLLAMA_BASE.rstrip("/")
    probe = base[:-3] + "/api/tags" if base.endswith("/v1") else base + "/api/tags"
    try:
        urllib.request.urlopen(probe, timeout=1.5)
        return True
    except Exception:  # noqa: BLE001
        return False


def _backend_name() -> str:
    """Which backend will actually interpret (shown in the UI steps)."""
    backend = os.getenv("NL_BACKEND", "auto").lower()
    if backend == "fallback":
        return "fallback (forced by settings)"
    if backend in ("deepseek", "auto") and os.getenv("DEEPSEEK_API_KEY"):
        return f"deepseek:{os.getenv('DEEPSEEK_MODEL', MODEL)}"
    if backend in ("ollama", "auto") and _ollama_alive():
        return f"ollama:{os.getenv('OLLAMA_MODEL', OLLAMA_MODEL)}"
    if backend == "deepseek":
        return "fallback (deepseek selected, DEEPSEEK_API_KEY missing)"
    if backend == "ollama":
        return "fallback (ollama selected, server unreachable)"
    return "fallback (no model)"


def _answer_source() -> str:
    if os.getenv("NL_ANSWER_LLM", "1") == "0":
        return "template (disabled)"
    return "llm" if _llm() is not None else "template (no model)"


def _llm():
    """LLM backend, in priority order:
       1. DeepSeek V4 Flash (DEEPSEEK_API_KEY) — the cloud model this demo was written on
       2. local Ollama (OLLAMA_BASE/OLLAMA_MODEL) — offline, no key, e.g. qwen3:4b
       3. None -> the deterministic fallback in interpret()
    All three speak the OpenAI chat-completions API, so langchain-openai covers both."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:          # gates run under the cube venv, which has no langchain
        return None
    backend = os.getenv("NL_BACKEND", "auto").lower()
    if backend == "fallback":
        return None
    if backend in ("deepseek", "auto") and os.getenv("DEEPSEEK_API_KEY"):
        return ChatOpenAI(model=os.getenv("DEEPSEEK_MODEL", MODEL), temperature=0,
                          api_key=os.getenv("DEEPSEEK_API_KEY"),
                          base_url=os.getenv("DEEPSEEK_BASE_URL", BASE_URL))
    if backend in ("ollama", "auto") and _ollama_alive():
        return ChatOpenAI(model=os.getenv("OLLAMA_MODEL", OLLAMA_MODEL), temperature=0,
                          api_key="ollama", base_url=OLLAMA_BASE, timeout=180)
    return None


def _apply_profile_aliases() -> None:
    """A profile may rename a dimension: in TPCH "region" is a real object, and retail's
    "region -> city" alias would be wrong there. Declared per profile, never global."""
    try:
        prof = json.loads(pathlib.Path(os.environ.get("APP_SETTINGS")
                                       or pathlib.Path(__file__).with_name("settings.json")
                                       ).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    for src, canon in (prof.get("aliases") or {}).items():
        # Keep the canonical's case: a camelCase target ("noShow") must stay splittable into
        # its parts, or the token it produces ("noshow") matches no metric word and then
        # trips the salient-noun check as an uncovered noun.
        ALIASES[str(src).lower()] = str(canon)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _label(g, name: str) -> tuple[str | None, str | None]:
    node = P(name)
    return sqlgen._one(g, node, RDFS.label), sqlgen._one(g, node, RDFS.comment)


def _features() -> dict:
    """The ACTIVE profile's feature flags (a profile may have no actions at all).

    `profile.use()` sets `actions.ACTIVE_PROFILE`; a child process instead carries `$APP_SETTINGS`.
    Reading the environment first is what made an in-process caller serve another ontology's flags.
    """
    import actions as _actions

    if getattr(_actions, "ACTIVE_PROFILE", None) is not None:
        return (_actions._settings().get("features") or {})
    try:
        s = json.loads(pathlib.Path(os.environ.get("APP_SETTINGS")
                                    or pathlib.Path(__file__).with_name("settings.json")
                                    ).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return s.get("features") or {}


def menu(graph=None) -> dict:
    """The ontology's public API: what exists, what each entry means, and the compiled SQL."""
    graph = graph or actions.load_graph()
    if not _features().get("actions", True):
        compiled = {}                      # a read-only profile: nothing to dry-run
    else:
        compiled = actions.compile_actions(graph, actions.load_config())
    metrics, classes, acts = [], [], []

    for name in sqlgen.metrics(graph):
        label, desc = _label(graph, name)
        entry = {"name": name, "label": label, "description": desc,
                 "unit": sqlgen._one(graph, P(name), P("unit")),
                 "formula": sqlgen._one(graph, P(name), P("formula")),
                 "grain": sqlgen._one(graph, P(name), P("grain")),
                 "group_by": [sqlgen._local(o) for o in graph.objects(P(name), P("groupBy"))
                              if sqlgen._local(o)]}
        try:
            entry["sql"] = sqlgen.compile_metric(graph, name).sql
        except sqlgen.Refusal as exc:
            entry["refused"] = str(exc).splitlines()[0]
        metrics.append(entry)

    for cls in sorted({sqlgen._local(s) for s in graph.subjects(RDF.type, OWL.Class)
                       if isinstance(s, URIRef)}):
        label, desc = _label(graph, cls)
        try:
            table = sqlgen.table_of(graph, cls)
        except sqlgen.Refusal:
            base = sqlgen.concept_base_class(graph, cls)
            if not base:
                continue
            table = sqlgen.table_of(graph, base)
        entry = {"name": cls, "label": label, "description": desc, "table": table}
        try:
            entry["predicate"] = sqlgen.concept_sql(graph, cls)
        except sqlgen.Refusal:
            entry["predicate"] = None
        classes.append(entry)

    for name, act in compiled.items():
        acts.append({"name": name, "applies_to": act["applies_to"],
                     "parameters": act["parameters"],
                     "param_specs": act.get("param_specs"),
                     "preconditions": [c["template"] for c in act["checks"]],
                     "effect": act["effect_sql"]})
    return {"metrics": metrics, "classes": classes, "actions": acts}


# ------------------------------------------------------------------ interpretation
INTENT_SCHEMA = """Return ONLY a JSON object, no prose:
{"kind": "metric" | "class" | "action", "name": "<entry from the menu>", "params": {},
 "slots": {"CustomerFilter": {"customer_id": <integer>}, "TimeWindow": {}}}
- metric: a business measurement (has a compiled SQL)
- class: a kind of object (count + sample rows)
- action: a WRITE that must be dry-run first (never auto-executed)
- params: only for actions, matching the declared parameter names
- slots: constraints the question applies ("for customer 2", "last month"); only declare
  them when the question actually states them. An unsupported slot is refused by name.
- if the question cannot be answered from the menu, return {"kind": "none", "name": null}"""


def _intent_prompt(question: str, menu_: dict) -> str:
    lines = [INTENT_SCHEMA, "", "MENU:"]
    lines.append("metrics:")
    for m in menu_["metrics"]:
        lines.append(f"- {m['name']} | label={m.get('label')} | {m.get('description') or ''} | "
                     f"unit={m.get('unit')} | sql={m.get('sql') or m.get('refused')}")
    lines.append("classes:")
    for c in menu_["classes"]:
        lines.append(f"- {c['name']} | label={c.get('label')} | {c.get('description') or ''} | "
                     f"predicate={c.get('predicate')}")
    lines.append("actions:")
    for a in menu_["actions"]:
        lines.append(f"- {a['name']} | applies_to={a['applies_to']} | "
                     f"params={a['parameters']} | effect={a['effect']}")
    lines.append("")
    lines.append(f"QUESTION: {question}")
    return "\n".join(lines)


def _parse_intent(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise NlRefusal("the model did not return a JSON intent")
    try:
        intent = json.loads(m.group(0))
    except json.JSONDecodeError:
        raise NlRefusal("the model returned malformed JSON")
    if not isinstance(intent, dict) or "kind" not in intent:
        raise NlRefusal("the model returned no intent kind")
    return intent


# ------------------------------------------------------------------ rules first
# The deterministic matcher is the FIRST stage, not a fallback: obvious questions
# ("how many orders", "高级客户的收入", "promote customer 2") never reach the model.
# The model is used only when the rules are unsure. Set NL_RULES_FIRST=0 to restore
# model-first behaviour.
RULES_FIRST = os.getenv("NL_RULES_FIRST", "1") != "0"

# Bilingual vocabulary for the rule matcher: a Chinese term in the question becomes the
# English canonical token the menu entries are named with.
ALIASES = {
    "收入": "revenue", "营收": "revenue", "销售额": "revenue", "营业额": "revenue",
    "总额": "sum", "金额": "amount", 
    "客户": "customer", "顾客": "customer", "用户": "customer",
    "高级": "premium", "优质": "premium", "贵宾": "premium",
    "订单": "order", "单量": "order",
    "产品": "product", "商品": "product", "品": "product",
    "按": "by", "分": "by", "分组": "by", "各": "by",
    "门店": "store", "商店": "store", "城市": "city",
    "地区": "city", "区域": "city", "region": "city",
    "money": "revenue", "spend": "revenue", "spent": "revenue", "spending": "revenue",
    "sales": "revenue", "turnover": "revenue", "amount spent": "revenue",
    "数量": "count", "几个": "count", "客户数": "customer",
    "最高": "maximum", "最大": "maximum", "峰值": "maximum",
    "平均": "average", "均价": "average", "均值": "average",
    "提升": "promote", "升级": "promote",
    "降级": "demote", "降为": "demote",
    "记录": "record", "下单": "record",
}

_apply_profile_aliases()
ENGLISH_HINTS = {"how many": "count", "how much": "sum", "total": "sum",
                 "maximum": "max", "largest": "max", "average": "average"}


def _camel_words(name: str) -> set[str]:
    words = set(w for w in re.split(r"[^a-z0-9]+",
                                    re.sub(r"([a-z])([A-Z])", r"\1 \2", name).lower()) if w)
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words}


# ── "this question asks for a NUMBER" ────────────────────────────────────────
# A class answer is a LIST, so it can never be the answer to a question that asks for a count,
# a sum, a rate or an amount. Chinese has no spaces: "高风险线路数" becomes CJK 2-grams plus
# the alias 线路→route, the class :Route won the tie (its name is one word short, and the
# tiebreak prefers the shorter name), and the matcher answered a count request with a listing
# of routes — a confidently wrong answer with no refusal anywhere. The salient-noun check that
# exists for exactly this cannot see it, because it deliberately skips CJK tokens.
#
# The cues are Chinese-first (数/多少/几条/率/占比/金额) with the same English measure words the
# aggregate hint already knows. "数据" and "参数" contain 数 and mean a noun, not a count.
_MEASURE_CUES_ZH = ("多少", "几个", "几条", "几趟", "几次", "几单", "几笔", "总量", "合计",
                    "平均", "占比", "率", "金额", "数",
                    # superlatives ask for a RANKING, which is a metric question: answered with a
                    # class it becomes "here is the list of damaged stops", which is not an answer.
                    "最多", "最少", "最大", "最小", "最高", "最低", "最好", "最差", "排名")
_MEASURE_SKIP_ZH = ("数据", "参数", "数量级", "系数")
_MEASURE_WORDS = {"count", "sum", "total", "average", "avg", "rate", "ratio", "percent",
                  "number", "how", "many", "much"}


def _measure_cue(question: str, toks: set[str]) -> str | None:
    """The word that makes this question ask for a number, or None.

    Returns the cue itself so a refusal can quote it ("asks for a number (数)") instead of
    claiming the rule fired without saying why.
    """
    q = question or ""
    for skip in _MEASURE_SKIP_ZH:
        q = q.replace(skip, "")
    for cue in _MEASURE_CUES_ZH:
        if cue in q:
            return cue
    hit = sorted(toks & _MEASURE_WORDS)
    return hit[0] if hit else None


# Words that make a metric name an AGGREGATE of a noun rather than the noun itself:
# `orderCount` is "the count of :Order", `tripCount` is "the count of :Trip".
_AGG_WORDS = {"count", "counting", "sum", "total", "average", "avg", "max", "min", "number",
              "rate", "ratio", "percent", "pct", "per", "thousand", "1k"}
_COUNT_CUES = {"数", "多少", "几个", "几条", "几趟", "几次", "几单", "几笔", "总量", "合计",
               "count", "number", "how", "many", "much"}


# CJK filler around a noun: the interrogative, the measure word, "how many", "please",
# "is/are", "the". Stripping them leaves the NOUN the user asked about — necessary because
# Chinese runs are matched as whole strings and 2-grams, so "有多少条订单行" (order LINES) also
# contains "订单" (orders) and the class :Order would swallow the sentence.
# NOT stripped: 行/列/单 — they are part of nouns here (订单行 is a LINE, not an ORDER); the
# first version stripped 行 and turned 订单行 back into 订单, which is precisely the noun loss
# this guard exists to catch.
_ZH_FILLER = ("有多少", "有多少条", "有多少个", "多少", "几个", "几条", "几趟", "几次", "几单",
              "几笔", "哪些", "哪几个", "是什么", "一共", "总共", "总量", "合计", "请", "帮我",
              "查一下", "一下", "的", "是", "有", "条", "个", "了", "吗", "呢", "数")


def _zh_residual(question: str) -> str:
    """The Chinese noun a question is about, with the measure cues and filler removed."""
    q = question or ""
    for w in _ZH_FILLER:
        q = q.replace(w, "")
    return re.sub(r"[^\u4e00-\u9fff]", "", q)


def _zh_covers(question: str, label: str) -> bool:
    """Does the declaration's label account for the Chinese noun the question names?

    Only used when the question is Chinese and the best match came from a class; a mismatch
    means the noun was dropped by the 2-gram tokenizer, and answering anyway is the confidently
    wrong answer this file refuses on principle.
    """
    residual = _zh_residual(question)
    if not residual or not re.search(r"[\u4e00-\u9fff]", residual):
        return True
    lab = re.sub(r"[^\u4e00-\u9fff]", "", label or "")
    if not lab:
        # An ENGLISH label over a Chinese question: compare against the alias table instead.
        # Every alias key found in the noun is accounted for; a leftover character is a noun
        # the ontology never declared ("订单行" leaves 行 after 订单 -> not the same noun).
        leftovers = residual
        for zh in sorted(ALIASES, key=len, reverse=True):
            if zh and zh in leftovers:
                leftovers = leftovers.replace(zh, "")
        return leftovers == ""
    # A Chinese noun keeps its modifier in FRONT: "高风险线路" ends with 线路, so the
    # declaration accounts for the question. "订单行" merely CONTAINS 订单 — order LINES are
    # not orders, and answering orderCount there is the wrong number, so a prefix-only match
    # does not count as coverage.
    return (residual == lab or residual.endswith(lab) or lab.endswith(residual))


def _count_of_class(menu_: dict, cls_name: str, cue: str,
                    only_metrics: set[str] | None = None) -> dict | None:
    """The metric that is literally the count of this class — `orderCount` for :Order.

    The tiebreak in `_rule_intent` prefers the shorter name, so a bare class always beat the
    two-word metric that declares its count; "订单数" was answered with a listing of orders
    while `orderCount` sat on the menu. This looks the count up BY NAME WORDS (`order`) and
    only accepts a metric whose remaining words are aggregate words — `overloadsByRouteVersion`
    is not the count of :Route, so a question about a count of routes still refuses.
    """
    if cue not in _COUNT_CUES:
        return None
    want = _camel_words(cls_name)
    if not want:
        return None
    for m in menu_["metrics"]:
        if only_metrics is not None and m["name"] not in only_metrics:
            continue
        words = _camel_words(m["name"]) - _AGG_WORDS
        if words and words == want:
            return m
    return None



def _question_tokens(question: str) -> set[str]:
    toks = set(w for w in re.split(r"[^a-z0-9]+", question.lower()) if w)
    # CJK has no spaces, so the ASCII split drops the whole question: "预约数是多少" produced
    # NO tokens, `_rule_intent` returned None on its first line, and every Chinese sample
    # was refused while the menu was complete. The run and its 2-grams are the cheap
    # equivalent of word tokens; the label-literal rule in _rule_intent does the precise
    # matching, this only makes the question non-empty.
    for run in re.findall(r"[\u4e00-\u9fff]+", question):
        if len(run) >= 2:
            toks.add(run)
            toks |= {run[i:i + 2] for i in range(len(run) - 1)}
    for zh, canon in ALIASES.items():
        if zh in question:
            # A canonical name is often camelCase ("noShow") while the metric's own words
            # are its PARTS ("no", "show", "rate"); adding the joined form "noshow" matched
            # nothing AND then tripped the salient-noun check as an uncovered noun.
            if canon != canon.lower():
                toks |= _camel_words(canon)
            else:
                toks.add(canon)
    for phrase, canon in ENGLISH_HINTS.items():
        if phrase in question.lower():
            toks.add(canon)
    # collapse simple plurals (orders -> order) so both sides compare in one form.
    # pure digits are parameters, not nouns: they fill slots/action params and must not
    # make the rules look unsure.
    out = set()
    for t in toks:
        if t.isdigit():
            continue
        out.add(t[:-1] if len(t) > 3 and t.endswith("s") else t)
    return out


TIME_WORDS = ("last month", "this month", "last week", "this week", "today", "yesterday",
              "this year", "last year", "上个月", "本月", "上周", "这周", "今天", "昨天",
              "今年", "去年", "过去", "最近")


def _time_range(label: str, now=None) -> dict:
    """label -> {since, until} half-open range [since, until) on UTC dates."""
    import datetime as dt
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if label in ("today", "今天"):
        return {"since": today.isoformat(), "until": (today + dt.timedelta(days=1)).isoformat()}
    if label in ("yesterday", "昨天"):
        s = today - dt.timedelta(days=1)
        return {"since": s.isoformat(), "until": today.isoformat()}
    if label in ("last week", "上周"):
        s = today - dt.timedelta(days=today.weekday() + 7)
        return {"since": s.isoformat(), "until": (s + dt.timedelta(days=7)).isoformat()}
    if label in ("this week", "这周"):
        s = today - dt.timedelta(days=today.weekday())
        return {"since": s.isoformat(), "until": (s + dt.timedelta(days=7)).isoformat()}
    first = today.replace(day=1)
    if label in ("this month", "本月"):
        nxt = (first + dt.timedelta(days=32)).replace(day=1)
        return {"since": first.isoformat(), "until": nxt.isoformat()}
    if label in ("last month", "上个月"):
        prev = (first - dt.timedelta(days=1)).replace(day=1)
        return {"since": prev.isoformat(), "until": first.isoformat()}
    if label in ("this year", "今年"):
        return {"since": today.replace(month=1, day=1).isoformat(),
                "until": today.replace(year=today.year + 1, month=1, day=1).isoformat()}
    if label in ("last year", "去年"):
        return {"since": today.replace(year=today.year - 1, month=1, day=1).isoformat(),
                "until": today.replace(month=1, day=1).isoformat()}
    raise NlRefusal(f"unknown time label {label!r}")


def _slots(question: str) -> dict:
    """Deterministic slot extraction: the constraints a question states, typed by the
    capability graph's slot nodes (not free text). Ranges are computed here so the
    compiled SQL carries real values; the confirmation echo shows them to the user."""
    slots: dict = {}
    m = re.search(r"(?:customer|客户)\s*#?(\d+)", question)
    if m:
        slots["CustomerFilter"] = {"customer_id": int(m.group(1))}
    ql = question.lower()
    m = re.search(r"(?:last|过去|最近)\s*(\d+)\s*(?:days?|天)", ql)
    if m:
        import datetime as dt
        days = int(m.group(1))
        now = dt.datetime.now(dt.timezone.utc)
        slots["TimeWindow"] = {"label": f"last {days} days",
                               "since": (now - dt.timedelta(days=days)).isoformat(),
                               "until": now.isoformat()}
        return slots
    for w in TIME_WORDS:
        if w in ql:
            slots["TimeWindow"] = {"label": w, **_time_range(w)}
            break
    return slots


def _rule_intent(question: str, menu_: dict, only_metrics: set[str] | None = None) -> dict | None:
    """Deterministic intent: score menu entries by token overlap, pick the best.

    Returns None when nothing clears the confidence bar — the caller then asks the model.
    Metrics are scored before classes, so a tie prefers the measurement (the more precise
    answer). Numbers in the question fill the declared integer parameters of an action.
    """
    toks = _question_tokens(question)
    if not toks:
        return None

    # ACTIONS are decided by an explicit VERB, not by a noun: "orders" must not select
    # RecordOrder just because the name contains "order".
    #
    # AND a question that asks for a NUMBER can never be answered by a verb. The built-in glossary
    # maps 记录 -> "record" (line ~435), so "派单决策记录覆盖率是多少" produced the token `record`,
    # matched the verb in RecordDispatchDecision, and the coverage question came back as a DRY RUN
    # of the write. A measure cue decides it: 「是多少」 asks for a number, so the metric wins and the
    # verb is only reachable by an imperative ("记录一次派单决策 …").
    VERBS = {"promote", "demote", "record"}
    asking_for_a_number = _measure_cue(question, toks) is not None
    for a in menu_["actions"]:
        verbs = _camel_words(a["name"]) & VERBS
        if asking_for_a_number:
            break
        if verbs & toks:
            nums = re.findall(r"\d+", question)
            ints = [p for p in a["parameters"]
                    if (a.get("param_specs") or {}).get(p, {}).get("type") in ("integer", "number")]
            params = {p: int(n) for p, n in zip(ints, nums)}
            return {"kind": "action", "name": a["name"], "params": params}

    best = None
    # a "by X" question must be answered by a metric that GROUPS BY X (if one exists);
    # otherwise "order revenue by region" would silently return the ungrouped total.
    dims = _group_dims(question, menu_)
    group_signal = "by" in toks or "per" in toks
    dim_metrics = ({m["name"] for m in menu_["metrics"]
                    if dims and dims <= set(m.get("group_by") or [])}
                   if group_signal and dims else None)
    if dim_metrics is not None:
        if only_metrics is None:
            only_metrics = dim_metrics
        else:
            only_metrics = only_metrics & dim_metrics

    # "how many" hints at a COUNT, but a hint alone must not outrank the noun: the
    # aggregate bonus only applies when the entry also matches a NOUN of the question.
    HINTS = {"count", "sum", "max", "average"}
    STOPWORDS = {"how", "many", "much", "which", "what", "who", "show", "me", "do", "we",
                 "have", "has", "the", "a", "an", "of", "for", "and", "or", "in", "on",
                 "at", "is", "are", "was", "were", "be", "been", "by", "with", "per",
                 "to", "from", "all", "list", "tell", "give", "please", "there", "any",
                 "some", "each", "their", "its",
                 # quantifiers that describe the SUM rather than select a different one:
                 # "total revenue" IS "revenue", and refusing it would be pedantry.
                 "total", "overall", "altogether", "combined", "grand",
                 # auxiliaries and pronouns that say WHO is talking, not WHAT is asked
                 "did", "does", "done", "had", "should", "would", "could", "will", "can",
                 "our", "us", "i", "you", "they", "them", "this", "that", "these", "those",
                 "about", "like", "roughly", "exactly", "currently", "now", "so", "far"}
    noun_toks = toks - HINTS - STOPWORDS

    def consider(kind: str, entry: dict) -> None:
        nonlocal best
        words = _camel_words(entry["name"]) | set(
            w for w in re.split(r"[^a-z0-9]+", (entry.get("label") or "").lower()) if w)
        # The label the ontology's author wrote IS the phrase a user types — in any
        # language. The token overlap below is ASCII-only (it splits on [^a-z0-9]), so a
        # Chinese label such as 预约数 can never match a Chinese question and every
        # sample refuses while the menu is perfectly complete. Measured on the clinic
        # ontology: 11 of 13 samples refused for want of this one rule.
        label = (entry.get("label") or "").strip()
        if len(label) >= 2 and label in question:
            key = (1000 + len(label), 1, -len(words))
            if best is None or key > best[0]:
                # `_by_label`: the question contains this declaration's label VERBATIM — the
                # strongest evidence there is. The noun check below exists for partial matches;
                # letting it veto a literal label is how 「每千公里破损箱数是多少」 was refused even
                # though that exact string is a metric's label (the alias token 破损→damaged had no
                # counterpart in the metric's own words {damage, per1k, km}).
                best = (key, kind, dict(entry, _words=words, _by_label=True))
            return
        body = words & noun_toks
        if not body:
            return
        score = len(body)
        sql = (entry.get("sql") or "").lower()
        for agg in ("count", "sum", "max", "average"):
            if agg in sql and agg in toks:
                score += 1
        key = (score, len(body), -len(words))
        if best is None or key > best[0]:
            best = (key, kind, dict(entry, _words=words))

    for m in menu_["metrics"]:
        if only_metrics is not None and m["name"] not in only_metrics:
            continue
        consider("metric", m)
    for c in menu_["classes"]:
        consider("class", c)
    if best is None:
        return None
    _, kind, entry = best
    # A NUMBER CANNOT BE ANSWERED BY A CLASS. This is a fact about the ontology, not a
    # misfire, so it does not hand the question to the model: no metric declares that count,
    # and a model cannot invent one. Two outcomes, both honest:
    #   - a metric that IS the count of this class exists (`orderCount` for :Order) -> answer
    #     that metric. Without this step "订单数" was refused even though orderCount existed,
    #     because the one-word class name won the tiebreak over the two-word metric name;
    #   - nothing declares it -> refuse, naming the class, the cue, and what to declare.
    cue = _measure_cue(question, toks)
    if cue and kind == "class":
        cls_label = (entry.get("label") or entry["name"]).strip()
        count_metric = (_count_of_class(menu_, entry["name"], cue, only_metrics)
                        if _zh_covers(question, cls_label) else None)
        if count_metric is not None:
            kind, entry = "metric", dict(count_metric, _words=_camel_words(count_metric["name"]))
        else:
            raise NlRefusal(
                f"{question!r} asks for a number ({cue!r}), and the best declaration is the "
                f"CLASS :{entry['name']} (\u300c{cls_label}\u300d) — no metric declares that "
                f"count. A class is a list, not a number: declare a metric on "
                f":{entry['name']} with :aggregate and :grain, or ask for the list instead "
                f"(\u300c{cls_label}\u300d).")
    # A literal-label match is final. `slots` is computed here (it used to be computed further
    # down, which is why the first version of this early return raised UnboundLocalError — a bug
    # the probe caught immediately, and the reason this is one statement and not a copy of the
    # block below).
    if entry.get("_by_label"):
        intent = {"kind": kind, "name": entry["name"]}
        bounds = _slots(question)
        if bounds:
            intent["slots"] = bounds
        return intent
    # SALIENT-NOUN CHECK: if the question carries a noun the chosen entry does not cover,
    # the rules are effectively answering a truncated question ("which premium people
    # bought boots?" must not silently become "who is premium"). Treat it as unsure so the
    # model gets a chance; without a model it becomes a refusal, not a confident wrong pick.
    covered = set(entry["_words"]) | {w for w in re.split(r"[^a-z0-9]+",
                                                          (entry.get("label") or "").lower())
                                      if w}
    for gb in (entry.get("group_by") or []):
        covered |= _camel_words(gb)
    for w in re.split(r"[^a-z0-9]+", (entry.get("formula") or "").lower()):
        if w:
            covered.add(w)
    for w in _camel_words(entry.get("grain") or ""):
        covered.add(w)
    slots = _slots(question)
    for slot_name in slots:
        covered |= _camel_words(slot_name)
    tw = slots.get("TimeWindow") or {}
    for w in re.split(r"[^a-z0-9]+", (tw.get("label") or "").lower()):
        if w:
            covered.add(w)
    # an alias source word is covered when its canonical token is covered
    for src, canon in ALIASES.items():
        if src in question and canon in covered:
            covered |= {w for w in re.split(r"[^a-z0-9]+", src.lower()) if w}
    # CJK tokens are synthetic 2-grams of the question, not claimed nouns: a Chinese
    # dimension claim is caught by _claimed_dims ("按…") and _check_dimensions, which run
    # before this. Leaving them in the uncovered set made every Chinese question "unsure"
    # even when its metric's label appeared verbatim.
    uncovered = {t for t in (noun_toks - covered) if not re.search(r"[\u4e00-\u9fff]", t)}
    if uncovered:
        return None
    intent = {"kind": kind, "name": entry["name"]}
    if slots:
        intent["slots"] = slots
    return intent


def _fallback_intent(question: str, menu_: dict) -> dict | None:
    """Deterministic menu matcher (offline). Names/labels are compared normalised, so
    'premium customer revenue' finds :premiumCustomerRevenue."""
    q = _norm(question)
    for a in menu_["actions"]:
        if _norm(a["name"]) and _norm(a["name"]) in q:
            # off-line fallback: numbers in the question fill the integer parameters in
            # declaration order ("promote customer 2" -> {customer_id: 2}); anything the
            # question does not provide is refused by validate() rather than guessed.
            specs = a.get("param_specs") or {}
            ints = [p_ for p_ in a["parameters"]
                    if (specs.get(p_) or {}).get("type") in ("integer", "number")]
            nums = re.findall(r"\d+", question)
            params = {p_: int(n) for p_, n in zip(ints, nums)}
            return {"kind": "action", "name": a["name"], "params": params}
    for m in menu_["metrics"]:
        if _norm(m["name"]) in q or (_norm(m.get("label") or "") and _norm(m["label"]) in q):
            return {"kind": "metric", "name": m["name"]}
    for c in menu_["classes"]:
        if _norm(c["name"]) in q or (_norm(c.get("label") or "") and _norm(c["label"]) in q):
            return {"kind": "class", "name": c["name"]}
    return None


def _raw_intent(question: str, menu_: dict) -> dict:
    """The model call (or fallback): returns an unvalidated intent."""
    llm = _llm()
    if llm is not None:
        text = llm.invoke(_intent_prompt(question, menu_)).content
        return _parse_intent(text)
    return _fallback_intent(question, menu_) or {"kind": "none", "name": None}


def _claimed_dims(question: str) -> list[str]:
    """The phrases a question claims to GROUP BY ("by product and city" -> [product, city]).

    Only "by" (and 按) makes a claim; "per" is left alone because "revenue per customer" names
    a declared metric rather than a dimension. This exists so an UNKNOWN dimension ("by
    brand") cannot be silently dropped while the rest of the question is answered.
    """
    ql = question.lower()
    chunks = []
    for marker in (r"\bby\b", "按"):
        for m in re.finditer(marker, ql):
            chunks.append(ql[m.end():])
    out: list[str] = []
    for chunk in chunks:
        chunk = re.split(r"[.?!;，。？！]", chunk)[0]
        # Chinese has no word boundaries, so "按专科看预约数" arrived as ONE chunk that
        # contained the dimension, the verb and the measure, and was refused as an unknown
        # dimension called 「专科看预约数」. Cut at the words that END a dimension phrase;
        # what follows them is the measure, not a grouping claim.
        if re.search(r"[\u4e00-\u9fff]", chunk):
            chunk = re.split(r"看|的|是|有|多少|几个|几笔|呢|吗|了", chunk)[0]
        for part in re.split(r",|、|/|\band\b|&|和|与|跟|及", chunk):
            part = part.strip()
            if part:
                out.append(part)
    return out


def _uncovered_dims(question: str, menu_: dict) -> list[str]:
    """Dimensions a question asks for that no metric can group by.

    A word counts as COVERED when some metric's :groupBy uses it, or when it is a word a
    metric already owns elsewhere (formula, grain, label) — "城市 的收入" is one dimension
    plus its measure, not an unknown dimension.
    """
    claimed = _claimed_dims(question)
    if not claimed:
        return []
    dim_words: set[str] = set()
    owned_words: set[str] = set()
    for m in menu_["metrics"]:
        for gb in (m.get("group_by") or []):
            dim_words |= _camel_words(gb)
            dim_words |= {w for w in re.split(r"[^a-z0-9\u4e00-\u9fff]+", gb.lower()) if w}
        owned_words |= _camel_words(m["name"])
        for field in ("label", "formula", "grain"):
            val = m.get(field)
            if isinstance(val, str):
                owned_words |= {w for w in re.split(r"[^a-z0-9\u4e00-\u9fff]+", val.lower())
                                if w}
    stop = {"revenue", "sales", "total", "of", "the", "for", "in", "on", "me", "show",
            "give", "list", "all", "each", "per", "amount", "value", "sum"}
    # Chinese has no spaces: a phrase is covered when it CONTAINS a known word
    # ("城市的收入" contains 城市), not only when it splits into one.
    def is_cjk(w: str) -> bool:
        return any("\u4e00" <= ch <= "\u9fff" for ch in w)

    known = dim_words | owned_words
    # single-character aliases ("品" -> product) are too ambiguous to prove coverage:
    # "品牌" (brand) contains 品, and that must NOT count as the product dimension.
    cjk_dims = {src for src, canon in ALIASES.items()
                if is_cjk(src) and len(src) > 1 and canon in dim_words}
    cjk_measures = {src for src, canon in ALIASES.items()
                    if is_cjk(src) and len(src) > 1 and canon in known
                    and canon not in dim_words}
    # words that carry no dimension at all: "按城市的收入" is one dimension plus its measure
    CJK_FILLER = {"的", "按", "分组", "分别", "各", "从", "高", "到", "低", "排名", "排序",
                  "是", "有", "多少", "每个", "每", "个", "维", "和", "与", "跟", "及", "里"}
    uncovered = []
    for phrase in claimed:
        toks = {t for t in re.split(r"[^a-z0-9\u4e00-\u9fff]+", phrase) if t} - stop
        toks = {ALIASES.get(t, t) for t in toks}
        toks -= stop
        if toks and (toks & dim_words):
            continue                       # an English dimension word is present
        if is_cjk(phrase):
            rest = phrase
            for w in sorted(cjk_measures, key=len, reverse=True):
                rest = rest.replace(w, " ")
            if any(w in rest for w in cjk_dims):
                continue                   # a known dimension survives the measure words
            leftovers = "".join(ch for ch in rest if is_cjk(ch))
            for w in sorted(CJK_FILLER, key=len, reverse=True):
                leftovers = leftovers.replace(w, " ")
            leftovers = leftovers.replace(" ", "")
            if leftovers:
                uncovered.append(leftovers)   # name the fragment, not the whole clause
            continue
        if toks and not (toks & dim_words) and not (toks & owned_words):
            uncovered.append(phrase)
    return uncovered


def _check_dimensions(question: str, menu_: dict) -> set[str]:
    """If the question groups by several dimensions, a metric must cover ALL of them.

    Returns the covering metric names (so the rules stage can pick one); refuses when no
    declared metric covers the requested combination — dropping a dimension would answer a
    different question.
    """
    uncovered = _uncovered_dims(question, menu_)
    if uncovered:
        grouped = sorted((m["name"], m.get("group_by")) for m in menu_["metrics"]
                         if m.get("group_by"))
        raise NlRefusal(
            f"nothing declares a grouping by {uncovered} — refusing rather than dropping a "
            f"dimension and answering a different question "
            f"(grouped metrics: {grouped})")
    dims = _group_dims(question, menu_)
    if len(dims) < 2:
        return set()
    covering = {m["name"] for m in menu_["metrics"]
                if dims <= set(m.get("group_by") or [])}
    if not covering:
        grouped = sorted((m["name"], m.get("group_by")) for m in menu_["metrics"]
                         if m.get("group_by"))
        raise NlRefusal(
            "no declared metric groups by "
            f"{sorted(dims)} — refusing rather than silently dropping a dimension "
            f"(grouped metrics: {grouped})")
    return covering


def _head_word(name: str) -> str:
    """The HEAD noun of a property name: storeZone -> "zone", coreZonePermit -> "permit".

    Dimantion matching used to test `_camel_words(gb) & toks` — ANY camel word. With the profile's
    alias 区域 -> "zone", the question 「按门店区域看破损箱数」 produced `zone`, which matched
    BOTH :storeZone and :coreZonePermit (core-zone-permit), so the conjunction "grouped by
    storeZone AND coreZonePermit" matched no metric and a perfectly answerable sample REFUSED.
    The head noun is the word that distinguishes one dimension from another.
    """
    parts = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+", name or "")
    return parts[-1].lower() if parts else (name or "").lower()


def _group_dims(question: str, menu_: dict) -> set[str]:
    """Which GROUP BY dimensions the question mentions.

    A dimension is matched by a WORD of the question, not by a whole property name: the profile's
    alias 区域 -> "zone" makes the word `zone` match both :storeZone and :coreZonePermit, so a
    question about 门店区域 produced the conjunction "grouped by storeZone AND coreZonePermit", which
    no metric satisfies — and a perfectly answerable sample refused. The rule: keep the dimensions
    whose matched word is UNAMBIGUOUS (no other dimension matched the same word). An ambiguous word
    is dropped here; the label-literal matcher and the refusals downstream still see the question.
    """
    toks = _question_tokens(question)
    by_word: dict[str, set[str]] = {}
    for m in menu_["metrics"]:
        for gb in (m.get("group_by") or []):
            for word in (_camel_words(gb) & toks):
                by_word.setdefault(word, set()).add(gb)
    dims: set[str] = set()
    for word, owners in by_word.items():
        if len(owners) == 1:
            dims |= owners
    return dims


def interpret(question: str, menu_: dict | None = None) -> dict:
    """NL -> validated intent.

    RULES FIRST: the deterministic matcher runs before the model. Only when it is unsure
    (below the confidence bar) is the model asked; when there is no model at all the old
    keyword fallback runs. Off-menu results are refused by name either way.
    """
    menu_ = menu_ or menu()
    covering = _check_dimensions(question, menu_)
    if RULES_FIRST:
        guess = _rule_intent(question, menu_,
                             only_metrics=_check_dimensions(question, menu_) or None)
        if guess is not None:
            try:
                validate(guess, menu_)
                return guess
            except NlRefusal:
                pass              # the rules misfired; the model gets a chance
    intent = _raw_intent(question, menu_)
    validate(intent, menu_)
    return intent


def validate(intent: dict, menu_: dict) -> None:
    kind = intent.get("kind")
    if kind not in {"metric", "class", "action"}:
        raise NlRefusal(
            "I can answer about: metrics "
            f"{[m['name'] for m in menu_['metrics']]}, classes "
            f"{[c['name'] for c in menu_['classes']]}, or dry-run an action "
            f"{[a['name'] for a in menu_['actions']]}")
    pool = {"metric": menu_["metrics"], "class": menu_["classes"],
            "action": menu_["actions"]}[kind]
    name = intent.get("name")
    if name not in {e["name"] for e in pool}:
        raise NlRefusal(f"{kind} {name!r} is not on the menu — refusing rather than guessing "
                        f"(available: {[e['name'] for e in pool]})")
    if kind == "action":
        spec = next(e for e in pool if e["name"] == name)
        params = intent.get("params") or {}
        missing = [p for p in spec["parameters"] if p not in params]
        if missing:
            raise NlRefusal(f"{name} needs parameter(s) {missing}; the question did not "
                            f"provide them")
        # local models often return "2" for an integer parameter: coerce numeric strings
        # to the DECLARED type instead of failing on a technicality (the engine's type
        # gate still rejects anything that is not really a number)
        specs = spec.get("param_specs") or {}
        for pname, pspec in specs.items():
            v = params.get(pname)
            if isinstance(v, str):
                if pspec["type"] == "integer" and re.fullmatch(r"-?\d+", v):
                    params[pname] = int(v)
                elif pspec["type"] == "number" and re.fullmatch(r"-?\d+(\.\d+)?", v):
                    params[pname] = float(v)
        intent["params"] = params
        try:
            actions._validate_params(name, {"param_specs": specs}, params)
        except actions.Refusal as exc:
            raise NlRefusal(f"{name}: {exc}")


# ------------------------------------------------------------------ execution
def _exec_metric(intent: dict, plan: dict, cur, graph) -> dict:
    name = intent["name"]
    slots = intent.get("slots") or {}
    filters = {"customer_id": (slots.get("CustomerFilter") or {}).get("customer_id"),
               "since": (slots.get("TimeWindow") or {}).get("since"),
               "until": (slots.get("TimeWindow") or {}).get("until")}
    filters = {k: v for k, v in filters.items() if v is not None}
    compiled = sqlgen.compile_metric(graph, name, **filters)
    g = guard.run(cur, compiled.sql, filters or None, mode="declared")  # a metric is its definition
    rows = g["rows"]
    out = {"kind": "metric", "name": name, "sql": g["sql"], "compiled_sql": compiled.sql,
           "guard": {"notes": g["notes"], "plan_rows": g.get("plan_rows"), "ms": g.get("ms")},
           "notes": compiled.notes, "slots": slots, "filters": filters}
    if " GROUP BY " in compiled.sql:
        out["rows"] = ([{"keys": [str(x) for x in r[:-1]], "value": _val(r[-1])}
                        for r in rows] if len(rows[0]) > 2
                       else [{"key": str(r[0]), "value": _val(r[1])} for r in rows])
        out["value"] = None
    else:
        out["value"] = _val(rows[0][0]) if rows else None
    return out


def _exec_class(intent: dict, plan: dict, cur, graph) -> dict:
    name = intent["name"]
    base = sqlgen.concept_base_class(graph, name)
    table = plan["table"] or sqlgen.table_of(graph, base or name)
    pred = None
    try:
        pred = sqlgen.concept_sql(graph, name)
    except sqlgen.Refusal:
        pass
    where = f" WHERE {pred}" if pred else ""
    g = guard.run(cur, f"SELECT count(*) FROM {table}{where}", mode="declared")
    total = g["rows"][0][0]
    cols = [c for c in (sqlgen.class_columns(graph, base or name) or {}).values()]
    label_col = "name" if "name" in cols else (cols[0] if cols else "*")
    g2 = guard.run(cur, f"SELECT {label_col} FROM {table}{where} ORDER BY 1 LIMIT 5")
    sample = [r[0] for r in g2["rows"]]
    return {"kind": "class", "name": name, "sql": g["sql"], "compiled_sql":
            f"SELECT count(*) FROM {table}{where};",
            "guard": {"notes": g["notes"], "plan_rows": g.get("plan_rows"), "ms": g.get("ms")},
            "value": total, "sample": sample, "predicate": pred}


def _exec_action(intent: dict, plan: dict, cur, graph) -> dict:
    name = intent["name"]
    params = intent.get("params") or {}
    dry = actions.check_action(name, params,
                               compiled=actions.compile_actions(graph, actions.load_config()))
    return {"kind": "action", "name": name, "sql": dry.get("effect_bound") or dry["effect"],
            "dry_run": dry,
            "requires_confirmation": bool(dry["admitted"]),
            "note": "dry-run only — the write happens only after an explicit confirm, "
                    "through lane C with an audit row"}


# Dispatch is a registry keyed on the capability node's kind — the graph already decided
# WHICH node and validated the path (metrics reach a table, actions apply to a class).
EXECUTORS = {
    "metric": _exec_metric,
    "class": _exec_class,
    "action": _exec_action,
}


def execute(intent: dict, cur, graph, menu_: dict | None = None) -> dict:
    """Resolve the intent against the capability graph, then run its registered executor.

    Reads only; an action is ALWAYS a dry-run here. No `if kind == ...` dispatch: the
    graph refuses by name when no path exists, the registry picks the executor otherwise.
    """
    cap = capability.build(graph, menu_ or menu())
    plan = capability.resolve(intent, cap)
    result = EXECUTORS[plan["node"]["kind"]](intent, plan, cur, graph)
    result["capability_path"] = capability.edges_text(plan)
    return result


def _val(v):
    """Decimal -> int when integral, else float (4, not 4.0; 599.5 stays 599.5)."""
    if hasattr(v, "as_integer_ratio"):
        return int(v) if v == int(v) else float(v)
    return v


# ------------------------------------------------------------------ verbalization
ANSWER_RULES = """You write the final answer for a business user. The system already computed
the result from a compiled, audited query — rewrite it naturally, do not re-derive it.

Rules:
- Answer in the user's language (Chinese if the question is Chinese).
- Use ONLY the numbers/keys listed in RESULT: repeat each one exactly as given (same digits,
  do not round, do not add a unit that is not in the result). Never compute a new number.
- At most three sentences; if RESULT has rows, one lead sentence plus a compact list
  ("key: value" lines) is fine. No markdown tables or headings, no "Based on the data".
- Keep result KEYS and metric/class names EXACTLY as written in RESULT — never translate
  them (translate only the surrounding prose).
- Print numbers as plain digits: no currency symbols, no unit words, no thousand separators.
- Name the metric/class the answer came from and say what it means in one short clause.
- If the result is an action dry-run, say it was dry-run and that confirming is required to
  write; repeat ADMITTED/REFUSED as given.
- If the result is a refusal, explain by name what was missing (no invention)."""


def _result_numbers(result: dict) -> list[str]:
    """The numbers/keys the polished answer must echo exactly."""
    out: list[str] = []
    v = result.get("value")
    if v is not None and not isinstance(v, bool):
        out.append(str(v))
        if isinstance(v, float):
            out.append(f"{v:.2f}")
    for r in result.get("rows") or []:
        val = r.get("value")
        if val is not None:
            out.append(str(val))
            if isinstance(val, float):
                out.append(f"{val:.2f}")
        if r.get("key"):
            out.append(str(r["key"]))
        for k in r.get("keys") or []:
            out.append(str(k))
    if result.get("dry_run") is not None:
        out.append("ADMITTED" if result["dry_run"].get("admitted") else "REFUSED")
    return out


def _language_mismatch(question: str, text: str) -> bool:
    """The polish must be in the question's language (local models ignore this often)."""
    zh_q = any("\u4e00" <= ch <= "\u9fff" for ch in question)
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    ratio = cjk / max(1, len(text))
    if zh_q:
        return ratio < 0.05
    return ratio > 0.20


def _answer_trustworthy(text: str, result: dict) -> bool:
    """The polish must not invent or drop the computed numbers.

    Local models are the risk: they re-calculate, round differently, or answer the
    template's question instead of the user's. If any expected number/key/verdict is
    missing, the answer falls back to the deterministic template.
    """
    if not text or len(text) < 8:
        return False
    low = text.lower()
    for expected in _result_numbers(result):
        needle = expected.lower()
        if needle not in low:
            # allow numeric equality (599.5 vs 599.50) without string equality
            try:
                num = float(expected)
            except ValueError:
                return False
            import re as _re
            if not any(abs(float(m) - num) < 1e-9
                       for m in _re.findall(r"-?\d+(?:\.\d+)?", text)):
                return False
    return True


def answer(question: str, intent: dict, result: dict, lang: str = "en") -> dict:
    """Polish the result with the model, then VERIFY the polish.

    Every answer goes through the model when one is available (`NL_ANSWER_LLM=0` disables
    it). The polish is checked afterwards — `_answer_trustworthy` (every number, key and
    ADMITTED/REFUSED verdict must appear verbatim) and `_language_mismatch` (the answer
    must be in the question's language). A polish that fails either check is discarded and
    the deterministic template answers instead, so the user always sees correct numbers.
    Returns {"text", "source"} for the step trace.
    """
    polish = os.getenv("NL_ANSWER_LLM", "1") != "0"
    llm = _llm() if polish else None
    if llm is not None:
        zh = any("\u4e00" <= ch <= "\u9fff" for ch in question)
        language = "Chinese" if zh else "English"
        prompt = (ANSWER_RULES + f"\nLANGUAGE: {language} (write the answer in {language} only)."
                  "\n\nQUESTION: " + question + "\nINTENT: " +
                  json.dumps(intent, ensure_ascii=False) + "\nRESULT: " +
                  json.dumps(result, ensure_ascii=False, default=str))
        try:
            text = llm.invoke(prompt).content.strip()
            if not text:
                return {"text": _template_answer(question, intent, result, lang),
                        "source": "template (empty polish)"}
            if _language_mismatch(question, text):
                return {"text": _template_answer(question, intent, result, lang),
                        "source": "template (polish rejected: wrong language)"}
            if not _answer_trustworthy(text, result):
                return {"text": _template_answer(question, intent, result, lang),
                        "source": "template (polish rejected: a number or key changed)"}
            return {"text": text, "source": f"llm ({_backend_name()})"}
        except Exception:  # noqa: BLE001 — a failed polish is not a failed answer
            return {"text": _template_answer(question, intent, result, lang),
                    "source": "template (polish failed)"}
    return {"text": _template_answer(question, intent, result, lang),
            "source": "template (disabled)" if not polish else "template (no model)"}


def _template_answer(question: str, intent: dict, result: dict, lang: str) -> str:
    zh = _norm(question).startswith(("什么", "多少", "几", "是", "how")) is False and \
        any("\u4e00" <= ch <= "\u9fff" for ch in question)
    kind, name = result["kind"], result["name"]
    if result.get("rows"):
        rows = result["rows"]
        shown = rows[:8]                      # a 1000-group answer must not become the sentence
        parts = " · ".join(
            (" / ".join(r["keys"]) if "keys" in r else r["key"]) + f": {r['value']}"
            for r in shown)
        if len(rows) > len(shown):
            parts += (" · … 还有 %d 组" % (len(rows) - len(shown)) if zh
                      else " · … %d more groups" % (len(rows) - len(shown)))
        if zh:
            return f"{name} 按组拆分：{parts}。口径（编译 SQL）：{result['sql']}"
        return f"{name} by group — {parts}. Compiled SQL: {result['sql']}"
    if kind == "metric":
        if result["value"] is None:
            if zh:
                return f"在所选过滤/时间窗内没有数据（{name}）。口径（编译 SQL）：{result['sql']}"
            return f"No data in the requested window for {name}. Compiled SQL: {result['sql']}"
        if zh:
            return f"{name} 的值是 {result['value']}。口径（编译 SQL）：{result['sql']}"
        return f"{name} = {result['value']}. Compiled SQL: {result['sql']}"
    if kind == "class":
        if zh:
            return (f"{name} 有 {result['value']} 个，例如：{result.get('sample')}。"
                    f"编译 SQL：{result['sql']}")
        return (f"{name} has {result['value']} instance(s), e.g. {result.get('sample')}. "
                f"Compiled SQL: {result['sql']}")
    dry = result["dry_run"]
    verdict = "ADMITTED (dry-run)" if dry["admitted"] else "REFUSED (dry-run)"
    if zh:
        return (f"{name} 预演结果：{verdict}。未写入任何数据；确认后才会通过 lane C 执行并留审计。"
                f"效果：{result['sql']}")
    return (f"{name} dry-run: {verdict}. Nothing was written; confirm to execute through "
            f"lane C (audited). Effect: {result['sql']}")


# ------------------------------------------------------------------ end to end
def _filters_of(intent: dict) -> dict:
    slots = intent.get("slots") or {}
    filters = {"customer_id": (slots.get("CustomerFilter") or {}).get("customer_id"),
               "since": (slots.get("TimeWindow") or {}).get("since"),
               "until": (slots.get("TimeWindow") or {}).get("until")}
    return {k: v for k, v in filters.items() if v is not None}


def _understanding(intent: dict, plan: dict, graph, question: str) -> dict:
    """The natural-language restatement of what the system understood, tied to the
    compiled query and the capability path — this is what the user confirms."""
    kind, name = intent["kind"], intent["name"]
    slots = intent.get("slots") or {}
    zh = any("\u4e00" <= ch <= "\u9fff" for ch in question)
    path = capability.edges_text(plan)
    sql = None
    if kind == "metric":
        sql = sqlgen.compile_metric(graph, name, **_filters_of(intent)).sql
    elif kind == "action":
        try:
            sql = actions.compile_actions(graph, actions.load_config())[name]["effect_sql"]
        except Exception:  # noqa: BLE001 — the echo is a courtesy; never fail here
            sql = None
    elif kind == "class":
        sql = plan.get("sql") or "(count over the class)"

    lines = []
    if zh:
        lines.append(f"我的理解：{kind} {name}")
        cf = slots.get("CustomerFilter")
        if cf:
            lines.append(f"  · 客户限定：customer_id = {cf.get('customer_id')}")
        tw = slots.get("TimeWindow")
        if tw:
            since = (tw.get("since") or "")[:10]
            until = (tw.get("until") or "")[:10]
            lines.append(f"  · 时间窗：{tw.get('label') or ''}（{since} → {until}）")
        if sql:
            lines.append(f"将执行：{sql}")
        lines.append(f"依据（能力路径）：{' · '.join(path)}")
        lines.append("确认后执行。" + ("动作类确认后经 lane C 写入并留审计。" if kind == "action" else ""))
    else:
        lines.append(f"I understand: {kind} {name}")
        cf = slots.get("CustomerFilter")
        if cf:
            lines.append(f"  · customer filter: customer_id = {cf.get('customer_id')}")
        tw = slots.get("TimeWindow")
        if tw:
            since = (tw.get("since") or "")[:10]
            until = (tw.get("until") or "")[:10]
            lines.append(f"  · time window: {tw.get('label') or ''} ({since} → {until})")
        if sql:
            lines.append(f"I will run: {sql}")
        lines.append(f"Basis (capability path): {' · '.join(path)}")
        lines.append("Confirm to execute." + (" Confirming an action writes through lane C with an audit row." if kind == "action" else ""))
    return {"text": "\n".join(lines), "slots": slots, "sql": sql, "path": path}


def _ms(t0: float) -> int:
    return max(0, int(round((time.perf_counter() - t0) * 1000)))


def ask(question: str, confirm: bool = False, record: bool = True, graph=None,
        slots: bool = True) -> dict:
    """End-to-end. A COMPLEX question (slots, or an action) is echoed back as an
    understanding and requires `confirm=True` before the read runs / the action is
    suggested for a write. Simple questions answer immediately.

    Every outcome is appended to `nl_events` (refusal telemetry); `record=False` is for
    gates so their synthetic questions do not pollute the backlog.
    """
    try:
        out = _ask(question, confirm, graph, slots)
    except (NlRefusal, capability.CapabilityError) as exc:
        polished = _polish_refusal(question, str(exc))
        if isinstance(exc, NlRefusal):
            exc.polished = polished
        else:
            exc = NlRefusal(str(exc), polished)
        if record:
            _record(question, False, str(exc), _refusal_kind(str(exc)))
        raise exc
    if record:
        stage = next((st for st in out.get("steps", []) if st["step"].startswith("2")), {})
        _record(question, True, None, None, out.get("intent"),
                backend=stage.get("backend") or _backend_name())
    return out


def _ask(question: str, confirm: bool = False, graph=None, slots: bool = True) -> dict:
    """`graph` lets a caller answer against another ontology (the tutorial's overlay, for
    instance) — the pipeline is the same one /query runs, only the menu differs."""
    steps: list[dict] = []

    t = time.perf_counter()
    menu_ = menu(graph)
    steps.append({
        "step": "1 · menu",
        "ms": _ms(t),
        "detail": f"{len(menu_['metrics'])} metrics · {len(menu_['classes'])} classes · "
                  f"{len(menu_['actions'])} actions — built from the compiled ontology "
                  f"(sqlgen + actions.compile_actions), read-only",
    })

    t = time.perf_counter()
    covering = _check_dimensions(question, menu_)
    used_rules = False
    intent = (_rule_intent(question, menu_, only_metrics=covering or None)
              if RULES_FIRST else None)
    if intent is not None:
        validate(intent, menu_)     # rules must pass the SAME gate as the model
        used_rules = True
    else:
        intent = _raw_intent(question, menu_)
    steps.append({
        "step": "2 · interpret",
        "ms": _ms(t),
        "detail": f"{intent['kind']} {intent['name']}"
                  + (f" params={intent['params']}" if intent.get("params") else ""),
        "backend": "rules (deterministic, no llm)" if used_rules else _backend_name(),
    })

    t = time.perf_counter()
    validate(intent, menu_)
    steps.append({
        "step": "3 · validate",
        "ms": _ms(t),
        "detail": "name is on the menu · parameters match the declared types "
                  "(off-menu or untyped -> refused by name)",
    })

    if not slots:                   # a caller may own the constraints itself
        intent["slots"] = {}
    else:
        # SLOT PRESERVATION. The rules attach the constraints a question states; the MODEL does not,
        # and nothing used to notice. Measured: "order revenue last 90 days" came back from the model
        # as {kind: metric, name: orderRevenue} with no slots, compiled to `SELECT sum(amount)` with no
        # WHERE, and answered the all-time total — the period vanished from a question that stated it.
        # A SECOND shape of the same failure was measured later: the model returned
        # `{"TimeWindow": {"days": 90}}` — a slot that EXISTS but is UNTYPED, so `since`/`until` were
        # never computed and the window was silently dropped again. Presence is not typing.
        stated = _slots(question)
        current = intent.get("slots") or {}
        tw = current.get("TimeWindow") or {}
        untyped = bool(stated and "TimeWindow" in stated
                       and not (tw.get("since") and tw.get("until")))
        if stated and (not current or untyped):
            intent["slots"] = {**current, **stated}   # the typed form wins over an untyped one
            steps.append({
                "step": "2b · slots",
                "ms": 0,
                "detail": ("the question states " + ", ".join(sorted(stated))
                           + " — attached before executing; a metric that does not declare it is "
                             "refused rather than answered without it"),
            })
    t = time.perf_counter()
    graph = graph if graph is not None else actions.load_graph()
    cap = capability.build(graph, menu_)
    try:
        plan = capability.resolve(intent, cap)
    except capability.CapabilityError as exc:
        steps.append({"step": "4 · execute", "ms": _ms(t), "detail": f"REFUSED — {exc}"})
        raise NlRefusal(str(exc))
    needs_confirm = bool(intent.get("slots")) or intent.get("kind") == "action"
    if needs_confirm and not confirm:
        if intent.get("kind") == "metric":
            understanding = _understanding(intent, plan, graph, question)
            understanding["text"] = _polish_understanding(question, understanding["text"])
            steps.append({"step": "4 · execute", "ms": _ms(t),
                          "detail": "complex query — awaiting confirmation",
                          "path": capability.edges_text(plan)})
            return {"ok": True, "needs_confirmation": True, "question": question,
                    "intent": intent, "understanding": understanding,
                    "steps": steps, "total_ms": sum(st["ms"] for st in steps)}
        # an action: the dry-run is safe, so run it and ask the user to confirm the WRITE
    conn = psycopg2.connect(**actions.dsn())
    try:
        cur = conn.cursor()
        try:
            result = execute(intent, cur, graph, menu_)
        except capability.CapabilityError as exc:
            conn.rollback()
            steps.append({"step": "4 · execute", "ms": _ms(t),
                          "detail": f"REFUSED — {exc}"})
            raise NlRefusal(str(exc))
        conn.rollback()   # reads only; even the action dry-run must leave nothing behind
    finally:
        conn.close()
    steps.append({
        "step": "4 · execute",
        "ms": _ms(t),
        "detail": result["sql"],
        "value": result.get("value", result.get("dry_run", {}).get("admitted")),
        "path": result.get("capability_path"),
    })

    t = time.perf_counter()
    ans = answer(question, intent, result)
    steps.append({
        "step": "5 · answer",
        "ms": _ms(t),
        "detail": ("narrated by the model" if ans["source"] == "llm"
                   else "deterministic template (value + compiled SQL)"),
        "source": ans["source"],
    })
    total = sum(st["ms"] for st in steps)
    understanding = _understanding(intent, plan, graph, question) if needs_confirm else None
    if understanding and intent.get("kind") == "action":
        steps.append({"step": "5 · confirm", "ms": _ms(t),
                      "detail": "action dry-run shown — confirm to write (audited)"})
    return {"ok": True, "question": question, "intent": intent,
            "result": result, "answer": ans["text"], "answer_source": ans["source"],
            "steps": steps, "total_ms": total,
            "understanding": understanding, "needs_confirmation": False}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="natural-language query over the ontology")
    ap.add_argument("question", nargs="?", help="the question (zh or en)")
    ap.add_argument("--menu", action="store_true", help="print the menu the LLM chooses from")
    ap.add_argument("--show-prompt", action="store_true",
                    help="print the exact intent prompt sent to the model")
    ap.add_argument("--confirm", action="store_true",
                    help="execute a complex query instead of echoing the understanding")
    ap.add_argument("--backlog", action="store_true",
                    help="print the refusal backlog (what to declare next, from data)")
    args = ap.parse_args()
    if args.menu:
        print(json.dumps(menu(), indent=2, default=str))
        return 0
    if args.backlog:
        print(json.dumps(backlog(), indent=2, ensure_ascii=False, default=str))
        return 0
    if args.show_prompt:
        print(_intent_prompt(args.question or "", menu()))
        return 0
    if not args.question:
        ap.print_help()
        return 1
    try:
        print(json.dumps(ask(args.question, confirm=args.confirm), indent=2,
                         ensure_ascii=False, default=str))
        return 0
    except (NlRefusal, capability.CapabilityError) as exc:
        print(json.dumps({"ok": False, "refused": str(exc),
                          "answer": getattr(exc, "polished", str(exc))},
                         ensure_ascii=False, indent=2))
        return 2
    except Exception as exc:  # noqa: BLE001 — an internal error is still a JSON result
        print(json.dumps({"ok": False,
                          "refused": f"{type(exc).__name__}: {exc}",
                          "answer": "The query layer hit an internal error; nothing was "
                                    "written. Please retry."},
                         ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
