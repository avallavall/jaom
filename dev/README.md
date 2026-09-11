# dev/ — local dev stack

P1.1 deliverable (PLAN.md). Odoo 19 Community + PostgreSQL 16 in Docker, for
developing and testing the JAOM addons. The repo root is mounted as Odoo's
extra addons path, so modules created at the repo root (`jaot_base`,
`jaot_stock`, ...) are picked up without any rebuild.

## Bring up

```
docker compose -f dev/docker-compose.yml up -d
# first DB init (installs the v1 routing domain, incl. fleet for the
# VRP "vehicles" role — see P1.2 note):
docker compose -f dev/docker-compose.yml run --rm odoo \
  odoo -d odoo --stop-after -i stock,delivery,fleet
```

## Verify (session-start rule: check what you inherit)

```
python dev/odoo_smoke.py            # stack alive? ALL PASS / exit 0
python dev/metamodel_probe.py --module fleet
python dev/metamodel_probe.py --models stock.picking,stock.move
```

- `odoo_smoke.py` — XML-RPC metamodel smoke: server 19.x, `stock` +
  `delivery` installed, partner geo fields present, `stock.picking`
  available. Stdlib only.
- `metamodel_probe.py` — module states and per-model field lists over
  XML-RPC; the tool the research notes quote for live evidence.

## Current dev DB baseline

`stock`, `delivery`, `fleet` (+ `account_fleet` alongside) — `fleet`
installed 2026-09-11 for the P1.2 role mapping. A fresh DB init should use
`-i stock,delivery,fleet`. The dev DB is disposable:
`docker compose down -v` wipes it.

## Addons path: read this before "module not found" (P1.2 finding F3)

Odoo only accepts an addons directory while it **directly contains at least
one module** (a subdirectory with `__init__.py` + `__manifest__.py`) —
`odoo.tools.config._is_addons_path`. Since the repo root is
`/mnt/extra-addons`:

- While the repo root holds no module (e.g. before `jaot_base` exists),
  Odoo **silently drops the path** ("invalid addons directory" warning in
  the logs).
- A `run --rm` process re-validates at start: the moment a module directory
  exists at the repo root, `run --rm odoo odoo -d odoo --stop-after -i <mod>`
  finds it — nothing to do.
- The **long-running** server validates once, at process start: if it
  started while the root was module-less, it will not see modules that
  appear later. **Restart it once the first module lands:**
  `docker compose -f dev/docker-compose.yml restart odoo`.

## Layout

- `docker-compose.yml` — the stack. PG on `127.0.0.1:5433` (the JAOT dev
  stack owns 5432, so both stacks can run at once); Odoo on
  `127.0.0.1:8069` (admin/admin).

## Notes

- Official Odoo image: library pull name `odoo:19.0` — **not** `odoo/odoo`
  (that repo 404s on Docker Hub as of 2026-09-11). See
  `docs/research/A-odoo-terrain.md` §3/§9.
- P1.3 (JAOT contract): the sibling repo `../jaot` runs its own dev stack
  (pg 5432, api 8001, frontend 3000) — no port conflicts. As of 2026-09-11
  it is up and healthy: `GET http://127.0.0.1:8001/api/v2/health` →
  `status: ok, version: 3.9.0` (its committed `openapi.json` says 3.8.0 —
  stale; the live instance settles the discrepancy).
