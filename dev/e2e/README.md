# JAOM end-to-end suite

Playwright suite that drives the real Odoo 19 web client and asserts behaviour
through JSON-RPC. It lives under `dev/` (lint-excluded dev tooling) and
depends only on Node + Playwright — nothing it does leaks into the add-on
modules. One case per user flow; the runner exits `0` only when every case
passes and writes per-case results (plus a screenshot per failure) to
`dev/e2e/results/e2e_results.json` (git-ignored).

## What it exercises (32 cases)

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

**Recipe and binding authoring**
- *Validate* on a valid recipe (UI + RPC).
- *Validate* catching a syntactically invalid expression planted by direct
  SQL (the audit re-check is not a rubber stamp).
- Binding create/write guards: expression syntax, domain syntax, non-list
  domain literal, missing source model for a variable role, missing constant
  value for a parameter role.

**Scenario lifecycles**
- New scenario from the UI (list > New > name + recipe > Save).
- Full MRP lifecycle: Solve → solved (4 lines, optimal) → Compare with
  baseline (delta on `kpi_summary`) → What-if (rows stored) → Apply
  (confirmation-gated, MO dates + audit log + `applied_by`) → Revert
  (confirmation-gated, MO dates restored).
- Second round: re-Apply on the reverted scenario, then re-Revert; the
  `jaot_scenario_id` link on the MOs follows the scenario and is
  audit-logged.
- State-machine guards: every action refuses the wrong state with a clear
  message.
- Staleness: positive (mutated source MO → `data_stale` + warning banner)
  and negative (untouched data → current).
- Infeasible MRP solve (capacity cut → failed + infeasibility record).
- Cancel a queued scenario from the UI.
- Orphan backstop: a scenario stuck `queued` without a JAOT task id is
  failed by the reconcile with a timeout error.
- Apply with a deleted source record: the apply skips the missing record,
  writes the rest, and reverts cleanly (the record is restored afterwards).
- VRP lifecycle: Solve → solved (4 pickings) → Apply (confirmation-gated,
  vehicle + route sequence + `jaot_scenario_id` written) → Revert (restored).
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
- System admin (`e2eadmin`): the positive control — the expression column
  and the *JAOT identifiers* block are visible.

**Audit and rendering**
- Scenario list renders the accumulated rows with their states.
- The scenario chatter carries the lifecycle events (submitted, solved,
  applied, reverted); the config chatter carries the key events.
- Reverted audit-log rows are listed in the Apply Log.

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
