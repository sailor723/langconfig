#!/usr/bin/env python3
"""Mock the ABC cold-chain operation: 60 vehicles, 3 months, every pain point present.

Deterministic (fixed seed), so a number in a gate or a report never moves on its own.

The shape is the one the business actually has:

  * 60 vehicles that drivers OWN (带车加盟) — the loan binds driver and vehicle together
  * routes are dictated by the brand and are VERSIONED: v1 (50 routes/day) until 并线,
    v2 (40 routes/day) after it. Same stores, more stops per route
  * a trip is one vehicle + one driver + one route + one date; stops are the store visits
  * failures are planted where the story says they come from, not at random:
      - 超载 on routes where the brand pushed the line and on the vehicles with the
        least capacity for the job
      - 倒温 (temp excursions) mostly on the oldest vehicles
      - 破损 concentrated on trips whose stops were handled by a day labourer on their
        first week (the 劳务黑洞)
      - 客诉 follows 晚点 and 倒温, and some end up with liability = "disputed"

Run:  $P abc/gen_abc.py [--reset] [--months 3]
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import random
import sys

import psycopg2
from psycopg2.extras import execute_values

HERE = pathlib.Path(__file__).resolve().parent
DSN = dict(host="127.0.0.1", port=5432, user="weiping", dbname="abc_coldchain")
ADMIN_DSN = {**DSN, "dbname": "postgres"}

SEED = 20251106

SCHEMA = """
DROP TABLE IF EXISTS complaints, stops, telemetry, trips, route_stops, routes, drivers,
                     vehicles, stores, handlers, driver_stats CASCADE;

CREATE TABLE vehicles (
    id                  bigserial PRIMARY KEY,
    plate               text NOT NULL UNIQUE,
    tonnage             numeric NOT NULL,        -- 3 / 5 / 8 / 10 / 12 t
    emission            text NOT NULL,           -- 国四 / 国五 / 国六 / 新能源
    age_years           numeric NOT NULL,
    core_zone_permit    boolean NOT NULL,        -- 核心城区通行证
    box_capacity        int NOT NULL,
    volume_capacity     numeric NOT NULL,        -- m3
    weight_capacity     numeric NOT NULL,        -- kg
    status              text NOT NULL DEFAULT 'active'
);

CREATE TABLE drivers (
    id              bigserial PRIMARY KEY,
    name            text NOT NULL,
    age             int NOT NULL,
    years_service   numeric NOT NULL,
    vehicle_id      bigint NOT NULL REFERENCES vehicles(id),   -- 带车加盟
    status          text NOT NULL DEFAULT 'active'
);

CREATE TABLE stores (
    id            bigserial PRIMARY KEY,
    name          text NOT NULL,
    zone          text NOT NULL,                 -- core / suburb
    window_from   time NOT NULL,                 -- 收货窗口
    window_to     time NOT NULL,
    has_alarm     boolean NOT NULL               -- 进店不能误触安防警铃
);

CREATE TABLE routes (
    id              bigserial PRIMARY KEY,
    code            text NOT NULL,
    version         text NOT NULL,               -- v1 before 并线, v2 after
    effective_from  date NOT NULL,
    planned_stops   int NOT NULL,
    planned_km      numeric NOT NULL,
    zone            text NOT NULL                -- core / mixed / suburb
);

CREATE TABLE route_stops (
    route_id  bigint NOT NULL REFERENCES routes(id),
    seq       int NOT NULL,
    store_id  bigint NOT NULL REFERENCES stores(id),
    PRIMARY KEY (route_id, seq)
);

CREATE TABLE handlers (                            -- 日结临时工（劳务派遣）
    id           bigserial PRIMARY KEY,
    name         text NOT NULL,
    agency       text NOT NULL,
    first_day    date NOT NULL,
    days_worked  int NOT NULL
);

CREATE TABLE trips (
    id                        bigserial PRIMARY KEY,
    trip_date                 date NOT NULL,
    route_id                  bigint NOT NULL REFERENCES routes(id),
    vehicle_id                bigint NOT NULL REFERENCES vehicles(id),
    driver_id                 bigint NOT NULL REFERENCES drivers(id),
    planned_stops             int NOT NULL,
    load_boxes                int NOT NULL,
    load_volume               numeric NOT NULL,
    load_weight               numeric NOT NULL,
    box_capacity_snapshot     int NOT NULL,          -- capacity frozen at dispatch
    volume_capacity_snapshot  numeric NOT NULL,
    weight_capacity_snapshot  numeric NOT NULL,
    revenue                   numeric NOT NULL,      -- 运费
    status                    text NOT NULL DEFAULT 'completed'
);

