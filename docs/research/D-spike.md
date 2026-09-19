# D — Spike: Odoo → JAOT end-to-end VRP (script, no addon)

**Status:** complete — 2026-09-19 (PLAN P1.4)

**Verdict: the full flow works end-to-end with real Odoo records and real
JAOT.** Extraction follows the P1.2 binding set, the VRP is submitted as a
plain `OptimizationProblem`, and the SPECS 4.6 baseline (fix-all-variables
re-solve) matches the solution exactly (delta 0.000000). **P1.5 gate:
PASSED** — no failure attributable to the JAOT API or the role mapping;
the only infeasibility encountered was a sign bug in the spike's own
formulation, caught by JAOT's infeasibility-analysis (F8).

## 1. What the spike proves

`scripts/spike/spike_vrp.py` (stdlib only, no Odoo addon, no third-party
packages):

1. **Seed** — loads the seeded synthetic dataset (`vrp_data.py`, the future
   P2.6 generator, kept verbatim) into the local Odoo dev DB over XML-RPC:
   50 outbound pickings (200 move lines, one product per line), 4 vehicles,
   depot partner geo. Idempotent (`--seed` cleans first).
2. **Extract** — follows the P1.2 binding set exactly: per role
   `res_model` + `domain` define the record set, `field_path` is evaluated
   per record through a path resolver (finding F2: `read()` does not
   resolve dotted paths natively), `vehicle_capacity` is a constant
   parameter (finding F1).
3. **Build** — arc-flow + MTZ CVRP as a JAOT `OptimizationProblem`:
   binary `x[t][i][j]` (truck t travels i→j, node 0 = depot), per-truck
   flow conservation, visit-exactly-once, depot out/in, capacity, MTZ
   subtour elimination; objective = total haversine km.
4. **Solve** — `POST /solve/async` → poll `GET /solve/async/{task_id}` →
   `GET /models/executions/{id}` (contract per note C, field names frozen
   there).
5. **Baseline** (SPECS 4.6) — re-solves the same problem with every
   decision variable fixed to the found solution; objective delta must be
   ~0. Exit code 0 = match, 1 = mismatch.

## 2. How to run

Prerequisites: the dev stack (`dev/docker-compose.yml`, Odoo 19 + PG16)
and the JAOT stack (sibling repo, API on `:8001`) both up; `fleet`
installed on the dev DB. The API key lives in `dev/.env`
(`JAOT_API_KEY=…`, gitignored).

```
python scripts/spike/spike_vrp.py --seed            # load dataset
python scripts/spike/spike_vrp.py --run             # needs JAOT_API_KEY env
python scripts/spike/spike_vrp.py --clean           # remove dataset
```

Env overrides: `ODOO_URL`, `ODOO_DB`, `ODOO_USER`, `ODOO_PASSWORD`,
`JAOT_BASE`. `--run` exit code: 0 = solution + baseline match, 1 =
mismatch or infeasible.

## 3. Dataset

`scripts/spike/vrp_data.py` — seeded (`SEED=42`), pure data (no Odoo or
network imports): one depot (Madrid city centre), 50 orders in a ~8 km
spread, 4 lines per order (200 total), order demand 40–160 kg (sum of line
weights, rounded), 4 vehicles at 1600 kg, total demand ≈ 5055 kg
(< 6400 kg fleet capacity). The same module is reused verbatim by the
addon test suite (P2.6).

## 4. Formulation

Arc-flow + MTZ, node 0 = depot. One binary per (truck, i≠j) arc; MTZ
variables `u[t][i] ∈ [1, n]` per (truck, city); constraints: visit
exactly once (any truck), per-truck flow conservation, one departure and
one return per truck, per-truck load ≤ 1600 kg (constant — F1), MTZ.
Objective: minimize total distance (haversine, km). Distance matrix role:
Euclidean placeholder until the provider decision (P1.5 input, OPEN in
SPECS).

## 5. Findings (F4–F9 — numbering continues B-roles)

- **F4 — `stock.move.weight` is computed, not writable.** It is
  `product.weight × product_uom_qty` (stock_delivery); seeding a weight on
  the move is silently ignored. Per-line demand therefore rides on the
  product: one `product.product` per order line with
  `weight = weight_kg / qty`. (One product per line matters because Odoo
  merges same-product moves into one move line.) `product.product.weight`
  is a regular writable float.
