# JAOM — Development Plan (Phases & Tasks)

**Status:** v0.4 — 2026-09-19 (Phase 1 complete: P1.1–P1.5 done)
**Companion:** `SPECS.md` (the what); this file (the how, in what order, and
who verifies).

---

## 0. Execution protocol (for the implementing session)

1. **Session start:** read `AGENTS.md`, `SPECS.md`, `jaot-odoo-brief.md`
   (the kickoff brief, same directory), this plan, and the progress table
   below. Verify the inherited state by actually running what the last
   session claims (repo rule: a green signal you did not check yourself is
   not evidence).
2. Work the **first phase whose prerequisites are satisfied**, tasks in order,
   one task at a time.
3. **Per task:** implement → **verify** (run and observe what you will claim)
   → **Conventional Commit** (the message explains the mechanism and the why)
   → update the progress table.
4. **OPEN questions** (SPECS §3.2): never settle by inference. Record the
   blocker in the progress table, ask the maintainer, continue on
   non-blocking tasks.
5. **Gates** (marked ⛔) stop the plan: if a gate fails, write a short note in
   `docs/research/`, report to the maintainer, and wait. Do not redesign D3,
   the license, or the MVP on your own initiative.
6. **Session end:** update the progress table and commit, so the next session
   resumes cold.

### Progress table

| Phase | Task | Status | Updated | Commit |
|---|---|---|---|---|
| P1.1 | A-odoo-terrain: Odoo 19 verification at doc/source level + live stand-up (dev compose `odoo:19.0` + `postgres:16`; metamodel smoke ALL PASS; auto_install verified live with a probe, then removed) — full 19.0 docs link index in `docs/rag_odoo19.md`; live evidence in the note §9 | done | 2026-09-11 | fdf3ada |
| P1.2 | B-roles gate: hand-mapped the VRP recipe's nine roles vs standard Odoo 19 Community (live metamodel) and one OCA module in the same domain (`partner_delivery_schedule`, OCA/delivery-carrier 19.0 @ `543a240`, installed → binding simulated → uninstalled/removed). **Gate passed: D3 holds** — every required role binds to a standard source; vehicle capacity + distance matrix are parameter/config bindings; the OCA case moves exactly one binding with zero code change. Findings F1–F3 feed P2.3/P3.2. Live evidence + evidence log in the note §2–§6 | done | 2026-09-11 | ecd014a |
| P1.3 | C-jaot-contract: SPECS §6 verified **live end-to-end** on JAOT v3.9.0 (`c5a07e2`) with real calls — all 10 steps pass (`dev/jaot_contract_probe.py`, key via env); live OpenAPI spec (3.9.0) fetched from `GET /openapi.json` (committed file is a stale 3.8.0); exact response field names frozen in note §4 (feeds P2.2 + the §6.4 CI smoke test); three deltas corrected in SPECS §6.2 (D1 preview is POST, D2 scenario-analysis bodyless, D3 infeasibility via execution `solver_status`); SPECS §4.7 answered: the formulation assistant takes external context via its per-conversation attachment channel (verified live to the LLM call; final mile blocked by platform billing) | done | 2026-09-11 | 37a942b |
| P1.4 | D-spike: standalone script (`scripts/spike/`, stdlib only) runs the full flow live — seed the P2.6 generator dataset into the dev Odoo DB over XML-RPC, extract it through the P1.2 binding set (incl. the F2 path resolver), build the arc-flow + MTZ `OptimizationProblem`, submit to JAOT async, poll, print the solution, and compare against the SPECS 4.6 fix-all baseline (delta 0.000000, exit 0). Live run: 10 400 vars / 10 062 cons, SCIP 600 s at gap 0.60 %, 4 tours within capacity. Findings F4–F9 (computed move weight, computed vehicle name, fleet brand model, weight-digit drift, IIS-caught sign bug, scale numbers) | done | 2026-09-19 | 1477685 |
| P1.5 | GATE ⛔: the spike works end-to-end with real data and real JAOT — **PASSED** on the P1.4 live run; the only infeasibility seen was the spike's own formulation bug, surfaced correctly by JAOT's IIS endpoint (D-spike §6). No API or role-mapping failure; P2 may proceed | done | 2026-09-19 | 1477685 |
| P2.1 | Module skeleton `jaot_base`: manifest (LGPL-3, depends `base`+`mail`, application), security groups (`jaot_base.group_user` read-only / `group_manager` full), ACL CSV, company rule, root + Configuration menus (Odoo 19: `ir.ui.menu.group_ids`, no `res.groups.category_id`). Installed + verified live | done | 2026-09-19 | 42a4a5f |
| P2.2 | `jaot.config` (per-company: endpoint, masked key in `ir.config_parameter`, poll interval, time limit, gap tolerance) + framework-free `jaot_client.py` against the C-jaot-contract §4 frozen names, with a `transport` seam for tests. Verified live: config + key saved via form fields, `action_test_connection` hit real JAOT 3.9.0 and returned health + solvers notification. Odoo 19: `tree` view type renamed `list` | doing→done | 2026-09-19 | pending commit |

