# Metric recipes — the three shapes that need declarations, not a hand-written query

A metric that "can just be written in SQL" is not the interesting case. These three are: every JOIN in
them exists **only** because a relationship is declared, and the compiler refuses rather than guesses
when a piece is missing. Each recipe below was measured on the logistics ontology (`abc_coldchain`),
with the numbers shown, so you can tell a real build from a plausible one.

Copy the shape, not the names. The rule behind all three: **a metric declares meaning; the compiler
derives the joins from `:references`.**

---

## Recipe 1 — cross-grain ratio whose denominator lives on another object

**The ask.** "每千公里破损箱数是多少" — damage intensity, boxes per 1,000 km driven.

**Why it is not one table.** The numerator is at `:Stop` grain (one row per delivery: `damaged_boxes`);
the denominator is at `:Trip` grain and its column (`planned_km`) lives on `:Route`, two hops away.
The ratio must be two aggregates divided, not a join-then-count — a join would multiply stops by trips
and inflate both sides.

```ttl
# the denominator as its own declared metric (a ratio always names its two metrics)
:totalPlannedKm a owl:DatatypeProperty ;
    rdfs:label "计划里程合计（按行程）" ;
    :domain :Trip ; :aggregate "sum" ; :formula "planned_km" ; :grain :Trip ; :universe :Trip ;
    :unit "km" ; :additivity "additive" ;
    :businessDescription "每趟按它所用线路的 planned_km 计一次，再对行程求和；不是对 90 条线路定义求和（那是 5,025.8，不是实际跑过的里程）。" .

:damagePer1kKm a owl:DatatypeProperty ;
    rdfs:label "每千公里破损箱数" ;
    :askedAs "每跑一千公里会破多少箱？" ;
    :grain :Stop ; :universe :Trip ; :aggregate "ratio_of_sums" ;
    :numerator :damagedBoxCount ; :denominator :totalPlannedKm ; :scale "1000.0" ;
    :unit "count" ;
    :businessDescription "分子在站点，分母在行程×线路。两侧各自先聚合再相除；:universe 写分母的颗粒度。" .
```

**What the compiler produced** (note the JOIN — it exists because `:routeOf` is declared):

```sql
SELECT (1000.0) * (((SELECT sum(stops.damaged_boxes) … FROM stops)::numeric) /
       NULLIF((SELECT sum(routes.planned_km) … FROM trips JOIN routes ON trips.route_id = routes.id), 0))
```

**Measured (logistics):** `damagePer1kKm = 36.0097452699625488`.
**Independent route** (per-route km × that route's trip count, then summed; damaged boxes summed per
trip first): `8,144 / 226,161.0 × 1000` → the same number, to the last digit.
**Why the denominator is `:Trip`, not `:Route`:** summing the 90 route *definitions* gives 5,025.8 km —
it answers "how long are the routes", not "how far did the fleet drive".

**Conventions this encodes.** `:grain` = the numerator's grain, `:universe` = the denominator's
(same as the existing `complaintsPer1kStops`); a ratio declares `:numerator`/`:denominator` and never
`sum(a)/sum(b)` typed by hand; `:scale` for "per 1000".

---

## Recipe 2 — grouped metric whose dimension is two hops away

**The ask.** "按线路版本看破损箱数" / "哪台车破损最多".

**Why it is not one table.** `damaged_boxes` is on `stops`; the dimension (`routes.version`,
`vehicles.plate`) is two declared hops away: `stops → trips → routes|vehicles`.

```ttl
:damagedBoxesByRouteVersion a owl:DatatypeProperty ;
    rdfs:label "按线路版本看破损箱数" ;
    :askedAs "并线前后破损有变化吗？" ;
    :domain :Stop ; :aggregate "sum" ; :formula "damaged_boxes" ; :grain :Stop ; :universe :Stop ;
    :groupBy :routeVersion ; :unit "count" ; :additivity "additive" .

:damagedBoxesByVehicle a owl:DatatypeProperty ;
    rdfs:label "按车辆看破损箱数" ;
    :askedAs "哪台车破损最多？" ;
    :domain :Stop ; :aggregate "sum" ; :formula "damaged_boxes" ; :grain :Stop ; :universe :Stop ;
    :groupBy :plate ; :unit "count" ; :additivity "additive" .
```

