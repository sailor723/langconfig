#!/usr/bin/env python3
"""Extend `new_coldchain` with the data the six KPI families need — ADDITIVELY.

Why a second generator instead of editing `gen.py`
--------------------------------------------------
`gen.py` is a full `DROP TABLE … CREATE TABLE` builder. The v6 ontology declares 46 metrics
whose expected values live in `truth.json`, and those values were measured against the rows
`gen.py` produced (SEED 20261107). Adding draws to that generator shifts its RNG stream and
moves every one of those 46 numbers — which would silently re-baseline a proof that is supposed
to be independent of the pipeline.

So this script only ADDS: 7 new tables and 6 new columns. It never deletes or rewrites an
existing row, it derives every new value from rows already in the database, and its own seed is
independent (20261108). Re-running it is idempotent.

    python3 gen_kpi_extension.py --plan     # say what it would do, write nothing
    python3 gen_kpi_extension.py --apply    # create + fill (idempotent)
    python3 gen_kpi_extension.py --check    # assert every invariant below, write nothing

What it adds
------------
Tables (the KPI that needs them in brackets):

    driver_schedule        K4 出勤率          — 应出勤/实出勤; the only source of a denominator
    incident_tickets       K2 异常率          — the REPORTED channel (type, party, status, primary)
    violations             K5 违章率          — 交管 records per vehicle/day
    fuel_logs              K6 油耗            — the reconcilable fill record (liters, odometer)
    maintenance_orders     K6 维修成本        — 维修工单 (cost, downtime)
    zone_permits           K5 路权合规率      — dated permit validity (a boolean cannot expire)
    vehicle_fixed_costs    K6 TCO             — insurance / depreciation / road tax / inspection

Columns:

    stops.service_status     (delivered | not_delivered | refused | closed_store)
    trips.actual_km          the one fact behind 百公里油耗, 每万公里违章率 and 单公里成本
    trips.fuel_liters        fuel apportioned to the trip (fuel_logs stays the measurement)
    trips.maintenance_cost   maintenance apportioned to the trip by km share
    trips.stops_delivered    frozen count, so a trip-grain completion metric can compile
    trips.weighbridge_weight 地磅 reading for the trips that were weighed (a second source)

Invariants this script ENFORCES (each one is a line in --check)
---------------------------------------------------------------
I1  service_status is only ever attached to stops that were ALREADY `on_time = false`, so
    `onTimeRate` cannot move. A refused stop that the ontology still calls "on time" is the
    contradiction this rule exists to prevent.
I2  every driver_schedule `attended` day has a trip; no `absent`/`leave` day has one.
I3  every violation happens on a (vehicle, day) that really ran, and names that day's driver.
I4  fuel_logs odometer never decreases per vehicle, and its liters/cost reconcile with
    trips.fuel_liters and trip_costs.fuel_cost.
I5  Σ maintenance apportioned per vehicle equals that vehicle's maintenance_orders cost.
I6  a permit exists for exactly the vehicles whose `core_zone_permit` is true at window start;
    the two that expire mid-window are the 路权 story, not a contradiction.
I7  no maintenance order lands on a day that vehicle drove.
I8  every incident ticket points at a real anomaly (temp excursion, damaged boxes, or a
    complaint) on its own trip, and the reported set is a small subset of the anomalies.
I9  trips.stops_delivered equals the count of its delivered stops.
I10 actual_km is within [1.00, 1.15] × the route's planned_km (a detour, never a teleport).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import pathlib
import sys

import psycopg2
from psycopg2.extras import execute_values

#: Where the declarations live, so a version's profile decides which database this fills.
#: Nothing below assumes `new_coldchain`: run it against v1, v2 or any other version by passing
#: `--profile <key>_settings.json`, and the DSN, the seed and the baseline follow that profile.
DEFAULT_PROFILE = pathlib.Path(__file__).resolve().parents[1] / "new_coldchain_v6_settings.json"
WORK = pathlib.Path(__file__).resolve().parent

SEED = 20261108
START = dt.date(2026, 8, 1)
END = dt.date(2026, 10, 29)
END_EXCLUSIVE = dt.date(2026, 10, 30)
MERGE_DAY = dt.date(2026, 9, 22)          # 并线: permits expire for the vehicles that did not renew
EXPIRED_PERMIT_DAY = dt.date(2026, 9, 21)

FUEL_PRICE_TOLERANCE = 0.01

#: 维修 cost bands per category (RMB).
MAINT_BANDS = {"制冷机组": (1800, 6500), "轮胎": (900, 3200), "刹车": (400, 1800),
               "保养": (600, 1500), "车厢": (500, 2600), "电瓶": (350, 1200)}

#: 柴油冷藏车 L/100km by rated tonnage — the DEMO sheet's own target bands
#: (8T 11–13 L/100km city distribution; 12T ≤ 22.5 L/100km).
CONSUMPTION_L_PER_100KM = {3: 9.0, 5: 10.5, 8: 12.5, 10: 18.0, 12: 21.5}

DDL = """
-- ── K4: the roster. 应出勤 is a fact nobody can derive from trips, so it is a table. ─────────
CREATE TABLE IF NOT EXISTS driver_schedule (
    driver_id    bigint      NOT NULL REFERENCES drivers(id),
    day          date        NOT NULL,
    status       text        NOT NULL,          -- attended | absent | leave | not_scheduled
    scheduled    boolean     NOT NULL,          -- 应出勤: Sunday is not a working day
    hours        numeric,                       -- rostered hours (null when not scheduled)
    reason       text,                          -- absent/leave reason (null when attended)
    PRIMARY KEY (driver_id, day)
);