Statuses: `todo` / `doing` / `done` / `blocked(question)` / `gate-failed`.

### Definition of Done — the whole project (P8)

A free Odoo 19 addon set, installable from public docs, that takes a real
delivery-routing decision from a real Odoo installation to an auditable,
revertible, applied optimized plan — with baseline comparison and guided
what-if — plus one more domain (MRP or HR) at the same quality bar; CI green
including the JAOT contract smoke test; README + changelog complete; first
external user live.

---

## Phase 0 — Decisions (human: the maintainer)

**Prerequisites:** none. **Blocks:** nothing — Phase 0 complete; every
question answered 2026-09-11 (SPECS §3.3).

| Task | Action |
|---|---|
| P0.1 | ~~Answer Q1~~ — **answered 2026-09-11: LGPL-3, zero OCA dependencies (DECIDED, SPECS §3.3)** |
| P0.2 | ~~Answer Q2~~ — **answered 2026-09-11: customer-self-hosted (DECIDED, SPECS §3.3)** |
| P0.3 | Answer **Q3** (privacy: `jaot_local_solver` required?) |
| P0.4 | ~~Answer Q4~~ — **answered 2026-09-11: partners/integrators (DECIDED, SPECS §3.3)** |
| P0.5 | ~~Answer Q5~~ — **answered 2026-09-11: Odoo 19 (DECIDED)** |
| P0.6 | ~~Answer Q6~~ — **answered 2026-09-11: delivery routing (DECIDED, SPECS §3.3)** |
| P0.7 | ~~Answer Q7~~ — **answered 2026-09-11: no LLM in v1 (DECIDED, SPECS §3.3)** |

**Exit:** SPECS §3.2 updated — every answered row flips to DECIDED; remaining
rows keep their documented defaults.

## Phase 1 — Research (brief §8)

**Prerequisites:** P0.6 (default may stand — mark it; P0.5 is already
DECIDED: Odoo 19). Produces
notes in `docs/research/` — notes, not code (the spike excepted).

- **P1.1** (brief A, ~½ day) Stand up Odoo 19 Community + Postgres locally
  (docker). Verify: `auto_install` semantics in the target version (boolean vs
  dependency list — grep `odoo/modules/`); Community/Enterprise classification
  of `mrp`, `stock`, `delivery`, `hr_holidays`, `purchase`, `account`,
  `base_geolocalize`; Python and PG versions.
  → `docs/research/A-odoo-terrain.md`
- **P1.2** ⛔ **GATE.** (brief B, ~1 day) Take the routing recipe (VRP) and
  hand-map its roles against (1) standard Odoo Community and (2) **one OCA
  module in the same domain** (find a candidate in github.com/OCA first).
  Question to answer: do the roles survive both cases with bindings only, or
  are there structural differences that break the abstraction?
  → `docs/research/B-roles.md`.
  **If the abstraction breaks: stop. Report. No P2 code until D3 is
  re-decided.** This is the cheapest failure point of the whole plan, placed
  first on purpose.
- **P1.3** (brief C, ~½ day) Stand up JAOT from the local repo (docker
  compose). Verify the SPECS §6 contract end-to-end with real calls: key
  creation, health, `solvers/available`, async solve → poll → execution,
  exact-analysis, scenario-analysis, infeasibility-analysis, templates list +
  routing template preview. **Freeze the exact response field names.** Also
  answer the SPECS §4.7 question: can the existing formulation assistant take
  external context (the Odoo schema) instead of a new pipeline?
  → `docs/research/C-jaot-contract.md` (supersedes the 2026-09-11
  source-level verification; both are kept on record).
- **P1.4** (brief D, 1–2 days) **Spike** (code lives in `scripts/spike/`): a
  standalone Python script — no Odoo addon yet — that connects to the local
  Odoo via XML-RPC, extracts the routing dataset (the synthetic generator from
  P2.6, run early), builds the `OptimizationProblem` payload, submits it to
  JAOT async, polls, and prints the solution **and** the baseline
  (fix-all-variables re-solve) comparison.
  → `docs/research/D-spike.md` + the script.
- **P1.5** ⛔ **GATE.** The spike works end-to-end with real data and real
  JAOT. If it fails for reasons of the JAOT API or the role mapping → stop,
  report, fix the plan before any addon code exists.

