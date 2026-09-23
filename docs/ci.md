# CI — local verification records

The CI pipeline (`.github/workflows/ci.yml`) has four jobs. GitHub
Actions itself runs on push to the public repository (the maintainer's
call — see AGENTS.md: never `git push` unless asked), so this document
records the local run of each job, with the exact commands, against the
same pinned images and pinned JAOT commit the workflow uses. Two
records: the P5.7 run of 2026-09-20 (below) and the P9.6 gate run of
2026-09-22 (at the end).

## Pinned inputs

- Odoo 19 Community image: `odoo:19.0` (19.0-20260908)
- PostgreSQL 16 for the Odoo CI stack
- JAOT v3.9.0 at commit `c5a07e2a0fe9da35bcd69b57b8eda5f33b082d58`
- Ruff `0.15.6`

## 1. lint

```
pip install ruff==0.15.6
ruff check .
```

Result: `All checks passed!` Scope is the addons (`ruff.toml`);
`dev/` and `scripts/` are the development harness and are excluded.
`E741` is ignored: `l` is the established loop variable for scenario
lines (`jaot.scenario.line`).

## 2. tests

```
docker compose -f .github/ci.yml up -d db
docker compose -f .github/ci.yml run --rm odoo odoo \
  -d ci --stop-after -i stock,delivery,fleet,mrp,jaot_base,jaot_stock,jaot_mrp \
  --test-enable \
  --test-tags '-base:TestCommand,-account_edi_ubl_cii:CiiExportFacturXFR.test_invoice_deferred_dates'
```

Fresh database, offline (the tests patch `JaotConfig.get_client` with a
deterministic fake client — SPECS §10.3). The module list installs the
three addons plus their dependency chain (`delivery` pulls in
`sale`/`account`, `mrp` the production stack), so the full test suite
of the installed core modules runs.

Two core tests of the pinned image are excluded, and nothing else:

- `-base:TestCommand`: `test_cli` spawns `odoo-bin <subcommand>` as a
  subprocess and resolves the binary path relative to the test file
  (`Path(__file__).parents[4] / 'odoo-bin'`), a layout that only
  exists in a source checkout. In the Debian-packaged `odoo:19.0`
  image the binary lives in `/usr/bin`, so the class fails
  100%-reproducibly there — verified against the image directly
  (every one of its subtests exits with status 2; a run showed 3
  failed + 20 errors, all inside that class, zero in the addon
  tests).
- `-account_edi_ubl_cii:CiiExportFacturXFR.test_invoice_deferred_dates`:
  the test writes `deferred_start_date` on `account.move.line`
  unconditionally, but that field only exists when
  `l10n_tr_nilvera_einvoice` (Turkish e-invoice l10n) is installed.
  The model code guards the field (`in _fields`), and the sibling
  tests in the same class guard with `ensure_installed` — this one
  does not. Upstream bug in the pinned image (19.0-20260908),
  reproduced 100%: `ValueError: Invalid field 'deferred_start_date'
  on model 'account.move.line'`.

The combined spec was verified to remove exactly those two tests and
nothing else — `TagsSelector` checked against `base:TestCommand`,
`base:TestACL`, the excluded method, its siblings in the same class,
`account_edi_ubl_cii` tests in other classes, and a `jaot_base` test
(all of the rest select `True`).

Result: **0 failed, 0 errors of 5620 tests** on a fresh `ci` database
(30 min 11 s including module install) — `jaot_base` 70, `jaot_stock`
13 and `jaot_mrp` 14 tests, all green.

## 3. contract-smoke

The job checks out the pinned JAOT commit, builds it with
`.github/jaot-pinned.yml` (the trimmed stack: no qdrant/frontend,
RAG disabled), waits for `/api/v2/health/status`, mints an admin API
key (`scripts/ensure_admin_api_key.py`, never committed or logged) and
runs `dev/ci_contract_smoke.py` (stdlib only) — one async solve of a
toy MIP, polling to a terminal state, fetching the execution and the
exact-analysis, asserting every frozen response field name (SPECS
§6.4).

Result:

- Build from a clean copy of the pinned checkout: `docker compose -f
  .github/jaot-pinned.yml build` — exit 0.
- Run against the live pinned stack (v3.9.0, the same commit): `PASS`
  — all frozen fields present (`AsyncSolveEnvelope`, poll status,
  `ModelExecutionResponse`, `ExactAnalysis`), toy MIP solved
  (objective 5.0, solver scip).

API drift on any of those fields fails this job; that is a
release-blocking event per SPECS §6.4, not something to work around.

## 4. i18n

