"""P1.1 live metamodel smoke (PLAN.md P1.1, terrain note A §9).

Talks XML-RPC to the local Odoo 19 dev stack (dev/docker-compose.yml) as
admin/admin. Stdlib only — no third-party dependencies.

    python dev/odoo_smoke.py [--url http://127.0.0.1:8069] [--db odoo]

Checks (each printed PASS/FAIL; exit code 0 iff all pass):
  1. server answers and reports version 19.x
  2. stock / delivery are installed
  3. auto_install probe: PASS if jaot_probe is installed, SKIPPED once the
     P1.1 probe was removed (evidence: terrain note A §9)
  4. res.partner has partner_latitude / partner_longitude (float)
     (stored-ness already source-verified, terrain note §7)
  5. res.partner has NO x / y fields (gone from base in 19)
  6. stock.picking model exists
"""

import argparse
import sys
import xmlrpc.client


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://127.0.0.1:8069")
    ap.add_argument("--db", default="odoo")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="admin")
    a = ap.parse_args()

    try:
        common = xmlrpc.client.ServerProxy(a.url + "/xmlrpc/2/common")
        info = common.version()
    except Exception as e:
        print(f"FAIL  cannot reach Odoo at {a.url}: {e}")
        return 1

    ok = True
    failures = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal ok
        if not cond:
            ok = False
            failures.append(name)
        print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

    check("server version 19.x", info.get("server_version", "").startswith("19"),
          str(info.get("server_version")))

    try:
        uid = common.authenticate(a.db, a.user, a.password, {})
    except Exception as e:
        print(f"FAIL  authenticate: {e}")
        return 1
    check("authenticate as admin", bool(uid), f"uid={uid}")
    if not uid:
        return 1

    obj = xmlrpc.client.ServerProxy(a.url + "/xmlrpc/2/object")

    def kw(model: str, method: str, args: list, kwargs: dict | None = None):
        return obj.execute_kw(a.db, uid, a.password, model, method, args, kwargs or {})

    mods = {m["name"]: m["state"] for m in kw(
        "ir.module.module", "search_read",
        [[["name", "in", ["stock", "delivery", "jaot_probe", "base_geolocalize"]]],
         ["name", "state"]])}
    check("stock installed", mods.get("stock") == "installed", str(mods.get("stock")))
    check("delivery installed", mods.get("delivery") == "installed", str(mods.get("delivery")))
    # The P1.1 probe (jaot_probe) was a throwaway module that proved
    # auto_install fires live; it was removed (files + DB uninstall) after
    # the evidence was recorded (terrain note A §9). Uninstalling leaves
    # the ir.module.module row as "uninstalled", so both "absent" and
    # "uninstalled" mean "probe gone" -> skip; anything else is a surprise.
    probe_state = mods.get("jaot_probe")
    if probe_state in (None, "uninstalled"):
        print("[info] jaot_probe removed (P1.1 probe) — check skipped")
    else:
        check("jaot_probe installed (auto_install fired on stock)",
              probe_state == "installed", str(probe_state))
    print(f"[info] base_geolocalize state: {mods.get('base_geolocalize')}")

    fields = {f["name"]: f for f in kw(
        "ir.model.fields", "search_read",
        [[["model", "=", "res.partner"],
          ["name", "in", ["partner_latitude", "partner_longitude", "x", "y"]]],
         ["name", "ttype"]])}
    for fname in ("partner_latitude", "partner_longitude"):
        f = fields.get(fname)
        check(f"res.partner.{fname} is a float field",
              bool(f) and f.get("ttype") == "float", str(f))
    for fname in ("x", "y"):
        check(f"res.partner.{fname} is gone from base", fname not in fields)

    check("stock.picking model exists",
          bool(kw("ir.model", "search", [[["model", "=", "stock.picking"]]])))

    print()
    if ok:
        print("ALL PASS")
        return 0
    print(f"{len(failures)} FAILURE(S): {failures}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