**Exit:** four research notes + a working spike.

## Phase 2 — `jaot_base` (the foundation)

**Prerequisites:** P1.1–P1.5 passed, P0.1 answered (license in the manifest).

- **P2.1** Module skeleton: manifest (license per P0.1, `odoo` version 19),
  security groups (`group_user`, `group_manager`), basic views,
  `ir.config_parameter` wiring.
- **P2.2** `jaot.config` + the HTTP client: `http.request` with timeouts,
  Bearer auth, error mapping that carries JAOT error codes, latency logging,
  payload capture on the scenario, `test_action` connectivity check.
- **P2.3** `jaot.recipe` + `jaot.recipe.role` + `jaot.binding`: models, views,
  per-bridge defaults; the expression field gated to `base.group_system`,
  restricted `safe_eval`, every evaluation logged.
- **P2.4** `jaot.scenario` + `jaot.scenario.line` + the lifecycle (SPECS §4.4)
  + `ir.cron` polling/reconciliation (idempotent, worker-restart safe) +
  cancel + timeout handling.
- **P2.5** The apply engine: diff computation, batched writes in savepoints,
  `jaot.apply.log`, revert through the same machinery.
- **P2.6** **Synthetic data generator** (shared, versioned, seeded): the
  routing dataset (depots, vehicles with capacities, ~50 pickings / ~200 order
  lines, partner geo) and a toy knapsack dataset for fast tests. (The spike
  already uses it — keep the generator identical in both places.)
- **P2.7** Tests: `TransactionCase` per model + lifecycle with a **fake JAOT
  client** (no network); integration tests marker-gated against a real JAOT
  docker instance.
- **P2.8** ⛔ **GATE.** End-to-end with the toy recipe (knapsack on synthetic
  data) through base alone: draft → queued → solving → solved → applied →
  reverted, all covered by tests and run by hand.

**Exit:** a complete, tested base module with zero domain logic.

## Phase 3 — MVP domain: routing (end-to-end)

**Prerequisites:** P2.8 gate, P0.6 (default: routing).

- **P3.1** `jaot_stock` bridge: manifest with `auto_install` (per the P1.1
  semantics), views inside the existing Delivery menu.
- **P3.2** The VRP recipe + default bindings for `stock.picking` / `delivery`
  / `res.partner` (geo). **Distance matrix decision:** OSRM self-hosted
  (docker) vs paid API vs simplified (haversine) for v1 — record the choice
  and its rationale; it affects P5 and the README.
- **P3.3** Compact extraction: stored fields only, paginated, company-filtered,
  snapshot hash for staleness (SPECS §4.6).
- **P3.4** Solution mapping: the JAOT variable naming convention →
  `jaot.scenario.line` (the convention is fixed in P1.3/P1.4 and documented in
  the README — it is the contract that makes "apply" safe).
- **P3.5** Scenario UI: scenario list with states; detail view with the KPI
  summary + line diff; the Apply button (`group_manager`, with confirmation);
  the baseline badge.
- **P3.6** Map view: check the P1.1 notes for a Community-friendly option
  (OCA `web_map` or a small Leaflet widget). **If nothing is cleanly
  available, v1 ships the table view — the diff view is the product, the map
  is garnish.** (Watch AGPL contagion — SPECS §8.)
- **P3.7** E2E test on the synthetic routing dataset: solve → baseline → diff
  → apply → records changed → revert → records restored.
- **P3.8** ⛔ **GATE (MVP).** The SPECS §11.1 acceptance flow, run **by a
  human** (the maintainer) on a fresh Odoo + JAOT, documented with
  screenshots in `docs/mvp.md`.

**Exit:** the MVP is complete and demonstrated.

## Phase 4 — Scenario comparison (D6-bis, the killer feature)

**Prerequisites:** P3.8 gate.

- **P4.1** Baseline capture wired into every routing solve (SPECS §4.6
  fix-all mechanism; an infeasible current plan is reported as a finding).
- **P4.2** KPI delta view: baseline vs optimized summary + per-line deltas;
  the "how much you improve" number front and center.
- **P4.3** Guided what-if: expose JAOT `scenario-analysis` on a solved
  scenario ("+1 vehicle", "+10% capacity on the bottleneck"); time-limited
  rows displayed as bounds.
- **P4.4** Staleness: snapshot-hash check on display + warning banner.
- **P4.5** Upstream: file the JAOT issue for a native evaluate-only /
  fix-solution endpoint (non-blocking; the workaround stands).
- **P4.6** ⛔ **GATE.** The comparison flow tested end-to-end, including the
  stale-data warning path.

