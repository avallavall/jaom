# C — JAOT contract verification (live) — PLAN P1.3

**Status:** complete — 2026-09-11

**Supersedes:** the 2026-09-11 source-level verification referenced in the
SPECS §6 header (sources under `app/` + committed `openapi.json`). Both are
kept on record; this note is built on **real calls** against a running
instance.

**Verdict: the SPECS §6 contract holds end-to-end on live JAOT v3.9.0**
(commit `c5a07e2`). Three method/behavior deltas found (D1–D3) — none
breaks the contract; D1 (preview is POST) requires a one-line SPECS §6.2
fix. The SPECS §4.7 question is answered: **yes, the existing formulation
assistant takes external context** through a designed attachment channel —
verified live up to the upstream LLM call (which was blocked by the
platform's Anthropic billing mid-test, see §5).

## 1. Instance under test

- Local JAOT stack (docker compose, sibling repo `../jaot` @ `c5a07e2`),
  all services healthy; api on `127.0.0.1:8001`.
- Version: **3.9.0 live** (`GET /api/v2/health/status`) vs the committed
  `openapi.json` (3.8.0 — stale). The live spec is served unauthenticated at
  `GET /openapi.json`; all schema extractions in this note come from that
  live 3.9.0 document, not the stale file.
- Auth: API key via the documented flow
  `docker compose exec api python scripts/ensure_admin_api_key.py`
  (prints the key once; never committed — SPECS §7.1).
- Solvers (live `solvers/available`): scip 10.0, highs 1.15.1, cbc 2.10.12,
  glpk 5.0 — all available.
- `health/status` reports `degraded` solely because of
  `solver_worker_hexaly` (optional Hexaly SDK not installed — expected on
  the local stack).

## 2. Contract steps verified (real calls — 10/10)

Tool: `dev/jaot_contract_probe.py` (stdlib only; key via the `JAOT_API_KEY`
env var, base via `JAOT_BASE`; exit 0 = all steps passed). Run twice;
latencies below are from the second run.

| # | Call | Live result | Latency |
|---|---|---|---|
| 1 | `GET /api/v2/health/status` | `status`, `version=3.9.0`, checks 4/5, `components[]` | 42 ms |
| 2 | `GET /api/v2/solvers/available` | 4 solvers, all `available: true` | 544 ms (cold) |
| 3 | `GET /api/v2/solve/templates?page_size=100` | `total=102`; routing generators: `vehicle_routing` (logistics), `waste_collection_routing` (environmental), `drug_distribution` (pharmaceutical), `pick_route_optimization` (warehouse) | 23 ms |
| 4 | `POST /api/v2/solve/templates/{id}/preview` | grounded problem `"Route 2 vehicles to 6 locations"` — binary arc variables `x_truck_1_depot_site_1 …` | 34 ms |
| 5 | `POST /api/v2/solve/async` (toy feasible MIP) | envelope `{task_id, execution_id, status: "pending", message, ws_url, poll_url}` | 41 ms |
| 6 | `GET /api/v2/solve/async/{task_id}` (poll) | terminal `status=completed`; inner `result.result.status=optimal`; objective 5.0 (as expected by hand); `solver_used=scip` | <1 s |
| 7 | `GET /api/v2/models/executions/{execution_id}` | `status=completed`, `solver_status=optimal`, `objective_value=5.0`, `execution_time_ms=44`, `result_data.model={x1:1, x2:1, x3:0}`, `result_data.variables[]`, `result_data.sensitivity` | 31 ms |
| 8 | `GET …/executions/{id}/exact-analysis` | 2/2 constraints binding; `coverage`: activity 2.0 / rhs 2.0 / slack 0.0; contributions x1=2.0 + x2=3.0 (= objective, exact) | 32 ms |
| 9 | `POST …/executions/{id}/scenario-analysis` → poll `GET` | **no request body**; batch auto-derived: 7/7 re-solves (RHS relax/tighten per constraint + forced decision flips per binary); rows `status: computed|infeasible`; `partial=false` | ~4 s |
| 10 | `POST /api/v2/solve/{execution_id}/infeasibility-analysis` (infeasible toy) | `iis_constraints=["impossible"]`, `conflict_type=constraint`, `method=iis` | 39 ms |

Toy problems (embedded in the probe, also the future §6.4 CI smoke test
shape): **feasible** — `min 2*x1 + 3*x2 + 5*x3 s.t. x1+x2+x3 >= 2
(coverage), x1+x3 <= 1 (conflict)`, binaries → optimum 5.0 at
x1=x2=1, x3=0 (coverage binding, conflict at its limit). **Infeasible** —
`x1+x2 >= 3` with two binaries (max sum 2).

## 3. Deltas vs SPECS §6.2 (frozen 2026-09-11)

- **D1 — template preview is POST, not GET.** `GET /solve/templates/{id}/preview`
  → HTTP 405. The live method is **POST** with an optional JSON body (user
  input — arbitrary object or null) → 200 with the grounded
  `OptimizationProblem`. §6.2 row updated in this cycle.
- **D2 — scenario-analysis takes NO request body.** The what-if batch is
  **auto-derived from the execution** (per-constraint RHS relax/tighten +
  per-variable decision flips). `POST` → 202 `ScenarioAnalysisJob`
  (`status: absent|running|completed|failed`, `progress{done,planned}`);
  poll the `GET` until it leaves `running`. The spec's behavioral note stays
  correct: budget-truncated rows come back flagged (`status:
  SKIPPED_BUDGET`, `partial: true`), infeasible perturbations return
  `status: infeasible` with null objective — never silent.
- **D3 — an infeasible solve ends `completed` at the task level.**
  Infeasibility lives in the execution: `solver_status=infeasible`
  (and `result.result.status=infeasible` in the poll payload); the task
  payload has `error=null`. Client terminal logic must therefore read the
  **execution**'s `solver_status` (or the poll's inner `result.result.status`),
  never the task `status` alone.
