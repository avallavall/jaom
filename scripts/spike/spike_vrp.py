#!/usr/bin/env python3
"""P1.4 spike — Odoo -> JAOT delivery routing, end to end.

Standalone Python (stdlib only, no Odoo addon, no third-party packages):

  --seed    load the seeded synthetic routing dataset (vrp_data.py, the
            future P2.6 generator) into the local Odoo dev DB over
            XML-RPC;
  --run     EXTRACT the dataset following the P1.2 binding set (roles ->
            res_model + field_path + domain, incl. the per-record path
            resolver required by finding F2), BUILD the VRP as a JAOT
            OptimizationProblem (arc-flow + MTZ, constant vehicle
            capacity per F1), SUBMIT it to JAOT async, POLL, print the
            solution; then re-solve with EVERY decision variable fixed to
            that solution (the SPECS 4.6 baseline: fix-all re-solve) and
            print the comparison;
  --clean   remove the synthetic records again.

Configuration via environment:
  ODOO_URL (default http://127.0.0.1:8069), ODOO_DB (odoo),
  ODOO_USER (admin), ODOO_PASSWORD (admin),
  JAOT_API_KEY (required for --run), JAOT_BASE (default
  http://127.0.0.1:8001).
"""
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
import xmlrpc.client

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vrp_data  # noqa: E402  (the P2.6 generator, shared verbatim later)

ODOO_URL = os.environ.get("ODOO_URL", "http://127.0.0.1:8069")
ODOO_DB = os.environ.get("ODOO_DB", "odoo")
ODOO_USER = os.environ.get("ODOO_USER", "admin")
ODOO_PASS = os.environ.get("ODOO_PASSWORD", "admin")
JAOT_BASE = os.environ.get("JAOT_BASE", "http://127.0.0.1:8001").rstrip("/")
JAOT_KEY = os.environ.get("JAOT_API_KEY", "")

# ---------------------------------------------------------------------------
# The P1.2 binding set for the routing recipe (what P2.3 will store in
# jaot.binding rows). res_model + domain define the record set; field_path
# is evaluated per record through the path resolver (finding F2: Odoo 19
# read() does not resolve dotted paths natively).
# ---------------------------------------------------------------------------
B = vrp_data
_ORDER_DOMAIN = [
    ["name", "like", f"SPK{B.SEED:02d}-"],
    ["picking_type_code", "=", "outgoing"],
    ["state", "in", ("confirmed", "assigned")],
]
BINDINGS = {
    "depot": {
        "res_model": "stock.warehouse",
        "field_path": "partner_id.partner_latitude",
        "domain": [],
    },
    "orders": {"res_model": "stock.picking", "field_path": None,
               "domain": _ORDER_DOMAIN},
    "order_lat": {"res_model": "stock.picking",
                  "field_path": "partner_id.partner_latitude",
                  "domain": _ORDER_DOMAIN},
    "order_lng": {"res_model": "stock.picking",
                  "field_path": "partner_id.partner_longitude",
                  "domain": _ORDER_DOMAIN},
    "order_demand": {"res_model": "stock.picking",
                     "field_path": "shipping_weight",
                     "domain": _ORDER_DOMAIN},
    # fleet.vehicle.name is COMPUTED (brand/model/license_plate), so the
    # role keys on the writable license_plate instead.
    "vehicles": {"res_model": "fleet.vehicle", "field_path": None,
                 "domain": [["license_plate", "like", f"SPK{B.SEED:02d}-"],
                            ["active", "=", True]]},
    # F1: no standard cargo-capacity field -> constant parameter binding.
    "vehicle_capacity": {"res_model": None, "field_path": None,
                         "domain": None, "parameter": 1600.0},
    # P1.5: distance provider decision pending -> Euclidean placeholder.
    "distance_matrix": {"res_model": None, "field_path": None,
                        "domain": None, "provider": "euclidean"},
}

# ---------------------------------------------------------------------------
# Odoo XML-RPC
# ---------------------------------------------------------------------------
common = xmlrpc.client.ServerProxy(ODOO_URL + "/xmlrpc/2/common")
UID = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASS, {})
if not UID:
    sys.exit(f"Odoo authentication failed at {ODOO_URL} (db={ODOO_DB})")
OBJ = xmlrpc.client.ServerProxy(ODOO_URL + "/xmlrpc/2/object")


def kw(model, method, args, kwargs=None):
    return OBJ.execute_kw(ODOO_DB, UID, ODOO_PASS, model, method, args,
                          kwargs or {})


