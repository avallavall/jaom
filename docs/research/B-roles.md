# B — Role mapping gate: VRP recipe vs Odoo 19 (standard + OCA)

**Status:** complete — 2026-09-11 (PLAN P1.2 gate ⛔)

**Verdict: the role abstraction SURVIVES both cases with bindings only. D3
holds.** No redesign needed. Three findings recorded (F1–F3); none breaks
the abstraction, two are inputs to P2.3/P3.2.

## 1. Recipe and role set under test

The delivery-routing (VRP) recipe — the Q6 MVP domain, mapped to a JAOT
CVRP-family template (SPECS §6.2). Roles as they will be declared in P3.2
(`jaot.recipe.role`, SPECS §5.3: `kind`, `required`, `semantics`,
`data_type`):

| Role | kind | required | data_type | Semantics |
|---|---|---|---|---|
| `depot` | parameter | yes | reference | The single origin (a warehouse with geo) |
| `orders` | variable | yes | reference | Record set: delivery stops (outbound pickings) |
| `order_lat` | parameter | yes | number | Latitude of each stop |
| `order_lng` | parameter | yes | number | Longitude of each stop |
| `order_demand` | parameter | yes | quantity | Load per stop (weight) |
| `vehicles` | parameter | yes | reference | Record set: available vehicles |
| `vehicle_capacity` | constraint | yes | quantity | Max load per vehicle/route |
| `order_time_window` | constraint | no | date | Service window per stop, optional |
| `distance_matrix` | parameter | yes | number | Pairwise travel cost (external provider — P1.5) |

**Binding semantics used for this mapping** (SPECS §5.4: one binding per
role per company = `res_model` + `field_path` + optional `domain` +
optional restricted `expression`): each binding is self-contained. The
record-set roles (`orders`, `vehicles`) carry the `res_model` + `domain`
that define the record set; the scalar roles repeat the same `res_model` +
`domain` and their `field_path` is evaluated **per record** of that set.
Explicit per-role domains keep the engine model-agnostic (no implicit
"parent role" state) — that uniformity is what both test cases below
exercise.

## 2. Case 1 — standard Odoo 19 Community (live)

Environment: the dev stack (`docs/README.md`), server `19.0-20260908`,
modules `stock` + `delivery` + `fleet` installed for this note. Field
evidence: `python dev/metamodel_probe.py --models ...` (live XML-RPC
queries, run 2026-09-11).

| Role | res_model | field_path | domain (record set) | Live evidence |
|---|---|---|---|---|
| `depot` | `stock.warehouse` | `partner_id.partner_latitude` / `partner_id.partner_longitude` | company warehouse (single) | `stock.warehouse.partner_id` → `res.partner` (probe); `partner_latitude/longitude` float (P1.1 smoke) |
| `orders` | `stock.picking` | (record set) | `picking_type_code='out'`, `state in ('confirmed','assigned')` | `picking_type_code` selection on the model (probe) |
| `order_lat` / `order_lng` | `stock.picking` | `partner_id.partner_latitude` / `…_longitude` | same set | same as above, one hop through `partner_id` |
| `order_demand` | `stock.picking` | `shipping_weight` (alt: expression over `move_ids`) | same set | `shipping_weight` float, `move_ids` one2many → `stock.move` (probe) |
| `vehicles` | `fleet.vehicle` | (record set) | `active=True` | `fleet` is a **standard Community module in 19** (module state `uninstalled`, `latest_version=False` = not OCA; installed for this note, 102 fields probed) |
| `vehicle_capacity` | — parameter binding | constant (recipe/config) or a per-vehicle field when one exists | — | **no cargo-capacity field on `fleet.vehicle`** (it has `seats`, `power`, `co2`…); `delivery.carrier` has `max_weight`/`max_volume` but at carrier level — see F1 |
| `order_time_window` | — **unbound** | — | — | no per-stop window in standard (closest: `stock.picking.date_deadline`, a single deadline); the role is optional, so the recipe runs without it |
| `distance_matrix` | `ir.config_parameter` | `value` (JSON) / external provider | `key='jaot.distance.*'` | provider decision is P1.5; the binding shape is config, not code |

Every required role resolves to a standard source. Two roles are
parameter/config bindings by design (`vehicle_capacity`, `distance_matrix`)
— the binding model already supports that (expression field), so it is
coverage, not a gap.

## 3. Case 2 — one OCA module in the same domain

**Selected: `partner_delivery_schedule`** (OCA/delivery-carrier, branch
19.0 @ `543a240`, AGPL-3, Production/Stable, depends `stock_delivery`).
It adds per-partner delivery windows — exactly the data the VRP role set
lacks in standard Community:

- new model `delivery.schedule`: `hour_from`/`hour_to` (floats 0–24) +
  seven day booleans;
- `res.partner.delivery_schedule_ids` (many2many → `delivery.schedule`).

Why this one: it stress-tests the hardest structural case of the gate —
an **optional role that is unbound in one installation and bound in the
other**. Candidates considered and not chosen: `delivery_carrier`/
`partner_delivery_info` (same repo — carrier cost info, not a VRP input),
OCA/fleet `fleet_vehicle_configuration` (adds `max_seats` per vehicle
configuration — seats, not cargo capacity).

