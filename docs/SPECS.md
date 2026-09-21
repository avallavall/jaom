# JAOM — Specification

**Project:** JAOM — Just Another Optimization Module (Odoo)
**Status:** Draft v0.7 — 2026-09-20 (v1.1 scope added — §13, Phase 9:
explanation, named scenarios, es translation, intraday re-optimization,
forecast + safety stock. Phase 0 fully answered by the maintainer — §3.3,
including Q1: LGPL-3; kickoff brief imported into the repo; Odoo 19 terrain
verified at doc/source level and live — `docs/research/A-odoo-terrain.md`)
**Supersedes:** nothing (first spec). Operationalizes the kickoff brief
`jaot-odoo-brief.md` (2026-07-29, kept in this directory).
**Companion document:** `PLAN.md` (phases, tasks, execution protocol).

---

## 0. How to read this document

Decision-status legend:

- **DECIDED** — closed; treat as fact.
- **PROPOSED** — comes from the kickoff brief; adopted as the working default by
  this spec; the maintainer may veto (see §3).
- **OPEN** — unresolved question; the phases it blocks are listed; a documented
  default is used in the meantime.
- **VERIFIED** — checked against a local checkout of JAOT (v3.9.0, commit
  `c5a07e2`, 2026-09-01) or against Odoo sources, on the date stated.

Rule inherited from the repo `AGENTS.md`: OPEN items are **not** settled by
inference. If an OPEN item is hit during execution, the affected task stops, the
blocker is recorded, the maintainer is asked, and work continues on non-blocking
tasks.

## 1. Product definition

JAOM is a free, open-source Odoo addon set that brings real mathematical
optimization into Odoo workflows. It is a **thin client** of a JAOT
optimization-platform instance (self-hosted by default):

1. **Extract** — pull a compact problem instance out of the Odoo modules the
   customer has installed (production, inventory, purchasing, HR, accounting).
2. **Formulate** — build the optimization problem from *recipes* (stable problem
   structures mapped to JAOT templates) with **role-based bindings** (the
   volatile mapping of "which field holds the data in *this* installation").
3. **Solve** — hand the problem to JAOT asynchronously. Never inside an Odoo
   request.
4. **Present** — materialize the answer as a first-class Odoo object — a
   *scenario* — with an exact diff against the current state.
5. **Apply** — write the solution to Odoo records only on explicit human
   action, batched, audited, and revertible.