-- ── K2: the REPORTED channel. The planted failures stay in stops/complaints; this is what was
--        actually filed, so 异常率 (reported) and 实际异常 (measured) are two different numbers. ──
CREATE TABLE IF NOT EXISTS incident_tickets (
    id                bigserial  PRIMARY KEY,
    trip_id           bigint     NOT NULL REFERENCES trips(id),
    stop_id           bigint     REFERENCES stops(id),
    type              text       NOT NULL,       -- 破损 | 倒温 | 少送/错送 | 拒收 | 超时 | 态度
    raised_at         timestamptz NOT NULL,
    channel           text       NOT NULL,       -- 客服工单 | 司机APP上报 | POD签收
    responsible_party text       NOT NULL,       -- 承运 | 客户 | 不可抗力
    status            text       NOT NULL,       -- 已处理 | 处理中
    is_primary        boolean    NOT NULL,       -- 一单多异常：只按主类型去重计 1 单
    detail            text
);

-- ── K5: 交管 records. A rate per 10,000 km needs both halves; this is the numerator. ─────────
CREATE TABLE IF NOT EXISTS violations (
    id          bigserial    PRIMARY KEY,
    vehicle_id  bigint       NOT NULL REFERENCES vehicles(id),
    driver_id   bigint       NOT NULL REFERENCES drivers(id),
    occurred_at timestamptz  NOT NULL,
    code        text         NOT NULL,
    category    text         NOT NULL,          -- 超速 | 闯禁行 | 违停 | 疲劳驾驶
    points      integer      NOT NULL,          -- 扣分
    fine_amount numeric      NOT NULL,          -- 罚款 (RMB)
    status      text         NOT NULL,          -- 已处理 | 处理中 | 未处理
    road_zone   text         NOT NULL           -- core | suburb | highway
);

-- ── K6: 油耗. The fill record is the measurement; trips.fuel_liters is the apportionment. ────
CREATE TABLE IF NOT EXISTS fuel_logs (
    id          bigserial    PRIMARY KEY,
    vehicle_id  bigint       NOT NULL REFERENCES vehicles(id),
    filled_at   timestamptz  NOT NULL,
    liters      numeric      NOT NULL,
    unit_price  numeric      NOT NULL,          -- RMB / L
    amount      numeric      NOT NULL,          -- liters × unit_price
    odometer_km numeric      NOT NULL,          -- 表读里程, monotone per vehicle
    station     text         NOT NULL
);

-- ── K6: 维修. 工单 cost and downtime; trips.maintenance_cost apportions it by km share. ──────
CREATE TABLE IF NOT EXISTS maintenance_orders (
    id             bigserial   PRIMARY KEY,
    vehicle_id     bigint      NOT NULL REFERENCES vehicles(id),
    opened_at      date        NOT NULL,
    closed_at      date,
    category       text        NOT NULL,        -- 制冷机组 | 轮胎 | 刹车 | 保养 | 车厢 | 电瓶
    cost           numeric     NOT NULL,
    odometer_km    numeric     NOT NULL,
    downtime_hours numeric     NOT NULL,
    vendor         text        NOT NULL,
    note           text
);

-- ── K5: 路权. A boolean cannot expire; 合规与否 depends on the DATE of the trip. ─────────────
CREATE TABLE IF NOT EXISTS zone_permits (
    id          bigserial  PRIMARY KEY,
    vehicle_id  bigint     NOT NULL REFERENCES vehicles(id),
    zone        text       NOT NULL,            -- core
    permit_no   text       NOT NULL,
    valid_from  date       NOT NULL,
    valid_to    date       NOT NULL,            -- 失效日; the 路权 story lives here
    status      text       NOT NULL             -- 有效 | 已失效
);

-- ── K6: TCO. Insurance/depreciation/tax are not per-trip and have no home in trip_costs. ─────
CREATE TABLE IF NOT EXISTS vehicle_fixed_costs (
    id           bigserial   PRIMARY KEY,
    vehicle_id   bigint      NOT NULL REFERENCES vehicles(id),
    period       date        NOT NULL,          -- first day of the month
    insurance    numeric     NOT NULL,
    depreciation numeric     NOT NULL,
    road_tax     numeric     NOT NULL,
    inspection   numeric     NOT NULL,
    currency     text        NOT NULL DEFAULT 'RMB'
);