- Not deltas: live-progress WebSocket exists, unused in v1 (decided, §6.2);
  sync `POST /solve` exists, never used by JAOM (decided, D1 worker-timeout
  rule); `wait=true` on `solve/async` (returns the sync `OptimizationResult`
  inline past a budget) is new in 3.9.0 and likewise unused in v1 —
  polling stays the contract.

## 4. Frozen response field names (live 3.9.0 — observed keys)

Frozen here for the P2.2 HTTP client and the §6.4 CI contract smoke test.
These are the observed keys on the live instance; the CI smoke test pins
them.

- **AsyncSolveEnvelope** (`POST /solve/async`): `task_id`, `execution_id`,
  `status` (default `"pending"`), `message`, `ws_url`, `poll_url`.
- **AsyncSolveStatusResponse** (`GET /solve/async/{task_id}`): `task_id`,
  `status` (discriminator: `pending|running|completed|failed|…`),
  `message`, `error`, `result`, `solver_used`, `auto_route_reason`,
  `warning`, `progress`, `iteration`, `objective_value`, `gap`,
  `timestamp`. Terminal `result`: `status` (`success`), `task_id`,
  `result{ status (optimal|infeasible|…), execution_id, objective_value,
  variables[{name, value, type, family, index_tuple}], solution
  {name: value}, variables_omitted, solve_time_seconds, gap, iterations,
  nodes, dual_bound, error_message, solver_used, auto_route_reason,
  warning, sensitivity{constraints[{name, shadow_price, is_binding,
  is_approximate}], variables[{name, reduced_cost, is_at_bound,
  is_approximate}], objective_ranges, rhs_ranges, is_approximate, note},
  infeasibility_analysis, warm_start_used,
  progress_history[{iteration, node, objective, primal_bound, dual_bound,
  gap, elapsed_seconds}] }`, `execution_time_seconds`, `solver_used`,
  `auto_route_reason`.