**Exit:** the killer feature works.

## Phase 5 — Hardening and quality

**Prerequisites:** P3.8 gate (P4 may overlap).

- **P5.1** Realistic synthetic datasets per domain: tight capacities,
  multi-warehouse, multi-company, 50 k records.
- **P5.2** Security pass (SPECS §7): record rules, **negative** company
  isolation tests (cross-company extraction refused), `safe_eval` negative
  tests, key masking, webhook signature verification (if in use).
- **P5.3** Performance measurements: extraction at 50 k, apply of 1,000
  lines, cron poll load — documented in `docs/PERF.md`; fix whatever misses
  the SPECS §10 targets.
- **P5.4** Error paths: JAOT down (503/timeout), quota exceeded, solver
  error, infeasible (the IIS view wired), worker restart mid-solve, cancel
  race.
- **P5.5** i18n: complete `.pot` for en + es, checked in CI.
- **P5.6** CI: GitHub Actions — Odoo in docker, unit tests (fake client),
  linters, the **JAOT contract smoke test** against the pinned image
  (SPECS §6.4), i18n check.
- **P5.7** ⛔ **GATE.** CI green from a clean checkout; SPECS §10 targets met
  and documented.

**Exit:** production quality.

## Phase 6 — v2: more domains + LLM (after the MVP is stable)

**Prerequisites:** P4.6 gate. Order set by customer demand (maintainer).

- **P6.1** `jaot_mrp` — production scheduling. (Brief §7 warns: real data
  quality is poor — validate with a real installation's dataset first, and
  make the recipe tolerate missing capacities with explicit UI warnings.)
- **P6.2** `jaot_hr` — coverage vs `hr_holidays` (Community-only data per
  brief §1.3).
- **P6.3** `jaot_purchase` / `jaot_account` — purchasing, cashflow.
- **P6.4** Opportunity scan + LLM-assisted binding (D4) — **only if P0.7 =
  yes**; the SPECS §4.7 contract applies (nothing applied without human
  confirmation).
- Every bridge: recipe + default bindings + in-module views + synthetic
  dataset + tests — the same bar as P3.

## Phase 7 — Packaging and distribution

**Prerequisites:** P5.7 gate, P0.1/P0.2 answered.

- **P7.1** README (target: Odoo 19; install; endpoint + key configuration;
  first solve) + per-bridge docs.
- **P7.2** The channel per decision: App Store free listing / OCA / GitHub —
  prepare artifacts (screenshots, license files, manifest metadata).
- **P7.3** Versioning + changelog discipline (Odoo version + module version;
  1–3 user-facing lines per release, repo rule).
- **P7.4** Fresh-install smoke: clean machine, Odoo 19 + pinned JAOT, follow
  public docs only, first applied solve — timed and documented (target < 30
  minutes, SPECS §10.6).

**Exit:** third-party installable.

## Phase 8 — Release and maintenance

- **P8.1** First public version: tag, changelog, announcement (repo + the
  P7.2 channel).
- **P8.2** Feedback loop: triage cadence (best-effort model, cf. JAOT:
  monthly), first external installation supported.
- **P8.3** Post-release roadmap (maintainer-owned): `jaot_local_solver` (if
  P0.3), an Enterprise bridge (separate repo, never a hard dependency),
  multi-version Odoo (only on explicit demand), JAOS adoption — which
  happens inside JAOT's adapter layer and requires **no** JAOM work.

---

## Risks (top, with mitigations)

1. **The role abstraction breaks** (P1.2) → plan stops, D3 redesigned.
   Cheapest failure point, placed first on purpose.
2. **JAOT API drift** (no external stability guarantee) → pinned version +
   contract smoke test in CI + drift is a release blocker.
3. **Dirty real-world data** (especially MRP) → MVP on routing;
   realistic-but-synthetic datasets; explicit data-quality warnings in the UI.
4. **License contagion** (any OCA dependency, e.g. a map widget) → option-A
   default; every new dependency reviewed against SPECS §8 before merge.
5. **Odoo worker timeouts / RAM** → nothing long in a request; compact
   extraction; measured at P5.3.
6. **Scope creep** (LLM, extra domains, enterprise) → the non-goals (SPECS
   §2.3), P0.7, and the gates.

## Effort (order of magnitude — recalibrate after P1.4)

| Phase | Estimate |
|---|---|
| P0 | minutes (human) |
| P1 | 3–5 working days |
| P2 | 1.5–2 weeks |
| P3 | 1–1.5 weeks |
| P4 | ~1 week |
| P5 | ~1 week |
| P6 | ~1 week per bridge |
| P7 | 3–4 days |
| P8 | ongoing |