ALTER TABLE stops ADD COLUMN IF NOT EXISTS service_status text;
ALTER TABLE trips ADD COLUMN IF NOT EXISTS actual_km        numeric;
ALTER TABLE trips ADD COLUMN IF NOT EXISTS fuel_liters      numeric;
ALTER TABLE trips ADD COLUMN IF NOT EXISTS maintenance_cost numeric;
ALTER TABLE trips ADD COLUMN IF NOT EXISTS stops_delivered  integer;
ALTER TABLE trips ADD COLUMN IF NOT EXISTS weighbridge_weight numeric;
"""

NEW_TABLES = ["driver_schedule", "incident_tickets", "violations", "fuel_logs",
              "maintenance_orders", "zone_permits", "vehicle_fixed_costs"]


def dsn_from_profile(path: pathlib.Path) -> dict:
    """The profile's dsn block, with ${ENV:-default} references expanded the way the compiler does."""
    import json
    import os
    import re

    cfg = json.loads(path.read_text(encoding="utf-8"))
    raw = cfg.get("dsn") or {}
    if not raw:
        raise SystemExit(f"{path} declares no dsn — nothing to fill")

    def expand(value):
        if not isinstance(value, str):
            return value
        return re.sub(r"\$\{(\w+)(?::-([^}]*))?\}", lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)

    dsn = {k: expand(v) for k, v in raw.items()}
    dsn["port"] = int(dsn.get("port") or 5432)
    dsn.setdefault("password", "")
    return dsn


def baseline_path(dbname: str) -> pathlib.Path:
    return WORK / f"{dbname}.baseline.json"


def read_baseline(dbname: str) -> dict | None:
    import json

    path = baseline_path(dbname)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def write_baseline(cur, dbname: str) -> dict:
    """Record the numbers this version must still hold after the extension.

    A version's own truth, not v6's: a literal in a checker is a fact about ONE database, and
    reusing it on another version turns a proof into a coincidence.
    """
    import json

    cur.execute("""select count(*) filter (where on_time), count(*), sum(damaged_boxes) from stops""")
    on_time, stops_n, damaged = cur.fetchone()
    cur.execute("select count(*), sum(revenue), sum(cost_total) from trips")
    trips_n, revenue, cost = cur.fetchone()
    cur.execute("""select count(*), sum(fuel_cost), sum(toll_cost), sum(driver_pay),
                          sum(handler_cost), sum(external_fee) from trip_costs""")
    tc = cur.fetchone()
    cur.execute("""select count(*), count(*) filter (where liability is null), sum(amount) from complaints""")
    cp = cur.fetchone()
    cur.execute("select count(*), count(*) filter (where adopted) from dispatch_decisions")
    dd = cur.fetchone()
    cur.execute("select count(*) from refusals")
    refusals = cur.fetchone()[0]
    base = {
        "_doc": f"the numbers {dbname} had BEFORE gen_kpi_extension; --check asserts they still hold",
        "stops": {"n": stops_n, "on_time": on_time, "damaged_boxes": int(damaged or 0)},
        "trips": {"n": trips_n, "revenue": round(float(revenue or 0), 2),
                  "cost_total": round(float(cost or 0), 2)},
        "trip_costs": {"n": tc[0], "fuel": round(float(tc[1] or 0), 2), "toll": round(float(tc[2] or 0), 2),
                       "driver_pay": round(float(tc[3] or 0), 2), "handler": round(float(tc[4] or 0), 2),
                       "external": round(float(tc[5] or 0), 2)},
        "complaints": {"n": cp[0], "unjudged": cp[1], "amount": round(float(cp[2] or 0), 2)},
        "dispatch": {"n": dd[0], "adopted": dd[1]},
        "refusals": refusals,
    }
    baseline_path(dbname).write_text(json.dumps(base, indent=1, ensure_ascii=False), encoding="utf-8")
    return base


# ─────────────────────────────────────────────────────────── determinism helpers
def _u(*parts) -> float:
    """A stable 0..1 draw, independent of insertion order and of any RNG stream."""
    h = hashlib.sha256(("%s|" % SEED + "|".join(str(p) for p in parts)).encode()).digest()
    return int.from_bytes(h[:8], "big") / float(1 << 64)


def _pick(*parts, choices):
    return choices[min(len(choices) - 1, int(_u(*parts) * len(choices)))]


def _money(x: float) -> float:
    return round(float(x) + 1e-9, 2)


# ─────────────────────────────────────────────────────────── the work
def _load(cur) -> dict:
    """Everything the extension derives from. Read-only."""
    data = {}
    cur.execute("""
        select t.id, t.trip_date, t.route_id, t.vehicle_id, t.driver_id, t.planned_stops,
               t.load_weight, t.load_boxes, t.load_volume, t.revenue, t.external_cost,
               t.route_version, r.planned_km, v.tonnage
        from trips t join routes r on r.id = t.route_id join vehicles v on v.id = t.vehicle_id
        order by t.id""")
    data["trips"] = cur.fetchall()
    cur.execute("""select id, trip_id, seq, on_time, temp_excursion, damaged_boxes,
                          alarm_triggered from stops order by trip_id, seq""")
    data["stops"] = cur.fetchall()
    cur.execute("""select c.id, s.trip_id, c.stop_id, c.kind from complaints c
                          join stops s on s.id = c.stop_id""")
    data["complaints"] = cur.fetchall()
    cur.execute("select id, plate, tonnage, core_zone_permit from vehicles order by id")
    data["vehicles"] = cur.fetchall()
    cur.execute("select id, vehicle_id from drivers order by id")
    data["drivers"] = cur.fetchall()
    cur.execute("select day, is_peak from calendar order by day")
    data["calendar"] = cur.fetchall()
    cur.execute("select sum(fuel_cost) from trip_costs")
    data["fuel_cost_total"] = float(cur.fetchone()[0] or 0)
    return data


