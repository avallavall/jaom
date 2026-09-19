# -*- coding: utf-8 -*-
# License LGPL-3
"""VRP formulation for the delivery-routing bridge (PLAN P3.2 / P3.4).

Framework-free (no Odoo) so it can be unit-tested with a plain snapshot and
driven by the base ``jaot.scenario`` lifecycle. Ported from the P1.4 spike
(``scripts/spike/spike_vrp.py`` ``build_problem``): arc-flow + MTZ vehicle
routing over haversine distance, node 0 = depot, nodes 1..n = orders.

The ``metadata`` block carries the per-record data needed by
``map_solution`` to turn a solved variable dict back into scenario lines
(which picking rides on which vehicle, at which route position).
"""
import math

from odoo.addons.jaot_base.jaot_formulations import (
    JaotFormulation,
    register,
)


@register
class Vrp(JaotFormulation):
    """Arc-flow + MTZ vehicle routing.

    Roles (set on the ``vrp`` recipe, see ``data/jaot_vrp_recipe.xml``):
      - ``depot_lat`` / ``depot_lng`` (number): the depot warehouse partner geo
      - ``order_lat`` / ``order_lng`` / ``order_demand``: per picking
      - ``vehicle`` (reference): the fleet (record set)
      - ``vehicle_capacity`` (parameter): constant kg bound (F1: no standard
        per-vehicle cargo field in Community)
    """

    recipe_code = 'vrp'
    _DEPOT_MODEL = 'stock.warehouse'
    _ORDER_MODEL = 'stock.picking'
    _VEHICLE_MODEL = 'fleet.vehicle'
    _VEHICLE_FIELD = 'jaot_vehicle_id'
    _SEQ_FIELD = 'jaot_route_sequence'

    # ------------------------------------------------------------------
    @staticmethod
    def _haversine_km(lat1, lon1, lat2, lon2):
        r = 6371.0
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
        a = (math.sin(dp / 2) ** 2
             + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
        return 2 * r * math.asin(math.sqrt(a))

    # ------------------------------------------------------------------
    def formulate(self, snapshot, config_meta):
        depot_recs = snapshot.get(self._DEPOT_MODEL, {})
        orders = snapshot.get(self._ORDER_MODEL, {})
        vehicles = snapshot.get(self._VEHICLE_MODEL, {})
        capacity = (snapshot.get('_parameters', {})
                    .get('vehicle_capacity'))
        if not depot_recs:
            raise ValueError('vrp: no depot (warehouse) extracted')
        if not orders:
            raise ValueError('vrp: no orders (pickings) extracted')
        if not vehicles:
            raise ValueError('vrp: no vehicles extracted')
        if capacity is None:
            raise ValueError('vrp: missing vehicle_capacity parameter')
        capacity = float(capacity)

        depot_res_id = min(depot_recs)
        depot = depot_recs[depot_res_id]
        depot_lat = float(depot.get('depot_lat'))
        depot_lng = float(depot.get('depot_lng'))

        order_ids = sorted(orders)
        n = len(order_ids)
        vehicle_ids = sorted(vehicles)
        n_veh = len(vehicle_ids)

        # node 0 = depot, nodes 1..n = orders in sorted res_id order
        nodes = [(depot_lat, depot_lng)] + [
            (float(orders[oid].get('order_lat')),
             float(orders[oid].get('order_lng')))
            for oid in order_ids]
        demands = [
            float(orders[oid].get('order_demand') or 0.0)
            for oid in order_ids]

        dist = [[0.0] * (n + 1) for _ in range(n + 1)]
        for i in range(n + 1):
            for j in range(n + 1):
                if i != j:
                    dist[i][j] = round(
                        self._haversine_km(*nodes[i], *nodes[j]), 4)

        variables, obj_terms, constraints = [], [], []
        for t in range(n_veh):
            for i in range(n + 1):
                for j in range(n + 1):
                    if i != j:
                        variables.append({
                            'name': f'x_{t}_{i}_{j}', 'type': 'binary',
                            'lower_bound': 0, 'upper_bound': 1})
                        obj_terms.append(f'{dist[i][j]}*x_{t}_{i}_{j}')
            for i in range(1, n + 1):
                variables.append({
                    'name': f'u_{t}_{i}', 'type': 'continuous',
                    'lower_bound': 1, 'upper_bound': n})
        for k in range(1, n + 1):  # each order visited exactly once
            terms = [f'x_{t}_{i}_{k}' for t in range(n_veh)
                     for i in range(n + 1) if i != k]
            constraints.append({
                'name': f'visit_{k}',
                'expression': ' + '.join(terms) + ' = 1'})
        for t in range(n_veh):
            for k in range(1, n + 1):  # per-truck flow conservation
                tin = [f'x_{t}_{i}_{k}' for i in range(n + 1) if i != k]
                tout = [f'x_{t}_{k}_{j}' for j in range(n + 1) if j != k]
                constraints.append({
                    'name': f'flow_{t}_{k}',
                    'expression': (' + '.join(tin) + ' - '
                                   + ' - '.join(tout) + ' = 0')})
            constraints.append({
                'name': f'depot_out_{t}',
                'expression': ' + '.join(
                    f'x_{t}_{0}_{j}' for j in range(1, n + 1)) + ' = 1'})
            constraints.append({
                'name': f'depot_in_{t}',
                'expression': ' + '.join(
                    f'x_{t}_{i}_{0}' for i in range(1, n + 1)) + ' = 1'})
            load = ' + '.join(
                f'{demands[k - 1]}*x_{t}_{i}_{k}'
                for k in range(1, n + 1) for i in range(n + 1) if i != k)
            constraints.append({
                'name': f'capacity_{t}',
                'expression': load + f' <= {capacity}'})
            for k in range(1, n + 1):  # MTZ subtour elimination
                for i in range(1, n + 1):
                    if i != k:
                        constraints.append({
                            'name': f'mtz_{t}_{k}_{i}',
                            'expression': (f'u_{t}_{k} - u_{t}_{i} '
                                           f'+ {n}*x_{t}_{k}_{i} <= {n - 1}')})

        # Baseline (SPECS 4.6 fix-all): a second scenario of the same recipe
        # in which every decision variable is pinned to the incumbent
        # (current) plan and re-solved. The incumbent comes from the
        # current_vehicle / current_sequence roles in the snapshot. Pinning
        # an unassigned order to no arc makes the re-solve infeasible, which
        # the scenario reports as a finding, not a failure.
        if config_meta.get('is_baseline'):
            vehicle_index = {vid: t for t, vid in enumerate(vehicle_ids)}
            tours = {}  # t -> [(position, node_index), ...]
            for idx, oid in enumerate(order_ids):
                o = orders[oid]
                cv = o.get('current_vehicle')
                cv_id = getattr(cv, 'id', cv)
                seq = o.get('current_sequence') or 0
                if cv_id is None or not seq:
                    continue
                t = vehicle_index.get(cv_id)
                if t is None:
                    continue
                tours.setdefault(t, []).append((int(seq), idx + 1))
            for t in range(n_veh):
                tour = [k for _pos, k in sorted(tours.get(t, []))]
                arc_nodes = [0] + tour + [0]
                tour_arcs = {(a, b)
                             for a, b in zip(arc_nodes, arc_nodes[1:])
                             if a != b}
                for i in range(n + 1):
                    for j in range(n + 1):
                        if i == j:
                            continue
                        pin = 1 if (i, j) in tour_arcs else 0
                        constraints.append({
                            'name': f'fix_{t}_{i}_{j}',
                            'expression': f'x_{t}_{i}_{j} = {pin}'})

        metadata = {
            'depot': {'res_id': depot_res_id,
                      'lat': depot_lat, 'lng': depot_lng},
            'orders': {
                str(oid): {
                    'lat': float(orders[oid].get('order_lat')),
                    'lng': float(orders[oid].get('order_lng')),
                    'demand': demands[idx],
                } for idx, oid in enumerate(order_ids)
            },
            'vehicles': list(vehicle_ids),
            'n_orders': n,
            'n_vehicles': n_veh,
            'total_demand_kg': round(sum(demands), 1),
            'order_model': self._ORDER_MODEL,
            'vehicle_field': self._VEHICLE_FIELD,
            'seq_field': self._SEQ_FIELD,
        }

        problem = {
            'name': 'jaom_vrp',
            'description': 'JAOM delivery routing: arc-flow + MTZ VRP',
            'variables': variables,
            'objective': {
                'sense': 'minimize',
                'expression': ' + '.join(obj_terms),
            },
            'constraints': constraints,
            'options': {
                'time_limit_seconds': config_meta.get(
                    'time_limit_seconds', 300),
                'gap_tolerance': config_meta.get('gap_tolerance', 0.05),
            },
            'metadata': metadata,
        }
        if config_meta.get('solver_name'):
            problem['solver_name'] = config_meta['solver_name']
        return problem

    # ------------------------------------------------------------------
    def map_solution(self, problem, model_values):
        meta = (problem.get('metadata', {}) or {})
        orders = meta.get('orders', {})
        vehicles = meta.get('vehicles', [])
        n = meta.get('n_orders', len(orders))
        n_veh = meta.get('n_vehicles', len(vehicles))
        order_model = meta.get('order_model', self._ORDER_MODEL)
        vehicle_field = meta.get('vehicle_field', self._VEHICLE_FIELD)
        seq_field = meta.get('seq_field', self._SEQ_FIELD)
        order_ids = sorted(orders, key=int)

        lines = []
        for t in range(n_veh):
            if t >= len(vehicles):
                break
            arcs = [(i, j) for i in range(n + 1) for j in range(n + 1)
                    if i != j and model_values.get(f'x_{t}_{i}_{j}')]
            # walk the route from the depot back to the depot
            seq, node, guard = [], 0, 0
            while guard <= n + 2:
                nxt = next((j for (i, j) in arcs if i == node), None)
                if nxt is None or nxt == 0:
                    break
                seq.append(nxt)
                node = nxt
                guard += 1
            for pos, k in enumerate(seq, start=1):
                oid = order_ids[k - 1]
                lines.append({
                    'res_model': order_model,
                    'res_id': int(oid),
                    'decision': {
                        vehicle_field: vehicles[t],
                        seq_field: pos,
                    },
                    'kpi_contribution': 0.0,
                })
        return lines
