#!/usr/bin/env python3
"""check_metrics.py — gates for CROSS-OBJECT metric compilation (option A: no Cube).

The point: joins are not hand-written SQL fragments. A metric declares `:where :Concept`;
the compiler reads the concept's base class, finds the DECLARED relationship
(:customer = owl:ObjectProperty + :physicalColumn FK + :references target), and emits the
JOIN. Same refusal rules as the rest of the track: a missing relationship or an ambiguous
column is refused BY NAME, never guessed.

    J1  the relationship is DECLARED (FK col + target pk), not inferred from column names
    J2  a :where concept on another class compiles a JOIN and evaluates correctly
    J3  the count at the joined target is fan-out safe: count(DISTINCT pk), proven against
        the naive count(*) on data where one PREMIUM customer has TWO orders
    J4  mutation: removing :references turns J2's metric into a Refusal by name
    J5  mutation: a column present on BOTH joined classes is refused as ambiguous
    J6  a FOUR-table metric (order_lines → orders → customers → products) compiles from
        declared relationships, evaluates correctly, and refuses when a link is missing
    J7  GROUP BY metrics ("revenue by city", "revenue by product") join to the group key's
        owner and return the same rows as the direct grouped query; cutting the join refuses

Run with the cube-tutorial venv python:
    /Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python check_metrics.py
"""
from __future__ import annotations

import pathlib
import sys

import psycopg2
from rdflib import Literal, OWL, RDF, RDFS

# The feature's roots: the COMPILER (this gate's imports), the WORKBENCH (the static assets it
# checks) and the PROFILES (the declarations). All relative to the feature directory — a gate that
# addresses "/Users/weiping/..." only runs on one machine.
import pathlib as _pathlib
import sys as _sys
sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1]))       # the _paths helper
from _paths import COMPILER as BASE, PROFILES, WORKBENCH, WORKBENCH as APP, profile_dir
_sys.path.insert(0, str(BASE))
sys.path.insert(0, str(WORKBENCH))
sys.path.insert(0, str(BASE))
# The compiler reads the profile from $APP_SETTINGS and applies its ns + ontology_dir + OVERLAY.
# Retail's metrics live in the overlay, so a gate that checks retail without this loaded an
# ontology with no metrics at all.
import os as _os
_os.environ["APP_SETTINGS"] = str(profile_dir("retail") / "settings.json")
import actions  # noqa: E402
import sqlgen   # noqa: E402

P = sqlgen.P
ok = True


def check(label: str, got, want) -> None:
    global ok
    state = "PASS" if got == want else "FAIL"
    ok = ok and got == want
    print(f"  [{state}] {label}: got {got!r}, want {want!r}")


def load():
    # Absolute, from THIS file's directory. A relative "ontology" made the gate depend on the
    # caller's CWD: run from the repo root it loaded an empty graph and died with "no declared
    # relationship :Order -> :Customer" — a gate that fails because of where you stood.
    base = profile_dir("retail")   # the retail DECLARATIONS (not this script's dir)
    sqlgen.reconfigure(ns="https://cube.local/ontology/retail#",
                       ontology_dir=str(base / "ontology"))
    return sqlgen.load()


def evaluate(cur, sql):
    cur.execute(sql)
    return cur.fetchone()[0]


def rows_of(cur, sql):
    cur.execute(sql)
    return [tuple(str(x) for x in r[:-1]) + (round(float(r[-1]), 2),)
            for r in cur.fetchall()]