def _trip_km(trips) -> dict[int, float]:
    """I10: a detour factor in [1.00, 1.15] over the route's planned kilometres."""
    return {t[0]: round(float(t[12]) * (1.0 + 0.15 * _u("km", t[0])), 1) for t in trips}


def _service_status(stops, complaints_by_trip) -> dict[int, str]:
    """I1: only stops that are ALREADY late can be non-delivered.

    A refused stop is not "on time", so attaching a refusal to an on-time row would make the
    declaration and the data disagree. Everything that was on time stays delivered, which is why
    `onTimeRate` (0.9459…) cannot move when this column appears.
    """
    late = [s for s in stops if not s[3]]
    # a deterministic, well-spread split of the late population, not the first N rows
    late_sorted = sorted(late, key=lambda s: _u("svc", s[0]))
    out = {s[0]: "delivered" for s in stops}
    n = len(late_sorted)
    cut_refused = int(n * 0.15)
    cut_closed = cut_refused + int(n * 0.10)
    cut_missing = cut_closed + int(n * 0.08)
    for i, s in enumerate(late_sorted):
        if i < cut_refused:
            out[s[0]] = "refused"
        elif i < cut_closed:
            out[s[0]] = "closed_store"
        elif i < cut_missing:
            out[s[0]] = "not_delivered"
    return out


def _fuel_liters(trips, km) -> dict[int, float]:
    return {t[0]: round(km[t[0]] * CONSUMPTION_L_PER_100KM[int(t[13])] / 100.0
                        * (0.95 + 0.10 * _u("fuel", t[0])), 1) for t in trips}


