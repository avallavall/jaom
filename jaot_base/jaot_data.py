# -*- coding: utf-8 -*-
# License LGPL-3
"""Seeded synthetic datasets for the base module's fast tests (PLAN P2.6).

Framework-free (no Odoo, no network): plain dicts, deterministic per seed,
so the same generator drives the P2.8 gate and the P2.7 test suite.

The routing dataset below is the canonical copy used by the addon (P3 E2E
test, P5.1). A byte-identical copy lives in ``scripts/spike/vrp_data.py``
for the standalone stdlib-only P1.4 spike, which cannot import this addon
without pulling in Odoo. Keep the two identical; the spike's P1.5 gate
evidence was produced from the seed-42 output.
"""
import random

KNAPSACK_SEED = 7
KNAPSACK_CAPACITY = 50.0

# Routing dataset constants (must match scripts/spike/vrp_data.py).
ROUTING_SEED = 42
ROUTING_N_ORDERS = 50
ROUTING_LINES_PER_ORDER = 4  # 50 * 4 = 200 order lines
ROUTING_VEHICLES = [
    {"name": "Spike Vehicle 1", "capacity_kg": 1600.0},
    {"name": "Spike Vehicle 2", "capacity_kg": 1600.0},
    {"name": "Spike Vehicle 3", "capacity_kg": 1600.0},
    {"name": "Spike Vehicle 4", "capacity_kg": 1600.0},
]
_ROUTING_REF_LAT = 40.4168
_ROUTING_REF_LON = -3.7038
_ROUTING_SPREAD = 0.07  # degrees, ~8 km at this latitude


def generate_knapsack(seed=KNAPSACK_SEED, n_items=5,
                      capacity=KNAPSACK_CAPACITY):
    """Return ``{'capacity': float, 'items': [{'name','weight','value'}]}``.

    Every item weighs at most 20 kg (well under the default 50 kg capacity),
    so a non-empty feasible selection always exists and the greedy stand-in
    in the tests picks a deterministic subset.
    """
    rng = random.Random(seed)
    items = []
    for i in range(1, n_items + 1):
        weight = round(rng.uniform(5.0, 20.0), 1)
        value = round(weight * rng.uniform(2.5, 4.0), 1)
        items.append({
            'name': 'KAP-%02d' % i,
            'weight': weight,
            'value': value,
        })
    return {'capacity': capacity, 'items': items}


def _routing_geo(rng):
    return (_ROUTING_REF_LAT + rng.uniform(-_ROUTING_SPREAD, _ROUTING_SPREAD),
            _ROUTING_REF_LON + rng.uniform(-_ROUTING_SPREAD, _ROUTING_SPREAD))


def generate_routing(seed=ROUTING_SEED, n_orders=ROUTING_N_ORDERS,
                     lines_per_order=ROUTING_LINES_PER_ORDER):
    """Return ``{'depot':…, 'vehicles': […], 'orders': […],
    'total_demand_kg': float}`` (plain dicts).

    One depot with geo, vehicles with a load capacity (a constant parameter
    — standard Odoo 19 has no per-vehicle cargo field, P1.2 finding F1),
    ``n_orders`` delivery orders with ``lines_per_order`` order lines each,
    partner geo and weight. Byte-identical to ``scripts/spike/vrp_data.py``.
    """
    rng = random.Random(seed)
    depot = {
        "name": "Spike Depot",
        "lat": _ROUTING_REF_LAT,
        "lon": _ROUTING_REF_LON,
    }
    vehicles = [dict(v) for v in ROUTING_VEHICLES]
    orders = []
    for i in range(1, n_orders + 1):
        lat, lon = _routing_geo(rng)
        demand = round(rng.uniform(40.0, 160.0), 1)
        lines = []
        for j in range(1, lines_per_order + 1):
            w = round(demand / lines_per_order
                      * rng.uniform(0.7, 1.3), 1)
            lines.append({
                "name": f"Line {i}-{j}",
                "qty": float(rng.randint(1, 5)),
                "weight_kg": w,
            })
        demand = round(sum(l["weight_kg"] for l in lines), 1)
        orders.append({
            "name": f"SPK{seed:02d}-{i:03d}",
            "partner_name": f"Spike Customer {i:03d}",
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "demand_kg": demand,
            "lines": lines,
        })
    total = sum(o["demand_kg"] for o in orders)
    cap = sum(v["capacity_kg"] for v in vehicles)
    if total > cap:
        raise ValueError(
            f"dataset infeasible: total demand {total} kg > fleet capacity "
            f"{cap} kg — tune ROUTING_VEHICLES or n_orders")
    return {
        "depot": depot,
        "vehicles": vehicles,
        "orders": orders,
        "total_demand_kg": total,
    }


