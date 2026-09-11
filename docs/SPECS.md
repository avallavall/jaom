# JAOM — Specification

**Project:** JAOM — Just Another Optimization Module (Odoo)
**Status:** Draft v0.2 — 2026-09-11 (Q5 decided: Odoo 19)
**Supersedes:** nothing (first spec). Operationalizes `jaot-odoo-brief.md` (2026-07-29).
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

Rule inherited from the repo `CLAUDE.md`: OPEN items are **not** settled by
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

### 1.1 Users and target installation (OPEN — Q4)

Default assumption: primary audience is Odoo partners/integrators installing
for their customers; the UI must still be usable by end customers who are not
optimization experts. Target installation: Odoo Community with an arbitrary
subset of modules, including OCA and custom development.

## 2. Scope

### 2.1 v1 (MVP)

- `jaot_base`: configuration, HTTP client, recipes, role-based bindings,
  scenario lifecycle, apply engine, `ir.cron`-based async polling, security,
  tests with synthetic data.
- **One domain end-to-end: delivery routing** (PROPOSED — Q6): `jaot_stock`
  bridge (`stock` + `delivery` + partner geo), VRP recipe, scenario views
  inside the Delivery menu, apply + revert.
- **Scenario comparison** (D6-bis): baseline capture, KPI delta, guided
  what-if, staleness warning.
- i18n: en + es.
- CI: Odoo unit tests + JAOT contract smoke test against a pinned JAOT version.

### 2.2 v2 (after MVP is stable)

- Further bridges: `jaot_mrp` (production scheduling), `jaot_hr` (coverage vs
  `hr_holidays`), `jaot_purchase`, `jaot_account` — ordered by customer demand.
- Opportunity scan + LLM-assisted binding (D4) — only if Q7 = yes.
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
| Q1 | License: commercial intent? (LGPL-3 / AGPL-3 / OPL-1 dual) | PLAN P2.1 (manifest), P7 | LGPL-3, zero OCA dependencies (brief §6 option A) |
| Q2 | Deployment: customer-self-hosted JAOT vs jaot.io SaaS | P2 (auth/URL), P7 | Customer-self-hosted |
| Q3 | Privacy: customers that refuse data leaving Odoo? | `jaot_local_solver` priority (v2) | Not a v1 requirement |
| Q4 | Audience: partners vs end users | UI depth (P3) | Partner-grade configuration, simple happy path |
| Q5 | Target Odoo version | — (answered 2026-09-11) | **DECIDED: Odoo 19 Community** — single target version in v1 |
| Q6 | MVP domain: routing vs production scheduling | P3 | Routing (brief §7) |
| Q7 | LLM-assisted binding in v1? | P6.4 | No — v2 (brief recommendation) |

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

- `auto_install` semantics (boolean vs dependency list) verified for the target
  version at PLAN P1.1.
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

**VERIFIED 2026-09-11 against local JAOT v3.9.0 (commit `c5a07e2`)** — sources
under `app/` and `openapi.json` (194 endpoints under `/api/v2`).

### 6.1 Instance and auth

- One JAOT instance per company (default: customer-self-hosted — Q2).
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
| 5 | `POST /api/v2/models/executions/{id}/scenario-analysis` → poll `GET` | What-if batch (real re-solves; time-limited rows are bounds, not values) |
| 6 | `POST /api/v2/solve/{execution_id}/infeasibility-analysis` | Minimal conflicting constraint set when infeasible |
| — | `GET /api/v2/solve/templates` · `…/templates/{id}/preview` · `…/templates/{id}/solve` | Template catalog; a VRP/routing generator exists (CVRP with nearest-neighbor warm start) |
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

- **Q1 default (working assumption):** `jaot_base` and all v1 bridges
  **LGPL-3**, **zero OCA dependencies** (brief §6 option A).
- A bridge that later needs an OCA module is AGPL-3 and documents it in its
  manifest.
- Channels (after Q1): GitHub (always), Odoo App Store free listing (default),
  OCA (only on an explicit AGPL decision).
- The license header is decided **before** PLAN P2.1 (it shapes manifests and
  CI).

## 9. Target platform

- Odoo **19 Community** (DECIDED by the maintainer, 2026-09-11; single target
  version in v1; exact LTS/stable status verified at PLAN P1.1).
- Python and PostgreSQL per Odoo 19 (verified at P1.1).
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

- `../../jaot-odoo-brief.md` — the kickoff brief (source of D1–D6-bis, the
  trap list, MVP candidates, and confidence levels).
- `projectes/jaot` (v3.9.0) — the platform this spec integrates with; §6 was
  verified against its sources and `openapi.json`.
- `projectes/jaos` — future in-house solver; when/wherever JAOT adopts it,
  JAOM is unaffected (the adapter boundary is inside JAOT).
- `jaot/docs/ROADMAP.md` — JAOM listed there as an official "Later /
  Exploring" item.