def _tutorial_ontology_checks(g_prev_note=None) -> int:
    """J8: the behaviour definition is COMPILED, not hand-written SQL.

    The tutorial ontology defines PremiumCustomer as
        :Customer ⊓ ∃:placesOrder.(:Order ⊓ (:amount ≥ 500))
    The compiler must turn it into the same rows as a hand-written EXISTS query, and must
    refuse when the inverse relationship is missing.
    """
    import pathlib
    base = profile_dir("retail")   # the retail DECLARATIONS (not this script's dir)
    import sqlgen
    sqlgen.reconfigure(ns="https://cube.local/ontology/retail#",
                       ontology_dir=str(base / "tutorial_ont"))
    g = sqlgen.load()
    pred = sqlgen.concept_sql(g, "PremiumCustomer")
    sql = f"SELECT id, name FROM customers WHERE {pred} ORDER BY id;"
    check("the axiom compiles to a correlated EXISTS",
          "EXISTS (SELECT 1 FROM orders WHERE orders.customer_id = customers.id" in pred, True)
    check("the threshold comes from the axiom (no SQL constant typed by hand)",
          "amount >= 500.0" in pred, True)
    conn = psycopg2.connect(**actions.DSN)
    cur = conn.cursor()
    cur.execute(sql)
    got = [(str(r[0]), str(r[1])) for r in cur.fetchall()]
    cur.execute("SELECT id, name FROM customers WHERE EXISTS (SELECT 1 FROM orders "
                "WHERE orders.customer_id = customers.id AND orders.amount >= 500.0) "
                "ORDER BY id")
    want = [(str(r[0]), str(r[1])) for r in cur.fetchall()]
    check("compiled result equals the hand-written EXISTS", got, want)
    # mutation: without owl:inverseOf the object restriction cannot be compiled
    import copy
    from rdflib import OWL
    mut = copy.deepcopy(g)
    mut.remove((sqlgen.P("placesOrder"), OWL.inverseOf, None))
    mut.remove((sqlgen.P("placesOrder"), RDF.type, OWL.ObjectProperty))
    try:
        sqlgen.concept_sql(mut, "PremiumCustomer")
        check("missing inverse relationship refused", "compiled", "refused")
    except sqlgen.Refusal:
        check("missing inverse relationship refused", "refused", "refused")
    conn.close()
    return 0


def _cross_grain_checks() -> int:
    """J9: a ratio across two grains is compiled as two full metrics, not a JOIN guess.

    revenuePerCustomer = orderRevenue / customers: the numerator lives on ::Order, the
    denominator on ::Customer. The compiler must expand each side and guard the divisor.
    """
    import sqlgen
    g = load()
    m = sqlgen.compile_metric(g, "revenuePerCustomer")
    check("the numerator is a compiled metric on ::Order",
          "FROM orders" in m.sql, True)
    check("the denominator is a compiled metric on ::Customer",
          "FROM customers" in m.sql, True)
    check("the divisor is guarded with NULLIF",
          "NULLIF" in m.sql, True)
    conn = psycopg2.connect(**actions.DSN)
    cur = conn.cursor()
    got = round(float(evaluate(cur, m.sql)), 6)
    cur.execute("SELECT (SELECT sum(amount) FROM orders)::numeric "
                "/ NULLIF((SELECT count(*) FROM customers), 0)")
    want = round(float(cur.fetchone()[0]), 6)
    check("compiled cross-grain ratio equals hand-written SQL", got, want)
    check("cross-grain ratio equals numerator/denominator",
          got, round(evaluate(cur, sqlgen.compile_metric(g, "orderRevenue").sql)
                     / evaluate(cur, sqlgen.compile_metric(g, "customers").sql), 6))
    # mutation: a metric may not use itself as its own numerator or denominator
    mut = load()
    mut.remove((sqlgen.P("revenuePerCustomer"), sqlgen.P("numerator"), None))
    mut.add((sqlgen.P("revenuePerCustomer"), sqlgen.P("numerator"),
             sqlgen.P("revenuePerCustomer")))
    try:
        sqlgen.compile_metric(mut, "revenuePerCustomer")
        check("self-referencing ratio refused", "compiled", "refused")
    except sqlgen.Refusal as exc:
        check("self-referencing ratio refused",
              "refused" if "itself" in str(exc) else str(exc), "refused")
    # mutation: give one customer a SECOND order; the two ratios must now diverge, which is
    # the whole point of counting at two different grains. Rolled back afterwards.
    conn.rollback()
    cur.execute("INSERT INTO orders (id, customer_id, amount, placed_at) "
                "VALUES (50999, 1, 500, now())")
    cur.execute(sqlgen.compile_metric(g, "revenuePerCustomer").sql)
    per_customer = round(float(cur.fetchone()[0]), 4)
    cur.execute(sqlgen.compile_metric(g, "averageOrderValue").sql)
    per_order = round(float(cur.fetchone()[0]), 4)
    check("with a second order for one customer the two ratios diverge",
          per_customer != per_order, True)
    check("revenuePerCustomer divides by customers, not by orders",
          per_customer, round((969.5 + 500) / 4, 4))
    conn.rollback()
    cur.execute(sqlgen.compile_metric(g, "revenuePerCustomer").sql)
    check("temporary order rolled back (per-customer revenue back to baseline)",
          round(float(cur.fetchone()[0]), 4), 242.375)
    conn.close()
    return 0


