# Fresh-install smoke (PLAN P7.4)

Clean stack, public docs only, first applied solve. Run date:
2026-09-20.

**Stack:** fresh `smoke` database on the pinned `odoo:19.0` image
(19.0-20260908) with PostgreSQL 16; the live pinned JAOT v3.9.0 stack
(commit `c5a07e2a0fe9da35bcd69b57b8eda5f33b082d58`) answering at
`/api/v2` — reachable from the Odoo container as
`http://host.docker.internal:8001`.

## Steps (README, verbatim)

1. **Install** — addons in the addons path, then install the modules
   (the bridges follow their `auto_install` rules):

   ```
   odoo -d smoke --stop-after \
     -i stock,delivery,fleet,mrp,jaot_base,jaot_stock,jaot_mrp
   ```

   **51 s** to load 74 modules; `jaot_base`, `jaot_stock` and
   `jaot_mrp` all report `installed`.

2. **Connection** — one API key minted on the JAOT instance
   (the `POST /api/v2/keys/` call, run through the JAOT script; the
   key is never committed or logged), then **JAOT > Configuration >
   Connections** with the base URL and the key. **Test connection**:
   `degraded 3.9.0 — 4/5 health checks. Solvers available: scip,
   highs, cbc, glpk.` (the one failing component is the optional
   Hexaly SDK; database, solver worker, memory and disk are healthy).

3. **First solve** (production scheduling) — one product, two
   confirmed production orders (100 due 2026-10-05, 150 due
   2026-10-06), incumbent plan both starting 2026-10-05. Scenario
   created from **Manufacturing > Scheduling scenarios** and
   submitted: 7 variables, 8 constraints.

   | Step | Result | Time |
   |---|---|---|
   | connection + test | 200 OK, solvers listed | 0.7 s |
   | submit | task enqueued, payload captured | 0.1 s |
   | solve (SCIP) | `optimal`, gap 0.0, objective **500.0** (2 setups × 250) | 5.1 s |
   | compare with baseline | baseline **575.0**, delta **75.0** — the incumbent holds 150 units a day before its deadline (150 × 1 day × 0.5) | 5.1 s |
   | apply | `date_start` written on both orders, 2 before/after audit rows | < 1 s |
   | revert | before-state restored, 2 rows reverted | < 1 s |
   | check staleness | data current | — |

   Optimized plan: order 1 starts 2026-10-05, order 2 starts
   2026-10-06 (its deadline day) — exactly the 75.0 saving the
   baseline delta predicted.

## Result

| Phase | Time |
|---|---|
| fresh install (74 modules) | 51 s |
| connection → applied solve (full flow) | 11.2 s |
| **total** | **≈ 1.5 min** — target < 30 min (SPECS §10.6) met |

Single-run figures on a warm Docker host; not a benchmark.
