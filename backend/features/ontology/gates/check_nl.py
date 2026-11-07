#!/usr/bin/env python3
"""check_nl.py — gates for the natural-language layer.

The LLM must never be trusted with SQL or arithmetic. These gates assert the contract:

    N1  the menu is complete: every declared metric/class/action is exposed to the model
    N2  an intent naming something OFF the menu is refused BY NAME (no free SQL)
    N3  metric answers carry the value the compiled SQL produces (SQL computes, not the LLM)
    N4  an action intent is ALWAYS a dry-run: nothing written, no audit row; execution
        requires an explicit confirm (the /api/actions/run path)
    N5  the deterministic fallback maps an English question to the right metric and
        refuses an out-of-menu question by name (offline behaviour without an API key)
    N6  the answer text contains the computed value and the compiled SQL (provenance)

With DEEPSEEK_API_KEY set the LLM path runs; without it the fallback path runs — both are
validated here. Run:
    /Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python check_nl.py
    /Users/weiping/dev/Learn/ontology/.venv/bin/python check_nl.py   # with LLM extras
"""
from __future__ import annotations

import os
import pathlib
import sys

import psycopg2

os.environ.setdefault("NL_TELEMETRY", "0")   # gate questions must not pollute the backlog

# The feature's roots: the COMPILER (this gate's imports), the WORKBENCH (the static assets it
# checks) and the PROFILES (the declarations). All relative to the feature directory — a gate that
# addresses "/Users/weiping/..." only runs on one machine.
import pathlib as _pathlib
import sys as _sys
sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1]))       # the _paths helper
from _paths import COMPILER as BASE, PROFILES, WORKBENCH, WORKBENCH as APP, profile_dir
# The compiler reads the profile from $APP_SETTINGS and applies its ns + ontology_dir + OVERLAY.
# Retail's metrics live in the overlay, so a gate that checks retail without this loaded an
# ontology with no metrics at all.
import os as _os
_os.environ["APP_SETTINGS"] = str(profile_dir("retail") / "settings.json")
# DETERMINISTIC PROSE for the whole gate. N9 asserts the confirmation echo's WORDING ("will run" /
# 「将执行」), and that wording is model-written whenever an LLM key is present — measured: with
# DEEPSEEK_API_KEY in the environment the echo said "The SQL query to achieve this is", so a check about
# the pipeline failed on a paraphrase. The gate is about the pipeline, so it runs without the model;
# N15 already did this, and the need was not specific to N15.
_os.environ["NL_ANSWER_LLM"] = "0"
_sys.path.insert(0, str(BASE))
sys.path.insert(0, str(WORKBENCH))
sys.path.insert(0, str(BASE))
import actions     # noqa: E402
import capability  # noqa: E402
import nl          # noqa: E402
import sqlgen      # noqa: E402

ok = True


def check(label: str, got, want) -> None:
    global ok
    state = "PASS" if got == want else "FAIL"
    ok = ok and got == want
    print(f"  [{state}] {label}: got {got!r}, want {want!r}")