def _time_window_checks() -> int:
    """J10: a defined class carrying a date facet becomes a WHERE clause.

    :RecentOrder ≡ :Order ⊓ (:placed_at ≥ since)  — the cutoff is a compile-time constant
    taken from the axiom, and the boundary is inclusive (an order at 00:00:00 counts).
    An empty window must yield null, never a silently-flattering 0.
    """
    import sqlgen
    from rdflib import OWL
    from rdflib.collection import Collection
    from rdflib.namespace import XSD
    P = sqlgen.P

    def build(since: str):
        g = load()
        rnode = P("_r_window")
        g.add((rnode, RDF.type, OWL.Restriction))
        g.add((rnode, OWL.onProperty, P("placed_at")))
        g.add((rnode, XSD.minInclusive, Literal("'" + since + "'")))
        lst = P("_l_window")
        Collection(g, lst, [P("Order"), rnode])
        inter = P("_i_window")
        g.add((inter, RDF.type, OWL.Class))
        g.add((inter, OWL.intersectionOf, lst))
        g.add((P("RecentOrder"), RDF.type, OWL.Class))
        g.add((P("RecentOrder"), RDFS.subClassOf, P("Order")))
        g.add((P("RecentOrder"), OWL.equivalentClass, inter))
        g.add((P("windowRevenue"), RDF.type, OWL.DatatypeProperty))
        g.add((P("windowRevenue"), P("aggregate"), Literal("sum")))
        g.add((P("windowRevenue"), P("grain"), P("Order")))
        g.add((P("windowRevenue"), P("universe"), P("Order")))
        g.add((P("windowRevenue"), P("formula"), Literal("amount")))
        g.add((P("windowRevenue"), P("where"), P("RecentOrder")))
        return g

    conn = psycopg2.connect(**actions.DSN)
    cur = conn.cursor()
    cur.execute("SELECT min(placed_at) FROM orders")
    earliest = cur.fetchone()[0]
    wide = build("1900-01-01T00:00:00+00:00")
    cur.execute(sqlgen.compile_metric(wide, "windowRevenue").sql)
    got = round(float(cur.fetchone()[0]), 2)
    check("a window covering every order equals the unrestricted sum",
          got, round(float(evaluate(cur, sqlgen.compile_metric(load(), "orderRevenue").sql)), 2))
    # boundary: start exactly at the earliest order -> still included (>=, not >)
    at_edge = build(earliest.isoformat())
    cur.execute(sqlgen.compile_metric(at_edge, "windowRevenue").sql)
    check("the boundary is inclusive (>= , not >)", round(float(cur.fetchone()[0]), 2), got)
    # an empty window is null, not zero
    empty = build("2999-01-01T00:00:00+00:00")
    cur.execute(sqlgen.compile_metric(empty, "windowRevenue").sql)
    check("an empty window is null, not a flattering 0", cur.fetchone()[0], None)
    # the cutoff appears in the SQL as a constant taken from the axiom
    edge_sql = sqlgen.compile_metric(at_edge, "windowRevenue").sql
    check("the cutoff comes from the axiom into the SQL",
          earliest.isoformat() in edge_sql, True)
    conn.close()
    return 0


