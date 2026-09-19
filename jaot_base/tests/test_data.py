# -*- coding: utf-8 -*-
# License LGPL-3
"""Determinism + shape tests for the seeded synthetic datasets (PLAN P2.6).

The generators are the source of truth for the P2.8 gate, the P3 routing E2E
test and the spike, so pinning their output keeps those comparable.
"""
from odoo.tests import TransactionCase

from ..jaot_data import generate_knapsack, generate_routing


class TestData(TransactionCase):

    def test_knapsack_deterministic_and_feasible(self):
        a = generate_knapsack()
        b = generate_knapsack()
        self.assertEqual(a, b)
        self.assertEqual(len(a['items']), 5)
        # every item fits under the capacity, so a feasible selection exists
        self.assertTrue(all(it['weight'] <= a['capacity']
                            for it in a['items']))

    def test_routing_deterministic(self):
        a = generate_routing()
        b = generate_routing()
        self.assertEqual(a, b)

    def test_routing_shape(self):
        data = generate_routing()
        self.assertEqual(len(data['orders']), 50)
        self.assertEqual(sum(len(o['lines']) for o in data['orders']), 200)
        self.assertEqual(len(data['vehicles']), 4)
        self.assertEqual(data['depot']['lat'], 40.4168)
        # per-order demand is the sum of its line weights
        for order in data['orders']:
            self.assertEqual(
                order['demand_kg'],
                round(sum(l['weight_kg'] for l in order['lines']), 1))
        # total demand is within fleet capacity (feasible dataset)
        cap = sum(v['capacity_kg'] for v in data['vehicles'])
        self.assertLessEqual(data['total_demand_kg'], cap)
