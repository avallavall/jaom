# dev/ — local dev stack

P1.1 deliverable (PLAN.md). Odoo 19 Community + PostgreSQL 16 in Docker, for
developing and testing the JAOM addons. The repo root is mounted as Odoo's
extra addons path, so modules created at the repo root (`jaot_base`,
`jaot_stock`, ...) are picked up without any rebuild.

## Bring up

```
docker compose -f dev/docker-compose.yml up -d
# first DB init (installs the v1 routing domain):
docker compose -f dev/docker-compose.yml run --rm odoo \
  odoo -d odoo --stop-after -i stock,delivery
```

## Verify (session-start rule: check what you inherit)

```
python dev/odoo_smoke.py
```

`ALL PASS` (exit 0) means the stack is alive: server 19.x, `stock` +
`delivery` installed, partner geo fields present, `stock.picking` available.

## Layout

- `docker-compose.yml` — the stack. PG on `127.0.0.1:5433` (the JAOT dev
  stack owns 5432, so both stacks can run at once); Odoo on
  `127.0.0.1:8069` (admin/admin).
- `odoo_smoke.py` — XML-RPC metamodel smoke. Stdlib only, no dependencies.

## Notes

- Official Odoo image: library pull name `odoo:19.0` — **not** `odoo/odoo`
  (that repo 404s on Docker Hub as of 2026-09-11). See
  `docs/research/A-odoo-terrain.md` §3/§9.
- The dev DB is disposable: `docker compose down -v` wipes it.
- P1.3 (JAOT contract): the sibling repo `../jaot` runs its own dev stack on
  5432/8001/3000 — no port conflicts with this stack.