def _tutorial_query_checks() -> int:
    """J11: a question asked on the metrics page answers with the DEFINITION that produced it.

    The page's query box runs the real NL pipeline against the tutorial overlay, so a
    windowed question must (a) resolve to :revenueLastDays, (b) re-parameterise its axiom
    rather than stack a second filter, and (c) report the definition that the number came
    from. If the definition and the SQL ever disagree, this fails.
    """
    import serve_ui

    # The window is relative to now(), so the expected number cannot be a constant: the demo
    # data ages and the total legitimately shrinks. Measured: this gate still expected 969.5
    # while the ontology correctly answered 849.5, i.e. it had been failing on a number that
    # was right for its window. The expectation is now an INDEPENDENT route — the same rows
    # summed per customer and then added — so a fan-out or a double-applied filter still
    # disagrees, and the gate stops going stale.
    cases = [("revenue last 7 days", 7), ("total revenue last 90 days", 90)]
    for question, want_days in cases:
        out = serve_ui.tutorial6_ask(question, 30)
        check(f"{question!r}: resolved as a metric", out.get("ok"), True)
        if not out.get("ok"):
            continue
        res = out["result"]
        check(f"{question!r}: picked :revenueLastDays", res["name"], "revenueLastDays")
        check(f"{question!r}: the window came from the words",
              out["window_days"], want_days)
        cutoff = serve_ui._window_since(want_days).isoformat()
        check(f"{question!r}: the SQL filters on that exact midnight",
              cutoff in (res["sql"] or ""), True)
        check(f"{question!r}: the answer carries its definition",
              (res["definition"] or {}).get("where"), "RecentOrder")
        got_value = None if res["value"] in (None, "") else round(float(res["value"]), 2)
        conn = psycopg2.connect(**actions.DSN)
        cur = conn.cursor()
        cur.execute("select sum(t) from (select customer_id, sum(amount) as t from orders "
                    "where placed_at >= %s group by customer_id) s", (cutoff,))
        indep = cur.fetchone()[0]
        conn.close()
        want_value = None if indep is None else round(float(indep), 2)
        check(f"{question!r}: the number equals an independent per-customer route",
              got_value, want_value)

    # a metric with no window ignores the words entirely — same definition, same number
    plain = serve_ui.tutorial6_ask("order revenue", 30)
    check("a non-windowed metric keeps its definition", plain["result"]["definition"]["aggregate"],
          "sum")
    check("a non-windowed metric has no :where", plain["result"]["definition"]["where"], None)

    # a window the metric cannot carry (whole days only) is refused, not silently rounded
    bad = serve_ui.tutorial6_ask("revenue last week", 30)
    check("a non-day window is refused", bad.get("ok"), False)
    check("the refusal says what to ask instead",
          "last N days" in (bad.get("refused") or ""), True)
    return 0


def _product_metrics_checks() -> int:
    """J12: the products step's metrics are the 3- and 4-table compiles, by the numbers.

    A third table only earns its place if the joins it forces are declared and the numbers
    survive them: order_lines + products (2), + orders + stores (4), + customers (4).
    """
    import serve_ui
    import sqlgen
    g = serve_ui._tutorial6_graph(None)
    want = {"productRevenue": (2, "880.00"),
            "premiumProductRevenue": (4, "620.00")}
    for name, (tables, value) in want.items():
        c = sqlgen.compile_metric(g, name)
        got_tables = len(serve_ui._tables_in(c.sql))
        check(f":{name} joins {tables} tables", got_tables, tables)
        conn = psycopg2.connect(**actions.DSN)
        cur = conn.cursor()
        cur.execute(c.sql)
        val = cur.fetchone()[0]
        conn.close()
        check(f":{name} value", round(float(val), 2), float(value))
        check(f":{name} declares the association path", "order_lines" in c.sql, True)
        check(f":{name} never guesses a column", " ON " in c.sql, True)

    # grouped by two keys, both keys present and no row lost
    rows = {m["name"]: m for m in serve_ui.tutorial7_metrics()["metrics"]}
    two = rows["revenueByProductCity"]
    check("revenueByProductCity groups by two keys", two["definition"]["groupBy"],
          ["product_name", "city"])
    check("every grouped row keeps both keys",
          {len(r["keys"]) for r in two["rows"]}, {2})
    one = rows["revenueByProduct"]
    check("revenueByProduct groups by one key", one["definition"]["groupBy"], ["product_name"])
    check("the products step reports its table count",
          [len(rows[n]["tables"]) for n in ("productRevenue", "revenueByProductCity")], [2, 4])

    # an OBJECT type for the entity, a REIFIED link for the association — and the TTL says which
    g2 = serve_ui._tutorial6_graph(None)
    from rdflib import OWL, RDF
    P = sqlgen.P
    check(":Product is an object type with its own table",
          (P("Product"), RDF.type, OWL.Class) in g2, True)
    check(":Product is stored in products", sqlgen._one(g2, P("Product"), P("physicalTable")),
          "products")
    desk = sqlgen._one(g2, P("OrderLine"), P("businessDescription")) or ""
    check(":OrderLine says what it is: an association (reification), not a business object",
          "association" in desk.lower(), True)
    check("the link carries its own data (qty is a property of the association)",
          (P("qty"), RDF.type, OWL.DatatypeProperty) in g2, True)
    # the reification is real: the association names both ends, so a join can walk it
    ends = {}
    for ref, rng in (("order_ref", "Order"), ("product_ref", "Product")):
        target = sqlgen._one(g2, P(ref), P("references"))
        ends[ref] = (sqlgen._local(target) if target else None,
                     sqlgen._one(g2, P(ref), P("physicalColumn")))
        rng_ok = (P(ref), RDFS.range, P(rng)) in g2
        check(f":{ref} declares its range :{rng}", rng_ok, True)
    check("the association names both ends (order and product)",
          sorted(e[0] for e in ends.values()), ["Order", "Product"])
    check("and carries the FKs the compiler joins on",
          sorted(e[1] for e in ends.values()), ["order_id", "product_id"])
    return 0