def main() -> int:
    graph = actions.load_graph()
    menu = nl.menu(graph)

    print("=== N1 the menu is complete ===")
    declared = set(sqlgen.metrics(graph))
    exposed = {m["name"] for m in menu["metrics"]}
    check("every declared metric is on the menu", exposed, declared)
    check("classes include the declared class set",
          {"Customer", "Order", "PremiumCustomer"} <= {c["name"] for c in menu["classes"]}, True)
    check("actions include the compiled actions",
          {a["name"] for a in menu["actions"]}, {"PromoteCustomer", "DemoteCustomer",
                                                 "RecordOrder"})
    check("every menu metric carries its compiled SQL or a named refusal",
          all(m.get("sql") or m.get("refused") for m in menu["metrics"]), True)

    print("=== N2 off-menu intents are refused BY NAME ===")
    for bad in ({"kind": "metric", "name": "revenueOfEverything"},
                {"kind": "class", "name": "Gremlin"},
                {"kind": "none", "name": None}):
        try:
            nl.validate(bad, menu)
            check(f"intent {bad} refused", "accepted", "refused")
        except nl.NlRefusal as exc:
            check(f"intent {bad} refused",
                  "refused" if "not on the menu" in str(exc) or "can answer about" in str(exc)
                  else str(exc), "refused")

    print("=== N3 metric answers come from the compiled SQL ===")
    conn = psycopg2.connect(**actions.DSN)
    cur = conn.cursor()
    def db_value(sql):
        cur.execute(sql)
        return cur.fetchone()[0]
    wants = {
        "premiumCustomerRevenue": db_value(
            "SELECT sum(amount) FROM orders JOIN customers "
            "ON orders.customer_id = customers.id WHERE tier = 'PREMIUM'"),
        "orderRevenue": db_value("SELECT sum(amount) FROM orders"),
        "premiumCustomers": db_value(
            "SELECT count(*) FROM customers WHERE tier = 'PREMIUM'"),
    }
    for name in wants:
        want = float(wants[name])
        intent = nl._fallback_intent(
            {"premiumCustomerRevenue": "premium customer revenue",
             "orderRevenue": "order revenue",
             "premiumCustomers": "premium customers"}[name], menu)
        check(f"fallback maps the question to :{name}", intent["name"], name)
        result = nl.execute(intent, cur, graph)
        check(f":{name} value matches the direct SQL", float(result["value"]), want)
        check(f":{name} result carries its compiled SQL", bool(result["sql"]), True)
    conn.rollback()

    print("=== N4 an action intent is ALWAYS a dry-run (nothing written) ===")
    cur.execute("SELECT count(*) FROM audit_events")
    before = cur.fetchone()[0]
    # pick a customer the guard will actually ADMIT (STANDARD), so the dry-run is exercised
    cur.execute("SELECT id FROM customers WHERE tier IS DISTINCT FROM 'PREMIUM' "
                "ORDER BY id LIMIT 1")
    target = cur.fetchone()
    check("a STANDARD customer exists for the dry-run", bool(target), True)
    target = target[0] if target else 1
    intent = nl._fallback_intent(f"promote customer {target}", menu)
    check("fallback maps the verb to PromoteCustomer", intent["name"], "PromoteCustomer")
    result = nl.execute(intent, cur, graph)
    conn.rollback()
    cur.execute("SELECT count(*) FROM audit_events")
    check("no audit row from an NL action intent", cur.fetchone()[0], before)
    check("the intent requires confirmation", result["requires_confirmation"], True)
    check("the intent mentions the audit/confirm path",
          "confirm" in result["note"].lower(), True)

    print("=== N5 fallback: English maps, off-menu refuses ===")
    check("English question -> metric",
          nl._fallback_intent("how much is premium customer revenue?", menu)["name"],
          "premiumCustomerRevenue")
    try:
        nl.validate({"kind": "metric", "name": "gremlinRevenue"}, menu)
        check("off-menu question refused", "answered", "refused")
    except nl.NlRefusal:
        check("off-menu question refused", "refused", "refused")
    if os.getenv("DEEPSEEK_API_KEY"):
        zh = nl.interpret("高级客户的收入是多少？", menu)
        check("LLM path answers a Chinese question", zh["name"], "premiumCustomerRevenue")
    else:
        print("  [note] DEEPSEEK_API_KEY absent — LLM path not exercised (fallback verified)")

    print("=== N6 the answer carries the value and the SQL (provenance) ===")
    if nl._llm() is None:
        out = nl.ask("what is premium customer revenue?")
        res, ans, steps = out["result"], out["answer"], out["steps"]
    else:
        intent = nl.interpret("what is premium customer revenue?", menu)   # rules path
        res = nl.execute(intent, cur, graph)
        conn.rollback()
        ans = nl._template_answer("what is premium customer revenue?", intent, res, "en")
        steps = nl.ask("what is premium customer revenue?")["steps"]
    check("answer text contains the computed value", str(res["value"]) in ans, True)
    # with LLM polishing enabled the prose need not contain the SQL text; the provenance
    # (result["sql"]) always does. Check both paths: polish -> sql in result, template -> in answer
    check("the compiled SQL is carried in the result provenance", bool(res["sql"]), True)
    check("a template answer (no model) also carries the SQL",
          str(res["value"]) in ans and res["sql"] in ans if nl._llm() is None else True, True)
    check("the answer carries a 5-step trace (menu→interpret→validate→execute→answer)",
          [st["step"] for st in steps],
          ["1 · menu", "2 · interpret", "3 · validate", "4 · execute", "5 · answer"])
    check("every step carries its elapsed time in ms",
          all(isinstance(st.get("ms"), int) and st["ms"] >= 0 for st in steps), True)
    check("the trace carries a total_ms",
          isinstance(nl.ask("what is premium customer revenue?").get("total_ms"), int)
          if nl._llm() is None else True, True)

    print("=== N7 dispatch goes through the capability graph (no if/elif on kind) ===")
    cap = capability.build(graph, menu)
    from rdflib import OWL, RDF
    declared_slots = {("slot", sqlgen._local(slot)) for slot in
                      graph.subjects(RDF.type, OWL.Class)
                      if sqlgen._one(graph, slot, sqlgen.P("isSlot")) == "true"}
    expected_nodes = ({(k, e["name"]) for k, es in
                       (("metric", menu["metrics"]), ("class", menu["classes"]),
                        ("action", menu["actions"])) for e in es} | declared_slots)
    check("the graph covers every menu node plus the declared slots",
          {(k, n) for (k, n) in cap["nodes"]}, expected_nodes)
    for m in menu["metrics"]:
        plan = capability.resolve({"kind": "metric", "name": m["name"]}, cap)
        kinds = {e["kind"] for e in plan["path"]}
        check(f":{m['name']} resolves with a measures edge to a table",
              {"measures"} <= kinds and {"measures", "physicalTable"} <= kinds, True)
    for c in menu["classes"]:
        plan = capability.resolve({"kind": "class", "name": c["name"]}, cap)
        check(f":{c['name']} resolves to a table",
              plan["path"][0]["kind"], "physicalTable")
    plan = capability.resolve({"kind": "action", "name": "PromoteCustomer",
                               "params": {"customer_id": 1}}, cap)
    check("an action resolves through appliesTo to a table",
          [e["kind"] for e in plan["path"]], ["appliesTo", "physicalTable"])
    try:
        capability.resolve({"kind": "metric", "name": "revenueOfEverything"}, cap)
        check("an unknown intent is refused by name", "accepted", "refused")
    except capability.CapabilityError as exc:
        check("an unknown intent is refused by name",
              "capability graph" in str(exc) or "not on" in str(exc), True)
    # mutation: a metric whose class loses its table edge must be refused
    mut = {"nodes": dict(cap["nodes"]),
           "edges": [e for e in cap["edges"]
                     if e["kind"] != "physicalTable"]}
    try:
        capability.resolve({"kind": "metric", "name": "orderRevenue"}, mut)
        check("a metric with no reachable table is refused", "accepted", "refused")
    except capability.CapabilityError as exc:
        check("a metric with no reachable table is refused",
              "reaches no physical table" in str(exc), True)

    print("=== N8 slots: supported execute, unsupported refuse BY NAME ===")
    check(":orderRevenue declares :CustomerFilter",
          bool([e for e in cap["edges"] if e["src"] == "orderRevenue"
                and e["kind"] == "supportsSlot" and e["dst"] == "CustomerFilter"]), True)
    check(":orderRevenue declares :TimeWindow",
          bool([e for e in cap["edges"] if e["src"] == "orderRevenue"
                and e["kind"] == "supportsSlot" and e["dst"] == "TimeWindow"]), True)
    check(":RegionFilter is declared but unsupported (the refusal example)",
          any(e["kind"] == "supportsSlot" and e["dst"] == "RegionFilter"
              for e in cap["edges"]), False)
    plan = capability.resolve({"kind": "metric", "name": "orderRevenue",
                               "slots": {"CustomerFilter": {"customer_id": 1}}}, cap)
    check("a supported slot resolves", plan["node"]["name"], "orderRevenue")
    # the filter must be real SQL, and the value must match the direct query
    intent = nl._fallback_intent("order revenue for customer 1", menu) or {
        "kind": "metric", "name": "orderRevenue",
        "slots": {"CustomerFilter": {"customer_id": 1}}}
    intent["slots"] = {"CustomerFilter": {"customer_id": 1}}
    res = nl.execute(intent, cur, graph, menu)
    conn.rollback()
    cur.execute("SELECT coalesce(sum(amount),0) FROM orders WHERE customer_id = 1")
    check("the slot filter reaches the SQL", round(float(res["value"]), 2),
          round(float(cur.fetchone()[0]), 2))
    try:
        capability.resolve({"kind": "metric", "name": "orderRevenue",
                            "slots": {"RegionFilter": {}}}, cap)
        check("an unsupported slot is refused", "accepted", "refused")
    except capability.CapabilityError as exc:
        check("an unsupported slot is refused",
              "does not support the RegionFilter slot" in str(exc), True)
    mut = {"nodes": dict(cap["nodes"]),
           "edges": [e for e in cap["edges"] if e["kind"] != "supportsSlot"]}
    try:
        capability.resolve({"kind": "metric", "name": "orderRevenue",
                            "slots": {"CustomerFilter": {"customer_id": 1}}}, mut)
        check("mutation: removing supportsSlot refuses the slot", "accepted", "refused")
    except capability.CapabilityError as exc:
        check("mutation: removing supportsSlot refuses the slot",
              "does not support the CustomerFilter slot" in str(exc), True)
    check("slots are extracted deterministically (EN)",
          nl._slots("order revenue for customer 2"), {"CustomerFilter": {"customer_id": 2}})
    check("slots are extracted deterministically (ZH time)",
          "TimeWindow" in nl._slots("上个月的高级客户收入"), True)

    print("=== N9 complex queries are confirmed before they run ===")
    complex_q = "order revenue for customer 1"
    out = nl.ask(complex_q)                      # no confirm -> understanding only
    check("a slot query defers execution", out.get("needs_confirmation"), True)
    check("no value is executed before confirmation", "result" in out, False)
    ut = out["understanding"]["text"]
    check("the echo states what will run", "will run" in ut.lower() or "将执行" in ut, True)
    check("the echo carries the capability path",
          "capability path" in ut.lower() or "能力路径" in ut, True)
    check("the echo carries the slot values", "customer_id = 1" in ut, True)
    out2 = nl.ask(complex_q, confirm=True)       # confirmed -> executes
    cur.execute("SELECT coalesce(sum(amount),0) FROM orders WHERE customer_id = 1")
    check("confirming executes and matches the direct query",
          round(float(out2["result"]["value"]), 2), round(float(cur.fetchone()[0]), 2))
    simple = nl.ask("how many orders do we have?")
    check("a simple question does not ask for confirmation",
          simple.get("needs_confirmation"), False)

    print("=== N13 LLM polish is guarded: numbers must survive the rewrite ===")
    good = {"value": 599.5, "sql": "SELECT 1"}
    check("an answer that echoes the number is accepted",
          nl._answer_trustworthy("Premium revenue is 599.5 across all orders.", good), True)
    check("a rounded/renamed number is rejected",
          nl._answer_trustworthy("Premium revenue is about 600.", good), False)
    check("a number-less rewrite is rejected",
          nl._answer_trustworthy("Premium revenue looks healthy.", good), False)
    rows = {"rows": [{"key": "Shanghai", "value": 599.5},
                     {"key": "Shenzhen", "value": 370.0}], "sql": "SELECT 2"}
    check("grouped answers must keep every key and value",
          nl._answer_trustworthy("By city: Shanghai 599.5, Shenzhen 370.", rows), True)
    check("a grouped answer that drops a row is rejected",
          nl._answer_trustworthy("By city: Shanghai 599.5.", rows), False)
    dry = {"dry_run": {"admitted": True}, "sql": "SELECT 3"}
    check("an action verdict must be repeated",
          nl._answer_trustworthy("Dry-run: ADMITTED, confirm to write.", dry), True)
    check("a missing verdict is rejected",
          nl._answer_trustworthy("The action looks fine.", dry), False)
    check("an English question answered in Chinese is rejected",
          nl._language_mismatch("premium product revenue", "高级产品收入是620。"), True)
    check("a Chinese question answered in Chinese is accepted",
          nl._language_mismatch("高级客户收入", "高级客户收入是620。"), False)
    check("an English question answered in English is accepted",
          nl._language_mismatch("premium product revenue", "Premium revenue is 620."), False)

    print("=== N10 grouped questions: one dimension, region=city, 2+ dimensions refused ===")
    check("revenue by product resolves to the grouped metric",
          nl.interpret("revenue by product", menu)["name"], "revenueByProduct")
    check("region is approximated by the city dimension",
          nl.interpret("revenue by region", menu)["name"], "revenueByCity")
    check("a grouped metric's rows are returned",
          bool(nl.ask("revenue by product")["result"].get("rows")), True)
    two = nl.interpret("revenue by region and by product", menu)
    check("two dimensions resolve to the covering metric", two["name"],
          "revenueByProductCity")
    rows = nl.ask("revenue by product and city")["result"]["rows"]
    check("two-key rows come back", all("keys" in r for r in rows) and len(rows) > 0, True)
    # a combination with NO covering metric must still be refused (no silent drop)
    menu_no_two = {**menu,
                   "metrics": [m for m in menu["metrics"]
                               if m["name"] != "revenueByProductCity"]}
    try:
        nl._check_dimensions("revenue by region and by product", menu_no_two)
        check("an uncovered two-dimension question is refused", "accepted", "refused")
    except nl.NlRefusal as exc:
        check("an uncovered two-dimension question is refused",
              "refused" if "no declared metric groups by" in str(exc) else str(exc),
              "refused")
    conn.close()

    print("=== N11 refusal telemetry feeds the declaration backlog (read-only) ===")
    os.environ["NL_TELEMETRY"] = "1"          # switch recording on just for this gate
    try:
        nl.ask("how many gremlins do we have?") if False else None
        try:
            nl.ask("how many gremlins do we have?")
            check("an off-menu question is refused", "answered", "refused")
        except nl.NlRefusal:
            check("an off-menu question is refused", "refused", "refused")
        b = nl.backlog()
        check("the refusal was recorded with a kind",
              any(i["question"] == "how many gremlins do we have?" and
                  i["kind"] == "off_menu" for i in b["items"]), True)
        check("every backlog item carries a suggested declaration",
              all(i.get("suggestion") for i in b["items"]), True)
        check("the backlog counts answered and refused",
              b["answered"] >= 0 and b["refused"] >= 0, True)
    finally:
        os.environ["NL_TELEMETRY"] = "0"      # leave the environment as we found it

    print("=== N12 salient-noun check: rules defer instead of answering a truncated question ===")
    check("a question with an unknown noun does NOT fire the rules",
          nl._rule_intent("which premium people bought boots?", menu), None)
    # rules still fire on well-formed questions (the check must not be over-eager)
    for q, want in (("premium product revenue", "premiumProductRevenue"),
                    ("revenue by product", "revenueByProduct"),
                    ("order revenue by region", "revenueByCity"),
                    ("how many orders", "orderCount")):
        got = nl._rule_intent(q, menu)
        check(f"rules still answer {q!r}", got["name"] if got else None, want)
    check("a 'by X' question prefers a grouped metric (order revenue by region)",
          nl._rule_intent("order revenue by region", menu)["name"], "revenueByCity")
    check("slot constraints survive the noun check",
          nl._rule_intent("order revenue for customer 1", menu).get("slots"),
          {"CustomerFilter": {"customer_id": 1}})

    # ── N13 a question that asks for a NUMBER is never answered by a class ──────────────
    # Measured on the logistics ontology: "高风险线路数" was ANSWERED with a listing of :Route.
    # Chinese has no spaces, the CJK 2-grams are skipped by the salient-noun check above, and
    # the class won the tiebreak simply because its name is one word short. A count that no
    # metric declares must refuse — and a count that IS declared must find its metric even
    # when the class name is shorter ("订单数" must reach orderCount, not :Order).
    print("=== N13 a count is answered by a metric or refused — never by a class listing ===")
    for q, want in (("how many orders", "orderCount"), ("订单数", "orderCount"),
                    ("有多少订单", "orderCount"), ("order count", "orderCount")):
        check(f"a declared count finds its metric: {q!r}",
              nl._rule_intent(q, menu)["name"], want)
    for q, cls in (("how many order lines", ":OrderLine"), ("有多少条订单行", None),
                   ("订单行数", None)):
        # the Chinese cases name a class whose label the 2-gram tokenizer reduced to 订单, so
        # the refusal names the class it matched; what matters is that it refuses and says why.
        try:
            got = nl._rule_intent(q, menu)
            check(f"an undeclared count is refused: {q!r}", got["name"] if got else "refused",
                  "refused")
        except nl.NlRefusal as exc:
            msg = str(exc)
            check(f"an undeclared count is refused: {q!r}", "CLASS :" in msg, True)
            check(f"  … and the refusal says no metric declares it: {q!r}",
                  "no metric declares that count" in msg, True)
            if cls:
                check(f"  … and names the class it matched: {q!r}", cls in msg, True)
    # a LIST request still answers with the class (the rule must not eat honest class reads)
    for q, want in (("list order lines", "OrderLine"), ("list customers", "Customer"),
                    ("list products", "Product")):
        check(f"a list request still answers with the class: {q!r}",
              nl._rule_intent(q, menu)["name"], want)
    # "数据"/"参数" contain 数 and are nouns, not counts
    check("a noun that merely contains the cue is not a count request",
          nl._rule_intent("订单数据", menu).get("kind"), "class")

    # ── N15 a constraint the question states reaches the query, or the question is refused ──────
    # Measured: "order revenue last 90 days" came back from the MODEL path as {kind, name} with no
    # slots, compiled to `SELECT sum(amount)` with no WHERE, and answered the all-time total — the
    # period vanished. A question that states a period either carries that slot into the SQL, or it
    # asks for a confirmation first; answering without it is the bug this gate exists to prevent.
    print("=== N15 a stated constraint is carried, not dropped ===")
    out = nl.ask("order revenue last 90 days", record=False)
    slots = (out.get("intent") or {}).get("slots") or {}
    check("a period in the question becomes a TimeWindow slot",
          "TimeWindow" in slots, True)
    check("a slot question is echoed for confirmation before it runs",
          bool(out.get("needs_confirmation")), True)
    confirmed = nl.ask("order revenue last 90 days", confirm=True, record=False)
    sql = (confirmed.get("result") or {}).get("sql") or ""
    check("after confirmation the period is IN the SQL", "placed_at" in sql, True)
    check("… and the number is the windowed one, not the all-time total",
          (confirmed.get("result") or {}).get("value") != 969.5, True)

    print("=== N14 multi-dimension GROUP BY: every requested dimension survives ===")
    for q in ("revenue by product and city", "revenue by city and product",
              "按产品、城市的收入"):
        check(f"{q!r} resolves to the two-key metric",
              nl.interpret(q, menu).get("name"), "revenueByProductCity")
    # an unknown dimension must be named, never dropped so the rest can be answered
    for q, word in (("revenue by product and city and brand", "brand"),
                    ("按产品、城市、品牌的收入", "品牌")):
        try:
            nl.interpret(q, menu)
            check(f"{q!r}: unknown dimension refused", "accepted", "refused")
        except nl.NlRefusal as exc:
            check(f"{q!r}: the refusal names {word}", word in str(exc), True)
    # "per" is a rate, not a dimension: the declared ratio still answers
    check("'revenue per customer' is not read as a dimension",
          nl.interpret("revenue per customer", menu).get("name"), "revenuePerCustomer")
    # and the rows really carry both keys
    conn = psycopg2.connect(**actions.DSN)
    try:
        out = nl._exec_metric(nl.interpret("revenue by product and city", menu), {}, conn.cursor(),
                              actions.load_graph())
        keys = {len(r.get("keys") or []) for r in (out.get("rows") or [])}
        check("every row carries both group keys", keys, {2})
    finally:
        conn.close()

    print("=== N15 every sample question on the query pages actually works ===")
    # A sample that has rotted is worse than no sample: these are the buttons a reader
    # clicks first. Each one is run through the real pipeline, and the two that are meant
    # to be refused are named here so a broken sample cannot hide as an intended refusal.
    import re as _re
    import serve_ui
    os.environ["NL_ANSWER_LLM"] = "0"          # deterministic: numbers, not prose
    REFUSE_ON_PURPOSE = {"revenue by product and city and brand",
                         "revenue by product and brand",
                         "revenue by store", "revenue by city and brand"}

    def samples(filename: str, const: str) -> list[str]:
        html = (APP / filename).read_text(encoding="utf-8")
        block = _re.search(r"const " + const + r" = \[(.*?)\n\];", html, _re.S)
        return _re.findall(r'"([^"\n]+)"', block.group(1)) if block else []

    step6 = samples("tutorial6.html", "AEX")
    step7 = samples("tutorial7.html", "AEX")
    step8 = samples("tutorial8.html", "AEX")
    query = samples("nl.html", "EX")
    check("the metrics page offers samples", len(step6) >= 8, True)
    check("the products page offers samples", len(step7) >= 6, True)
    check("the stores page offers samples", len(step8) >= 5, True)
    check("the query page offers samples", len(query) >= 8, True)
    for q in step6:
        out = serve_ui.tutorial6_ask(q, 30)
        if q in REFUSE_ON_PURPOSE:
            check(f"metrics sample {q!r} is refused on purpose", out.get("ok"), False)
        else:
            check(f"metrics sample {q!r} is answered", bool(out.get("ok")), True)
    for q in step8:
        out = serve_ui.tutorial6_ask(q, None)
        if q in REFUSE_ON_PURPOSE:
            check(f"stores sample {q!r} is refused on purpose", out.get("ok"), False)
        else:
            check(f"stores sample {q!r} is answered", bool(out.get("ok")), True)
    for q in step7:
        out = serve_ui.tutorial6_ask(q, None)
        if q in REFUSE_ON_PURPOSE:
            check(f"products sample {q!r} is refused on purpose", out.get("ok"), False)
        else:
            check(f"products sample {q!r} is answered", bool(out.get("ok")), True)
    for q in query:
        try:
            out = nl.ask(q, record=False)
            got = bool(out.get("needs_confirmation") or out.get("result"))
        except nl.NlRefusal:
            got = False
        if q in REFUSE_ON_PURPOSE:
            check(f"query sample {q!r} is refused on purpose", got, False)
        else:
            check(f"query sample {q!r} is answered (or asks to confirm)", got, True)

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
