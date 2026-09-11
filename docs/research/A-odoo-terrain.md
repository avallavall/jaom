# A — Odoo 19 terrain (research note)

**Status (2026-09-11):** doc/source-level verification **complete**. The
remaining part of PLAN P1.1 is the live stand-up: `docker compose` with
`odoo:19` + `postgres:16`, first boot, and a live metamodel smoke query.
This note does **not** claim that was done.

**Method.** Checked against the `odoo/odoo` **19.0 branch** (full source
tarball fetched 2026-09-11, grepped locally) and the official 19.0 docs
(`www.odoo.com/documentation/19.0/`; the complete link index is
[`../rag_odoo19.md`](../rag_odoo19.md)). No inference; every claim below has
an evidence pointer.

---

## 1. `auto_install` semantics — VERIFIED (SPECS §4.2, brief D2)

Source: `odoo/addons/base/models/ir_module.py` (19.0).

- Manifest parse (L764): `'auto_install': terp.get('auto_install', False) is not False`
  — both a boolean and a non-empty list mark the module auto-installable.
- Trigger marking (L825, L830–840): `_update_dependencies(depends, terp.get('auto_install'))`
  sets `ir.module.module.dependency.auto_install_required = (name = any(<the list>))`.
  With a boolean, the full `depends` list is passed → **all** dependencies are
  triggers.
- Install decision (L411–434, `button_install` → `must_install`): a
  auto-installable module is installed when **all** its `auto_install_required`
  dependencies are in `{installed, to install, to upgrade}` **and at least one**
  of them is `to install` (plus the country rule).

**Conclusion.** The brief's open question ("¿acepta lista de dependencias en vez
de booleano, y desde qué versión?") is answered for 19.0: **both forms work**;
the list form restricts *which* dependencies trigger the auto-install (the
others remain hard `depends`). Either form fits our topology
(`jaot_stock` depends on `jaot_base` + domain modules); boolean is simplest,
the list form gives finer control (trigger on the domain modules only).

## 2. Worker timeouts — VERIFIED (SPECS D1/D5, brief trap 1)

Source: `odoo/tools/config.py` (19.0):

| Option | Default | Line |
|---|---|---|
| `--limit-time-real` | **120 s** | L487 |
| `--limit-time-cpu` | **60 s** | L484 |
| `--limit-time-real-cron` | **−1** (no real-time limit for cron threads) | L490 |
| `--limit-time-worker-cron` | 0 | L446 |

The brief's "~120 s / ~60 s" figures are exact. The async design (D5) holds:
the polling cron runs in a cron thread that is **exempt from
`limit_time_real` by default**, so `ir.cron`-based reconciliation is safe
without any server flag.

## 3. Target version status — VERIFIED

- `19.0` is the current stable series: docs version switcher lists
  `master`, `saas-19.4`, `18.0`, … (19 is the latest numbered release).
  `odoo/release.py` (19.0): `version_info = (19, 0, 0, FINAL, 0, '')`.
- **`odoo:19` / `odoo:19.0` docker images exist** (Docker Hub, daily builds
  through `19.0-20260908`) → the P1.1 compose is runnable.
- Q5 (target = Odoo 19) remains the right call.

## 4. Platform requirements — VERIFIED (SPECS §9)

Docs: `administration/on_premise/source.html` ("Install from source");
source: `odoo/release.py`.

- **Python ≥ 3.10** (`MIN_PY_VERSION = (3, 10)`; docs: "Changed in version 17"
  — unchanged since).