**Live verification** (probe pattern: installed → simulated → uninstalled →
files removed):

- installed on the dev DB without issues (69 modules loaded, exit 0);
- created a schedule 08:00–18:00 Mon–Fri, linked it to a partner, read it
  back through the binding path —
  `res.partner.read(delivery_schedule_ids)` → ids →
  `delivery.schedule.read(hour_from, hour_to)` →
  `{'hour_from': 8.0, 'hour_to': 18.0}`;
- dotted path works natively **in a domain**:
  `search res.partner [("delivery_schedule_ids.hour_from", "<", 9.0)]` →
  hit;
- the module was then uninstalled (`button_immediate_uninstall`, state
  `uninstalled`) and its files removed from the repo root.

**The only binding that changes** versus case 1 (everything else is
identical; zero code change):

| Role | res_model | field_path | domain |
|---|---|---|---|
| `order_time_window` | `stock.picking` | `partner_id.delivery_schedule_ids.hour_from` / `…hour_to` (+ day booleans) | same order set |

(Verified one hop short — on `res.partner` directly; the extra hop through
`stock.picking.partner_id` is the same ORM mechanism already proven for
`order_lat`.) When a partner has several schedules, the bridge picks the
window matching the stop's delivery date — domain extraction logic, as
expected.

## 4. Findings

- **F1 — vehicle cargo capacity has no standard per-vehicle source.**
  `fleet.vehicle` (standard in 19) carries `seats`/`power`/`co2`, no cargo
  load; `delivery.carrier` has `max_weight`/`max_volume` at carrier level.
  ⇒ P3.2 default: `vehicle_capacity` binds to a **constant parameter**
  (homogeneous-fleet CVRP — solvable and honest for v1); an installation
  with a module that adds a per-vehicle load field re-binds it in the UI.
  Data-availability gap, not an abstraction break.
- **F2 — Odoo 19 `read` does not resolve dotted field paths in the FIELDS
  list** (live: `Invalid field 'delivery_schedule_ids.hour_from' on
  'res.partner'`), while dotted paths **do** work in domains. ⇒ The
  binding engine (P2.3/P3.3) needs a per-record **path resolver**: try the
  field directly, else walk the relation hop-by-hop (or evaluate the
  restricted `expression`). SPECS §5.4's own example
  (`production_id.date_deadline`) depends on this. Engineering requirement,
  not an abstraction break.
- **F3 — an Odoo addons path is only accepted while it directly contains at
  least one module** (`odoo.tools.config._is_addons_path`: a subdirectory
  with `__init__.py` + `__manifest__.py`). While the repo root held no
  module (after the P1.1 probe was removed), `/mnt/extra-addons` was
  **silently dropped** — in `run` processes and in the long-running server
  (started before any module existed); the moment a module directory
  appeared, fresh processes re-accepted it (the "invalid addons directory"
  warning disappeared). Consequences are documented in `dev/README.md`:
  restart the long-running server once the first module lands.

## 5. Gate question and answer

**Q (PLAN P1.2):** do the roles survive both cases with bindings only, or
are there structural differences that break the abstraction?

**A: yes, they survive.** In standard Community every required role binds
to a standard source (live-verified); the two roles without a standard
record source are parameter/config bindings, which the binding model
already covers. In the OCA case exactly one binding
(`order_time_window`) moves to the OCA-supplied field path — same
`res_model` + domain as the rest of the order roles, zero code change.
This is precisely the "remap = configuration, not code" promise (SPECS
§4.3). **D3 holds; P2 may proceed.** Inputs to carry forward: uniform
per-role binding semantics (§1), F2 path resolver → P2.3, F1 capacity
default → P3.2.

## 6. Evidence log (run 2026-09-11)

```
python dev/metamodel_probe.py --module fleet
  -> module fleet: state=uninstalled latest_version=False   (standard, not OCA)
docker compose -f dev/docker-compose.yml run --rm odoo \
  odoo -d odoo --stop-after -i fleet
  -> 68 modules loaded, exit 0
python dev/metamodel_probe.py --models fleet.vehicle,stock.picking,stock.move,\
  delivery.carrier,stock.warehouse,stock.location
  -> field lists (fleet.vehicle: 102 fields; picking: partner_id,
     picking_type_code, shipping_weight, move_ids; carrier: max_weight,
     max_volume; warehouse: partner_id; location: no partner_id in 19)
git clone --depth 1 -b 19.0 https://github.com/OCA/delivery-carrier
  -> HEAD 543a240; module copied to repo root for the run
docker compose ... run --rm odoo odoo -d odoo --stop-after -i partner_delivery_schedule
  -> 69 modules loaded, exit 0, no addons-path warning
binding simulation (throwaway script, since removed):
  create delivery.schedule {hour_from: 8.0, hour_to: 18.0} -> id
  link to partner (m2m command 4) -> ok
  dotted read in fields list  -> Invalid field (F2)
  two-read path resolution    -> {'hour_from': 8.0, 'hour_to': 18.0}
  dotted-domain search        -> hits the linked partner
uninstall (button_immediate_uninstall) -> state: uninstalled
```

Also observed (belongs to note C): the live JAOT instance answers
`/api/v2/health` with `version: 3.9.0` — the local `openapi.json` (3.8.0)
is stale; P1.3 pins response field names against the live instance.