# P5.1 / P5.3: realistic and stress datasets. These are additive — the
# seed-42 routing set above stays byte-frozen for the P1.4 spike.

def generate_routing_multi(seed=43, n_companies=2, orders_per_company=20,
                           depots_per_company=1, tight=True,
                           lines_per_order=4):
    """Multi-company, multi-depot routing dataset with an optional tight
    fleet (P5.1). Returns ``{'companies': [{'company','depots','vehicles',
    'orders','total_demand_kg'}]}`` as plain dicts, deterministic per seed.

    With ``tight`` the fleet capacity is scaled to ~95% of each company's
    demand, so the instance is feasible but close to the limit (the case the
    gate and P5.3 want to stress). Each company is geo-separated so a
    cross-company leak is detectable in the security tests (P5.2).
    """
    rng = random.Random(seed)
    companies = []
    for c in range(n_companies):
        lat0 = _ROUTING_REF_LAT + c * 2.0
        lon0 = _ROUTING_REF_LON + c * 2.0
        depots = [{
            "name": f"C{c}D{d}",
            "lat": round(lat0 + rng.uniform(-0.5, 0.5), 6),
            "lon": round(lon0 + rng.uniform(-0.5, 0.5), 6),
        } for d in range(depots_per_company)]
        orders = []
        for i in range(1, orders_per_company + 1):
            lat, lon = (lat0 + rng.uniform(-0.5, 0.5),
                        lon0 + rng.uniform(-0.5, 0.5))
            demand = round(rng.uniform(40.0, 160.0), 1)
            lines = [{
                "name": f"Line {i}-{j}",
                "qty": float(rng.randint(1, 5)),
                "weight_kg": round(demand / lines_per_order
                                   * rng.uniform(0.7, 1.3), 1),
            } for j in range(1, lines_per_order + 1)]
            demand = round(sum(l["weight_kg"] for l in lines), 1)
            orders.append({
                "name": f"MC{c}-{i:03d}",
                "partner_name": f"MC Customer {c}-{i:03d}",
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "demand_kg": demand,
                "lines": lines,
            })
        total = sum(o["demand_kg"] for o in orders)
        n_vehicles = max(2, int(round(total / 1600.0)) + (0 if tight else 1))
        if tight:
            per_vehicle = max(1.0, round(total * 0.95 / n_vehicles, 1))
            vehicles = [{"name": f"C{c}V{k}", "capacity_kg": per_vehicle}
                        for k in range(n_vehicles)]
        else:
            vehicles = [{"name": f"C{c}V{k}", "capacity_kg": 1600.0}
                        for k in range(n_vehicles)]
        companies.append({
            "company": f"Company {c + 1}",
            "depots": depots,
            "vehicles": vehicles,
            "orders": orders,
            "total_demand_kg": total,
        })
    return {"companies": companies}


def generate_routing_stress(seed=44, n_orders=50000, lines_per_order=4):
    """Large single-company dataset (default 50 k orders) for the P5.3
    extraction benchmark. Plain dicts, deterministic per seed."""
    rng = random.Random(seed)
    depot = {"name": "Stress Depot",
             "lat": _ROUTING_REF_LAT, "lon": _ROUTING_REF_LON}
    orders = []
    for i in range(1, n_orders + 1):
        lat, lon = _routing_geo(rng)
        demand = round(rng.uniform(40.0, 160.0), 1)
        lines = [{
            "name": f"Line {i}-{j}",
            "qty": float(rng.randint(1, 5)),
            "weight_kg": round(demand / lines_per_order
                               * rng.uniform(0.7, 1.3), 1),
        } for j in range(1, lines_per_order + 1)]
        demand = round(sum(l["weight_kg"] for l in lines), 1)
        orders.append({
            "name": f"STR-{i:05d}",
            "partner_name": f"Stress Customer {i:05d}",
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "demand_kg": demand,
            "lines": lines,
        })
    total = sum(o["demand_kg"] for o in orders)
    return {"depot": depot, "orders": orders, "total_demand_kg": total}
