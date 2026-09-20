# -*- coding: utf-8 -*-
# License LGPL-3
"""Offline tests for the lot-sizing formulation (PLAN P6.1).

Driven with a plain snapshot dict (the shape
``jaot.scenario._extract_snapshot`` produces) — no Odoo data, no network.
"""
from odoo.tests import TransactionCase

from ..jaot_mrp_formulation import MrpLotSizing


def _snapshot():
    return {
        'mrp.production': {
            1: {'order_qty': 100.0, 'order_due': '2026-10-05 17:00:00'},
            2: {'order_qty': 100.0, 'order_due': '2026-10-05 17:00:00'},
            3: {'order_qty': 150.0, 'order_due': '2026-10-06 17:00:00'},
            4: {'order_qty': 150.0, 'order_due': '2026-10-06 17:00:00'},
        },
        '_parameters': {
            'resource_capacity': 800.0,
            'setup_cost': 250.0,
            'holding_cost': 0.5,
        },
    }


def _snapshot_baseline():
    """A snapshot whose orders carry an incumbent plan: every order starts
    on the first date (2026-10-05), so orders 3 and 4 are held one day."""
    snap = _snapshot()
    snap['mrp.production'] = {
        1: {'order_qty': 100.0, 'order_due': '2026-10-05 17:00:00',
            'current_start': '2026-10-05 06:00:00'},
        2: {'order_qty': 100.0, 'order_due': '2026-10-05 17:00:00',
            'current_start': '2026-10-05 06:00:00'},
        3: {'order_qty': 150.0, 'order_due': '2026-10-06 17:00:00',
            'current_start': '2026-10-05 06:00:00'},
        4: {'order_qty': 150.0, 'order_due': '2026-10-06 17:00:00',
            'current_start': '2026-10-05 06:00:00'},
    }
    return snap