def upsert(model, name, values):
    """Create-or-write by unique `name`; returns the record id."""
    ids = kw(model, "search", [[["name", "=", name]]])
    if ids:
        kw(model, "write", [ids, values])
        return ids[0]
    return kw(model, "create", [[{**values, "name": name}]])[0]


def field_meta(model, field):
    """(comodel, ttype) of a field; exits if the field is unknown."""
    rows = kw("ir.model.fields", "search_read",
              [[["model", "=", model], ["name", "=", field]],
               ["relation", "ttype"]])
    if not rows:
        sys.exit(f"field {model}.{field} not found")
    return rows[0]["relation"], rows[0]["ttype"]


def resolve_path(model, rec_ids, field_path):
    """Finding F2, implemented: walk a dotted field path record-by-record.

    read() does not resolve dotted paths (verified live, P1.2 finding F2),
    so each hop is a separate read. The field that PRODUCED the current
    values determines their shape: many2one arrives as [id, name] pairs
    (res_ids); one2many/many2many as lists of child ids, which expand to
    one value list per record.
    """
    hops = field_path.split(".")
    rows = kw(model, "read", [rec_ids], {"fields": [hops[0]]})
    out = [r[hops[0]] for r in rows]
    cur, prev_ttype = model, None
    for idx, h in enumerate(hops):
        relation, ttype = field_meta(cur, h)
        if idx == 0:
            cur, prev_ttype = relation, ttype
            continue
        if prev_ttype == "many2one":
            ids = sorted({v[0] for v in out if v})
        else:
            ids = sorted({i for v in out for i in (v or [])})
        if not ids:
            return [None] * len(out)
        vals = {r["id"]: r[h]
                for r in kw(cur, "read", [ids],
                            {"fields": [h]})}
        out = [None if v is None else
               ([vals.get(i) for i in v] if prev_ttype != "many2one"
                else vals.get(v[0]))
               for v in out]
        cur, prev_ttype = relation, ttype
    return out


def extract():
    """Extract the routing dataset strictly through the binding set."""
    print("== extract (binding set, P1.2 semantics) ==")

    def recs(role):
        b = BINDINGS[role]
        return kw(b["res_model"], "search_read",
                  [b["domain"], ["id", "name"]], {"limit": 200})

    depot = recs("depot")
    if len(depot) != 1:
        sys.exit(f"depot role: expected 1 record, got {len(depot)}")
    wh = depot[0]
    partner_id = kw("stock.warehouse", "read", [[wh["id"]]],
                    {"fields": ["partner_id"]})[0]["partner_id"]
    # the depot binding is a two-hop path: resolve it through the resolver
    geo = resolve_path("stock.warehouse", [wh["id"]],
                       "partner_id.partner_latitude")
    geo_lng = resolve_path("stock.warehouse", [wh["id"]],
                           "partner_id.partner_longitude")
    if not geo[0] or not geo_lng[0]:
        sys.exit(f"depot {wh['name']}: partner {partner_id} has no geo")
    print(f"  depot: {wh['name']} -> partner {partner_id[1]} "
          f"({geo[0]:.6f}, {geo_lng[0]:.6f})")

    orders = recs("orders")
    oids = [o["id"] for o in orders]
    lat = resolve_path("stock.picking", oids, "partner_id.partner_latitude")
    lng = resolve_path("stock.picking", oids, "partner_id.partner_longitude")
    # demand: the stored shipping_weight (weight_bulk + package weights);
    # fallback to the sum of the move weights through the F2 path resolver
    # (move_ids is x2m, so the resolver returns a list per record).
    move_ws = {rid: ws for rid, ws in zip(oids,
                                          resolve_path("stock.picking",
                                                        oids,
                                                        "move_ids.weight"))}
    dem_rows = kw("stock.picking", "read", [oids],
                  {"fields": ["id", "name", "shipping_weight"]})
    dem = {}
    for r in dem_rows:
        w = r["shipping_weight"]
        if not w:
            w = sum(move_ws.get(r["id"]) or [0.0])
        dem[r["name"]] = w
    for o, a, l in zip(orders, lat, lng):
        if not a or not l or dem[o["name"]] <= 0:
            sys.exit(f"order {o['name']}: missing geo or demand "
                     f"(lat={a} lng={l} dem={dem[o['name']]})")
    print(f"  orders: {len(orders)} pickings, "
          f"total demand {sum(dem[o['name']] for o in orders):.1f} kg")

    vehicles = recs("vehicles")
    cap = BINDINGS["vehicle_capacity"]["parameter"]
    print(f"  vehicles: {len(vehicles)} (constant capacity {cap} kg — F1)")
    return {
        "depot": (geo[0], geo_lng[0]),
        "orders": [(o["name"], a, l, dem[o["name"]])
                   for o, a, l in zip(orders, lat, lng)],
        "vehicles": len(vehicles),
        "capacity": cap,
    }