- **PostgreSQL ≥ 13 — raised from 12 in version 19** (docs: "Changed in
  version 19: Minimum requirement updated from PostgreSQL 12 to PostgreSQL
  13"). The P1.1 plan's `postgres:16` is fine.
- (Aside, not needed by JAOM: Odoo's AI features require the `pg-vector`
  extension.)

## 5. Module classification for the v1 domains — VERIFIED

Checked against the 19.0 branch (638 Community addons):

- **In Community:** `mrp`, `stock`, `delivery`, `purchase`, `account`, `hr`,
  **`hr_holidays`**, `base_geolocalize`, `resource`, `sale`. The brief's
  correction of the external expert (hr_holidays is Community, not
  Enterprise) holds in 19.
- **Not in Community (Enterprise):** `planning`, `hr_payroll` — as expected
  (they are not in the Community repo at all).
- **Map view = Enterprise feature, officially.** The 19.0 developer docs
  (`developer/reference/user_interface/view_architectures.html`) label the
  map view: *"Enterprise feature — This view is able to display records on a
  map and the routes between them"*. The Community `web` module ships no
  `<map>` view, and no `web_map` addon exists in the Community repo.
  → **P3.6's fallback is confirmed as the right plan:** the diff table view is
  the product; a map needs an OCA widget (AGPL contagion — SPECS §8) or a
  small Leaflet widget.

## 6. Metamodel and infrastructure models — VERIFIED

All exist in 19.0 (paths relative to the repo root):

| Model / utility | Location |
|---|---|
| `ir.model`, `ir.model.fields`, `ir.model.constraint`, `ir.model.relation` (+ `ir.model.inherit`, `ir.model.access`, `ir.model.data`) | `odoo/addons/base/models/ir_model.py` |
| `ir.module.module` | `odoo/addons/base/models/ir_module.py` |
| `ir.cron` | `odoo/addons/base/models/ir_cron.py` |
| `resource.calendar` (+ `.attendance`, `.leaves`) | `addons/resource/models/resource_calendar.py` |
| `safe_eval` | `odoo/tools/safe_eval.py` |

The D4 opportunity-scan substrate (brief §2.3) and the binding machinery are
fully present in 19.

## 7. Routing-domain fields — VERIFIED, one version trap ⚠

- **⚠ The partner geo fields in 19.0 are `partner_latitude` /
  `partner_longitude`** (Float, stored — `odoo/addons/base/models/res_partner.py`
  L270–271). The historical `x` / `y` fields are **gone** from `base` in 19.0
  (no definition anywhere in the core; the only surviving `<field name="x">`
  is the unrelated `ir.ui.menu` position). `base_geolocalize` geocodes into
  `partner_latitude` / `partner_longitude`.
  → **The VRP recipe's default bindings (P3.2) must use
  `partner_latitude` / `partner_longitude`**, not `x` / `y`.
- `stock.picking` — `addons/stock/models/stock_picking.py` ✓
- `delivery` module — `addons/delivery/` ✓
- The brief's job-shop example fields all exist in 19.0:
  `mrp.workorder.workcenter_id`, `mrp.workorder.duration_expected` (computed
  via `_compute_duration_expected` — mind SPECS trap 3 for extraction),
  `mrp.workcenter.capacity` (per-product through `capacity_ids`),
  `mrp.production.date_deadline`.

## 8. 19.0 layout/doc changes that affect development — VERIFIED

- **Community addons moved out of `odoo/addons/` into a top-level `addons/`
  directory** (638 modules; only 24 core addons remain under
  `odoo/addons/`, e.g. `base`, `web`). Affects `addons_path` in P1.1's docker
  compose and where our addons/tests live in P2+.
- Framework renames: `odoo/modules/graph.py` → `odoo/modules/module_graph.py`;
  `odoo/modules/registry.py` → `odoo/modules/registry/` (package).
- **Docs reorg:** the old top-level `webservices/`, `upgrade/`, `reference/`
  doc trees no longer exist. Current locations: external/XML-RPC/JSON-RPC API
  docs at `developer/reference/external_api.html`,
  `developer/reference/external_rpc_api.html`, `developer/reference/extract_api.html`;
  the upgrade process at `administration/upgrade.html`; developer upgrade-script
  docs at `developer/reference/upgrades/`. The full 19.0 link index (944
  pages) is in [`../rag_odoo19.md`](../rag_odoo19.md).

## 9. Still open — the rest of P1.1 (live checks only)

1. `docker compose` up with `odoo:19` + `postgres:16`; first boot green.
2. Live metamodel smoke: `ir.module.module` / `ir.model.fields` queries
   against a running 19.0 DB.
3. Confirm the bridge `auto_install` actually fires in a real session
   (P3.1 re-proves this, but an early check is cheap).