class TestMrpFormulation(TransactionCase):

    def test_formulate_shape(self):
        problem = MrpLotSizing().formulate(_snapshot(), {})
        self.assertEqual(problem['objective']['sense'], 'minimize')
        names = [v['name'] for v in problem['variables']]
        # days = [2026-10-05, 2026-10-06]
        # x/q: orders 1,2 due day 1 (1 day each); 3,4 due day 2 (2 days)
        self.assertEqual(len([n for n in names if n.startswith('x_')]), 6)
        self.assertEqual(len([n for n in names if n.startswith('q_')]), 6)
        self.assertEqual(len([n for n in names if n.startswith('i_')]), 2)
        meta = problem['metadata']
        self.assertEqual(meta['days'], ['2026-10-05', '2026-10-06'])
        self.assertEqual(meta['n_orders'], 4)
        self.assertEqual(meta['orders']['3'],
                         {'qty': 150.0, 'due_day': 2, 'start_day': None})
        by_name = {c['name']: c for c in problem['constraints']}
        # one delivery per order, one balance per pre-deadline day,
        # one link per (order, day), one capacity per day
        self.assertEqual(
            len([n for n in by_name if n.startswith('deliver_')]), 4)
        self.assertEqual(
            len([n for n in by_name if n.startswith('bal_')]), 2)
        self.assertEqual(
            len([n for n in by_name if n.startswith('link_')]), 6)
        self.assertEqual(
            len([n for n in by_name if n.startswith('cap_')]), 2)
        self.assertEqual(by_name['cap_1']['expression'],
                         'q_1_1 + q_2_1 + q_3_1 + q_4_1 <= 800.0')
        self.assertEqual(by_name['cap_2']['expression'],
                         'q_3_2 + q_4_2 <= 800.0')
        self.assertEqual(by_name['deliver_3']['expression'],
                         'i_3_1 + q_3_2 = 150.0')

    def test_formulate_requires_orders(self):
        snap = _snapshot()
        snap['mrp.production'] = {}
        with self.assertRaises(ValueError):
            MrpLotSizing().formulate(snap, {})

    def test_formulate_requires_parameters(self):
        for param in ('resource_capacity', 'setup_cost', 'holding_cost'):
            snap = _snapshot()
            del snap['_parameters'][param]
            with self.assertRaises(ValueError):
                MrpLotSizing().formulate(snap, {})

    def test_map_solution(self):
        problem = MrpLotSizing().formulate(_snapshot(), {})
        # each order produced on its deadline day (no holding)
        model_values = {
            'x_1_1': 1, 'q_1_1': 100.0,
            'x_2_1': 1, 'q_2_1': 100.0,
            'x_3_2': 1, 'q_3_2': 150.0,
            'x_4_2': 1, 'q_4_2': 150.0,
        }
        lines = MrpLotSizing().map_solution(problem, model_values)
        by_id = {l['res_id']: l for l in lines}
        self.assertEqual(set(by_id), {1, 2, 3, 4})
        self.assertEqual(by_id[1]['decision'],
                         {'date_start': '2026-10-05 00:00:00'})
        self.assertEqual(by_id[3]['decision'],
                         {'date_start': '2026-10-06 00:00:00'})
        self.assertTrue(all(l['res_model'] == 'mrp.production'
                            for l in lines))
        # one setup per order, no holding
        self.assertTrue(all(l['kpi_contribution'] == 250.0
                            for l in lines))

    def test_baseline_fixes_current_plan(self):
        problem = MrpLotSizing().formulate(
            _snapshot_baseline(), {'is_baseline': True})
        fixes = [c for c in problem['constraints']
                 if c['name'].startswith('fix_')]
        self.assertTrue(fixes)
        # rebuild the pinned x variables and map them back to lines
        model_values = {}
        for c in fixes:
            var, val = c['expression'].split(' = ')
            model_values[var] = int(val)
        qtys = {'1': 100.0, '2': 100.0, '3': 150.0, '4': 150.0}
        for oid, qty in qtys.items():
            model_values['q_%s_1' % oid] = qty
            if oid in ('3', '4'):
                model_values['i_%s_1' % oid] = qty
        lines = MrpLotSizing().map_solution(problem, model_values)
        # every order keeps its incumbent start day (the first date)
        self.assertEqual(len(lines), 4)
        self.assertTrue(all(
            l['decision'] == {'date_start': '2026-10-05 00:00:00'}
            for l in lines))

    def test_baseline_infeasible_when_unassigned(self):
        snap = _snapshot_baseline()
        del snap['mrp.production'][4]['current_start']  # no incumbent plan
        problem = MrpLotSizing().formulate(snap, {'is_baseline': True})
        # every x variable of order 4 is pinned to 0, so its delivery
        # constraint is unsatisfiable
        pins = {c['expression'].split(' = ')[0]:
                int(c['expression'].split(' = ')[1])
                for c in problem['constraints']
                if c['name'].startswith('fix_4_')}
        self.assertTrue(pins)
        self.assertTrue(all(v == 0 for v in pins.values()))

    # -- plan explanation (SPECS 13.1) ------------------------------------
    def test_explain_objective_terms(self):
        problem = MrpLotSizing().formulate(_snapshot(), {})
        f = MrpLotSizing()
        # the incumbent: orders 3-4 produced on day 1, held one day
        model_values = {
            'x_1_1': 1, 'q_1_1': 100.0,
            'x_2_1': 1, 'q_2_1': 100.0,
            'x_3_1': 1, 'q_3_1': 150.0, 'i_3_1': 150.0,
            'x_4_1': 1, 'q_4_1': 150.0, 'i_4_1': 150.0,
        }
        terms = f.explain_objective(problem, model_values)
        by_name = {t['name']: t['value'] for t in terms}
        self.assertEqual(set(by_name), {'Setups', 'Inventory holding'})
        self.assertEqual(by_name['Setups'], 4 * 250.0)
        self.assertEqual(by_name['Inventory holding'], 0.5 * 300.0)
        # the terms sum to the objective of this plan (no solver call)
        self.assertEqual(sum(t['value'] for t in terms), 1150.0)
        # a plan with no holding has a zero holding term
        model_values = {
            'x_1_1': 1, 'q_1_1': 100.0,
            'x_2_1': 1, 'q_2_1': 100.0,
            'x_3_2': 1, 'q_3_2': 150.0,
            'x_4_2': 1, 'q_4_2': 150.0,
        }
        by_name = {t['name']: t['value']
                   for t in f.explain_objective(problem, model_values)}
        self.assertEqual(by_name['Setups'], 4 * 250.0)
        self.assertEqual(by_name['Inventory holding'], 0.0)

    def test_explain_constraint_labels(self):
        problem = MrpLotSizing().formulate(_snapshot(), {})
        f = MrpLotSizing()
        names = {('mrp.production', 1): 'MO A', ('mrp.production', 3): 'MO C'}
        self.assertEqual(
            f.explain_constraint('cap_1', problem, names),
            'Production capacity for 2026-10-05')
        self.assertEqual(
            f.explain_constraint('cap_2', problem, names),
            'Production capacity for 2026-10-06')
        self.assertEqual(
            f.explain_constraint('deliver_3', problem, names),
            'Order MO C must be delivered in full by 2026-10-06')
        # no display names -> the generic label, still plain language
        self.assertEqual(
            f.explain_constraint('deliver_3', problem, None),
            'An order must be delivered in full by 2026-10-06')
        # baseline fixes label only when they pin the incumbent start
        baseline = MrpLotSizing().formulate(
            _snapshot_baseline(), {'is_baseline': True})
        self.assertEqual(
            f.explain_constraint('fix_3_1', baseline, None),
            'An order keeps its current start day 2026-10-05')
        self.assertIsNone(f.explain_constraint('fix_1_2', baseline, None))
        # structural and unknown machine names stay invisible
        self.assertIsNone(f.explain_constraint('bal_3_1', problem, names))
        self.assertIsNone(f.explain_constraint('link_1_1', problem, names))
        self.assertIsNone(f.explain_constraint('cap_9', problem, names))
        self.assertIsNone(f.explain_constraint('deliver_99', problem, names))
        self.assertIsNone(f.explain_constraint('fix_bad', problem, names))