- **ModelExecutionResponse** (`GET /models/executions/{id}`): `id`,
  `model_project_id`, `organization_model_id`, `status`, `error_message`,
  `execution_time_ms`, `solver_status`, `solver_name`, `objective_value`,
  `origin`, `trigger_id`, `trigger_name`, `source_kind`, `source_id`,
  `dataset_id`, `dataset_name`, `model_name`, `model_author`, `created_at`,
  `completed_at`, `input_data` (the full problem as sent), `result_data{
  model{name: value}, objective_value, solver_status,
  solve_time_seconds, gap, nodes, iterations, dual_bound,
  warm_start_used, variables[], sensitivity, infeasibility_analysis,
  progress_history[] }`.
- **ExactAnalysis** (`GET …/executions/{id}/exact-analysis`):
  `objective_value`, `total_constraints`, `binding_count`,
  `constraints[{name, activity, rhs, operator, slack, is_binding,
  utilization, family}]`, `contributions[{label, contribution}]`,
  `families[{family, total, binding_count, slack_min, slack_mean,
  slack_max, utilization_mean, utilization_max}]`,
  `contribution_families[]`, `truncated_constraints`,
  `truncated_contributions`, `truncated_families`, `computed`, `note`.
- **ScenarioAnalysisJob** (`POST`/`GET …/scenario-analysis`): `status`
  (`absent|running|completed|failed`), `analysis`, `error`,
  `requested_at`, `completed_at`, `progress{done, planned}`,
  `explanation`, `explained_at`. **ScenarioAnalysis** (`analysis`):
  `computed`, `note`, `sense`, `base_objective`,
  `rhs_scenarios[{constraint, family, operator, direction
  (relax|tighten), is_equality, rhs, rhs_new, delta, status
  (computed|infeasible|SKIPPED_BUDGET), objective_value, objective_delta,
  objective_delta_per_unit, improves, solve_time_seconds}]`,
  `decision_scenarios[{variable, family, original_value, forced_value,
  status, objective_value, regret, solve_time_seconds}]`,
  `resolves_used`, `resolves_planned`, `seconds_used`, `budget_seconds`,
  `per_solve_limit_seconds`, `partial`.
- **InfeasibilityAnalysis** (`POST /solve/{execution_id}/infeasibility-analysis`):
  `iis_constraints[]`, `iis_variable_bounds[]`, `conflict_type
  (constraint|bound|mixed|unknown)`, `method (iis|llm_only)`, `note`,
  `explanation`.
- **AvailableSolversResponse**: `solvers[{name, available, description,
  version, capabilities, reason, retry_after, comparable,
  not_comparable_reason}]`.
- **DetailedStatusResponse** (`GET /health/status`): `status`, `version`,
  `uptime_seconds`, `components[{name, status, latency_ms, message}]`,
  `sla_target`, `checks_passed`, `checks_total`.
- **TemplateListResponse** (`GET /solve/templates`; query: `category`,
  `featured`, `page`, `page_size`): `templates[{id, name, display_name,
  short_description, category, tags, problem_type_tags, generator_type,
  is_featured, estimated_variables, estimated_constraints}]`, `total`,
  `page`, `page_size`. **Preview response** (`POST …/templates/{id}/preview`)
  is the grounded `OptimizationProblem` — same shape as the solve request.
- **Request `OptimizationProblem-Input`** (`POST /solve/async`): `name`,
  `description`, `variables[]` (minItems 1; `{name, type, lower_bound,
  upper_bound, family, index_tuple}`), `objective{sense, expression}`,
  `constraints[]` (default `[]`; `{name, expression, family}`),
  `options{time_limit_seconds (default 300), gap_tolerance (default
  0.0001), threads (default 0), verbose (default false)}`, `warm_start`,
  `heuristic_warm_start`, `metadata`, `solver_name`. Query params on
  `solve/async`: `solver_name`, `origin`, `source_kind`, `source_id`,
  `dataset_id`, `wait`, `workspace_id`.

