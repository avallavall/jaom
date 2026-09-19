"""Seeded synthetic routing dataset — PLAN P2.6 (used by the P1.4 spike).

Pure data, no Odoo or network dependency: returns plain dicts so the same
code can be loaded through XML-RPC (spike) and later reused verbatim by the
addon's test suite (P2.6: "keep the generator identical in both places").

Dataset (SPECS routing domain): one depot with geo, vehicles with a load
capacity (a constant parameter — standard Odoo 19 has no per-vehicle cargo
field, P1.2 finding F1), ~50 delivery orders / ~200 order lines with partner
geo and weight.
"""
import random

SEED = 42
N_ORDERS = 50
LINES_PER_ORDER = 4  # 50 * 4 = 200 order lines
VEHICLES = [
    {"name": "Spike Vehicle 1", "capacity_kg": 1600.0},
    {"name": "Spike Vehicle 2", "capacity_kg": 1600.0},
    {"name": "Spike Vehicle 3", "capacity_kg": 1600.0},
    {"name": "Spike Vehicle 4", "capacity_kg": 1600.0},
]

# A city-centre reference point (Madrid) and a spread of ~8 km.
_REF_LAT = 40.4168
_REF_LON = -3.7038
_SPREAD = 0.07  # degrees, ~8 km at this latitude


def _geo(rng):
    return (_REF_LAT + rng.uniform(-_SPREAD, _SPREAD),
            _REF_LON + rng.uniform(-_SPREAD, _SPREAD))


def generate(seed=SEED):
    """Return {'depot':…, 'vehicles': […], 'orders': […]} (plain dicts)."""
    rng = random.Random(seed)
    depot = {
        "name": "Spike Depot",
        "lat": _REF_LAT,
        "lon": _REF_LON,
    }
    orders = []
    for i in range(1, N_ORDERS + 1):
        lat, lon = _geo(rng)
        demand = round(rng.uniform(40.0, 160.0), 1)
        lines = []
        for j in range(1, LINES_PER_ORDER + 1):
            w = round(demand / LINES_PER_ORDER * rng.uniform(0.7, 1.3), 1)
            lines.append({
                "name": f"Line {i}-{j}",
                "qty": float(rng.randint(1, 5)),
                "weight_kg": w,
            })
        # keep the per-order demand equal to the sum of its line weights
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
    cap = sum(v["capacity_kg"] for v in VEHICLES)
    if total > cap:
        raise ValueError(
            f"dataset infeasible: total demand {total} kg > fleet capacity "
            f"{cap} kg — tune VEHICLES or N_ORDERS")
    return {
        "depot": depot,
        "vehicles": list(VEHICLES),
        "orders": orders,
        "total_demand_kg": total,
    }
