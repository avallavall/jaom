#!/usr/bin/env python3
"""Metamodel probe for JAOM research (P1.2+).

Queries the live dev Odoo over XML-RPC and prints module states or the
field list of a model, so that research notes can quote evidence that was
actually run, and the same check stays reproducible in later sessions.

Odoo 19 note: ir.model.fields has no 'string' or 'stored' column — query
'name', 'ttype', 'relation' only.

Usage:
  python dev/metamodel_probe.py --module fleet
  python dev/metamodel_probe.py --model fleet.vehicle
  python dev/metamodel_probe.py --models stock.picking,stock.move

Stdlib only (same constraints as odoo_smoke.py).
"""
import argparse
import sys
import xmlrpc.client

URL = "http://127.0.0.1:8069"
DB = "odoo"
USER = "admin"
PASSWORD = "admin"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=URL)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--user", default=USER)
    ap.add_argument("--password", default=PASSWORD)
    ap.add_argument("--module", help="comma list of module names to check")
    ap.add_argument("--models", help="comma list of models to dump fields for")
    a = ap.parse_args()
    if not (a.module or a.models):
        ap.error("give --module and/or --models")

    common = xmlrpc.client.ServerProxy(a.url + "/xmlrpc/2/common")
    uid = common.authenticate(a.db, a.user, a.password, {})
    if not uid:
        print("[FAIL] authentication", file=sys.stderr)
        return 1

    obj = xmlrpc.client.ServerProxy(a.url + "/xmlrpc/2/object")

    def kw(model, method, args, kwargs=None):
        return obj.execute_kw(
            a.db, uid, a.password, model, method, args, kwargs or {}
        )

    if a.module:
        for name in a.module.split(","):
            rows = kw(
                "ir.module.module",
                "search_read",
                [[["name", "=", name]], ["name", "state", "latest_version"]],
            )
            if not rows:
                print(f"module {name}: NOT FOUND in the registry")
            for r in rows:
                print(
                    f"module {r['name']}: state={r['state']} "
                    f"latest_version={r['latest_version']}"
                )
    if a.models:
        for name in a.models.split(","):
            fields = kw(
                "ir.model.fields",
                "search_read",
                [[["model", "=", name]], ["name", "ttype", "relation"]],
            )
            if not fields:
                print(f"== {name}: model NOT FOUND in the registry ==")
                continue
            fields.sort(key=lambda f: f["name"])
            print(f"== {name} ({len(fields)} fields) ==")
            for f in fields:
                rel = f" -> {f['relation']}" if f["relation"] else ""
                print(f"  {f['name']:<34} {f['ttype']:<10}{rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