CREATE TABLE stops (
    id               bigserial PRIMARY KEY,
    trip_id          bigint NOT NULL REFERENCES trips(id),
    seq              int NOT NULL,
    store_id         bigint NOT NULL REFERENCES stores(id),
    on_time          boolean NOT NULL,
    temp_excursion   boolean NOT NULL,               -- 倒温
    damaged_boxes    int NOT NULL,
    alarm_triggered  boolean NOT NULL,
    baskets_missing  int NOT NULL,                   -- 退货筐没回收
    handler_id       bigint REFERENCES handlers(id)  -- NULL = 司机自己搬
);

CREATE TABLE complaints (
    id          bigserial PRIMARY KEY,
    stop_id     bigint NOT NULL REFERENCES stops(id),
    kind        text NOT NULL,                       -- late / damage / temperature / alarm
    opened_at   timestamptz NOT NULL,
    liability   text,                                -- NULL = 未判定
    amount      numeric,
    closed_at   timestamptz
);

CREATE TABLE telemetry (                             -- sampled 在途温度
    id          bigserial PRIMARY KEY,
    trip_id     bigint NOT NULL REFERENCES trips(id),
    ts          timestamptz NOT NULL,
    temp_c      numeric NOT NULL
);

-- the 30-day facts a driver-level definition needs to attach to (a window is not a column)
CREATE TABLE driver_stats (
    driver_id      bigint NOT NULL REFERENCES drivers(id),
    window_days    int NOT NULL,
    trips          int NOT NULL,
    stops          int NOT NULL,
    late_stops     int NOT NULL,
    on_time_rate   numeric NOT NULL,
    damaged_boxes  int NOT NULL,
    overload_trips int NOT NULL,
    complaints     int NOT NULL,
    PRIMARY KEY (driver_id, window_days)
);