**Produced:**

```sql
SELECT routes.version AS key, sum(stops.damaged_boxes) AS v FROM stops
  JOIN trips ON stops.trip_id = trips.id JOIN routes ON trips.route_id = routes.id
  GROUP BY routes.version ORDER BY 2 DESC;

SELECT vehicles.plate AS key, sum(stops.damaged_boxes) AS v FROM stops
  JOIN trips ON stops.trip_id = trips.id JOIN vehicles ON trips.vehicle_id = vehicles.id
  GROUP BY vehicles.plate ORDER BY 2 DESC;
```

**Measured (logistics):** `v1 = 3,490` · `v2 = 4,654` (trips: v1 2,250 · v2 1,800);
top vehicles `沪A35091 = 253`, `沪A73435 = 229`, `沪A67859 = 204` (60 rows).
Both confirmed by an independent route that sums per trip first and then per version.

**The alias trap.** 「哪台车破损最多」 only reaches `damagedBoxesByVehicle` after the profile's
`aliases` gains `"车": "vehicle"`. A missing synonym is not a missing metric — check the words before
adding a declaration.

---

## Recipe 3 — two dimensions, four tables, three declared links

**The ask.** "哪个区域的哪台车破损最多" — a two-key GROUP BY whose keys live on two different objects.

```ttl
:damagedBoxesByZoneAndVehicle a owl:DatatypeProperty ;
    rdfs:label "按门店区域和车辆看破损箱数" ;
    :domain :Stop ; :aggregate "sum" ; :formula "damaged_boxes" ; :grain :Stop ; :universe :Stop ;
    :groupBy :storeZone ; :groupBy :plate ; :unit "count" ; :additivity "additive" .
```

```sql
SELECT stores.zone AS key1, vehicles.plate AS key2, sum(stops.damaged_boxes) AS v
FROM stops JOIN stores ON stops.store_id = stores.id
           JOIN trips   ON stops.trip_id = trips.id
           JOIN vehicles ON trips.vehicle_id = vehicles.id
GROUP BY stores.zone, vehicles.plate ORDER BY 3 DESC;
```

**Measured (logistics):** 120 rows, total 8,144 (the total is the arithmetic check: the groups must
add up to `damagedBoxCount`), top `core / 沪A73435 = 168`, then `core / 沪A35091 = 167`.

---

## What the compiler will NOT do (measured, refused by name)

- `:aggregate "ratio_of_sums"` **with** `:groupBy` → *":aggregate 'ratio_of_sums' with :groupBy is not
  supported (sum/count/avg/min/max are)"*. A grouped ratio has to be split: an ungrouped cross-grain
  ratio (Recipe 1) or a grouped additive metric (Recipe 2).
- a `:formula` column that is not a column of the grain class **or of a class reachable through
  declared relationships** → refused with the reachable set named, e.g.
  *"formula mentions 'reveneu', which is not a column of :Trip or of any class reachable through
  declared relationships (['Driver', 'Route', 'Trip', 'Vehicle'])"*. That list is the ontology telling
  you what it can join to.
- a `:where` class with no axiom, a `:grain` class with no `:physicalTable`, a `:formula` with no
  `:grain` → each refused by name, each a backlog item rather than a failure.

## The check that makes a recipe real

```bash
PY=/Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python
$PY scripts/check_metric.py --profile work/logistics/logistics_settings.json --metric damagePer1kKm
#   -> compiled SQL + value + guard notes
$PY scripts/check_metric.py --profile work/logistics/logistics_settings.json --metric damagePer1kKm \
    --independent "select 1000.0 * (select sum(damaged_boxes) from stops)::numeric
                   / (select sum(r.planned_km) from trips join routes r on r.id = trips.route_id)"
#   -> [PASS]/[FAIL] the two routes agree
```

A grouped metric prints its key/value pairs (a group key is not a number). A number that runs is not a
number that is right: the second route is the only proof.
