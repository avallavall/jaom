# -*- coding: utf-8 -*-
# License LGPL-3
"""Offline tests for the VRP formulation (PLAN P3.4).

Driven with a plain snapshot dict (the shape
``jaot.scenario._extract_snapshot`` produces) — no Odoo, no network.
"""
from odoo.tests import TransactionCase

from ..jaot_vrp_formulation import Vrp


def _snapshot():
    return {
        'stock.warehouse': {
            10: {'depot_lat': 40.40, 'depot_lng': -3.70},
        },
        'stock.picking': {
            1: {'order_lat': 40.41, 'order_lng': -3.71,
               'order_demand': 10.0},
            2: {'order_lat': 40.42, 'order_lng': -3.72,
               'order_demand': 20.0},
            3: {'order_lat': 40.43, 'order_lng': -3.73,
               'order_demand': 5.0},
        },
        'fleet.vehicle': {100: {'vehicle': 100}},
        '_parameters': {'vehicle_capacity': 1600.0},
    }


def _snapshot_baseline():
    """A snapshot whose orders carry an incumbent plan (current_vehicle /
    current_sequence): all three orders on vehicle 100, positions 1, 2, 3
    (a single tour depot -> 1 -> 2 -> 3 -> depot)."""
    snap = _snapshot()
    snap['stock.picking'] = {
        1: {'order_lat': 40.41, 'order_lng': -3.71, 'order_demand': 10.0,
            'current_vehicle': 100, 'current_sequence': 1},
        2: {'order_lat': 40.42, 'order_lng': -3.72, 'order_demand': 20.0,
            'current_vehicle': 100, 'current_sequence': 2},
        3: {'order_lat': 40.43, 'order_lng': -3.73, 'order_demand': 5.0,
            'current_vehicle': 100, 'current_sequence': 3},
    }
    return snap