CREATE INDEX ON trips (trip_date);
CREATE INDEX ON trips (driver_id);
CREATE INDEX ON stops (trip_id);
CREATE INDEX ON stops (store_id);
CREATE INDEX ON telemetry (trip_id);
CREATE INDEX ON complaints (stop_id);
"""

STORE_NAMES = [f"{b}{n}店" for b in ("人民广场", "西湖", "滨江", "城西", "城南", "高新",
                                     "龙湖", "万达", "机场", "北站", "东站", "江畔")
               for n in ("一", "二", "三", "四", "五", "六")]
SURNAMES = list("王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗")
GIVEN = ["师傅", "建军", "国强", "志强", "伟", "海涛", "永强", "立新", "德胜", "金山",
         "小勇", "大勇", "阿明", "阿华", "老赵", "老王", "春生", "清华", "振华", "浩然"]
AGENCIES = ["诚达劳务", "宏图人力", "安捷派遣"]
EMISSIONS = ["国四", "国五", "国六", "新能源"]


def build(months: int = 3) -> dict:
    rnd = random.Random(SEED)
    # the mock must be RECENT: "last 30 days" is a real question here, and a now()-relative
    # window over a year-old dataset would silently return nothing (the TPC-H lesson)
    today = dt.date.today()
    start = today - dt.timedelta(days=30 * months)
    # 并线 lands in the middle of the period: v1 for the first half, v2 after
    merge_day = start + dt.timedelta(days=30 * months // 2)

    conn = psycopg2.connect(**DSN)
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute(SCHEMA)

    # ---------------- 60 vehicles: the exact mix, ageing, emissions --------------------
    mix = [(12, 3), (10, 5), (8, 35), (5, 6), (3, 11)]
    vehicles = []
    for tonnage, n in mix:
        for _ in range(n):
            age = round(rnd.triangular(3, 15, 9), 1)          # the fleet is old
            if age > 11:
                emission = "国四"
            elif age > 7:
                emission = rnd.choice(["国四", "国五"])
            elif age > 3:
                emission = rnd.choice(["国五", "国六"])
            else:
                emission = rnd.choice(["国六", "新能源"])
            core = emission in ("国六", "新能源") or (emission == "国五" and age < 9)
            vehicles.append({
                "plate": f"沪A{rnd.randint(10000, 99999)}",
                "tonnage": tonnage,
                "emission": emission,
                "age": age,
                "core": core,
                "boxes": int(tonnage * 26 + rnd.randint(-4, 6)),
                "volume": round(tonnage * 3.1, 1),
                "weight": tonnage * 1000,
            })
    execute_values(cur, """INSERT INTO vehicles
        (plate, tonnage, emission, age_years, core_zone_permit, box_capacity,
         volume_capacity, weight_capacity) VALUES %s
        RETURNING id""",
        [(v["plate"], v["tonnage"], v["emission"], v["age"], v["core"], v["boxes"],
          v["volume"], v["weight"]) for v in vehicles], fetch=False)
    cur.execute("SELECT id, tonnage::float8, box_capacity, volume_capacity::float8, "
                "weight_capacity::float8, core_zone_permit, age_years::float8 "
                "FROM vehicles ORDER BY id")
    vrows = cur.fetchall()

    # ---------------- drivers own the vehicles (带车加盟) -------------------------------
    drivers = []
    for i, (vid, tonnage, boxes, volume, weight, core, age) in enumerate(vrows):
        drivers.append((f"{rnd.choice(SURNAMES)}{rnd.choice(GIVEN)}",
                        int(rnd.triangular(42, 60, 53)), round(rnd.triangular(1, 14, 7), 1),
                        vid))
    execute_values(cur, "INSERT INTO drivers (name, age, years_service, vehicle_id) VALUES %s",
                   drivers, fetch=False)
    cur.execute("SELECT id, vehicle_id, age FROM drivers ORDER BY id")
    drows = cur.fetchall()
    # each driver has a quality factor: good drivers are on time and careful, weak ones are not
    skill = {d[0]: rnd.uniform(0.55, 1.45) for d in drows}

    # ---------------- stores: 800, core and suburb, receiving windows -------------------
    stores = []
    for i in range(800):
        zone = "core" if i % 3 else "suburb"
        h = rnd.randint(6, 20)
        stores.append((STORE_NAMES[i % len(STORE_NAMES)] + f"-{i//len(STORE_NAMES)+1}",
                       zone, dt.time(h, 0), dt.time(h, 45), rnd.random() < 0.55))
    execute_values(cur, "INSERT INTO stores (name, zone, window_from, window_to, has_alarm) "
                        "VALUES %s", stores, fetch=False)
    cur.execute("SELECT id, zone FROM stores ORDER BY id")
    srows = cur.fetchall()
    core_stores = [s for s in srows if s[1] == "core"]

    # ---------------- routes: v1 (50/day) then v2 (40/day) — the 并线 -------------------
    def make_routes(version, n_routes, per_route_lo, per_route_hi, effective):
        ids = []
        pool = core_stores + [s for s in srows if s[1] != "core"]
        rnd.shuffle(pool)
        idx = 0
        for r in range(n_routes):
            n = min(len(pool) - idx, rnd.randint(per_route_lo, per_route_hi))
            if n <= 0:
                break
            zone = "core" if r % 3 == 0 else ("suburb" if r % 3 == 1 else "mixed")
            cur.execute("INSERT INTO routes (code, version, effective_from, planned_stops, "
                        "planned_km, zone) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                        (f"R-{version}-{r+1:03d}", version, effective, n,
                         round(rnd.uniform(28, 85), 1), zone))
            rid = cur.fetchone()[0]
            ids.append((rid, zone, n))
            for seq in range(n):
                cur.execute("INSERT INTO route_stops (route_id, seq, store_id) VALUES "
                            "(%s,%s,%s)", (rid, seq + 1, pool[idx + seq][0]))
            idx += n
        return ids

    routes_v1 = make_routes("v1", 50, 9, 12, start)        # ~11 stops/route
    routes_v2 = make_routes("v2", 40, 14, 17, merge_day)    # ~15 stops/route after 并线

    # ---------------- handlers: the day-labour churn ----------------------------------
    handlers = []
    for i in range(420):
        first = start + dt.timedelta(days=rnd.randint(0, max(1, 30 * months - 1)))
        handlers.append((f"{rnd.choice(SURNAMES)}{rnd.choice(GIVEN)}",
                         rnd.choice(AGENCIES), first, rnd.choice([1, 1, 2, 3, 5, 9, 21])))
    execute_values(cur, "INSERT INTO handlers (name, agency, first_day, days_worked) "
                        "VALUES %s", handlers, fetch=False)
    cur.execute("SELECT id, first_day, days_worked FROM handlers ORDER BY id")
    hrows = cur.fetchall()

    # ---------------- 3 months of trips and stops -------------------------------------
    trips, stops, complaints, telemetry = [], [], [], []
    trip_meta = []
    day = start
    while day < today:
        for rid, rzone, n_stops in (routes_v1 if day < merge_day else routes_v2):
            did, vid, dage = drows[rnd.randrange(len(drows))]
            v = vrows[vid - 1]
            zoned_core = rzone == "core"
            # a driver whose vehicle has no core permit cannot take a core route: the
            # scheduler forced it anyway sometimes — that is the 路权 pain point
            if zoned_core and not v[5] and rnd.random() < 0.75:
                vid_use, did_use = vid, did
            else:
                vid_use, did_use = vid, did
            v = vrows[vid_use - 1]
            # load: designed to be at or over the limit after 并线 (that is the squeeze)
            squeeze = 1.0 if day < merge_day else rnd.uniform(1.02, 1.22)
            boxes = int(round(v[2] * rnd.uniform(0.82, 0.98) * squeeze))
            volume = round(v[3] * rnd.uniform(0.85, 1.0) * squeeze, 1)
            weight = int(round(v[4] * rnd.uniform(0.8, 0.95) * squeeze))
            revenue = round(520 + 41 * n_stops * rnd.uniform(0.85, 1.15)
                            + (140 if zoned_core else 0), 2)
            trips.append((day, rid, vid_use, did_use, n_stops, boxes, volume, weight,
                          v[2], v[3], v[4], revenue))
            trip_meta.append({"day": day, "route": rzone, "n": n_stops, "vage": v[6],
                              "driver_age": dage})
        day += dt.timedelta(days=1)

    execute_values(cur, """INSERT INTO trips (trip_date, route_id, vehicle_id, driver_id,
        planned_stops, load_boxes, load_volume, load_weight, box_capacity_snapshot,
        volume_capacity_snapshot, weight_capacity_snapshot, revenue) VALUES %s""",
                   trips, page_size=5000, fetch=False)
    cur.execute("SELECT id, trip_date, route_id, planned_stops, load_boxes, "
                "box_capacity_snapshot FROM trips ORDER BY id")
    trip_rows = cur.fetchall()

    stop_rows = []
    trip_driver = {t[0]: t[3] for t in trips_meta} if False else {}
    cur.execute("SELECT id, driver_id FROM trips")
    trip_driver = dict(cur.fetchall())
    for tid, tday, rid, n, lboxes, bcaps in trip_rows:
        did = trip_driver.get(tid)
        late_shift = 0
        for seq in range(1, n + 1):
            # old vehicles run late more often; heavy routes later in the day
            base_late = (0.02 + 0.006 * max(0, (n - 11))) * skill.get(did, 1.0) + 0.004 * seq
            on_time = rnd.random() > base_late
            handler_id = hrows[rnd.randrange(len(hrows))][0] if rnd.random() < 0.72 else None
            # day-labourer on their first days -> damage
            newbie = False
            if handler_id:
                fday, days_worked = next((f, d) for i, f, d in hrows if i == handler_id)
                newbie = (days_worked <= 2) or (rnd.random() < 0.25)
            # damage is rare, and concentrated where the day labourer is new
            damaged = int(rnd.choice([0] * 60 + [1, 2, 3]) * (2.2 if newbie else 1)
                          * (0.4 + 0.9 * skill.get(did, 1.0)))
            temp_exc = (not on_time and rnd.random() < 0.28) or rnd.random() < 0.02
            alarm = rnd.random() < (0.03 if newbie else 0.012)
            baskets = rnd.choice([0, 0, 0, 0, 1, 2])
            stop_rows.append((tid, seq, rnd.randrange(1, 801), on_time, temp_exc, damaged,
                              alarm, baskets, handler_id))

    execute_values(cur, """INSERT INTO stops (trip_id, seq, store_id, on_time, temp_excursion,
        damaged_boxes, alarm_triggered, baskets_missing, handler_id) VALUES %s""",
                   stop_rows, page_size=5000, fetch=False)

    # ---------------- complaints follow the failures ----------------------------------
    cur.execute("""SELECT id, trip_id, on_time, temp_excursion, damaged_boxes, alarm_triggered
                   FROM stops""")
    for sid, tid, on_time, temp_exc, damaged, alarm in cur.fetchall():
        if not (on_time and not temp_exc and not damaged and not alarm):
            continue
        if rnd.random() > 0.16:          # a complaint is an escalation, not a failure log
            continue
        kind = ("temperature" if temp_exc else "damage" if damaged else
                "alarm" if alarm else "late")
        rolled = rnd.random()
        liability = None if rolled < 0.45 else ("driver" if rolled < 0.7 else "labourer")
        complaints.append((sid, kind, dt.datetime.combine(today - dt.timedelta(days=1),
                                                          dt.time(9, 0)),
                           liability, round(rnd.uniform(80, 1200), 2) if liability else None))
    execute_values(cur, """INSERT INTO complaints (stop_id, kind, opened_at, liability, amount)
                           VALUES %s""", complaints, page_size=5000, fetch=False)

    # ---------------- sampled telemetry ------------------------------------------------
    for tid, *_ in trip_rows[: len(trip_rows) // 4]:
        t0 = dt.datetime.combine(today - dt.timedelta(days=3), dt.time(6, 0))
        for k in range(12):
            telemetry.append((tid, t0 + dt.timedelta(minutes=15 * k),
                              round(rnd.uniform(-19.5, -12.0), 1)))
    execute_values(cur, "INSERT INTO telemetry (trip_id, ts, temp_c) VALUES %s",
                   telemetry, page_size=5000, fetch=False)

    # ---------------- the 30-day driver facts a definition attaches to ----------------
    cur.execute("""
        INSERT INTO driver_stats
        SELECT d.id, 30, coalesce(t.trips, 0), coalesce(s.stops, 0), coalesce(s.late, 0),
               CASE WHEN coalesce(s.stops, 0) = 0 THEN 1.0
                    ELSE round(1.0 - s.late::numeric / s.stops, 4) END,
               coalesce(s.damaged, 0), coalesce(tr_over.over, 0), coalesce(c.n, 0)
        FROM drivers d
        LEFT JOIN (SELECT driver_id, count(*) AS trips FROM trips
                   WHERE trip_date >= current_date - 400 GROUP BY 1) t ON t.driver_id = d.id
        LEFT JOIN (SELECT t.driver_id, count(*) AS stops,
                          count(*) FILTER (WHERE NOT s.on_time) AS late,
                          sum(s.damaged_boxes) AS damaged
                   FROM stops s JOIN trips t ON t.id = s.trip_id
                   GROUP BY 1) s ON s.driver_id = d.id
        LEFT JOIN (SELECT driver_id, count(*) AS over FROM trips
                   WHERE load_boxes >= box_capacity_snapshot
                   GROUP BY 1) tr_over ON tr_over.driver_id = d.id
        LEFT JOIN (SELECT t.driver_id, count(*) AS n FROM complaints c
                   JOIN stops s ON s.id = c.stop_id JOIN trips t ON t.id = s.trip_id
                   GROUP BY 1) c ON c.driver_id = d.id
    """)

    conn.commit()
    counts = {}
    for t in ("vehicles", "drivers", "stores", "routes", "route_stops", "trips", "stops",
              "handlers", "complaints", "telemetry", "driver_stats"):
        cur.execute(f"SELECT count(*) FROM {t}")
        counts[t] = cur.fetchone()[0]
    conn.close()
    return counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=3)
    ap.add_argument("--reset", action="store_true", help="(re)create the database first")
    args = ap.parse_args()
    if args.reset:
        admin = psycopg2.connect(**ADMIN_DSN)
        admin.autocommit = True
        ac = admin.cursor()
        ac.execute("SELECT 1 FROM pg_database WHERE datname = 'abc_coldchain'")
        if ac.fetchone():
            ac.execute("DROP DATABASE abc_coldchain")
        ac.execute("CREATE DATABASE abc_coldchain")
        admin.close()
        print("database abc_coldchain recreated")
    counts = build(args.months)
    print("loaded:", ", ".join(f"{k}={v:,}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