## 5. SPECS §4.7 — can the existing formulation assistant take Odoo context?

**Yes — a designed channel exists, and it was exercised live.**

The assistant (v2, `POST /api/v2/llm/…`):

- `POST /llm/conversations` → 201 `{id, created_at, expires_at (24 h),
  messages, current_formulation}`;
- `POST /llm/conversations/{id}/attachments` — multipart upload, **one
  `.pdf`/`.csv`/`.txt` per conversation, ≤ 50 MB**; the text is extracted,
  stored, and injected into **every** subsequent formulation prompt as
  `<document_context>` (`DOCUMENT_CONTEXT_TEMPLATE` — injected
  deterministically by `build_messages` whenever an attachment exists);
- `POST /llm/conversations/{id}/messages` → SSE stream
  (`delta` / `formulation` / `validation_errors` / `done` / `error`) with a
  structured `Formulation` (variables / constraints / objective);
- a second, independent context axis: RAG retrieval (Qdrant) of the
  platform's optimization-template corpus per message — curated knowledge,
  not user data.

Live evidence (2026-09-11, same instance): conversation creation 201 ✓;
attachment upload 200 ✓ (`odoo_metamodel_excerpt.txt`, 976 chars, preview
returned); message stream opened (SSE 200) and the assistant answered real
messages earlier in the session; the message **with the Odoo attachment**
was refused **upstream** — Anthropic 400 `credit balance is too low`
(platform billing, visible in the api logs). So: **the channel works and is
the right one; the last mile — observing a formulation whose content uses
the Odoo schema — was not observable today** because the platform's LLM
credits ran out mid-test. The injection is unconditional in the prompt
builder, so nothing further is needed on the JAOT side for v2. Practical
caveat: the attachment is one 50 MB document — a full metamodel dump should
be curated per conversation (the §4.7(a) opportunity scan is precisely what
produces that curated context). BYOK (org-supplied Anthropic key) is
supported, so customer-self-hosted instances run the assistant on their own
account.

## 6. Handoff implications

- **P2.2 client**: implement against §4 (frozen names); infeasibility
  detection per D3; preview per D1; scenario batch per D2 (no body).
- **SPECS §6.2**: two rows corrected in this cycle (preview POST;
  scenario-analysis bodyless) + the §6 header now cites this live
  verification.
- **P1.4 spike**: reuse the probe's toy shape; the routing generator to
  preview/compare is `vehicle_routing` (logistics) — the preview of
  `waste_collection_routing` returns the `vehicle_routing` problem
  (shared generator). The source-level note's "CVRP with
  nearest-neighbor warm start" claim is not re-verified here; the live
  preview shows the arc-assignment structure (2 trucks, 6 sites), and the
  toy run reported `warm_start_used: false`.

## 7. Evidence log (run 2026-09-11)

```
docker compose exec api python scripts/ensure_admin_api_key.py
  -> CLI Admin Key created (value shown once, not stored)
GET /openapi.json (live, unauthenticated) -> version 3.9.0 (committed file: 3.8.0)
python dev/jaot_contract_probe.py            (JAOT_API_KEY env)
  run 1: 9/10 — preview failed HTTP 405 (GET) -> D1 found, probe fixed
  run 2: 10/10 — table in §2
throwaway detail probe (removed after use):
  infeasible toy -> task status=completed, result.result.status=infeasible,
  execution: status=completed, solver_status=infeasible, error_message=null
throwaway SSE capture (removed): assistant answered
  "Yes, I'm the formulation assistant for JAOT…" (200, streamed)
throwaway Odoo-context test (removed):
  POST /llm/conversations -> 201
  POST …/attachments (multipart .txt, 976 chars) -> 200
  POST …/messages -> SSE 200; upstream Anthropic 400 credit-balance
  (api logs: two earlier anthropic 200s, then the 400)
conversations created during the test: all deleted (204)
```