def apply(cur) -> dict:
    data = _load(cur)
    trips, stops = data["trips"], data["stops"]
    km = _trip_km(trips)
    status = _service_status(stops, data["complaints"])
    liters = _fuel_liters(trips, km)

    cur.execute(DDL)

    # ── clear only what this script owns, so a re-run is idempotent and nothing else is touched
    for t in NEW_TABLES:
        cur.execute(f"delete from {t}")
    cur.execute("update stops set service_status = null")
    cur.execute("update trips set actual_km = null, fuel_liters = null, "
                "maintenance_cost = null, stops_delivered = null, weighbridge_weight = null")

    # ── stops.service_status  (I1) ────────────────────────────────────────────────────────
    execute_values(cur, "update stops s set service_status = v.st from (values %s) as v(id, st) "
                        "where s.id = v.id::bigint",
                   [(sid, st) for sid, st in status.items()], template="(%s::bigint, %s)")

    # ── trips: km, weight, liters, delivered count ───────────────────────────────────────
    delivered_by_trip: dict[int, int] = {}
    for s in stops:
        if status[s[0]] == "delivered":
            delivered_by_trip[s[1]] = delivered_by_trip.get(s[1], 0) + 1
    trip_rows = []
    for t in trips:
        tid, load_weight = t[0], float(t[7])
        weighed = (_u("scale", tid) < 0.85)
        weighbridge = round(load_weight * (1.0 + (_u("scalev", tid) - 0.5) * 0.008), 0) if weighed else None
        trip_rows.append((tid, km[tid], liters[tid], delivered_by_trip.get(tid, 0), weighbridge))
    execute_values(cur, "update trips t set actual_km = v.km, fuel_liters = v.liters, "
                        "stops_delivered = v.delivered, weighbridge_weight = v.wb "
                        "from (values %s) as v(id, km, liters, delivered, wb) "
                        "where t.id = v.id::bigint", trip_rows,
                   template="(%s::bigint, %s::numeric, %s::numeric, %s::int, %s)")

    # ── driver_schedule  (I2) ────────────────────────────────────────────────────────────
    trip_days: dict[int, set] = {}
    day_driver: dict[tuple, int] = {}
    for t in trips:
        trip_days.setdefault(t[4], set()).add(t[1])
        day_driver[(t[3], t[1])] = t[4]
    schedule_rows = []
    for drv in data["drivers"]:
        did = drv[0]
        for day, _peak in data["calendar"]:
            if day in trip_days.get(did, ()):
                # a day he drove is attended whether or not the roster says so; the roster is
                # the PLAN, and a plan that calls a working Sunday "not scheduled" is wrong.
                schedule_rows.append((did, day, "attended", True, 8, None))
                continue
            if day.weekday() == 6:                           # Sunday, nobody drove: not rostered
                schedule_rows.append((did, day, "not_scheduled", False, None, None))
                continue
            if _u("leave", did, day) < 0.30:
                schedule_rows.append((did, day, "leave", True, 8,
                                       _pick("lr", did, day, choices=["年假", "病假", "事假"])))
            else:
                schedule_rows.append((did, day, "absent", True, 8,
                                       _pick("ar", did, day,
                                             choices=["休息", "车辆维修", "私人事务"])))
    execute_values(cur, "insert into driver_schedule (driver_id, day, status, scheduled, hours, reason) "
                        "values %s", schedule_rows,
                   template="(%s::bigint, %s::date, %s, %s, %s, %s)")

    # ── maintenance_orders  (I7) ─────────────────────────────────────────────────────────
    # cumulative km per vehicle over its trips, to interpolate an odometer at any date
    veh_trips: dict[int, list] = {}
    for t in trips:
        veh_trips.setdefault(t[3], []).append(t)
    for v in veh_trips:
        veh_trips[v].sort(key=lambda t: (t[1], t[0]))
    cum_at: dict[tuple, float] = {}
    for veh, rows in veh_trips.items():
        total = 0.0
        for t in rows:
            total += km[t[0]]
            cum_at[(veh, t[1])] = round(total, 1)

    def odometer(veh: int, day: dt.date) -> float:
        best = 0.0
        for (v, d), val in cum_at.items():
            if v == veh and d <= day:
                best = max(best, val)
        return round(best, 1)

    maintenance_rows, maint_by_vehicle = [], {}
    busy = {(t[3], t[1]) for t in trips}
    candidates = [(v, day) for v in veh_trips
                  for day in (START + dt.timedelta(days=i) for i in range((END - START).days + 1))
                  if (v, day) not in busy]
    candidates.sort(key=lambda c: _u("maint", c[0], c[1]))
    for veh, day in candidates[:250]:
        cat = _pick("mcat", veh, day, choices=list(MAINT_BANDS))
        lo, hi = MAINT_BANDS[cat]
        cost = _money(lo + _u("mcost", veh, day) * (hi - lo))
        down = round(2 + _u("mdown", veh, day) * 28, 1)
        closed = day + dt.timedelta(days=int(down // 8) + 1)
        maintenance_rows.append((veh, day, min(closed, END), cat, cost, odometer(veh, day), down,
                                  _pick("vendor", veh, day,
                                        choices=["顺捷汽修", "冷王授权站", "快修联盟", "厂属修理班"]),
                                  None))
        maint_by_vehicle[veh] = maint_by_vehicle.get(veh, 0.0) + cost
    execute_values(cur, "insert into maintenance_orders (vehicle_id, opened_at, closed_at, category, "
                        "cost, odometer_km, downtime_hours, vendor, note) values %s", maintenance_rows,
                   template="(%s::bigint, %s::date, %s::date, %s, %s, %s, %s, %s, %s)")

    # ── trips.maintenance_cost: apportion this vehicle's 工单 by km share  (I5) ───────────
    for veh, rows in veh_trips.items():
        total_cost = maint_by_vehicle.get(veh)
        if not total_cost:
            continue
        total_km = sum(km[t[0]] for t in rows) or 1.0
        running, last = 0.0, None
        alloc = []
        for t in rows:
            share = _money(total_cost * km[t[0]] / total_km)
            running += share
            last = t[0]
            alloc.append((t[0], share))
        drift = _money(total_cost - running)
        if alloc and abs(drift) >= 0.01:
            tid, share = alloc[-1]
            alloc[-1] = (tid, _money(share + drift))
        execute_values(cur, "update trips t set maintenance_cost = v.c from (values %s) as v(id, c) "
                            "where t.id = v.id::bigint",
                       alloc, template="(%s::bigint, %s::numeric)")

    # ── fuel_logs  (I4) ─────────────────────────────────────────────────────────────────
    total_liters = sum(liters.values()) or 1.0
    price = round(data["fuel_cost_total"] / total_liters, 4)
    fuel_rows = []
    for veh, rows in veh_trips.items():
        since_fill, odo = 0.0, 0.0
        for i, t in enumerate(rows):
            since_fill += liters[t[0]]
            odo = cum_at[(veh, t[1])]
            if since_fill >= 120 or (i == len(rows) - 1 and since_fill > 0):
                amt = _money(since_fill * price)
                fuel_rows.append((veh, dt.datetime.combine(t[1], dt.time(6, 30)),
                                   round(since_fill, 1), price, amt, odo,
                                   _pick("st", veh, t[1],
                                         choices=["中石化-临港站", "中石油-华夏站", "壳牌-金桥站", "内部油罐"])))
                since_fill = 0.0
    # I4c: rounding 2,000 amounts to fen cannot land on the cent by accident. Put the residual on
    # the LAST fill so the log reconciles with trip_costs.fuel_cost exactly — a fill record that
    # disagrees with the cost export by a rounding grain is the kind of drift this dataset refuses.
    if fuel_rows:
        running = sum(r[4] for r in fuel_rows)
        residual = _money(data["fuel_cost_total"] - running)
        if abs(residual) >= 0.01:
            last = fuel_rows[-1]
            fuel_rows[-1] = (last[0], last[1], last[2], last[3], _money(last[4] + residual), last[5], last[6])
    execute_values(cur, "insert into fuel_logs (vehicle_id, filled_at, liters, unit_price, amount, "
                        "odometer_km, station) values %s", fuel_rows,
                   template="(%s::bigint, %s, %s, %s, %s, %s, %s)")

    # ── zone_permits  (I6) ──────────────────────────────────────────────────────────────
    permit_rows = []
    no_permit = [v for v in data["vehicles"] if not v[3]]
    expiring = sorted(v[0] for v in data["vehicles"] if v[3])[:2]
    for v in data["vehicles"]:
        vid = v[0]
        if v[3]:
            valid_to = EXPIRED_PERMIT_DAY if vid in expiring else END
            permit_rows.append((vid, "core", f"京{vid:04d}SG", START, valid_to,
                                 "有效" if vid not in expiring else "已失效"))
    for vid in sorted(v[0] for v in no_permit)[:6]:
        permit_rows.append((vid, "core", f"京{vid:04d}OLD", dt.date(2026, 1, 5),
                             dt.date(2026, 7, 31), "已失效"))
    execute_values(cur, "insert into zone_permits (vehicle_id, zone, permit_no, valid_from, valid_to, "
                        "status) values %s",
                   permit_rows, template="(%s::bigint, %s, %s, %s, %s, %s)")

    # ── violations  (I3) ────────────────────────────────────────────────────────────────
    ran = [(t[3], t[1], t[4]) for t in trips]
    ran.sort(key=lambda r: _u("viol", r[0], r[1]))
    seen, viol_rows = set(), []
    for veh, day, drv in ran:
        if (veh, day) in seen or len(viol_rows) >= 250:
            continue
        if _u("vpick", veh, day) > 0.09:
            continue
        seen.add((veh, day))
        cat = _pick("vcat", veh, day, choices=["超速", "闯禁行", "违停", "疲劳驾驶"])
        pts, fine, zone = {
            "超速": (3, 200, "highway"), "闯禁行": (3, 200, "core"),
            "违停": (0, 150, "suburb"), "疲劳驾驶": (6, 500, "highway")}[cat]
        viol_rows.append((veh, drv, dt.datetime.combine(day, dt.time(
            int(6 + _u("vh", veh, day) * 14), int(_u("vm", veh, day) * 60))),
            f"{cat[:-1] if cat != '违停' else '违停'}", cat, pts, fine,
            _pick("vst", veh, day, choices=["已处理", "已处理", "处理中", "未处理"]), zone))
    execute_values(cur, "insert into violations (vehicle_id, driver_id, occurred_at, code, category, "
                        "points, fine_amount, status, road_zone) values %s", viol_rows,
                   template="(%s::bigint, %s::bigint, %s, %s, %s, %s, %s, %s, %s)")

    # ── incident_tickets  (I8): the REPORTED channel, a small subset of real anomalies ───
    anomalies: dict[int, list] = {}
    for s in stops:
        sid, tid, _seq, _on_time, temp, dmg, alarm = s
        kinds = []
        if temp:
            kinds.append("倒温")
        if dmg and dmg > 0:
            kinds.append("破损")
        if status[sid] == "refused":
            kinds.append("拒收")
        if alarm:
            kinds.append("超时")
        if kinds:
            anomalies.setdefault(tid, []).append((sid, kinds))
    TICKET_TYPE = {"迟到": "超时", "少送/错送": "少送/错送", "货损": "破损", "态度": "态度"}
    for _cid, _tid, _stop, kind in data["complaints"]:
        if kind:
            anomalies.setdefault(_tid, []).append((_stop, [TICKET_TYPE.get(kind, kind)]))

    ticket_rows = []
    ordered = sorted(anomalies.items(), key=lambda kv: _u("tick", kv[0]))
    for tid, items in ordered:
        if len(ticket_rows) >= 107:                     # ≈2.6% of 4,120 trips
            break
        sid, kinds = items[0]
        tday = next(t[1] for t in trips if t[0] == tid)
        kind = kinds[0]
        ticket_rows.append((tid, sid, kind,
                            dt.datetime.combine(tday, dt.time(9 + int(_u("th", tid) * 9),
                                                              int(_u("tm", tid) * 60))),
                            _pick("tch", tid, choices=["客服工单", "司机APP上报", "POD签收"]),
                            _pick("trp", tid, choices=["承运", "承运", "承运", "客户", "不可抗力"]),
                            _pick("tst", tid, choices=["已处理", "已处理", "已处理", "处理中"]),
                            len(items) == 1, f"{kind}：门店反馈" if kind != "倒温" else "在途温度超限"))
    execute_values(cur, "insert into incident_tickets (trip_id, stop_id, type, raised_at, channel, "
                        "responsible_party, status, is_primary, detail) values %s", ticket_rows,
                   template="(%s::bigint, %s::bigint, %s, %s, %s, %s, %s, %s, %s)")

    # ── vehicle_fixed_costs  (K6 TCO) ───────────────────────────────────────────────────
    fixed_rows = []
    for v in data["vehicles"]:
        vid, tonnage = v[0], float(v[2])
        for period in (dt.date(2026, 8, 1), dt.date(2026, 9, 1), dt.date(2026, 10, 1)):
            fixed_rows.append((vid, period,
                                _money(9000 + _u("ins", vid) * 5000),
                                _money(3000 + tonnage * 180 + _u("dep", vid) * 900),
                                _money(200 + tonnage * 40),
                                _money(100 + _u("insp", vid, period) * 200)))
    execute_values(cur, "insert into vehicle_fixed_costs (vehicle_id, period, insurance, depreciation, "
                        "road_tax, inspection) values %s",
                   fixed_rows, template="(%s::bigint, %s::date, %s, %s, %s, %s)")

    return {"trips": len(trips), "stops": len(stops), "schedule": len(schedule_rows),
            "tickets": len(ticket_rows), "violations": len(viol_rows), "fuel_logs": len(fuel_rows),
            "maintenance": len(maintenance_rows), "permits": len(permit_rows),
            "fixed_costs": len(fixed_rows), "fuel_price": price}


# ─────────────────────────────────────────────────────────── the invariants
def check(cur, baseline: dict | None = None) -> list[tuple[str, bool, str]]:
    out = []

    def q(sql, args=None):
        cur.execute(sql, args or ())
        return cur.fetchone()

    def ok(label, cond, detail=""):
        out.append((label, bool(cond), str(detail)))

    # I1
    n = q("select count(*) from stops where service_status <> 'delivered' and on_time")[0]
    ok("I1 non-delivered statuses are only on stops that were already late",
       n == 0, f"{n} on-time stops carry a non-delivered status")
    late = q("select count(*) from stops where not on_time")[0]
    moved = q("select count(*) from stops where service_status is null")[0]
    ok("I1b every stop has a service_status", moved == 0, f"{moved} null")

    # I2
    bad = q("""select count(*) from driver_schedule s where s.status in ('absent','leave')
               and exists (select 1 from trips t where t.driver_id = s.driver_id and t.trip_date = s.day)""")[0]
    ok("I2 no absent/leave day has a trip", bad == 0, f"{bad} contradictions")
    miss = q("""select count(*) from trips t where not exists (
                  select 1 from driver_schedule s where s.driver_id = t.driver_id
                    and s.day = t.trip_date and s.status = 'attended')""")[0]
    ok("I2b every trip's driver is marked attended that day", miss == 0, f"{miss} trips")

    # I3
    bad = q("""select count(*) from violations v where not exists (
                 select 1 from trips t where t.vehicle_id = v.vehicle_id
                   and t.trip_date = v.occurred_at::date)""")[0]
    ok("I3 every violation is on a day that vehicle ran", bad == 0, f"{bad} violations")
    bad = q("""select count(*) from violations v where not exists (
                 select 1 from trips t where t.vehicle_id = v.vehicle_id and t.driver_id = v.driver_id
                   and t.trip_date = v.occurred_at::date)""")[0]
    ok("I3b every violation names that day's driver", bad == 0, f"{bad} violations")

    # I4
    bad = q("""select count(*) from (select vehicle_id, odometer_km,
                 lag(odometer_km) over (partition by vehicle_id order by filled_at) prev
               from fuel_logs) x where prev is not null and odometer_km < prev""")[0]
    ok("I4a fuel_logs odometer never decreases", bad == 0, f"{bad} decreases")
    dl = q("select abs(sum(fuel_liters) - (select sum(liters) from fuel_logs)) from trips")[0]
    ok("I4b Σ trips.fuel_liters == Σ fuel_logs.liters", float(dl) < 1.0, f"delta {dl}")
    dc = q("""select abs((select sum(amount) from fuel_logs) - (select sum(fuel_cost) from trip_costs))""")[0]
    ok("I4c Σ fuel_logs.amount reconciles with Σ trip_costs.fuel_cost",
       float(dc) <= FUEL_PRICE_TOLERANCE, f"delta {dc}")

    # I5
    bad = q("""select count(*) from (
                 select m.vehicle_id, m.total, coalesce(t.app, 0) app from
                   (select vehicle_id, sum(cost) total from maintenance_orders group by 1) m
                 join (select vehicle_id, sum(maintenance_cost) app from trips group by 1) t
                   on t.vehicle_id = m.vehicle_id) x where abs(total - app) > 0.05""")[0]
    ok("I5 maintenance apportioned per vehicle == its orders", bad == 0, f"{bad} vehicles off")

    # I6
    bad = q("""select count(*) from vehicles v where v.core_zone_permit and not exists (
                 select 1 from zone_permits p where p.vehicle_id = v.id and p.valid_from <= date '2026-08-01'
                   and p.valid_to >= date '2026-08-01')""")[0]
    ok("I6a every permitted vehicle holds a permit valid at window start", bad == 0, f"{bad} vehicles")
    bad = q("""select count(*) from vehicles v where not v.core_zone_permit and exists (
                 select 1 from zone_permits p where p.vehicle_id = v.id and p.valid_to >= date '2026-08-01')""")[0]
    ok("I6b no unpermitted vehicle holds a permit valid during the window", bad == 0, f"{bad} vehicles")

    # I7
    bad = q("""select count(*) from maintenance_orders m where exists (
                 select 1 from trips t where t.vehicle_id = m.vehicle_id and t.trip_date = m.opened_at)""")[0]
    ok("I7 no maintenance order lands on a day the vehicle drove", bad == 0, f"{bad} orders")

    # I8
    bad = q("""select count(*) from incident_tickets it where it.stop_id is not null and not exists (
                 select 1 from stops s where s.id = it.stop_id and s.trip_id = it.trip_id
                   and (s.temp_excursion or s.damaged_boxes > 0 or s.alarm_triggered
                        or s.service_status = 'refused'))
               and not exists (select 1 from complaints c where c.stop_id = it.stop_id)""")[0]
    ok("I8a every ticket points at a real anomaly (flag, complaint or refused stop)",
       bad == 0, f"{bad} tickets")
    rep = q("select count(distinct trip_id) from incident_tickets")[0]
    anom = q("""select count(distinct trip_id) from stops
                where temp_excursion or damaged_boxes > 0""")[0]
    ok("I8b the reported set is a small subset of the anomalies", 0 < rep < anom * 0.2,
       f"{rep} reported vs {anom} anomalous trips")

    # I9
    bad = q("""select count(*) from trips t where t.stops_delivered is distinct from (
                 select count(*) from stops s where s.trip_id = t.id and s.service_status = 'delivered')""")[0]
    ok("I9 trips.stops_delivered == its delivered stops", bad == 0, f"{bad} trips")

    # I10
    bad = q("""select count(*) from trips t join routes r on r.id = t.route_id
               where t.actual_km < r.planned_km * 1.0 or t.actual_km > r.planned_km * 1.15 + 0.05""")[0]
    ok("I10 actual_km is a detour of [1.00, 1.15] × planned_km", bad == 0, f"{bad} trips")

    # ── the version's own pre-existing numbers must not move ────────────────────────────
    if baseline is None:
        out.append(("L0 no pre-extension baseline recorded for this database", None,
                    "NOT RUN — run --apply on a fresh copy of this version to record one"))
    else:
        b = baseline
        n = q("select count(*) from stops where on_time")[0]
        ok(f"L1 on_time count is unchanged ({b['stops']['on_time']:,})", n == b["stops"]["on_time"], n)
        n = q("select count(*) from stops")[0]
        ok(f"L2 stop count is unchanged ({b['stops']['n']:,})", n == b["stops"]["n"], n)
        n = q("select round(sum(revenue), 2) from trips")[0]
        ok(f"L3 revenue total is unchanged ({b['trips']['revenue']:,.2f})",
           float(n) == b["trips"]["revenue"], n)
        n = q("select round(sum(cost_total), 2) from trips")[0]
        ok(f"L4 cost_total is unchanged ({b['trips']['cost_total']:,.2f})",
           float(n) == b["trips"]["cost_total"], n)
        n = q("select round(sum(fuel_cost), 2) from trip_costs")[0]
        ok(f"L5 fuel_cost is unchanged ({b['trip_costs']['fuel']:,.2f})",
           float(n) == b["trip_costs"]["fuel"], n)
        n = q("select count(*) from complaints where liability is null")[0]
        ok(f"L6 unjudged complaints is unchanged ({b['complaints']['unjudged']:,})",
           n == b["complaints"]["unjudged"], n)
        n = q("select count(*) from dispatch_decisions where adopted")[0]
        ok(f"L7 adopted dispatch decisions unchanged ({b['dispatch']['adopted']:,})",
           n == b["dispatch"]["adopted"], n)
        n = q("select count(*) from refusals")[0]
        ok(f"L8 refusal count is unchanged ({b['refusals']:,})", n == b["refusals"], n)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", type=pathlib.Path, default=DEFAULT_PROFILE,
                    help="the version's profile json; its dsn block decides the database")
    ap.add_argument("--apply", action="store_true", help="create + fill (idempotent)")
    ap.add_argument("--check", action="store_true", help="assert the invariants, write nothing")
    ap.add_argument("--plan", action="store_true", help="say what it would do")
    args = ap.parse_args()

    dsn = dsn_from_profile(args.profile)
    print(f"profile {args.profile.name} → database {dsn['dbname']} @ {dsn['host']}:{dsn['port']}")
    conn = psycopg2.connect(**dsn)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            if args.plan or not (args.apply or args.check):
                cur.execute("""select table_name from information_schema.tables
                               where table_schema='public'""")
                have = {r[0] for r in cur.fetchall()}
                print("ADDITIONS (7 tables) — present:", [t for t in NEW_TABLES if t in have] or "none")
                print("ADDITIONS (6 columns on stops/trips)")
                print("rows to write: schedule 5,400 · tickets ~107 · violations ~250 · "
                      "fuel_logs ~2,000 · maintenance ~250 · permits ~20 · fixed_costs 180")
                return 0
            if args.apply:
                if read_baseline(dsn["dbname"]) is None:
                    base = write_baseline(cur, dsn["dbname"])
                    print(f"recorded baseline for {dsn['dbname']}: "
                          f"{base['stops']['n']:,} stops / {base['trips']['n']:,} trips")
                stats = apply(cur)
                conn.commit()
                print("APPLIED:", stats)
            if args.apply or args.check:
                results = check(cur, read_baseline(dsn["dbname"]))
                width = max(len(r[0]) for r in results)
                for label, cond, detail in results:
                    print(f"  {'PASS' if cond else 'FAIL'}  {label:<{width}}  {detail}")
                ran = [r for r in results if r[1] is not None]
                failed = [r for r in ran if not r[1]]
                not_run = [r for r in results if r[1] is None]
                print(f"\n{len(ran) - len(failed)}/{len(ran)} invariants hold"
                      + (f" · {len(not_run)} NOT RUN (an unrun check is not a passed check)" if not_run else ""))
                return 1 if failed else 0
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
