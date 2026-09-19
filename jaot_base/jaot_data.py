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
