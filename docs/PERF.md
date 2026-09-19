# JAOM — Performance measurements (PLAN P5.3)

Measured 2026-09-19 against Odoo 19.0-20260908 in the dev Docker stack
(`dev/docker-compose.yml`), on the same hardware the CI and the MVP gate use.
The harness is `dev/perf.py`, run through the odoo shell:

```
Get-Content dev/perf.py | docker compose -f dev/docker-compose.yml \
    run --rm odoo odoo shell -d <db> --no-http
```

It seeds 50 000 partners + 50 000 confirmed outgoing pickings (uncommitted, so
the DB rolls back on exit), **invalidates the ORM cache** so the extraction is
measured cold (a fresh worker, not the warm session that just created the
rows), then measures a 1 000-line apply and the cron reconcile load. Only the
`PERF` lines below are the evidence; the seed time is setup cost, not a target.

## Results (cold cache)

| Measurement | SPECS target | Measured | Status |
|---|---|---|---|
| Extraction, 50 000 orders | no worker-RAM blow-up; stored fields (§10.2) | **2.20 s**, 50 000 orders captured, 1 vehicle | met |
| Apply, 1 000 lines (2 000 field writes + 2 000 audit rows) | < 60 s (§10.1) | **13.14 s** | met |
| Cron reconcile, 100 scenarios | idempotent + logged, no blow-up (§10.4) | **0.04 s** | met |

Setup cost (informational, not a target): seeding 50 000 pickings with one move
each took ~10–13 min. Real datasets arrive through normal Odoo stock
operations, not a bulk import, so this does not bound a user-facing step.

## Notes

- **Extraction reads only the bound fields** (`partner_id.partner_latitude`,
  `partner_id.partner_longitude`, `shipping_weight`, `jaot_vehicle_id`,
  `jaot_route_sequence`) plus the depot geo and the active fleet. It does not
  load whole picking records, so memory stays bounded by the number of bound
  fields, not the picking schema.
- The 2.20 s figure is for 50 000 orders in one company. The extraction is a
  single `search` plus per-record field resolution; if a domain outgrows
  ~100 000 orders, the next step is to switch the field resolution to a batched
  `search_read`. At the measured scale no change is required and none was made.
- The apply number includes the per-line `savepoint`, the before/after audit
  row per field, and the two field writes per picking. Revert uses the same
  machinery and is of the same order.
- The cron number is the ORM side of the reconcile (search + one poll per
  queued/solving scenario + state transition). Each real poll is one outbound
  HTTP call; with a fake client the 100 polls are 0.04 s, so the reconcile's
  cost scales linearly with the number of in-flight scenarios and never
  re-submits a known task (keyed by `jaot_task_id`).
