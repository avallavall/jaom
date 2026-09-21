# -*- coding: utf-8 -*-
# License LGPL-3
"""Unit tests for the framework-free formulation registry (PLAN P2.7).

No Odoo, no network: the formulation is driven with a plain snapshot dict,
exactly the shape ``jaot.scenario._extract_snapshot`` produces. The class
still inherits ``TransactionCase`` so Odoo's test loader collects it (plain
``unittest.TestCase`` is not picked up).
"""
from odoo.tests import TransactionCase

from ..jaot_formulations import get_formulation, ToyKnapsack


class TestFormulationRegistry(TransactionCase):

    def test_get_formulation_returns_instance(self):
        formula = get_formulation('toy_knapsack')
        self.assertIsInstance(formula, ToyKnapsack)

    def test_unknown_code_returns_none(self):
        self.assertIsNone(get_formulation('does_not_exist'))

    def test_register_is_idempotent(self):
        self.assertEqual(get_formulation('toy_knapsack').recipe_code,
                         'toy_knapsack')


class TestToyKnapsack(TransactionCase):

    def _snapshot(self):
        return {
            'jaot.demo.item': {
                1: {'item': 'A', 'weight': 10.0, 'value': 60.0},
                2: {'item': 'B', 'weight': 20.0, 'value': 100.0},
            },
            '_parameters': {'capacity': 50.0},
        }

    def test_formulate_shape(self):
        problem = ToyKnapsack().formulate(self._snapshot(),
                                           {'time_limit_seconds': 60,
                                            'gap_tolerance': 0.1})
        self.assertEqual([v['name'] for v in problem['variables']],
                         ['x_1', 'x_2'])
        self.assertEqual(problem['objective']['sense'], 'maximize')
        self.assertIn('60.0*x_1', problem['objective']['expression'])
        self.assertEqual(problem['constraints'][0]['name'], 'capacity')
        self.assertIn('<= 50.0', problem['constraints'][0]['expression'])
        self.assertEqual(problem['options']['time_limit_seconds'], 60)
        self.assertEqual(problem['metadata']['capacity'], 50.0)
        self.assertEqual(set(problem['metadata']['items']), {'1', '2'})

    def test_formulate_requires_items(self):
        with self.assertRaises(ValueError):
            ToyKnapsack().formulate(
                {'_parameters': {'capacity': 50.0}}, {})

    def test_formulate_requires_capacity(self):
        with self.assertRaises(ValueError):
            ToyKnapsack().formulate(
                {'jaot.demo.item': {1: {'item': 'A', 'weight': 1.0,
                                         'value': 1.0}}}, {})

    def test_map_solution(self):
        problem = ToyKnapsack().formulate(self._snapshot(), {})
        lines = ToyKnapsack().map_solution(problem, {'x_1': 1, 'x_2': 0})
        by_id = {l['res_id']: l for l in lines}
        self.assertEqual(by_id[1]['decision'], {'selected': True})
        self.assertEqual(by_id[1]['kpi_contribution'], 60.0)
        self.assertEqual(by_id[2]['decision'], {'selected': False})
        self.assertEqual(by_id[2]['kpi_contribution'], 0.0)
        self.assertEqual(by_id[1]['res_model'], 'jaot.demo.item')

    # -- human-readable presentation (P9.7) ----------------------------
    def test_presentation_objective_unit(self):
        self.assertEqual(ToyKnapsack().objective_unit(), '')

    def test_presentation_referenced_records(self):
        self.assertEqual(
            ToyKnapsack().referenced_records({'selected': True}), [])

    def test_presentation_render_line(self):
        f = ToyKnapsack()
        self.assertEqual(f.render_line({'selected': True}), 'Selected')
        self.assertEqual(f.render_line({'selected': False}), 'Not selected')
        self.assertEqual(f.render_line({}), '')
