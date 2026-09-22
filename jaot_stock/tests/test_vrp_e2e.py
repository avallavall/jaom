# -*- coding: utf-8 -*-
# License LGPL-3
"""End-to-end delivery routing on a real Odoo stock/fleet dataset (PLAN P3.6).

Offline: ``jaot.config.JaotConfig.get_client`` is patched to return a
``FakeVrpClient``. The scenario runs draft -> queued -> solved -> applied ->
reverted against confirmed outgoing pickings, a depot warehouse and a fleet
vehicle, and the apply/revert round-trip on ``stock.picking`` is checked.
"""
from unittest import mock

from odoo.exceptions import AccessError
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
                'product_uom_qty': 1.0,
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
        before = {p.id: (p.jaot_vehicle_id, p.jaot_route_sequence,
                         p.jaot_scenario_id) for p in pickings}
        self.assertTrue(all(not v[0] and not v[1] and not v[2]
                            for v in before.values()))

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
            # the link back to the scenario is stamped by the apply
            self.assertEqual(p.jaot_scenario_id, sc)
        # the route is a permutation of 1..3 (one position per picking)
        self.assertEqual(
            sorted(p.jaot_route_sequence for p in pickings), [1, 2, 3])
        # one apply log per decision field (2 per line here) plus one per
        # scenario-link write
        expected_logs = sum(
            len(l.decision) for l in sc.scenario_line_ids) \
            + len(sc.scenario_line_ids)
        logs = self.env['jaot.apply.log'].search(
            [('scenario_id', '=', sc.id), ('state', '=', 'applied')])
        self.assertEqual(len(logs), expected_logs)

        sc.action_revert()
        self.assertEqual(sc.state, 'solved')
        self.assertFalse(sc.applied)
        for p in pickings:
            p.invalidate_recordset()
            self.assertEqual(
                (p.jaot_vehicle_id, p.jaot_route_sequence,
                 p.jaot_scenario_id),
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

    def test_reoptimize_pins_done_legs(self):
        """Intraday re-optimization (SPECS 13.4): serve a prefix of the
        applied tour, flag the staleness, re-optimize. The served legs keep
        their vehicle and position; the KPI delta against the frozen plan
        and the per-line diff land on the re-route scenario; apply/revert
        round-trips without disturbing the served pickings' plan."""
        from odoo.exceptions import UserError
        self._ensure_config()
        _wh, pickings, vehicle = self._dataset(n_orders=3)
        sc = self._scenario()
        fake = FakeVrpClient()
        with self._patch_client(fake):
            sc.action_submit()
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        self.assertEqual(sc.state, 'solved')
        sc.action_apply()
        self.assertEqual(sc.state, 'applied')

        # guard: a scenario that is not applied cannot be re-optimized
        guard = self._scenario()
        with self.assertRaises(UserError):
            guard.action_reoptimize()

        # serve the first two stops of the applied tour
        tour = sorted(sc.scenario_line_ids,
                      key=lambda l: l.decision['jaot_route_sequence'])
        done = [self.env['stock.picking'].browse(l.res_id) for l in tour[:2]]
        for p in done:
            for m in p.move_ids:
                m._set_quantity_done(m.product_qty)
            p.button_validate()
        self.assertTrue(all(p.state == 'done' for p in done))
        # the done pickings leave the extraction domain -> stale
        sc.action_check_staleness()
        self.assertTrue(sc.data_stale)

        with self._patch_client(fake):
            child = sc.action_reoptimize()
        self.assertEqual(child.state, 'queued')
        self.assertEqual(child.reoptimize_of_id.id, sc.id)
        self.assertEqual(child.reoptimize_done, [
            {'res_id': done[0].id, 'vehicle': vehicle.id, 'sequence': 1},
            {'res_id': done[1].id, 'vehicle': vehicle.id, 'sequence': 2},
        ])
        with self._patch_client(fake):
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        self.assertEqual(child.state, 'solved')
        self.assertEqual(child.line_count, 3)

        # the served legs keep their vehicle and position, with no diff
        parent_lines = {l.res_id: l.decision for l in sc.scenario_line_ids}
        child_lines = {l.res_id: l for l in child.scenario_line_ids}
        for p in done:
            self.assertEqual(child_lines[p.id].decision,
                             parent_lines[p.id])
            self.assertFalse(child_lines[p.id].delta_vs_baseline)
        # the KPI delta against the frozen plan is stored on the child
        ks = child.kpi_summary
        self.assertEqual(ks['baseline_objective'], sc.objective_value)
        self.assertEqual(ks['optimized_objective'], child.objective_value)
        self.assertIn('delta_vs_baseline', ks)

        # apply the re-route: served pickings keep their plan, the scenario
        # link moves to the child
        child.action_apply()
        self.assertEqual(child.state, 'applied')
        for p in pickings:
            p.invalidate_recordset()
            self.assertEqual(p.jaot_vehicle_id, vehicle)
            self.assertGreater(p.jaot_route_sequence, 0)
            self.assertEqual(p.jaot_scenario_id, child)
        # revert restores the frozen plan
        child.action_revert()
        self.assertEqual(child.state, 'solved')
        for p in pickings:
            p.invalidate_recordset()
            self.assertEqual(p.jaot_vehicle_id, vehicle)
            self.assertGreater(p.jaot_route_sequence, 0)
            self.assertEqual(p.jaot_scenario_id, sc)
        # leave the dataset clean
        sc.action_revert()
        self.assertEqual(sc.state, 'solved')

    def test_explanation_on_solve(self):
        """SPECS 13.1: the solved scenario carries the manager-readable
        explanation: the transport term per vehicle and the tight
        constraints labelled with the record names (no machine
        identifiers leak into the text)."""
        self._ensure_config()
        _warehouse, pickings, vehicle = self._dataset(n_orders=3)
        sc = self._scenario()
        fake = FakeVrpClient()
        with self._patch_client(fake):
            sc.action_submit()
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        self.assertEqual(sc.state, 'solved')
        self.assertTrue(fake.exact_analysis_calls)
        self.assertTrue(sc.explanation)
        exp = sc.explanation
        self.assertEqual(exp['objective']['value'], sc.objective_value)
        self.assertEqual(exp['objective']['sense'], 'minimize')
        # one vehicle carries the whole tour: a single named term, the
        # tour length (4-decimal rounding may differ from the solver's
        # objective in the last decimals)
        terms = exp['objective']['terms']
        self.assertEqual(len(terms), 1)
        self.assertEqual(terms[0]['name'], 'Vehicle %s' % vehicle.name)
        self.assertAlmostEqual(terms[0]['value'], sc.objective_value,
                               places=2)
        # the three visit equalities are binding; the vehicle load is far
        # from its limit, so the labelled tight constraints are the visits
        labels = [b['label'] for b in exp['binding_constraints']]
        self.assertEqual(len(labels), 3)
        for p in pickings:
            self.assertTrue(any(p.name in l for l in labels),
                            'picking %s missing from the tight constraints'
                            % p.name)
        text = sc.explanation_text
        self.assertIn('Objective value', text)
        self.assertIn('Tightly used constraints:', text)
        self.assertNotIn('visit_', text)
        self.assertNotIn('capacity_', text)

    def test_presentation_id_free_for_viewer_without_fleet(self):
        """SPECS 13.7: a viewer who can read the delivery plan but not the
        fleet vehicles still gets a plain-language line — the vehicle is
        shown as a generic 'Vehicle' and its database id never leaks into
        decision_text or change_preview."""
        self._ensure_config()
        _wh, _pickings, vehicle = self._dataset(n_orders=3)
        sc = self._scenario()
        fake = FakeVrpClient()
        with self._patch_client(fake):
            sc.action_submit()
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        self.assertEqual(sc.state, 'solved')

        viewer = self.env['res.users'].create({
            'name': 'Vrp reader', 'login': 'vrp_reader_xyz',
            'company_id': self._company().id,
            'company_ids': [(6, 0, [self._company().id])],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('jaot_base.group_user').id])],
        })
        # self-check: the vehicle must genuinely be unreadable to this
        # viewer, so the AccessError fallback below is actually exercised
        with self.assertRaises(AccessError):
            vehicle.with_user(viewer).display_name

        for line in sc.scenario_line_ids:
            seq = line.decision['jaot_route_sequence']
            vline = line.with_user(viewer).browse(line.id)
            # the vehicle is unreadable, so both the line text and the
            # change preview degrade to the plan's own (id-free) value
            self.assertEqual(vline.decision_text,
                             'Vehicle · stop %d' % seq)
            self.assertEqual(vline.change_preview,
                             'Vehicle · stop %d' % seq)
            self.assertTrue(vline.record_label)
