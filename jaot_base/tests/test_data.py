# -*- coding: utf-8 -*-
# License LGPL-3
"""Determinism + shape tests for the seeded synthetic datasets (PLAN P2.6).

The generators are the source of truth for the P2.8 gate, the P3 routing E2E
test and the spike, so pinning their output keeps those comparable.
"""
from odoo.tests import TransactionCase

from ..jaot_data import (
    generate_knapsack,
    generate_routing,
    generate_routing_multi,
    generate_routing_stress,
)


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

    def test_routing_multi_deterministic_and_tight(self):
        # P5.1: multi-company / multi-depot, tight fleet, deterministic
        a = generate_routing_multi()
        b = generate_routing_multi()
        self.assertEqual(a, b)
        self.assertEqual(len(a['companies']), 2)
        for company in a['companies']:
            self.assertTrue(company['depots'])
            self.assertTrue(company['orders'])
            self.assertTrue(company['vehicles'])
            # tight: total demand exceeds the (scaled-down) fleet capacity,
            # but the generator only ever shrinks capacity toward demand, so a
            # feasible instance still exists
            cap = sum(v['capacity_kg'] for v in company['vehicles'])
            self.assertLessEqual(cap, company['total_demand_kg'] * 1.0 + 1.0)

    def test_routing_multi_depots(self):
        data = generate_routing_multi(depots_per_company=3)
        for company in data['companies']:
            self.assertEqual(len(company['depots']), 3)

    def test_routing_stress_deterministic_and_large(self):
        # P5.1 / P5.3: the 50 k extraction benchmark dataset, deterministic
        a = generate_routing_stress(n_orders=200)
        b = generate_routing_stress(n_orders=200)
        self.assertEqual(a, b)
        self.assertEqual(len(a['orders']), 200)
        self.assertEqual(sum(len(o['lines']) for o in a['orders']), 200 * 4)
        # the default size is 50 k orders (checked on a sample, not the full
        # list, to keep the test fast)
        full = generate_routing_stress()
        self.assertEqual(len(full['orders']), 50000)
        self.assertEqual(full['orders'][123], a['orders'][123])
