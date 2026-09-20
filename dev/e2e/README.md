# JAOM end-to-end suite

Playwright suite that drives the real Odoo 19 web client and asserts behaviour
through JSON-RPC. It lives under `dev/` (lint-excluded dev tooling) and depends
only on Node + Playwright — nothing it does leaks into the add-on modules.

## What it exercises

- Manager login and navigation.
- Connection management: create a per-company JAOT connection (API key stored
  through `ir.config_parameter`), the success path of *Test connection*, and
  the failure path with an unreachable endpoint.
- Recipe *Validate* (manager-gated).
- Full MRP scenario lifecycle: Solve → solved (4 lines, optimal, objective
  value) → Compare with baseline (pinned baseline scenario + delta on the
  lines) → What-if analysis (rows stored) → **Apply (confirmation-gated)** →
  MO start dates written + audit log → **Revert (confirmation-gated)** → MO
  start dates restored.
- Infeasible solve: the capacity binding is dropped to 80, the scenario must
  end `failed` with an infeasibility record, and the binding is restored.
- Cancel: a queued/solving scenario is cancelled from the UI.
- VRP scenario lifecycle: Solve → solved (4 pickings) → Apply (confirmation-
  gated, vehicle + route sequence written) → Revert (restored).
- Staleness: a source MO is mutated after extraction, *Check staleness* flags
  `data_stale` and renders the warning banner.
- Security: the viewer role can read a scenario but sees none of the manager
  action buttons, and the `group_system`-only `expression` column is hidden.
- Apply log: reverted audit rows are listed.

## Prerequisites

1. The dev stack is up: `docker compose -f dev/docker-compose.yml up -d`.
2. The `e2e` database is seeded (users `jaotmgr`/`jaotview`, company `E2E B`,
   the widget product, four confirmed MOs, two active fleet vehicles, four
   outgoing pickings):

   ```
   docker compose -f dev/docker-compose.yml run --rm odoo \
     odoo shell -d e2e --no-http < dev/e2e/seed_e2e.py
   ```

3. A self-hosted JAOT instance reachable from the Odoo container. The default
   endpoint baked into the suite is `http://host.docker.internal:8001`.
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

The suite exits `0` when every case passes and `1` when any case fails.
Per-case results (and a screenshot for each failure) are written to
`dev/e2e/results/e2e_results.json` (git-ignored).

## Notes

- Solves are driven by calling `jaot.scenario.reconcile_jaot_scenarios` in a
  poll loop rather than waiting the one-minute `ir.cron`; the reconcile logic
  is the same code the cron invokes, so it exercises the real production path
  without the wait.
- Scenarios are created with timestamped names and are not deleted, so re-
  runs do not collide; the seed and the suite are both idempotent.
