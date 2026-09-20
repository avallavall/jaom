# JAOM — JAOT for Odoo

JAOM connects an Odoo 19 Community installation to a
[self-hosted JAOT](https://github.com/avallavall/jaot) v3.9.0 optimizer.
It is a **thin client**: the math runs in JAOT, Odoo holds the business
data, and the addon extracts it, submits it, and writes the optimized
plan back — audited, explicit, and revertible. There is no solver in
Odoo and no data leaves your infrastructure.

## Components

| Module | Domain | What it adds |
|---|---|---|
| `jaot_base` | framework | JAOT connection, recipes, bindings, scenarios, the apply/revert engine, reconciliation cron |
| `jaot_stock` | delivery routing (VRP) | the `vrp` recipe over `stock.picking` / `stock.warehouse` / `fleet.vehicle`; writes the assigned vehicle + route position onto pickings |
| `jaot_mrp` | production scheduling | the `mrp` lot-sizing recipe over `mrp.production`; writes `date_start` onto confirmed production orders |

`jaot_stock` auto-installs when `stock` + `fleet` are present;
`jaot_mrp` auto-installs when `mrp` is present.

## Requirements

- Odoo 19 Community (tested against the `odoo:19.0` image)
- PostgreSQL 16
- A self-hosted JAOT v3.9.0 instance (pinned commit
  `c5a07e2a0fe9da35bcd69b57b8eda5f33b082d58` is the contract this
  addon was built and tested against; see `docs/ci.md`)
- License: LGPL-3, zero dependencies outside Odoo core

## Installation

1. Copy the three addon directories into your addons path
   (e.g. `/mnt/extra-addons`) and update the addons list.
2. In Odoo, update the apps list and install **JAOT Base**
   (the bridges follow their `auto_install` rules).
3. Open **JAOT > Configuration > Connections** and create one
   connection per company that will use JAOT:
   - **JAOT base URL** — e.g. `http://jaot.example.com` (the API
     lives under `/api/v2`)
   - **New API key** — a key from your JAOT instance (created
     against the JAOT API, `POST /api/v2/keys/`; the key is stored
     in `ir.config_parameter`, never on the record, and only a
     masked form is ever displayed)
   - Poll interval (5/10/30 s), solve time limit, gap tolerance,
     optional default solver
4. Click **Test connection** on the connection form: it calls
   `health/status` + `solvers/available` and reports the JAOT
   version and the available solvers.

## First solve

1. Open the domain menu — **Inventory > Operations > Routing
   scenarios** or **Manufacturing > Scheduling scenarios** — and
   create a scenario for the recipe.
2. **Submit**: the addon extracts the bound dataset (stored fields
   only, company-filtered, with a snapshot hash), formulates the
   problem, and enqueues it in JAOT (`solve_async`).
3. The reconciliation `ir.cron` (every poll interval) picks up
   terminal states: the scenario moves to *solved* with one line per
   business record — or *failed* with the infeasibility analysis
   (IIS) when the dataset cannot be satisfied.
4. Review the lines and the KPI summary. **Compare with baseline**
   re-solves the same recipe pinned to the incumbent plan and shows
   the objective delta (overall and per line). **What-if analysis**
   runs JAOT's scenario-analysis batch (parameter relax/tighten
   sweeps) and stores the rows on the scenario.
5. **Apply** (manager only, explicit confirmation) writes the
   decisions back in per-record savepoints, logging before/after
   values; **Revert** restores the logged before-state. Every write
   lands in the Apply Log with a full audit trail.
6. If the underlying data changed after the solve, the
   **Check staleness** action and the warning banner on the form
   tell you the snapshot no longer matches the database.

## The routing bridge (`jaot_stock`)

- **Formulation:** arc-flow + MTZ vehicle routing; minimises total
  distance (haversine in v1 — a road-distance provider is a
  documented future dependency decision, not a default).
- **Roles and default bindings:** depot geo from `stock.warehouse`
  (its partner), order geo + `shipping_weight` from `stock.picking`,
  fleet from `fleet.vehicle`, and the vehicle capacity as a constant
  parameter binding (Community has no per-vehicle cargo field).
- **Solution mapping:** one line per picking, carrying the assigned
  vehicle and the route position; the variable naming convention
  (node 0 = depot, nodes 1..n = orders in `res_id` order) is the
  contract that keeps apply safe.
- **Apply writes:** `jaot_vehicle_id` + `jaot_route_sequence` on
  `stock.picking`.

## The production scheduling bridge (`jaot_mrp`)

- **Dataset:** confirmed/planned production orders with a deadline
  (`product_qty`, `date_deadline`).
- **Formulation:** single-machine capacitated lot sizing — each
  order is produced in lots on days at or before its deadline under
  a daily capacity; the objective trades per-lot setup cost against
  per-unit, per-day inventory holding cost.
- **Parameters:** daily capacity, setup cost and holding cost have
  no standard source in Community, so they are parameter bindings
  (defaults: 800.0 / 250.0 / 0.5 — edit them per company under
  **JAOT > Configuration > Bindings**).
- **Apply writes:** `date_start` on the production order (the day
  the lot is produced).

## Security

- Two groups: **User** (read) and **Manager** (manage; Apply/Revert
  are Manager-only and confirmation-gated).
- Company rules on every model; extraction is company-filtered and
  the negative cross-company paths are covered by tests.
- The API key lives in `ir.config_parameter`, is masked in the UI,
  and is never logged.

## Documentation

- `docs/SPECS.md` — the specification (decisions, contract, quality
  bar)
- `docs/PLAN.md` — the development plan and progress
- `docs/ci.md` — the CI pipeline and its local verification record
- `docs/PERF.md` — performance measurements against the SPECS §10
  targets
- `docs/smoke.md` — the fresh-install smoke (install → first applied
  solve, timed)
- `CHANGELOG.md` — what changed in each release

## License

LGPL-3.