class TestVrpFormulation(TransactionCase):

    def test_formulate_shape(self):
        problem = Vrp().formulate(_snapshot(), {})
        self.assertEqual(problem['objective']['sense'], 'minimize')
        names = [v['name'] for v in problem['variables']]
        # 1 vehicle: x arcs (4 nodes, no self) = 12, u potentials = 3
        self.assertEqual(len([n for n in names if n.startswith('x_')]), 12)
        self.assertEqual(len([n for n in names if n.startswith('u_')]), 3)
        meta = problem['metadata']
        self.assertEqual(meta['n_orders'], 3)
        self.assertEqual(meta['n_vehicles'], 1)
        self.assertEqual(meta['vehicles'], [100])
        self.assertEqual(meta['depot']['res_id'], 10)
        self.assertEqual(set(meta['orders']), {'1', '2', '3'})
        # one visit constraint per order
        visits = [c for c in problem['constraints']
                  if c['name'].startswith('visit_')]
        self.assertEqual(len(visits), 3)

    def test_formulate_requires_orders(self):
        snap = _snapshot()
        snap['stock.picking'] = {}
        with self.assertRaises(ValueError):
            Vrp().formulate(snap, {})

    def test_formulate_requires_capacity(self):
        snap = _snapshot()
        del snap['_parameters']['vehicle_capacity']
        with self.assertRaises(ValueError):
            Vrp().formulate(snap, {})

    def test_map_solution_single_tour(self):
        problem = Vrp().formulate(_snapshot(), {})
        # one vehicle, route depot -> 1 -> 2 -> 3 -> depot
        model_values = {
            'x_0_0_1': 1, 'x_0_1_2': 1, 'x_0_2_3': 1, 'x_0_3_0': 1,
            'u_0_1': 1, 'u_0_2': 2, 'u_0_3': 3,
        }
        lines = Vrp().map_solution(problem, model_values)
        by_id = {l['res_id']: l for l in lines}
        self.assertEqual(set(by_id), {1, 2, 3})
        self.assertEqual(by_id[1]['decision'],
                         {'jaot_vehicle_id': 100, 'jaot_route_sequence': 1})
        self.assertEqual(by_id[2]['decision'],
                         {'jaot_vehicle_id': 100, 'jaot_route_sequence': 2})
        self.assertEqual(by_id[3]['decision'],
                         {'jaot_vehicle_id': 100, 'jaot_route_sequence': 3})
        self.assertTrue(all(l['res_model'] == 'stock.picking'
                            for l in lines))

    def test_baseline_fixes_current_plan(self):
        problem = Vrp().formulate(_snapshot_baseline(), {'is_baseline': True})
        fixes = [c for c in problem['constraints']
                 if c['name'].startswith('fix_')]
        self.assertTrue(fixes)
        # rebuild the pinned x variables and map them back to lines
        model_values = {}
        for c in fixes:
            var, val = c['expression'].split(' = ')
            model_values[var] = int(val)
        lines = Vrp().map_solution(problem, model_values)
        by_id = {l['res_id']: l for l in lines}
        # every order keeps its incumbent vehicle and route position
        self.assertEqual(by_id[1]['decision'],
                         {'jaot_vehicle_id': 100, 'jaot_route_sequence': 1})
        self.assertEqual(by_id[2]['decision'],
                         {'jaot_vehicle_id': 100, 'jaot_route_sequence': 2})
        self.assertEqual(by_id[3]['decision'],
                         {'jaot_vehicle_id': 100, 'jaot_route_sequence': 3})

    def test_baseline_infeasible_when_unassigned(self):
        snap = _snapshot_baseline()
        del snap['stock.picking'][3]['current_vehicle']  # order 3 has no plan
        problem = Vrp().formulate(snap, {'is_baseline': True})
        # no arc pinned to 1 points into node 3, so visit_3 is unsatisfiable
        visited = set()
        for c in problem['constraints']:
            if (c['name'].startswith('fix_')
                    and c['expression'].endswith('= 1')):
                visited.add(int(c['expression'].split(' = ')[0].split('_')[3]))
        self.assertNotIn(3, visited)

    # -- plan explanation (SPECS 13.1) ------------------------------------
    def test_explain_objective_terms(self):
        problem = Vrp().formulate(_snapshot(), {})
        f = Vrp()
        model_values = {
            'x_0_0_1': 1, 'x_0_1_2': 1, 'x_0_2_3': 1, 'x_0_3_0': 1,
        }
        terms = f.explain_objective(problem, model_values)
        # one vehicle -> one named term, the tour length (4-decimal
        # rounding, the same one the objective expression uses)
        self.assertEqual(len(terms), 1)
        self.assertEqual(terms[0]['name'], 'Vehicle 1')
        expected = (
            round(f._haversine_km(40.40, -3.70, 40.41, -3.71), 4)
            + round(f._haversine_km(40.41, -3.71, 40.42, -3.72), 4)
            + round(f._haversine_km(40.42, -3.72, 40.43, -3.73), 4)
            + round(f._haversine_km(40.43, -3.73, 40.40, -3.70), 4)
        )
        self.assertAlmostEqual(terms[0]['value'], expected, places=6)
        # the vehicle's display name is used when available
        names = {('fleet.vehicle', 100): 'Van 1'}
        terms = f.explain_objective(problem, model_values, names)
        self.assertEqual(terms[0]['name'], 'Vehicle Van 1')

    def test_explain_constraint_labels(self):
        problem = Vrp().formulate(_snapshot(), {})
        f = Vrp()
        names = {
            ('stock.picking', 1): 'PICK0001',
            ('fleet.vehicle', 100): 'Van 1',
        }
        self.assertEqual(
            f.explain_constraint('visit_1', problem, names),
            'Picking PICK0001 must be visited exactly once')
        self.assertEqual(
            f.explain_constraint('capacity_0', problem, names),
            'Vehicle Van 1 is at its load limit')
        # no display names -> the generic labels, still plain language
        self.assertEqual(
            f.explain_constraint('visit_2', problem, None),
            'A picking must be visited exactly once')
        self.assertEqual(
            f.explain_constraint('capacity_0', problem, None),
            'Vehicle 1 is at its load limit')
        # structural constraints stay invisible
        self.assertIsNone(f.explain_constraint('flow_0_1', problem, names))
        self.assertIsNone(f.explain_constraint('mtz_0_1_2', problem, names))
        self.assertIsNone(f.explain_constraint('depot_out_0', problem, names))
        # out-of-range / unknown machine names degrade to None
        self.assertIsNone(f.explain_constraint('visit_0', problem, names))
        self.assertIsNone(f.explain_constraint('visit_9', problem, names))
        self.assertIsNone(f.explain_constraint('capacity_3', problem, names))