```
docker compose -f .github/ci.yml up -d db
docker compose -f .github/ci.yml run --rm odoo odoo \
  -d i18n --stop-after -i stock,delivery,fleet,mrp,jaot_base,jaot_stock,jaot_mrp
docker compose -f .github/ci.yml run --rm odoo \
  odoo shell -d i18n --no-http < dev/gen_i18n.py
python dev/i18n_check.py
```

The .pot templates are regenerated into the checkout and compared
against the committed versions. `dev/i18n_check.py` normalizes the two
header lines Odoo re-stamps on every export (`POT-Creation-Date`,
`PO-Revision-Date` — inside the quoted msgstr header, hence the
`^"\s*` match) and fails on any other difference; a raw byte diff
would be red on every run because of the fresh stamps.

Result: all three templates checked (regenerated 2026-09-20 against
HEAD) — `jaot_base` and `jaot_stock` `OK`; `jaot_mrp` `NEW` (first
template, committed with the module).

## Final summary

| Job | Result |
|---|---|
| lint | pass |
| tests | pass — 0 failed, 0 errors of 5620 (30 min 11 s) |
| contract-smoke | pass (build + live run) |
| i18n | pass (regenerate + content check) |

The SPECS §10 performance targets are documented in `docs/PERF.md`
(P5.3) — all met.

## P9.6 gate run (2026-09-22)

Same four jobs, same pinned inputs; the only change since P5.7 is that
the `tests` and `i18n` jobs now install the fourth addon — `-i
stock,delivery,fleet,mrp,jaot_base,jaot_stock,jaot_mrp,jaot_forecast`
(`jaot_forecast` auto-installs with `jaot_mrp`; the list spells it out
to match `.github/workflows/ci.yml`). The same two pinned-image test
exclusions apply.

### 1. lint

First run flagged three issues in the new `jaot_forecast`
(`jaot_forecast/models/jaot_forecast.py`): an unused `UserError`
import, a loop variable shadowing the `_` translation function, and
one 82-character line. Fixed in `7760df7` (no behaviour change — the
offline suite was green before and after); rerun: `All checks
passed!` (ruff 0.15.6).

### 2. tests

```
docker compose -f .github/ci.yml down -v
docker compose -f .github/ci.yml up -d db
docker compose -f .github/ci.yml run --rm odoo odoo \
  -d ci --stop-after -i stock,delivery,fleet,mrp,jaot_base,jaot_stock,jaot_mrp,jaot_forecast \
  --test-enable \
  --test-tags '-base:TestCommand,-account_edi_ubl_cii:CiiExportFacturXFR.test_invoice_deferred_dates'
```

Result: **0 failed, 0 error(s) of 5711 tests** on a fresh `ci` database
(27 min) — `jaot_base` 111, `jaot_stock` 28, `jaot_mrp` 32,
`jaot_forecast` 29 tests. The two `duplicate key` ERROR lines in the
log are the intentional uniqueness tests
(`TestConfig.test_one_config_per_company`,
`TestRecipeAndBinding.test_one_binding_per_role_per_company`), not
regressions.

### 3. contract-smoke

Run against the live pinned stack (v3.9.0, the same commit built for
P5.7 — the pinned checkout is unchanged since): `PASS` — all frozen
fields present (`AsyncSolveEnvelope`, poll status,
`ModelExecutionResponse`, `ExactAnalysis`), toy MIP solved (objective
5.0, solver scip). The P9.5 cycle added no API surface, so the frozen
contract (SPECS §6.4) is untouched.

### 4. i18n

```
docker compose -f .github/ci.yml run --rm odoo odoo \
  -d i18n --stop-after -i stock,delivery,fleet,mrp,jaot_base,jaot_stock,jaot_mrp,jaot_forecast
docker compose -f .github/ci.yml run --rm odoo \
  odoo shell -d i18n --no-http < dev/gen_i18n.py
python dev/i18n_check.py
```

Fresh `i18n` database (75 modules). All four templates regenerated
into the checkout: the only difference against the committed versions
is the two re-stamped header lines. `dev/i18n_check.py` — all eight
lines OK (four pots, four `es` catalogs: 338 / 35 / 18 / 73 entries).

### Final summary

| Job | Result |
|---|---|
| lint | pass (after `7760df7` fixed three new issues) |
| tests | pass — 0 failed, 0 error(s) of 5711 (27 min) |
| contract-smoke | pass (live run vs the pinned stack) |
| i18n | pass (regenerate + content check, all four templates) |

Alongside the CI jobs, the gate also re-verified the two dev-stack
checks on fresh databases: the offline addon suite — `0 failed, 0
error(s) of 158 tests` (db `p96a`) — and the full live e2e suite
(`dev/e2e`, Playwright) — `43/43 cases passed`.
