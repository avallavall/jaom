# JAOM end-to-end suite

Playwright suite that drives the real Odoo 19 web client and asserts behaviour
through JSON-RPC. It lives under `dev/` (lint-excluded dev tooling) and
depends only on Node + Playwright — nothing it does leaks into the add-on
modules. One case per user flow; the runner exits `0` only when every case
passes and writes per-case results (plus a screenshot per failure) to
`dev/e2e/results/e2e_results.json` (git-ignored).

## What it exercises (39 cases)

**Connection management**
- Manager login and navigation.
- Create a per-company connection (API key stored through
  `ir.config_parameter`), masked key rendering, *Test connection* success.
- Failure path: unreachable endpoint.
- Failure path: reachable endpoint with a wrong key (JAOT 401 surfaced).
- `default_solver` not in the live solver list → the test result is a
  WARNING naming the solver.
- *Remove key* from the UI: key leaves the system parameter, the masked
  field clears, *Test connection* fails with a clear message, restore works;
  the chatter carries `API key stored.` / `API key removed.`.
- Save a new key through the manager form field (UI write path).
- Uniqueness: one connection per company, one recipe code per company.

**Company isolation**
- A scenario for a company with no binding for the recipe is refused at
  submit with an explicit error (no silent union of companies' data).
- A submit for a company with no connection at all names the missing
  connection; both scenarios stay draft.

**Recipe and binding authoring**
- *Validate* on a valid recipe (UI + RPC).
- *Show bindings* opens the binding list for the recipe.
- *Validate* catching a syntactically invalid expression planted by direct
  SQL (the audit re-check is not a rubber stamp).
- Binding create/write guards: expression syntax, domain syntax, non-list
  domain literal, missing source model for a variable role, missing constant
  value for a parameter role.

**Base-module domain (toy knapsack)**
- Full lifecycle on `jaot.demo.item`: Solve (the unique optimum is verified
  against the a-priori optimum), Apply writes the `selected` flags, Revert
  restores them; plain-language line text (Selected / Not selected).

**Scenario lifecycles**
- New scenario from the UI (list > New > name + recipe > Save).
- Full MRP lifecycle: Solve → solved (4 lines, optimal; the request payload,
  the solver's response, and the binding snapshot are all captured) → Compare
  with baseline (delta on `kpi_summary`) → What-if (rows stored and the
  *What-if analysis* tab renders them) → Apply (confirmation-gated, MO dates +
  audit log + `applied_by`, and the *JAOT scheduling* form group on each MO) →
  Revert (confirmation-gated, MO dates restored).
- Second round: re-Apply on the reverted scenario, then re-Revert; the
  `jaot_scenario_id` link on the MOs follows the scenario and is
  audit-logged.
- State-machine guards: every action refuses the wrong state with a clear
  message.
- Failed is a dead end: a scenario planted in `failed` can neither be
  submitted, applied, reverted, nor baselined — and the reconcile does not
  pull it back out.
- Staleness: positive (mutated source MO → `data_stale` + warning banner)
  and negative (untouched data → current).
- Infeasible MRP solve (capacity cut → failed + infeasibility record, and
  the *Error / infeasibility* tab renders it).
- KPI headline with no baseline: a freshly solved scenario states the
  objective value plainly, unit-labelled (e.g. "Objective 1000.00 USD
  (minimized)") and the form's Result banner shows the same sentence.
- Apply when every target record is gone: the error names the condition,
  the scenario stays `solved` (not `applied`), and the records can be rebuilt.
- Cancel a queued scenario from the UI.
- Orphan backstop: a scenario stuck `queued` without a JAOT task id is
  failed by the reconcile with a timeout error.
- Apply with a deleted source record: the apply skips the missing record,
  writes the rest, and reverts cleanly (the record is restored afterwards).
- VRP lifecycle: Solve → solved (4 pickings) → Apply (confirmation-gated,
  vehicle + route sequence + `jaot_scenario_id` written, and the *JAOT
  routing* form group on the picking) → Revert (restored).
- VRP baseline + what-if: an applied plan becomes the incumbent, a second
  scenario is baselined against it (delta written), and what-if runs on the
  applied scenario; both scenarios are reverted afterwards.
- Infeasible VRP solve (vehicle capacity below a picking's demand).
- Plan explanation: a solved MRP scenario exposes the *Explanation* form
  section — objective terms (setups / inventory holding) and the tightly
  used constraints in plain language, no machine identifiers leaking.

**Security (role/ACL controls)**
- Viewer: reads a scenario, sees no manager action buttons, no expression
  column, no key input field, no *Remove key*; cannot create scenarios or
  apply them (AccessError); can still read the apply log and run the
  un-gated *Test connection*.
- Manager: the `group_system`-only expression column and the *JAOT
  identifiers* block are hidden.
- Viewer on a solved MRP scenario: every plain-language field (record label,
  decision text, before→after preview) renders without leaking a machine
  identifier (variable name, field path, or a raw model reference).
- System admin (`e2eadmin`): the positive control — the expression column
  and the *JAOT identifiers* block are visible.

**Audit and rendering**
- Scenario list renders the accumulated rows with their states and a
  KPI headline column.
- The scenario chatter carries the lifecycle events (submitted, solved,
  applied, reverted); the config chatter carries the key events.
- Reverted audit-log rows are listed in the Apply Log.
- Human-readable presentation (P9.7): a solved MRP scenario exposes a
  plain-language KPI headline, per-line plain-text decisions and a
  before→after preview; the form renders the Result banner plus the
  plain-language line columns, with no machine identifiers leaking.

## Prerequisites

1. The dev stack is up: `docker compose -f dev/docker-compose.yml up -d`.
2. The `e2e` database is seeded (users `jaotmgr`/`jaotview`/`e2eadmin`,
   company `E2E B`, the widget product, four confirmed MOs, two active fleet
   vehicles, four outgoing pickings):

   ```
   docker compose -f dev/docker-compose.yml run --rm odoo \
     odoo shell -d e2e --no-http < dev/e2e/seed_e2e.py
   ```

   After seeding (or any out-of-band group change), restart the container:
   `docker restart jaom_odoo` — the running process keeps a stale ACL cache.
3. A self-hosted JAOT instance reachable from the Odoo container. The
   default endpoint baked into the suite is `http://host.docker.internal:8001`.
4. The JAOT API key, kept in a file **outside the repo** (never committed).
   The suite reads it from `C:\Users\vall-\.qwen\tmp\jaom\e2e_key.txt`.

## Run

```
cd dev/e2e
npm install            # first time only (Playwright + Chromium)
npm test               # = node e2e.mjs
```

Override via environment if needed:

| Variable | Default |
| --- | --- |
| `JAOT_E2E_BASE` | `http://127.0.0.1:8069` |
| `JAOT_E2E_KEY_FILE` | `C:\Users\vall-\.qwen\tmp\jaom\e2e_key.txt` |

## Notes

- Solves are driven by calling `jaot.scenario.reconcile_jaot_scenarios` in a
  poll loop rather than waiting the one-minute `ir.cron`; the reconcile logic
  is the same code the cron invokes, so it exercises the real production path
  without the wait.
- Scenarios are created with timestamped names and are not deleted, so re-
  runs do not collide; the seed and the suite are both idempotent.
- One case (`recipe_validate_invalid`) plants an invalid expression by direct
  SQL inside the Odoo container (`docker exec ... psql`) on purpose: it
  bypasses the ORM guards to prove the *Validate* audit check catches data
  the write path did not.
