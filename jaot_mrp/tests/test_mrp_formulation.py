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


def _snapshot_forecast():
    """A snapshot that also carries forecast demand rows: one committed MO
    plus two forecast rows (one due the first day, one due the second)."""
    return {
        'mrp.production': {
            1: {'order_qty': 100.0, 'order_due': '2026-10-05 17:00:00'},
        },
        'jaot.forecast.demand': {
            101: {'forecast_demand': 50.0,
                  'forecast_period': '2026-10-05 00:00:00'},
            102: {'forecast_demand': 80.0,
                  'forecast_period': '2026-10-06 00:00:00'},
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

    # -- forecast demand (SPECS 13.5) -----------------------------------
    def test_formulate_with_forecast(self):
        problem = MrpLotSizing().formulate(_snapshot_forecast(), {})
        names = [v['name'] for v in problem['variables']]
        meta = problem['metadata']
        # committed order 1 due day 1; forecast 101 due day 1, 102 due day 2
        self.assertEqual(meta['days'], ['2026-10-05', '2026-10-06'])
        self.assertEqual(meta['n_orders'], 1)
        self.assertEqual(meta['n_forecast'], 2)
        self.assertEqual(meta['forecast_orders']['102'],
                         {'qty': 80.0, 'due_day': 2})
        # synthetic variables are f-prefixed
        self.assertIn('fx_102_2', names)
        self.assertIn('fq_102_2', names)
        self.assertIn('fi_102_1', names)
        self.assertNotIn('x_102_2', names)
        by_name = {c['name']: c for c in problem['constraints']}
        self.assertIn('fdeliver_102', by_name)
        self.assertIn('fbal_102_1', by_name)
        self.assertIn('flink_102_2', by_name)
        # capacity now carries the synthetic demand too
        self.assertEqual(
            by_name['cap_1']['expression'],
            'q_1_1 + fq_101_1 + fq_102_1 <= 800.0')
        self.assertEqual(
            by_name['cap_2']['expression'], 'fq_102_2 <= 800.0')

    def test_formulate_forecast_only(self):
        snap = _snapshot_forecast()
        snap['mrp.production'] = {}
        problem = MrpLotSizing().formulate(snap, {})
        meta = problem['metadata']
        self.assertEqual(meta['n_orders'], 0)
        self.assertEqual(meta['n_forecast'], 2)
        names = [v['name'] for v in problem['variables']]
        self.assertTrue(any(n.startswith('fx_') for n in names))
        self.assertFalse(any(n.startswith('x_') for n in names))

    def test_formulate_requires_orders_or_forecast(self):
        snap = _snapshot_forecast()
        snap['mrp.production'] = {}
        snap['jaot.forecast.demand'] = {}
        with self.assertRaises(ValueError):
            MrpLotSizing().formulate(snap, {})

    def test_formulate_skips_empty_forecast_rows(self):
        snap = _snapshot_forecast()
        # a row with no period and a row with zero quantity are ignored
        snap['jaot.forecast.demand'][103] = {'forecast_demand': 40.0,
                                             'forecast_period': None}
        snap['jaot.forecast.demand'][104] = {'forecast_demand': 0.0,
                                             'forecast_period':
                                             '2026-10-06 00:00:00'}
        problem = MrpLotSizing().formulate(snap, {})
        self.assertEqual(problem['metadata']['n_forecast'], 2)

    def test_map_solution_ignores_forecast(self):
        problem = MrpLotSizing().formulate(_snapshot_forecast(), {})
        model_values = {
            'x_1_1': 1, 'q_1_1': 100.0,
            'fx_101_1': 1, 'fq_101_1': 50.0,
            'fx_102_2': 1, 'fq_102_2': 80.0,
        }
        lines = MrpLotSizing().map_solution(problem, model_values)
        # only the committed MO is written back; forecast rows are not
        self.assertEqual([l['res_id'] for l in lines], [1])
        self.assertEqual(lines[0]['res_model'], 'mrp.production')
        self.assertEqual(lines[0]['decision'],
                         {'date_start': '2026-10-05 00:00:00'})

    def test_baseline_skips_forecast(self):
        snap = _snapshot_forecast()
        snap['mrp.production'][1]['current_start'] = '2026-10-05 06:00:00'
        problem = MrpLotSizing().formulate(snap, {'is_baseline': True})
        fixes = [c['name'] for c in problem['constraints']
                 if c['name'].startswith('fix_')]
        # only the committed order is pinned; forecast orders are free
        self.assertTrue(all(f.startswith('fix_1_') for f in fixes))
        self.assertNotIn('fix_101_1', fixes)
        self.assertNotIn('fix_102_1', fixes)

    def test_explain_objective_includes_forecast(self):
        problem = MrpLotSizing().formulate(_snapshot_forecast(), {})
        f = MrpLotSizing()
        model_values = {
            'x_1_1': 1, 'q_1_1': 100.0,
            'fx_101_1': 1, 'fq_101_1': 50.0,
            'fx_102_1': 1, 'fq_102_1': 80.0, 'fi_102_1': 80.0,
        }
        terms = f.explain_objective(problem, model_values)
        by_name = {t['name']: t['value'] for t in terms}
        # 3 setups (order 1 + forecast 101 + 102), 1 day of holding on 102
        self.assertEqual(by_name['Setups'], 3 * 250.0)
        self.assertEqual(by_name['Inventory holding'], 0.5 * 80.0)

    def test_explain_fdeliver_label(self):
        problem = MrpLotSizing().formulate(_snapshot_forecast(), {})
        f = MrpLotSizing()
        self.assertEqual(
            f.explain_constraint('fdeliver_102', problem, None),
            'Forecast demand must be produced by 2026-10-06')
        # structural synthetic constraints stay invisible
        self.assertIsNone(f.explain_constraint('fbal_102_2', problem, None))
        self.assertIsNone(f.explain_constraint('flink_102_1', problem, None))

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

    # -- human-readable presentation (P9.7) ----------------------------
    def test_presentation_objective_unit(self):
        self.assertEqual(MrpLotSizing().objective_unit(), 'money')

    def test_presentation_referenced_records(self):
        # lot sizing references no record to label
        self.assertEqual(
            MrpLotSizing().referenced_records(
                {'date_start': '2026-10-05 00:00:00'}), [])

    def test_presentation_render_line(self):
        f = MrpLotSizing()
        self.assertEqual(
            f.render_line({'date_start': '2026-10-05 00:00:00'}),
            'Start 2026-10-05')
        self.assertEqual(f.render_line({}), '—')
