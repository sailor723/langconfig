# A test run of the skill on an unseen database

This is the artifact of testing `build-ontology-from-db` against a database the skill had never
seen: a small clinic (patients, doctors, appointments, treatments, invoices, payments, insurance
claims), 5,418 appointments and 6,443 treatment lines over 120 days.

What it exercised that the three examples do not:

- a **composite primary key** on the association (`treatment_lines (appointment_id, seq)`) — and the
  brief flagged it for confirmation instead of deciding
- a **reified many-to-many**: an appointment contains treatments, and the line carries
  `qty * unit_price * (1 - discount)`
- a **text primary key** (`treatments.code`)
- a **fiscal-ish ratio** (`noShowRate`) and a **cross-grain ratio** (`revenuePerCompletedVisit`)
- a **four-hop group-by** (`revenueByPatientCity`: treatment_lines → appointments → patients → city)
- a **nullable state** as a definition (`:PendingClaim ≡ decision IS NULL`) — the one declared predicate
- **recent dates**, so a 90-day guardrail window is correct here (the opposite of TPC-H)

## What the run produced

```
$ introspect_db.py --dsn …clinic_db            → 8 tables, composite keys, dimensions, date ranges
$ scaffold_ttl.py  --brief brief.json          → draft 01-structure.ttl
$ (human) 02-meaning.ttl                       → 5 definitions, 12 metrics
$ check_ontology.py --profile … --truth …      → 12/12 metrics == hand-written truth, 4 mutations red
```

Numbers (ground truth written by hand, revenue computed two ways that agreed):

| metric | value |
|---|---|
| appointments | 5,418 |
| noShowAppointments | 1,077 |
| noShowRate | 19.88 % |
| treatmentRevenue | 1,353,412.00 |
| revenuePerCompletedVisit | 418.24 |
| pendingClaims | 642 (of 1,934 claims = 33.2 %) |
| revenueByPatientCity | 无锡 361,352 · 上海 356,874 · 苏州 343,907 · 杭州 ~291,279 |
| revenueByTreatment | X光 403,312 · 输液 274,356 · 慢病随访 230,415 … |
| appointmentsByStatus | completed 3,236 · cancelled 1,105 · no_show 1,077 |

## Two defects the test found in the skill itself

Both are fixed in `scripts/scaffold_ttl.py`, and both would have cost a careful human a debugging
session:

1. **Property names collided across classes.** The draft emitted `:id` for six classes, `:name` for
   three, `:appointment` for two. In RDF that is ONE property with six domains, so
   `class_columns()` dropped it everywhere and every class lost its key column. Names are now unique
   per class (`:patientId`, `:appointmentId`).
2. **FK columns were emitted twice** — as a data property and as the link — so one relationship
   became two things and the name collided with the target's own key (`:doctorId` vs `:doctorId2`).
   A FK column now becomes only the link.

And one gap in the introspection: a freshly loaded database has `reltuples = -1`, so the brief said
"unknown rows" for every table. The script now runs `ANALYZE` first.