The killer feature is **scenario comparison**: capture the current manual plan
as a *baseline scenario*, compare it side by side with the optimized scenario
(KPI delta, line-by-line diff), and run guided what-ifs ("what if one more
truck?", "+10% capacity on the bottleneck you flagged?"). The improvement
number is the product.

What JAOM is **not**:

- Not a solver. No SCIP/HiGHS/CBC/GLPK code or native Python extensions run
  inside Odoo. (D1.)
- Not a JAOT portal. JAOT keeps its own web UI, MCP server, and API. JAOM is
  one integration channel, next to MCP.
- Not an autopilot. Nothing writes production records without explicit human
  confirmation; nothing an LLM proposes is applied without human confirmation.

### 1.1 Users and target installation (DECIDED — Q4)

Primary audience (DECIDED, Q4): Odoo partners/integrators installing for
their customers; the UI must still be usable by end customers who are not
optimization experts. Target installation: Odoo Community with an arbitrary
subset of modules, including OCA and custom development.

## 2. Scope

### 2.1 v1 (MVP)

- `jaot_base`: configuration, HTTP client, recipes, role-based bindings,
  scenario lifecycle, apply engine, `ir.cron`-based async polling, security,
  tests with synthetic data.
- **One domain end-to-end: delivery routing** (DECIDED — Q6): `jaot_stock`
  bridge (`stock` + `delivery` + partner geo), VRP recipe, scenario views
  inside the Delivery menu, apply + revert. (Odoo 19 partner geo fields are
  `partner_latitude` / `partner_longitude`; the historical `x` / `y` fields no
  longer exist — docs/research/A-odoo-terrain.md §7.)
- **Scenario comparison** (D6-bis): baseline capture, KPI delta, guided
  what-if, staleness warning.
- i18n: en + es.
- CI: Odoo unit tests + JAOT contract smoke test against a pinned JAOT version.

### 2.2 v2 (after MVP is stable)

- Further bridges: `jaot_mrp` (production scheduling), `jaot_hr` (coverage vs
  `hr_holidays`), `jaot_purchase`, `jaot_account` — ordered by customer demand.
- Opportunity scan + LLM-assisted binding (D4) — v2 (Q7 DECIDED: not in v1;
  the §4.7 contract applies when it lands).
- `jaot_local_solver` (optional, not auto-installable, degraded mode with
  embedded HiGHS for on-premise without connectivity) — only if Q3 = yes.

### 2.3 Explicit non-goals (v1) — carried over from the brief, unchanged

- ❌ Enterprise module support.
- ❌ Auto-generated optimization formulations without a human in the loop.
- ❌ Solver embedded in the Odoo process.
- ❌ Multi-version Odoo support.
- ❌ Automatic writes to production records without explicit confirmation.
- ❌ More than one optimization domain in v1.

## 3. Decisions and open questions

### 3.1 Architectural decisions (brief §3; adopted as working defaults)

| ID | Decision | Status |
|---|---|---|
| D1 | Thin client; the addon contains no solver | PROPOSED (adopted) |
| D2 | Bridge modules with `auto_install`, one per Odoo domain | PROPOSED (adopted) |
| D3 | Role-based bindings, remappable in the UI | PROPOSED (adopted; gated at PLAN P1.2) |
| D4 | LLM = discovery and drafting, never autopilot | PROPOSED (v2) |
| D5 | Async via native `ir.cron`, no OCA `queue_job` | PROPOSED (adopted) |
| D6 | Solutions land in own models; explicit Apply with diff/audit/revert | PROPOSED (adopted) |
| D6-bis | Scenario comparison as its own feature line | PROPOSED (adopted; PLAN P4) |

### 3.2 Open questions (maintainer only)

| # | Question | Blocks | Working default meanwhile |
|---|---|---|---|
| Q3 | Privacy: customers that refuse data leaving Odoo? | `jaot_local_solver` priority (v2) | Not a v1 requirement |

### 3.3 Phase 0 decisions — answered by the maintainer

| # | Question | Decision | Date |
|---|---|---|---|
| Q1 | License: commercial intent? (LGPL-3 / AGPL-3 / OPL-1 dual) | **DECIDED: LGPL-3**, zero OCA dependencies in v1 (brief §6 option A); per-bridge AGPL-3 stays available if a bridge needs an OCA module (§8) | 2026-09-11 |
| Q2 | Deployment: customer-self-hosted JAOT vs jaot.io SaaS | **DECIDED: customer-self-hosted** (one JAOT instance per company, §6.1) | 2026-09-11 |
| Q4 | Audience: partners vs end users | **DECIDED: partners/integrators** — partner-grade configuration, simple happy path | 2026-09-11 |
| Q5 | Target Odoo version | **DECIDED: Odoo 19 Community** — single target version in v1 | 2026-09-11 |
| Q6 | MVP domain: routing vs production scheduling | **DECIDED: delivery routing** (`jaot_stock`, VRP recipe) | 2026-09-11 |
| Q7 | LLM-assisted binding in v1? | **DECIDED: no — v2** (brief recommendation; the §4.7 contract applies when it lands) | 2026-09-11 |

## 4. Architecture

### 4.1 Responsibilities (D1)

The addon does exactly five things: extract → formulate → enqueue → present →
apply. Everything else (modeling, solving, analysis, LLM, marketplace) lives in
JAOT.

### 4.2 Module topology (D2)

```
jaom/
├── jaot_base/       depends: ['base']                          config, client, recipes, bindings, scenarios, cron, apply engine
├── jaot_stock/      depends: ['jaot_base','stock','delivery']  auto_install   # routing (v1)
├── jaot_mrp/        depends: ['jaot_base','mrp']               auto_install   # v2
├── jaot_hr/         depends: ['jaot_base','hr_holidays']       auto_install   # v2
├── jaot_purchase/   depends: ['jaot_base','purchase']          auto_install   # v2
└── jaot_account/    depends: ['jaot_base','account']           auto_install   # v2
```

- `auto_install` semantics — **VERIFIED 2026-09-11 against the 19.0 source**:
  both a boolean and a dependency list are accepted; the list restricts which
  dependencies trigger the auto-install (docs/research/A-odoo-terrain.md §1).
- Each bridge contributes: recipes + default bindings for its domain +
  extraction and apply logic + views inside that module's **existing menus**
  (no standalone "JAOT" menu — integration into the existing workflow is part
  of the value).
- No OCA dependency in v1 (license, §8). If a bridge later truly needs an OCA
  module (e.g. a map widget), that bridge is AGPL-3 and the choice is
  documented in its manifest.
- Optional (v2): `jaot_local_solver`, not auto-installable.

### 4.3 Recipes and role-based bindings (D3)

- A **recipe** (`jaot.recipe`) declares a problem structure mapped to a JAOT
  template: required and optional **roles** (`jaot.recipe.role`), each with a
  kind (`variable` / `constraint` / `parameter`), semantics, and data type.
- A **binding** (`jaot.binding`) maps a role, for a specific installation and
  company, to a source: Odoo model + field path, optional domain, optional
  restricted expression.
- Every supported module ships **default bindings**; a customer with OCA or
  custom models remaps roles in the UI. Remapping is configuration, not code —
  that is the answer to ecosystem fragmentation.
- Expression bindings use Odoo `safe_eval` with a closed namespace and are
  editable **only** by `base.group_system` (§7).
- **Gate:** the role abstraction must survive PLAN P1.2 (standard Community +
  one OCA module in the same domain). If it breaks, D3 is redesigned before
  any P2 code lands.

### 4.4 Solve lifecycle (D5)

States on `jaot.scenario`:

```
draft → queued → solving → solved → applied
                ↘ failed
                ↘ cancelled
```

- **draft** — data snapshot taken, problem payload built, dry-run validation
  (role coverage, payload size) before anything leaves the box.
- **queued / solving** — JAOT async solve submitted; an `ir.cron` (default
  every 10 s, configurable) polls the `poll_url` and updates the scenario.
  No request ever waits on a solve.
- **solved** — solution materialized as `jaot.scenario.line` rows;
  exact-analysis fetched; baseline computed when requested.
- **applied** — explicit Apply executed (§4.5); the scenario is immutable from
  then on (a new solve = a new scenario).
- **failed** — JAOT error surfaced with its code; IIS view when infeasible;
  retry creates a new scenario.
- **cancelled** — `POST …/cancel` on the JAOT task.
- **Idempotency / worker-restart safety:** one scenario = one JAOT task, keyed
  by `jaot_task_id`; the cron reconciles by task id — an orphaned `queued`
  scenario with a known task id is re-polled, never re-submitted.

### 4.5 Scenarios and apply (D6)

- The solution lands in `jaot.scenario` + `jaot.scenario.line` (own models,
  zero side effects). Each line references an Odoo record
  (`res_model` / `res_id`), the decided values (JSON), its KPI contribution,
  and its delta vs baseline.
- **Apply** is an explicit button action: writes in batches inside savepoints,
  logs every before/after to `jaot.apply.log`, and is **revertible** (the
  logged before-state is re-applied through the same machinery).
- The full request and response payloads are stored on the scenario:
  auditable, reproducible, debuggable without production access.
- Payload retention: keep everything in v1 (instances are compact by design);
  archival policy is a v2 note.

### 4.6 Scenario comparison (D6-bis)

- **Baseline mechanism (VERIFIED against JAOT v3.9.0, 2026-09-11):** JAOT has
  **no evaluate-only mode** — warm start seeds a solve from a previous
  incumbent, it does not fix a solution. The baseline is therefore a *second
  scenario of the same recipe in which every decision variable is fixed to the
  value of the current plan* and re-solved. If the current plan is infeasible
  against the model, that is reported as a finding, not a failure. Baseline
  KPIs are computed by JAOT with the **same objective**.
- **KPI delta view** — baseline vs optimized: summary numbers on top,
  line-by-line diff below (what moves, by how much, KPI impact).
- **Guided what-if** — exposes JAOT's `scenario-analysis` batch (RHS
  perturbations, real re-solves) as an action on a solved scenario. Rows that
  hit a time limit are shown as **bounds**, never as exact values.