# ---------------------------------------------------------------------------
# Jaot HTTP (contract per docs/research/C-jaot-contract.md)
# ---------------------------------------------------------------------------
def _req(method, path, body=None, timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(
        JAOT_BASE + "/api/v2" + path, data=data, method=method,
        headers={"Authorization": "Bearer " + JAOT_KEY,
                 "Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {}), \
                time.time() - t0
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw), time.time() - t0
        except Exception:
            return e.code, {"raw": raw[:300].decode(errors="replace")}, \
                time.time() - t0


def poll(task_id, cap_seconds=900, interval=3):
    t0 = time.time()
    while time.time() - t0 < cap_seconds:
        st, payload, _ = _req("GET", f"/solve/async/{task_id}")
        if st != 200:
            raise RuntimeError(f"poll HTTP {st}: {payload}")
        if payload.get("status") in ("completed", "failed", "infeasible",
                                     "cancelled", "error"):
            return payload
        time.sleep(interval)
    raise TimeoutError(f"task {task_id} not terminal in {cap_seconds}s")


# ---------------------------------------------------------------------------
# VRP -> OptimizationProblem  (arc-flow + MTZ; node 0 = depot)
# ---------------------------------------------------------------------------
def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2)
         * math.sin(dl / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def build_problem(data):
    """Arc-flow + MTZ VRP. x[t][i][j]: truck t travels i -> j (0 = depot)."""
    depot, orders, n_veh, cap = (data["depot"], data["orders"],
                                 data["vehicles"], data["capacity"])
    n = len(orders)
    nodes = [depot] + [(o[1], o[2]) for o in orders]
    dist = [[0.0] * (n + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        for j in range(n + 1):
            if i != j:
                dist[i][j] = round(haversine_km(*nodes[i], *nodes[j]), 4)

    variables, obj_terms, constraints = [], [], []
    for t in range(n_veh):
        for i in range(n + 1):
            for j in range(n + 1):
                if i != j:
                    variables.append({"name": f"x_{t}_{i}_{j}",
                                      "type": "binary", "lower_bound": 0,
                                      "upper_bound": 1})
                    obj_terms.append(f"{dist[i][j]}*x_{t}_{i}_{j}")
        for i in range(1, n + 1):
            variables.append({"name": f"u_{t}_{i}", "type": "continuous",
                              "lower_bound": 1, "upper_bound": n})
    for k in range(1, n + 1):  # each order visited exactly once (any truck)
        terms = [f"x_{t}_{i}_{k}" for t in range(n_veh)
                 for i in range(n + 1) if i != k]
        constraints.append({"name": f"visit_{k}",
                            "expression": " + ".join(terms) + " = 1"})
    for t in range(n_veh):
        for k in range(1, n + 1):  # per-truck flow conservation
            tin = [f"x_{t}_{i}_{k}" for i in range(n + 1) if i != k]
            tout = [f"x_{t}_{k}_{j}" for j in range(n + 1) if j != k]
            constraints.append({"name": f"flow_{t}_{k}",
                                "expression": (" + ".join(tin) + " - "
                                               + " - ".join(tout) + " = 0")})
        constraints.append({"name": f"depot_out_{t}",
                            "expression": " + ".join(
                                f"x_{t}_{0}_{j}" for j in range(1, n + 1))
                            + " = 1"})
        constraints.append({"name": f"depot_in_{t}",
                            "expression": " + ".join(
                                f"x_{t}_{i}_{0}" for i in range(1, n + 1))
                            + " = 1"})
        load = " + ".join(f"{orders[k - 1][3]}*x_{t}_{i}_{k}"
                          for k in range(1, n + 1)
                          for i in range(n + 1) if i != k)
        constraints.append({"name": f"capacity_{t}",
                            "expression": load + f" <= {cap}"})
        for k in range(1, n + 1):  # MTZ subtour elimination
            for i in range(1, n + 1):
                if i != k:
                    constraints.append({
                        "name": f"mtz_{t}_{k}_{i}",
                        "expression": (f"u_{t}_{k} - u_{t}_{i} "
                                       f"+ {n}*x_{t}_{k}_{i} <= {n - 1}")})
    problem = {
        "name": f"jaom_p14_vrp_seed{B.SEED}",
        "description": "P1.4 spike: arc-flow + MTZ VRP from Odoo bindings",
        "variables": variables,
        "objective": {"sense": "minimize",
                      "expression": " + ".join(obj_terms)},
        "constraints": constraints,
        "options": {"time_limit_seconds": 600, "gap_tolerance": 0.02},
        "metadata": {"n_orders": n, "n_vehicles": n_veh,
                     "total_demand_kg": round(sum(o[3] for o in orders), 1)},
    }
    return problem, dist, orders


def solve(problem, label, cap_seconds=900):
    st, body, dt = _req("POST", "/solve/async", problem, timeout=300)
    if st != 200:
        raise RuntimeError(f"{label}: enqueue HTTP {st}: {body}")
    print(f"[{label}] enqueued task={body['task_id'][:16]}… "
          f"exec={body['execution_id'][:16]}… ({dt * 1000:.0f} ms)")
    payload = poll(body["task_id"], cap_seconds)
    if payload.get("status") == "failed":
        raise RuntimeError(f"{label}: task failed: {payload.get('error')}")
    st, ex, _ = _req("GET", f"/models/executions/{body['execution_id']}")
    if st != 200:
        raise RuntimeError(f"{label}: execution HTTP {st}: {ex}")
    if ex.get("solver_status") == "infeasible":  # SPECS 4.6: a finding
        print(f"[{label}] INFEASIBLE (reported as a finding, per SPECS 4.6)")
        return None, ex
    res = ex["result_data"]
    print(f"[{label}] solver={ex['solver_name']} "
          f"solver_status={ex['solver_status']} "
          f"objective={res['objective_value']} "
          f"time_ms={ex['execution_time_ms']}")
    return res, ex


def main():
    if "--seed" in sys.argv:
        seed()
    if "--clean" in sys.argv:
        clean()
    if "--run" in sys.argv:
        if not JAOT_KEY:
            sys.exit("JAOT_API_KEY env var is required for --run")
        run()
    if len(sys.argv) == 1:
        print(__doc__)


def seed():
    """Load the synthetic dataset into the dev Odoo DB (idempotent)."""
    clean()
    ds = B.generate()
    wh = kw("stock.warehouse", "search_read",
            [[], ["id", "name", "partner_id", "lot_stock_id"]],
            {"limit": 1})[0]
    kw("res.partner", "write", [[wh["partner_id"][0]],
                                {"partner_latitude": ds["depot"]["lat"],
                                 "partner_longitude": ds["depot"]["lon"]}])
    print(f"depot: warehouse '{wh['name']}' — partner "
          f"{wh['partner_id']} geo set ({ds['depot']['lat']}, "
          f"{ds['depot']['lon']})")

    cust_loc = kw("stock.location", "search",
                  [[["usage", "=", "customer"]]], {"limit": 1})[0]
    out_type = kw("stock.picking.type", "search",
                  [[["code", "=", "outgoing"]]], {"limit": 1})[0]

    # stock.move.weight is COMPUTED from product.weight * qty (readonly),
    # so the line weight rides on a per-line product with
    # weight = weight_kg / qty. One product per line keeps the per-order
    # demand exact (Odoo merges same-product moves into one move line).
    n_lines = 0
    for o in ds["orders"]:
        pid = upsert("res.partner", o["partner_name"],
                     {"partner_latitude": o["lat"],
                      "partner_longitude": o["lon"], "is_company": False})
        moves = []
        for i, l in enumerate(o["lines"], start=1):
            prod = upsert("product.product",
                          f"Spike Line {o['name']}-{i}",
                          {"type": "consu", "is_storable": False,
                           "weight": l["weight_kg"] / l["qty"]})
            moves.append([0, 0, {"product_id": prod,
                                 "product_uom_qty": l["qty"],
                                 "quantity": 0.0,
                                 "location_id": wh["lot_stock_id"][0],
                                 "location_dest_id": cust_loc}])
        kw("stock.picking", "create", [[{
            "origin": "jaom spike",
            "name": o["name"],
            "partner_id": pid,
            "picking_type_id": out_type,
            "location_id": wh["lot_stock_id"][0],
            "location_dest_id": cust_loc,
            "move_ids": moves,
        }]])
        n_lines += len(o["lines"])

    # brand_id is a Many2one to fleet.vehicle.model.brand (NOT res.partner)
    brand = upsert("fleet.vehicle.model.brand", "Spike Auto", {})
    fleet_model = upsert("fleet.vehicle.model", "Spike Truck Model",
                         {"brand_id": brand})
    # fleet.vehicle.name is a computed field (brand/model/license_plate),
    # so identity comes from the writable license_plate.
    for i in range(1, len(ds["vehicles"]) + 1):
        plate = f"SPK{B.SEED:02d}-V{i}"
        ids = kw("fleet.vehicle", "search",
                 [[["license_plate", "=", plate]]])
        if ids:
            kw("fleet.vehicle", "write", [ids,
                                          {"model_id": fleet_model,
                                           "active": True}])
        else:
            kw("fleet.vehicle", "create",
               [[{"model_id": fleet_model, "license_plate": plate}]])

    pids = kw("stock.picking", "search",
              [[["name", "like", f"SPK{B.SEED:02d}-"]]])
    kw("stock.picking", "action_confirm", [pids])
    states = kw("stock.picking", "search_read",
                [[["name", "like", f"SPK{B.SEED:02d}-"]], ["id", "state"]],
                {"limit": 100})
    bad = [s["id"] for s in states if s["state"] not in
           ("confirmed", "assigned")]
    if bad:
        sys.exit(f"pickings not confirmed: {bad}")
    print(f"seeded: {len(ds['orders'])} pickings / {n_lines} lines, "
          f"{len(ds['vehicles'])} vehicles, "
          f"total demand {ds['total_demand_kg']} kg")


def clean():
    like = f"SPK{B.SEED:02d}-"
    # deletion order respects FKs: vehicles -> models -> brand
    targets = [
        ("stock.picking", [["name", "like", like]]),
        ("res.partner", [["name", "like", "Spike Customer"]]),
        ("fleet.vehicle", [["license_plate", "like", f"SPK{B.SEED:02d}-"]]),
        ("fleet.vehicle.model", [["name", "=", "Spike Truck Model"]]),
        ("fleet.vehicle.model.brand", [["name", "=", "Spike Auto"]]),
        ("product.product", [["name", "like", "Spike Line"]]),
    ]
    for model, domain in targets:
        ids = kw(model, "search", [domain])
        if ids:
            kw(model, "unlink", [ids])
            print(f"cleaned {model}: {len(ids)}")


def run():
    data = extract()
    problem, dist, orders = build_problem(data)
    payload_kb = len(json.dumps(problem)) // 1024
    print(f"problem: {len(problem['variables'])} variables, "
          f"{len(problem['constraints'])} constraints, "
          f"payload {payload_kb} KB")

    res, _ex = solve(problem, "solve")
    if res is None:
        sys.exit("infeasible — see finding above")
    model = res["model"]
    n = len(orders)

    # per-truck tours, loads, distances
    trucks = sorted({k.split("_")[1] for k, v in model.items()
                     if k.startswith("x_") and v == 1}, key=int)
    total_km = 0.0
    for t in trucks:
        arcs = [(i, j) for i in range(n + 1) for j in range(n + 1)
                if i != j and model.get(f"x_{t}_{i}_{j}") == 1]
        seq, node, guard = [], None, 0
        start = next((j for (i, j) in arcs if i == 0), None)
        node, guard = start, 0
        while node is not None and node != 0 and guard < n + 2:
            seq.append(node)
            node = next((j for (i, j) in arcs if i == node), None)
            guard += 1
        names = [orders[k - 1][0] for k in seq]
        load = sum(orders[k - 1][3] for k in seq)
        d = sum(dist[i][j] for (i, j) in arcs)
        total_km += d
        print(f"  truck {t}: {len(seq)} stops, load {load:.1f} kg, "
              f"{d:.1f} km: depot -> " + " -> ".join(names) + " -> depot")
    print(f"solution: objective {res['objective_value']} "
          f"(total {total_km:.1f} km, gap {res.get('gap')}, "
          f"nodes={res.get('nodes')}, iterations={res.get('iterations')})")

    # --- SPECS 4.6 baseline: fix EVERY decision variable, re-solve -------
    print("\n== baseline (fix-all-variables re-solve, SPECS 4.6) ==")
    fix_cons = [{"name": f"fix_{v['name']}",
                 "expression": f"{v['name']} = {1 if model.get(v['name']) else 0}"}
                for v in problem["variables"] if v["name"].startswith("x_")]
    fixed = {**problem, "name": problem["name"] + "_baseline_fixed",
             "constraints": problem["constraints"] + fix_cons}
    fres, _fex = solve(fixed, "baseline")
    if fres is None:
        print("baseline infeasible (finding per SPECS 4.6)")
        sys.exit(1)
    d = (fres["objective_value"] or 0) - (res["objective_value"] or 0)
    ok = abs(d) < 1e-6
    print(f"baseline objective {fres['objective_value']} vs solution "
          f"{res['objective_value']} -> delta {d:+.6f} "
          f"({'MATCH' if ok else 'MISMATCH'})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