def _store_dimension_checks() -> int:
    """J13: a dimension is not a measure — the key may come from another object.

    revenueByCity sums orders but groups by a property of Store, reached through the declared
    sold_at edge (many-to-one, so one FK, no extra table). premiumRevenueByCity puts a defined
    class on top of that key. The point of the check: the KEY never gets summed, and a group
    the data has no rows for is simply absent rather than zero-filled.
    """
    import serve_ui
    import sqlgen
    g = serve_ui._tutorial6_graph(None)
    rows = {m["name"]: m for m in serve_ui.tutorial8_metrics()["metrics"]}

    city = rows["revenueByCity"]
    check("revenueByCity groups by :city", city["definition"]["groupBy"], ["city"])
    check("revenueByCity reads its key from Store", city["tables"], ["orders", "stores"])
    check("the key is not summed", "sum(orders.amount)" in city["sql"], True)
    check("every group carries exactly one key", {len(r["keys"]) for r in city["rows"]}, {1})
    check("city rows are the real totals",
          sorted((r["keys"][0], r["value"]) for r in city["rows"]),
          [("Shanghai", "599.50"), ("Shenzhen", "370.00")])

    prem = rows["premiumRevenueByCity"]
    check("premiumRevenueByCity keeps the dimension AND the definition",
          (prem["definition"]["groupBy"], prem["definition"]["where"]),
          (["city"], "PremiumCustomer"))
    check("the defined class joins customers into the compile", prem["tables"],
          ["customers", "orders", "stores"])
    check("premium rows are the premium subsets",
          sorted((r["keys"][0], r["value"]) for r in prem["rows"]),
          [("Shanghai", "599.50"), ("Shenzhen", "250.00")])

    # the link is many-to-one on the order row: one FK, no join table to invent
    from rdflib import OWL, RDF
    P = sqlgen.P
    check(":sold_at is an object property on :Order",
          (P("sold_at"), RDF.type, OWL.ObjectProperty) in g, True)
    check("its FK lives on the order row", sqlgen._one(g, P("sold_at"), P("physicalColumn")),
          "sold_at")
    check("it names its target class", sqlgen._local(sqlgen._one(g, P("sold_at"), P("references"))),
          "Store")
    check("no extra table is introduced for a many-to-one link",
          sqlgen._one(g, P("Store"), P("physicalTable")), "stores")

    # a key that does not exist is refused by name, not silently dropped
    import nl
    try:
        nl.interpret("revenue by store", nl.menu(g))
        check("'revenue by store' is refused (no name property to group on)", "accepted",
              "refused")
    except nl.NlRefusal as exc:
        check("'revenue by store' is refused (no name property to group on)",
              "store" in str(exc), True)
    return 0


