# -*- coding: utf-8 -*-
# License LGPL-3
"""End-to-end delivery routing on a real Odoo stock/fleet dataset (PLAN P3.6).

Offline: ``jaot.config.JaotConfig.get_client`` is patched to return a
``FakeVrpClient``. The scenario runs draft -> queued -> solved -> applied ->
reverted against confirmed outgoing pickings, a depot warehouse and a fleet
vehicle, and the apply/revert round-trip on ``stock.picking`` is checked.
"""
from unittest import mock

from odoo.tests import TransactionCase

from odoo.addons.jaot_base.models.jaot_config import JaotConfig

from .common import FakeVrpClient


class TestVrpE2E(TransactionCase):

    # -- dataset --------------------------------------------------------
    def _company(self):
        return self.env.company

    def _ensure_config(self):
        cfg = self.env['jaot.config'].search(
            [('company_id', '=', self._company().id)])
        if not cfg:
            cfg = self.env['jaot.config'].create({
                'company_id': self._company().id,
                'endpoint_url': 'http://fake-jaot.invalid'})
        return cfg

    def _make_picking(self, warehouse, partner, weight):
        product = self.env['product.product'].create({
            'name': 'P-%s' % partner.id,
            'default_code': 'PROD%s' % partner.id})
        ptype = self.env['stock.picking.type'].search(
            [('code', '=', 'outgoing'),
             ('company_id', 'in', [self._company().id, False])],
            limit=1)
        cust_loc = self.env['stock.location'].search(
            [('usage', '=', 'customer')], order='id', limit=1)
        picking = self.env['stock.picking'].create({
            'picking_type_id': ptype.id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': cust_loc.id,
            'partner_id': partner.id,
            'company_id': self._company().id,
            'move_ids': [(0, 0, {
                'product_id': product.id,
                'product_uom': product.uom_id.id,
                'quantity': 1.0,
            })],
        })
        picking.action_confirm()
        picking.shipping_weight = weight
        self.assertIn(picking.state, ('confirmed', 'assigned'))
        return picking

    def _dataset(self, n_orders=3):
        """Depot (geo), n customer pickings (geo + weight), 1 vehicle."""
        company = self._company()
        warehouse = self.env['stock.warehouse'].search(
            [('company_id', 'in', [company.id, False])],
            order='id', limit=1)
        depot_partner = warehouse.partner_id
        if not depot_partner:
            depot_partner = self.env['res.partner'].create({
                'name': 'Depot contact', 'company_id': company.id})
            warehouse.partner_id = depot_partner
        depot_partner.partner_latitude = 40.40
        depot_partner.partner_longitude = -3.70

        pickings = []
        for i in range(1, n_orders + 1):
            # staggered (non-colinear) so the id-order tour and a reordered
            # tour have different lengths -> a real baseline delta
            partner = self.env['res.partner'].create({
                'name': 'Cust %d' % i,
                'partner_latitude': 40.40 + (i % 2) * 0.10,
                'partner_longitude': -3.70 - i * 0.05,
                'company_id': company.id,
            })
            pickings.append(self._make_picking(
                warehouse, partner, weight=10.0 * i))

        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'Jaom'})
        vmodel = self.env['fleet.vehicle.model'].create({
            'name': 'Van', 'brand_id': brand.id})
        vehicle = self.env['fleet.vehicle'].create({
            'name': 'Van 1', 'model_id': vmodel.id, 'company_id': company.id})
        return warehouse, pickings, vehicle

    def _scenario(self):
        recipe = self.env['jaot.recipe'].search(
            [('code', '=', 'vrp'),
             ('company_id', '=', self._company().id)],
            limit=1)
        self.assertTrue(recipe, 'vrp recipe missing for company')
        return self.env['jaot.scenario'].create({
            'name': 'VRP E2E', 'recipe_id': recipe.id,
            'company_id': self._company().id,
        })

    def _patch_client(self, fake):
        return mock.patch.object(JaotConfig, 'get_client',
                                  return_value=fake)

    # -- tests ----------------------------------------------------------
    def test_full_routing_lifecycle(self):
        self._ensure_config()
        _warehouse, pickings, vehicle = self._dataset(n_orders=3)
        before = {p.id: (p.jaot_vehicle_id, p.jaot_route_sequence)
                  for p in pickings}
        self.assertTrue(all(not v[0] and not v[1] for v in before.values()))

        sc = self._scenario()
        self.assertEqual(sc.state, 'draft')

        fake = FakeVrpClient()
        with self._patch_client(fake):
            sc.action_submit()
            self.assertEqual(sc.state, 'queued')
            self.assertEqual(sc.jaot_task_id, fake.task_id)
            self.assertTrue(sc.request_payload)
            self.env['jaot.scenario'].reconcile_jaot_scenarios()

        self.assertEqual(sc.state, 'solved')
        self.assertEqual(sc.solver_status, 'optimal')
        self.assertEqual(sc.line_count, 3)
        self.assertGreater(sc.objective_value, 0)
        # one line per picking, each riding the single vehicle
        self.assertEqual(
            {l.res_id for l in sc.scenario_line_ids},
            {p.id for p in pickings})
        self.assertTrue(all(
            l.decision['jaot_vehicle_id'] == vehicle.id
            for l in sc.scenario_line_ids))

        sc.action_apply()
        self.assertEqual(sc.state, 'applied')
        self.assertTrue(sc.applied)
        for p in pickings:
            p.invalidate_recordset()
            self.assertEqual(p.jaot_vehicle_id, vehicle)
            self.assertGreater(p.jaot_route_sequence, 0)
        # the route is a permutation of 1..3 (one position per picking)
        self.assertEqual(
            sorted(p.jaot_route_sequence for p in pickings), [1, 2, 3])
        # one apply log per decision field (2 per line here)
        expected_logs = sum(
            len(l.decision) for l in sc.scenario_line_ids)
        logs = self.env['jaot.apply.log'].search(
            [('scenario_id', '=', sc.id), ('state', '=', 'applied')])
        self.assertEqual(len(logs), expected_logs)

        sc.action_revert()
        self.assertEqual(sc.state, 'solved')
        self.assertFalse(sc.applied)
        for p in pickings:
            p.invalidate_recordset()
            self.assertEqual((p.jaot_vehicle_id, p.jaot_route_sequence),
                             before[p.id])
        reverted = self.env['jaot.apply.log'].search(
            [('scenario_id', '=', sc.id), ('state', '=', 'reverted')])
        self.assertEqual(len(reverted), expected_logs)

    def test_submit_requires_dataset(self):
        """No pickings -> the VRP formulation rejects the snapshot."""
        self._ensure_config()
        sc = self._scenario()
        from odoo.exceptions import UserError
        with self._patch_client(FakeVrpClient()):
            with self.assertRaises(UserError):
                sc.action_submit()

    def test_baseline_delta(self):
        """Fix-all baseline: pin the incumbent plan, re-solve, diff it
        against the optimized plan (SPECS 4.6)."""
        self._ensure_config()
        _warehouse, pickings, vehicle = self._dataset(n_orders=3)
        # incumbent plan: one vehicle in a suboptimal position order
        # (p1 -> p3 -> p2), so it differs from the id-order optimized tour
        positions = {pickings[0].id: 1, pickings[2].id: 2, pickings[1].id: 3}
        for p in pickings:
            p.jaot_vehicle_id = vehicle.id
            p.jaot_route_sequence = positions[p.id]

        sc = self._scenario()
        fake = FakeVrpClient()
        with self._patch_client(fake):
            sc.action_submit()
            self.assertEqual(sc.state, 'queued')
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        self.assertEqual(sc.state, 'solved')

        with self._patch_client(fake):
            baseline = sc.action_compare_baseline()
        self.assertTrue(baseline)
        self.assertTrue(baseline.is_baseline)
        self.assertEqual(baseline.baseline_of_id.id, sc.id)
        self.assertEqual(sc.baseline_scenario_id.id, baseline.id)
        self.assertEqual(baseline.state, 'queued')

        with self._patch_client(fake):
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        self.assertEqual(baseline.state, 'solved')

        # the delta is written back onto the optimized scenario
        ks = sc.kpi_summary
        self.assertIn('baseline_objective', ks)
        self.assertIn('optimized_objective', ks)
        self.assertIn('delta_vs_baseline', ks)
        self.assertNotEqual(ks['baseline_objective'],
                            ks['optimized_objective'])
        # p2 and p3 swapped positions; p1 kept its position
        lines = {l.res_id: l for l in sc.scenario_line_ids}
        self.assertTrue(lines[pickings[1].id].delta_vs_baseline)
        self.assertTrue(lines[pickings[2].id].delta_vs_baseline)
        self.assertFalse(lines[pickings[0].id].delta_vs_baseline)