- **Staleness** — the scenario stores a hash of the extracted data snapshot;
  if the underlying Odoo records changed after extraction, the UI warns
  ("solved against stale data").
- **Upstream, non-blocking:** a native evaluate-only / fix-solution endpoint
  is a candidate JAOT feature; file the issue when P4 lands (PLAN P4.5).

### 4.7 LLM (D4) — contract only (v2)

When it arrives: (a) **opportunity scan** over `ir.module.module` +
`ir.model.fields` producing `jaot.opportunity` records ("you have mrp, stock,
hr_holidays → these 6 recipes apply; these 3 would with 2 remapped fields");
(b) **assisted binding** — on recipe selection the LLM proposes a binding
draft for human review and versioned save.

Hard rule: **nothing the LLM proposes is applied without explicit human
confirmation** — no bindings, no writes. Reuse JAOT's existing formulation
assistant with the Odoo schema as extra context before building any new
pipeline (researched at PLAN P1.3).

## 5. Data model (Odoo models)

All models: `company_id` + company record rule, `_rec_name` set.

### 5.1 `jaot.config` (one per company)

| Field | Type | Notes |
|---|---|---|
| `endpoint_url` | Char | JAOT base URL |
| `api_key` | Char (stored elsewhere) | Kept in `ir.config_parameter` (`jaot.api_key.<company_id>`); masked in UI, never returned in full |
| `poll_interval` | Selection | 5 / 10 / 30 s (default 10) |
| `solve_time_limit` | Integer | Seconds forwarded to JAOT `options.time_limit_seconds` (default 300) |
| `gap_tolerance` | Float | Forwarded to JAOT (default 0.05) |
| `default_solver` | Selection | From JAOT `GET /api/v2/solvers/available` (default: server choice) |
| `test_action` | Button | Connectivity check (§6.1) |

### 5.2 `jaot.recipe`

`name`, `code`, `domain` (stock/mrp/hr/purchase/account),
`jaot_template_id` (JAOT template slug/id), `description`, `active`,
`company_id`, `recipe_role_ids` (One2many).

### 5.3 `jaot.recipe.role`

`recipe_id`, `name`, `kind` (variable/constraint/parameter), `required` (bool),
`semantics` (Text, human-readable), `data_type` (number/quantity/date/
boolean/reference).

### 5.4 `jaot.binding`

`recipe_id`, `role_id`, `res_model`, `field_path` (e.g.
`production_id.date_deadline`), `domain` (Char, evaluable), `expression`
(Char, restricted `safe_eval`, group_system only), `company_id`. One binding
per role per company; defaults shipped by the bridge.

### 5.5 `jaot.scenario`

`name`, `recipe_id`, `binding_snapshot` (Json — the bindings used, for
reproducibility), `state`, `jaot_task_id` (Char, unique when set),
`jaot_execution_id`, `solver_name`, `objective_value`, `objective_sense`,
`gap`, `solve_time_seconds`, `data_snapshot_hash`, `baseline_scenario_id`
(M2o, same recipe), `kpi_summary` (Json), `applied` (bool), `applied_at`,
`applied_by`, `line_count`.

### 5.6 `jaot.scenario.line`

`scenario_id`, `sequence`, `res_model`, `res_id`, `decision` (Json),
`kpi_contribution` (Float), `delta_vs_baseline` (Json), `note` (Char).

### 5.7 `jaot.apply.log`

`scenario_id`, `sequence`, `res_model`, `res_id`, `field_path`,
`before_value` (Json), `after_value` (Json), `state` (applied/reverted),
`applied_at`, `reverted_at`.

### 5.8 `jaot.opportunity` (v2)

`name`, `domain`, `detected_module_ids` (Many2many `ir.module.module`),
`matched_recipe_ids`, `missing_roles` (Text), `state`
(new/configured/dismissed).

### 5.9 Security

- Groups: `jaot.group_user` (view scenarios; apply if also manager),
  `jaot.group_manager` (manage recipes/bindings/config; apply).
- Expression bindings: `base.group_system` only.
- Apply button: `jaot.group_manager` only.

## 6. Integration contract with JAOT

**VERIFIED 2026-09-11 against local JAOT v3.9.0 (commit `c5a07e2`)** — first
at source level (sources under `app/` and `openapi.json`, 194 endpoints
under `/api/v2`), then **live end-to-end with real calls**
(`docs/research/C-jaot-contract.md`: frozen response field names + deltas
D1–D3; the live spec is served at `GET /openapi.json` and is the 3.9.0
document — the committed `openapi.json` is a stale 3.8.0).

### 6.1 Instance and auth

- One JAOT instance per company (DECIDED: customer-self-hosted — Q2).
- Auth: **Bearer API key** (JAOT `/api/v2/keys/`). Stored per §5.1.
- Connectivity check: `GET /api/v2/health/status` +
  `GET /api/v2/solvers/available` with the key.

### 6.2 Core solve flow

| Step | Call | Notes |
|---|---|---|
| 1 | `POST /api/v2/solve/async` | Body: `OptimizationProblem` (variables / objective / constraints with expressions — same shape as the JAOT quickstart). Response envelope: `{task_id, execution_id, status: "pending", ws_url, poll_url}` |
| 2 | `GET /api/v2/solve/async/{task_id}` | Poll until terminal (default 10 s). `POST …/cancel` to cancel |
| 3 | `GET /api/v2/models/executions/{execution_id}` | Solution: variable values, objective, gap, solver, time |
| 4 | `GET /api/v2/models/executions/{id}/exact-analysis` | Sync; binding constraints, slack/utilization — exact for the integer solution |
| 5 | `POST /api/v2/models/executions/{id}/scenario-analysis` → poll `GET` | **No request body** — the what-if batch is auto-derived from the execution (RHS relax/tighten per constraint + decision flips per variable); real re-solves under a budget; time-limited rows come back flagged (`SKIPPED_BUDGET` / `partial`), never silent |
| 6 | `POST /api/v2/solve/{execution_id}/infeasibility-analysis` | Minimal conflicting constraint set when infeasible |
| — | `GET /api/v2/solve/templates` · `POST …/templates/{id}/preview` · `POST …/templates/{id}/solve` | Template catalog (102 templates live; query `category`/`featured`/`page`/`page_size`); **four routing generators** (`vehicle_routing`, `waste_collection_routing`, `drug_distribution`, `pick_route_optimization`); `preview` is **POST** (live delta D1) and returns the grounded problem — 2 trucks / 6 sites arc-assignment for the logistics routing template |
| — | `POST /api/v2/triggers/` (+ schedule; signed webhook `X-Jaot-Signature`, HMAC-SHA256) | v2 candidate for scheduled re-solves that *push* to Odoo instead of Odoo polling |

- Live progress WebSocket (`/api/v2/ws/executions/{task_id}`) exists but is
  **not used in v1** (cron polling is sufficient; WS would need Odoo worker
  changes).
- Sync `POST /api/v2/solve` exists but is **never used** by JAOM (worker
  timeouts — D1).
- Exact response field names for steps 2–4 are frozen in the PLAN P1.3
  research note; the contract smoke test pins them.

### 6.3 Baseline

See §4.6: fix-all-variables re-solve (no native evaluate-only in v3.9.0).

### 6.4 Contract governance

- JAOM targets a **pinned JAOT minor version** (v3.x), declared in the README
  and in CI compose.
- CI runs a **contract smoke test** against the pinned JAOT image: one async
  solve → poll → execution → exact-analysis round-trip on a toy problem.
- API drift is a release-blocking event, not a silent workaround.

## 7. Security requirements

1. **API key** only in `ir.config_parameter`; masked in the UI; never in code,
   demo data, logs, or the repo.
2. **Company isolation:** every extraction respects `company_id` and record
   rules; a scenario never mixes companies; a cross-company solve is an
   explicit error, not a silent union.
3. **Data minimization:** send a compact instance (indexes + numbers), not raw
   ORM records; stored fields only, paginated (brief §5 traps 2–3).
4. **Restricted expressions** in bindings: `safe_eval` with a closed
   namespace; `base.group_system` only; every evaluation logged.
5. **Apply is explicit:** no automatic writes, ever; batched in savepoints;
   full before/after audit in `jaot.apply.log`; revert through the same
   machinery.
6. **Webhooks** (v2, if triggers are used): verify `X-Jaot-Signature` before
   trusting a payload; validate the sender.
7. **LLM** (v2): nothing applied without human confirmation; RAG lives in
   JAOT, not in the addon.

## 8. Licensing and distribution

- **DECIDED (Q1, 2026-09-11):** `jaot_base` and all v1 bridges are
  **LGPL-3** with **zero OCA dependencies** (brief §6 option A).
- A bridge that later needs an OCA module is AGPL-3 and documents it in its
  manifest.
- Channels: GitHub (always), Odoo App Store free listing (default), OCA
  (only on an explicit AGPL decision for a specific bridge).

## 9. Target platform

- Odoo **19 Community** (DECIDED by the maintainer, 2026-09-11; single target
  version in v1; exact LTS/stable status verified at PLAN P1.1).
- Python ≥ 3.10 and PostgreSQL ≥ 13 — **VERIFIED 2026-09-11** against the 19.0
  branch and the official docs; the PostgreSQL minimum was raised from 12 to 13
  in version 19 (docs/research/A-odoo-terrain.md §4).
- Development and CI: Docker (odoo + postgres + pinned jaot image).

## 10. Non-functional requirements

1. **No long work in a request:** extraction and payload build finish in the
   request; solving is async; apply is batched with progress (target: 1,000
   lines < 60 s, measured at PLAN P5.3).
2. **Extraction at scale:** 50 k records must not blow up worker RAM (stored
   fields, paginated `search_read` or `read_group`; measured at P5.3).
3. **Deterministic tests:** unit tests use a fake JAOT client (no network);
   integration tests are marker-gated against a real instance.
4. **Observability:** every JAOT HTTP call logged (endpoint, status, latency,
   error code); payloads stored on the scenario; cron reconciliation
   idempotent and logged.
5. **i18n:** en + es from day one (`.pot` checked in CI).
6. **Fresh-install experience:** from an empty Odoo 19 + running JAOT to the
   first applied solve in < 30 minutes, documented and timed at PLAN P7.4.

## 11. Acceptance criteria (project level)

1. Fresh Odoo 19 Community + pinned JAOT v3.x → configure endpoint + key → a
   routing recipe with default bindings is visible → a solve completes → the
   scenario shows the diff vs baseline → Apply updates delivery records in
   Odoo → the audit log is complete → Revert restores the before-state.
2. The same flow against an OCA/custom module remapped through role
   re-binding (no code change).
3. CI green from a clean checkout: Odoo unit tests + contract smoke test +
   linters.
4. A third party can install and reach the first solve using public docs only
   (PLAN P7.4).

## 12. References

- `jaot-odoo-brief.md` (this directory) — the kickoff brief (source of
  D1–D6-bis, the trap list, MVP candidates, and confidence levels). Written
  in Spanish; it is the historical record and is kept as-is.
- <https://github.com/avallavall/jaot> (v3.9.0) — the platform this spec
  integrates with; §6 was verified against a local checkout of its sources
  and `openapi.json`.
- <https://github.com/avallavall/jaos> — future in-house solver; when/wherever
  JAOT adopts it, JAOM is unaffected (the adapter boundary is inside JAOT).
- `jaot/docs/ROADMAP.md` — JAOM listed there as an official "Later /
  Exploring" item.

## 13. v1.1 scope — Phase 9 (added 2026-09-20)

Five features, selected 2026-09-20 from market + academic research
(`docs/research/D-v11-scope.md`) plus the v2 backlog. All build on machinery
that already exists (exact-analysis, IIS, batch re-solve, baseline fix-all,
role bindings); D1 (no solver in Odoo) holds; no new external dependencies.
The Q3 privacy question and the v2 items (§2.2) are untouched.

### 13.1 Plan explanation (P9.1)

Answer "why did the solver plan it this way?" for a non-technical user, on
every solved scenario (both bridges):

- **Objective decomposition** — the objective value split into named terms
  (MRP: setup / holding; VRP: transport, plus any penalty terms), computed as
  pure post-processing of the incumbent solution against the extracted data —
  no solver call.
- **Binding-constraint report** — from the JAOT `exact-analysis` already
  fetched (§6.2 step 4): the tight constraints, with slack and a
  plain-language name ("capacity of 2026-10-05 is fully used", "vehicle 12 is
  at capacity").
- **Infeasible cases** — the existing IIS plus a one-paragraph plain-language
  summary mapping the conflicting constraints to user-visible
  records/fields.
- **Storage/UI** — `jaot.scenario.explanation` (Json, filled at
  reconciliation) + a read-only explanation section on the scenario form.
  Manager-readable; no expressions or identifiers (§7).
- **Upstream note:** LP-relaxation shadow prices / ranging would strengthen
  this (HiGHS exposes ranging natively) but need a JAOT endpoint; it is a
  follow-up to avallavall/jaot#3, not implemented here.

### 13.2 Named scenario runner (P9.2)

Productize the what-if: user-defined named cases with parallel re-solves and
a side-by-side comparison.

- **Model** `jaot.scenario.case`: `name`, `scenario_id` (the solved parent),
  `perturbation` (Json: list of `{role_id, mode: set|scale, value}`),
  `state` (mirrors the child run), `case_run_id` (the child scenario actually
  submitted).
- **Mechanism** — a case runs as a normal child scenario: the parent's
  binding snapshot with the perturbation applied to the **parameter roles**,
  then the standard submit/reconcile path. Levers that are not parameter
  roles (e.g. fleet size) require a parameter role on the recipe — v1.1
  adds `max_vehicles` to the VRP recipe; MRP keeps its existing capacity /
  setup / holding roles.
- **Parallelism** — each case is an independent scenario/task (the cron
  already polls them independently); at most `max_parallel_cases` (default
  8) open per company, enforced at submit.
- **Comparison view** — table across cases: objective, gap, solve time, KPI
  summary, per-line delta vs the parent's baseline; time-limited rows remain
  bounds (§4.6).

### 13.3 es translation + i18n completion (P9.3)

The day-one promise (§10.5: "en + es from day one") shipped as `.pot`
templates only. v1.1 delivers `es.po` for `jaot_base`, `jaot_stock`,
`jaot_mrp` with full msgstr coverage, and the CI i18n job is extended to
check each `.po` against its `.pot` (msgid parity), so drift fails the build.

### 13.4 Intraday re-optimization (P9.4, routing)

Re-route when orders change after routes were issued, without disturbing
what is already done.

- **Trigger** — on an applied routing scenario, when the staleness check
  reports changed source pickings, a **Re-optimize** action appears.
- **Served legs are pinned** — pickings with `state = done` keep their
  vehicle + position (fixed in the formulation, same machinery as the
  baseline fix-all path, §4.6); the remaining pickings are re-optimized.
- **Delta vs the frozen plan** — the re-route scenario stores its KPI delta
  against the applied plan (reuses the baseline machinery), so the user sees
  what the changes cost or save.
- **Apply** writes only the changed pickings (existing per-line engine);
  audit + revert unchanged (§4.5). Cancellations and new pickings go through
  the same action (the extraction domain already covers confirmed/assigned
  outgoing pickings).

### 13.5 Forecast + safety stock for MRP (P9.5)

Demand-side value: per-product forecasts feeding the lot-sizing demand.

- **New bridge** `jaot_forecast` (depends: `jaot_base`, `stock`;
  auto_install).
- **Models** — `jaot.forecast` (product_id, company_id, method, adi,
  abc_class, horizon, point + quantile values, backtest accuracy, run
  timestamp) and `jaot.forecast.demand` (one row per product × period:
  quantity at the chosen quantile) — the latter is what the MRP binding
  reads, so the forecast plugs into the existing role machinery with zero
  special cases.
- **Method** — item classification by ADI (average inter-demand interval,
  default 24-month window from `stock.move`) and ABC (usage value, default
  80/15/5); ADI below the intermittent threshold (default 1.32) → ETS
  (Holt); otherwise Croston/SBA with the (1 − β/2) bias correction.
  Quantiles via normal approximation of the smoothed error; backtest
  accuracy (MAPE, bias) over a holdout tail so a planner can audit the
  numbers.
- **Safety stock** — from the chosen service level (default 95 %): the
  quantile of demand over the effective lead time; shown on the forecast and
  included in the `jaot.forecast.demand` rows. Not written onto
  `product.product` (Odoo Community has no standard field for it).
- **MRP hook** — the lot-sizing recipe gains an **optional** role
  `forecast_demand` (bound by default to `jaot.forecast.demand`); when the
  role is bound, daily demand = committed MO quantities + forecast
  quantities; unbound → exactly today's behavior. Refresh is an explicit
  action (+ optional cron); a stale forecast is flagged like a stale
  scenario (§4.6).

### 13.6 Gate (P9.6)

E2E suite extended with one case per feature (explanation rows present on a
solved scenario; two named cases run and compare; an es session renders the
translations; re-optimize pins done pickings and restores them on revert;
forecast refresh → demand rows → the lot-sizing solve uses them and revert
restores the dates); offline tests green; CI green; README + changelog
updated in the same commits.

### 13.7 Human-readable scenario presentation (P9.7)

The scenario UI showed raw decision JSON and a raw KPI Json — unreadable for
a non-expert. P9.7 presents the same data in plain language, presentation
only (no solver, no new dependency). The logic lives on the formulation
classes (framework-free), so the unit tests drive it with plain dicts; the
Odoo side only resolves units and record names and renders.

- **Plain-language lines** — each `jaot.scenario.line` gains a computed
  `record_label` (the target record's display name) and `decision_text`
  (the formulation's `render_line(decision, record_names)`): the toy
  knapsack says "Selected" / "Not selected", VRP says
  "Vehicle Van 1 · stop 3", lot sizing says "Start 2026-10-05". A line that
  references a record (a VRP vehicle) resolves its display name via the
  formulation's `referenced_records(decision)`. The raw `res_model` /
  `res_id` / `decision` columns stay available to system users. The
  referenced-record lookup is access-safe: a viewer who can read the plan
  but not the referenced record (e.g. no fleet access), or a record that has
  been deleted, gets a safe generic label and never a database id.
- **Pre-apply preview** — a computed `change_preview` renders before →
  after against the record's live value ("Not selected -> Selected",
  "Unchanged"), so a manager sees exactly what applying will do, before
  applying. It is recomputed when the scenario is applied (depends on the
  scenario state) and degrades to a "no longer exists" note when the target
  record is deleted.
- **Unit-labelled KPI headline** — `jaot.scenario` gains computed
  `objective_unit` (the formulation's `objective_unit()` resolved to
  `''` / `km` / the company currency) and `kpi_headline`. The headline
  states the result in words: "Saves 120.50 (8.2%) versus your current plan
  (1460.60 -> 1340.10)" for a minimise gain, "Gains …" for a maximise gain,
  "Worse by …" for a loss, or the objective-only line ("Objective 60.00
  (maximized)") when there is no baseline. Shown as a banner on the form
  and as a column in the list.