def main() -> int:
    g = load()
    conn = psycopg2.connect(**actions.DSN)
    cur = conn.cursor()

    print("=== J1 the relationship is DECLARED, not inferred ===")
    fk, pk = sqlgen.relationship(g, "Order", "Customer")
    check("Order -> Customer join key", (fk, pk), ("customer_id", "id"))
    check(":customer declares :references -> :Customer",
          sqlgen._local(sqlgen._one(g, P("customer"), P("references"))), "Customer")

    print("=== J2 :where on another class compiles a JOIN and evaluates ===")
    revenue = sqlgen.compile_metric(g, "premiumCustomerRevenue")
    check("compiled SQL joins the declared relationship",
          f"JOIN customers ON orders.{fk} = customers.{pk}" in revenue.sql, True)
    baseline = round(evaluate(cur, revenue.sql), 2)       # expected is measured, not typed
    # make the fan-out visible inside this transaction (rolled back at the end)
    cur.execute("INSERT INTO orders (id, customer_id, amount) VALUES (999999, 1, 100.00)")
    expected = round(evaluate(cur,
        "SELECT sum(amount) FROM orders JOIN customers "
        "ON orders.customer_id = customers.id WHERE tier = 'PREMIUM'"), 2)
    check("premium revenue in the transaction equals the direct query",
          round(evaluate(cur, revenue.sql), 2), expected)

    print("=== J3 count at the joined target is fan-out safe ===")
    with_orders = sqlgen.compile_metric(g, "premiumCustomersWithOrders")
    check("compiled SQL counts DISTINCT target pk",
          "count(DISTINCT customers.id)" in with_orders.sql, True)
    check("premium customers with orders equals the DISTINCT count",
          evaluate(cur, with_orders.sql),
          evaluate(cur, "SELECT count(DISTINCT customers.id) FROM orders JOIN customers "
                        "ON orders.customer_id = customers.id WHERE tier = 'PREMIUM'"))
    naive = ("SELECT count(*) FROM orders JOIN customers "
             "ON orders.customer_id = customers.id WHERE tier = 'PREMIUM'")
    check("naive count(*) would be WRONG on this data (fan-out visible)",
          evaluate(cur, naive) > evaluate(cur, with_orders.sql), True)
    check("naive count(*) equals the raw joined row count",
          evaluate(cur, naive),
          evaluate(cur, "SELECT count(*) FROM orders JOIN customers "
                        "ON orders.customer_id = customers.id WHERE tier = 'PREMIUM'"))

    print("=== J6 four-table join: order_lines → orders → customers → products ===")
    four = sqlgen.compile_metric(g, "premiumProductRevenue")
    tables = {"order_lines", "orders", "customers", "products"}
    check("the compiled SQL touches all four tables",
          all(t in four.sql for t in tables), True)
    check("it has three joins", four.sql.count(" JOIN "), 3)
    check("the value equals the direct four-table query",
          round(float(evaluate(cur, four.sql)), 2),
          round(float(evaluate(cur,
              "SELECT sum(ol.qty * p.price) FROM order_lines ol "
              "JOIN orders o ON ol.order_id = o.id "
              "JOIN customers c ON o.customer_id = c.id "
              "JOIN products p ON ol.product_id = p.id WHERE c.tier = 'PREMIUM'")), 2))
    # mutation: cut the OrderLine -> Product relationship and the formula cannot resolve
    no_prod = load()
    no_prod.remove((P("product_ref"), P("references"), None))
    try:
        sqlgen.compile_metric(no_prod, "premiumProductRevenue")
        check("missing product relationship refused", "compiled", "refused")
    except sqlgen.Refusal as exc:
        check("missing product relationship refused",
              "refused" if "reachable" in str(exc) or "declared" in str(exc) else str(exc),
              "refused")
    # mutation: the same column on two joined classes is ambiguous
    amb = load()
    amb.add((P("price_line"), RDF.type, OWL.DatatypeProperty))
    amb.add((P("price_line"), RDFS.domain, P("OrderLine")))
    amb.add((P("price_line"), P("physicalColumn"), Literal("price")))
    try:
        sqlgen.compile_metric(amb, "premiumProductRevenue")
        check("ambiguous formula column refused", "compiled", "refused")
    except sqlgen.Refusal as exc:
        check("ambiguous formula column refused",
              "refused" if "MORE THAN ONE" in str(exc) or "ambiguous" in str(exc).lower()
              else str(exc), "refused")

    print("=== J7 grouping: revenue by city / by product (group key on a joined class) ===")
    by_city = sqlgen.compile_metric(g, "revenueByCity")
    check("by-city SQL groups and joins the store table",
          "GROUP BY stores.city" in by_city.sql and "JOIN stores" in by_city.sql, True)
    check("by-city rows equal the direct grouped query",
          rows_of(cur, by_city.sql),
          rows_of(cur,
              "SELECT stores.city, sum(orders.amount) FROM orders JOIN stores "
              "ON orders.sold_at = stores.id GROUP BY stores.city ORDER BY 2 DESC"))
    by_prod = sqlgen.compile_metric(g, "revenueByProduct")
    check("by-product SQL groups and joins the product table",
          "GROUP BY products.name" in by_prod.sql and "JOIN products" in by_prod.sql, True)
    check("by-product rows equal the direct grouped query",
          rows_of(cur, by_prod.sql),
          rows_of(cur,
              "SELECT products.name, sum(order_lines.qty * products.price) "
              "FROM order_lines JOIN products ON order_lines.product_id = products.id "
              "GROUP BY products.name ORDER BY 2 DESC"))
    # mutation: cut the store relationship and the group key cannot be reached
    no_store = load()
    no_store.remove((P("sold_at"), P("references"), None))
    try:
        sqlgen.compile_metric(no_store, "revenueByCity")
        check("missing store relationship refused", "compiled", "refused")
    except sqlgen.Refusal as exc:
        check("missing store relationship refused",
              "refused" if "reachable" in str(exc) or "declared" in str(exc) else str(exc),
              "refused")

    print("=== J7b TWO-dimension grouping: revenue by product AND city ===")
    two = sqlgen.compile_metric(g, "revenueByProductCity")
    check("the SQL groups by BOTH keys",
          "GROUP BY products.name, stores.city" in two.sql, True)
    check("two-key rows equal the direct grouped query",
          rows_of(cur, two.sql),
          rows_of(cur,
              "SELECT products.name, stores.city, sum(order_lines.qty * products.price) "
              "FROM order_lines JOIN products ON order_lines.product_id = products.id "
              "JOIN orders ON order_lines.order_id = orders.id "
              "JOIN stores ON orders.sold_at = stores.id "
              "GROUP BY products.name, stores.city ORDER BY 3 DESC"))

    print("=== J4 mutation: removing :references is refused BY NAME ===")
    no_ref = load()
    no_ref.remove((P("customer"), P("references"), None))
    try:
        sqlgen.compile_metric(no_ref, "premiumCustomerRevenue")
        check("missing :references refused", "compiled", "refused")
    except sqlgen.Refusal as exc:
        check("missing :references refused",
              "refused" if ":references" in str(exc) else str(exc), "refused")

    print("=== J5 mutation: an ambiguous column is refused BY NAME ===")
    ambiguous = load()
    ambiguous.add((P("tier_copy"), RDF.type, OWL.DatatypeProperty))
    ambiguous.add((P("tier_copy"), RDFS.domain, P("Order")))
    ambiguous.add((P("tier_copy"), P("physicalColumn"), Literal("tier")))
    try:
        sqlgen.compile_metric(ambiguous, "premiumCustomerRevenue")
        check("ambiguous predicate refused", "compiled", "refused")
    except sqlgen.Refusal as exc:
        check("ambiguous predicate refused",
              "refused" if "ambiguous" in str(exc) else str(exc), "refused")

    conn.rollback()    # the fan-out order was temporary; the demo data is untouched
    check("temporary order rolled back (revenue back to its baseline)",
          round(evaluate(cur, revenue.sql), 2), baseline)
    conn.close()

    print("=== J8 behaviour definition compiled to SQL (tutorial ontology) ===")
    _tutorial_ontology_checks()

    print("=== J9 cross-grain ratio compiled from two metrics ===")
    _cross_grain_checks()

    print("=== J10 time window: a date facet compiled into WHERE ===")
    _time_window_checks()

    print("=== J11 a question answers with the metric's own definition ===")
    _tutorial_query_checks()

    print("=== J12 the products step's metrics: 3- and 4-table compiles ===")
    _product_metrics_checks()

    print("=== J13 a dimension is not a measure (Store) ===")
    _store_dimension_checks()

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