- **F5 — `fleet.vehicle.name` is computed** (brand/model/license_plate),
  so name-keyed upsert/clean never matches. Identity for vehicle records
  comes from the writable `license_plate`.
- **F6 — `fleet.vehicle.model.brand_id` points to `fleet.vehicle.model.brand`**,
  not `res.partner`. Creating a fleet model requires upserting a brand row
  first.
- **F7 — extracted demand drifts ≤ 0.3 kg (0.006%) from the source
  dataset.** The per-line product weight (`weight_kg / qty`) is rounded to
  the database weight digits, and `shipping_weight` is recomputed from the
  rounded values. The solution and the baseline both use the extracted
  values, so the SPECS 4.6 comparison is unaffected; a real installation
  sees the same rounding and it is honest data, not a bug.
- **F8 — JAOT's infeasibility-analysis caught a sign bug in the spike's
  own flow constraints.** The tout side of flow conservation was joined
  with `" + "` after a single `" - "`, so all outgoing arcs except the
  first were positive: the model sent was infeasible while the intended
  model was feasible. JAOT returned an IIS (`visit_*`, `flow_*`,
  `depot_in_*`) that was infeasible only under the mis-sent expression —
  dumping the JSON exposed it. Fixed by joining the tout side with
  `" - "`. Confirms the IIS endpoint (note C, step 10) is a practical
  debugging tool; note the exact-IIS cap (~150 constraints/bounds) — above
  it the analysis degrades to `llm_only` with no constraint list.
- **F9 — scale and solver behaviour at 50 orders / 4 vehicles:**
  10 400 variables, 10 062 constraints, 2 238 KB payload; SCIP hit the
  600 s option time limit at gap 0.60 % (objective 132.9485 km); the
  baseline re-solve (all decision variables fixed) went to proven optimal
  in 2.4 s with identical objective. MTZ is numerically fine at n = 50.
  The time limit is the problem's `options.time_limit_seconds`, not an
  API-side budget.

## 6. P1.5 gate verdict

The gate (PLAN P1.5): "the spike works end-to-end with real data and real
JAOT; if it fails for reasons of the JAOT API or the role mapping →
stop". It works. Every stage ran against live systems: XML-RPC reads from
the real dev DB, extraction through the P1.2 bindings, live JAOT
solve/poll/execution, and a baseline match to 1e-6. The one infeasibility
observed was the spike's own formulation bug (F8), which the platform's
IIS endpoint surfaced — i.e. the platform failed loudly and correctly, not
silently. **Gate passed; P2 may proceed.** Carry-forward: F4 (per-line
product weight) into the P3.2 binding documentation, F5/F6 (fleet field
semantics) into the P3.2 fleet binding notes, F7 into the P3.3
extraction-engine tests, F9 (solver time budgeting) into the P2.4
scenario timeout handling.

## 7. Evidence log (run 2026-09-19, Odoo 19.0-20260908, JAOT 3.9.0)

```
python scripts/spike/spike_vrp.py --seed
  -> seeded: 50 pickings / 200 lines, 4 vehicles, total demand 5055.1 kg
python scripts/spike/spike_vrp.py --run
  -> extract: depot partner geo ok; 50 pickings, total demand 5055.4 kg (F7)
  -> problem: 10400 variables, 10062 constraints, payload 2238 KB
  -> solve: scip, solver_status=time_limit, objective 132.9485,
     gap 0.6009, 569 725 ms, nodes 9722
  -> tours: 4 (loads 1523.8 / 1003.4 / 1392.0 / 1136.1 kg, all <= 1600)
  -> baseline (fix-all re-solve): scip, optimal, objective 132.9485,
     2389 ms, delta +0.000000 (MATCH), exit 0
python scripts/spike/spike_vrp.py --seed   (idempotency check)
  -> cleaned 50 pickings, 50 partners, 4 vehicles, 1 model, 1 brand,
     200 products; re-seeded cleanly
Infeasibility debugging session (before F8 fix):
  -> 2 orders / 1 vehicle (provably feasible by hand) -> infeasible
  -> IIS: visit_1, visit_2, flow_0_1, flow_0_2, depot_in_0 — feasible by
     hand, so the sent model must differ from the intent
  -> dumped JSON: flow_0_1 = "x_0_0_1 + x_0_2_1 - x_0_1_0 + x_0_1_2 = 0"
     (last term should be negative) -> fixed, all small instances optimal
  -> throwaway diag scripts removed after use
```
