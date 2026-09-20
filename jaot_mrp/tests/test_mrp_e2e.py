# -*- coding: utf-8 -*-
# License LGPL-3
"""End-to-end production scheduling on a real Odoo MRP dataset (P6.1).

Offline: ``jaot.config.JaotConfig.get_client`` is patched to return a
``FakeMrpClient``. The scenario runs draft -> queued -> solved -> applied
-> reverted against confirmed production orders with deadlines, and the
apply/revert round-trip on ``mrp.production.date_start`` is checked.
"""
from unittest import mock

from odoo.exceptions import UserError
from odoo.tests import TransactionCase

from odoo.addons.jaot_base.models.jaot_config import JaotConfig

from .common import FakeMrpClient


class TestMrpE2E(TransactionCase):

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

    def _make_production(self, index, qty, due):
        product = self.env['product.product'].create({
            'name': 'Widget %d' % index,
            'type': 'consu',  # Odoo 19 "Goods" (the storable type)
            'default_code': 'WGT%d' % index,
        })
        production = self.env['mrp.production'].create({
            'product_id': product.id,
            'product_qty': qty,
            'company_id': self._company().id,
        })
        production.action_confirm()
        # the deadline lives on the finished move (the production's
        # date_deadline is computed from it)
        production.move_finished_ids.date_deadline = due
        self.assertIn(production.state, ('confirmed', 'planned'))
        self.assertEqual(production.date_deadline.strftime('%Y-%m-%d'),
                         due[:10])
        return production

    def _dataset(self):
        """Four production orders due on two dates: orders 1-2 (100 units)
        due 2026-10-05, orders 3-4 (150 units) due 2026-10-06."""
        productions = [
            self._make_production(1, 100.0, '2026-10-05 17:00:00'),
            self._make_production(2, 100.0, '2026-10-05 17:00:00'),
            self._make_production(3, 150.0, '2026-10-06 17:00:00'),
            self._make_production(4, 150.0, '2026-10-06 17:00:00'),
        ]
        return productions

    def _scenario(self):
        recipe = self.env['jaot.recipe'].search(
            [('code', '=', 'mrp'),
             ('company_id', '=', self._company().id)],
            limit=1)
        self.assertTrue(recipe, 'mrp recipe missing for company')
        return self.env['jaot.scenario'].create({
            'name': 'MRP E2E', 'recipe_id': recipe.id,
            'company_id': self._company().id,
        })

    def _patch_client(self, fake):
        return mock.patch.object(JaotConfig, 'get_client',
                                  return_value=fake)

    # -- tests ----------------------------------------------------------
    def test_full_scheduling_lifecycle(self):
        self._ensure_config()
        productions = self._dataset()
        before = {p.id: p.date_start for p in productions}

        sc = self._scenario()
        self.assertEqual(sc.state, 'draft')

        fake = FakeMrpClient()
        with self._patch_client(fake):
            sc.action_submit()
            self.assertEqual(sc.state, 'queued')
            self.assertEqual(sc.jaot_task_id, fake.task_id)
            self.assertTrue(sc.request_payload)
            self.env['jaot.scenario'].reconcile_jaot_scenarios()

        self.assertEqual(sc.state, 'solved')
        self.assertEqual(sc.solver_status, 'optimal')
        # one line per order, each with a start date on its deadline day
        self.assertEqual(sc.line_count, 4)
        lines = {l.res_id: l for l in sc.scenario_line_ids}
        self.assertEqual(set(lines), {p.id for p in productions})
        expected_dates = {
            productions[0].id: '2026-10-05',
            productions[1].id: '2026-10-05',
            productions[2].id: '2026-10-06',
            productions[3].id: '2026-10-06',
        }
        for pid, date in expected_dates.items():
            self.assertEqual(lines[pid].decision['date_start'][:10], date)
        # four setups, no holding: the objective is 4 x the setup cost
        self.assertEqual(sc.objective_value, 4 * 250.0)

        sc.action_apply()
        self.assertEqual(sc.state, 'applied')
        self.assertTrue(sc.applied)
        for p in productions:
            p.invalidate_recordset()
            self.assertEqual(p.date_start.strftime('%Y-%m-%d'),
                             expected_dates[p.id])
        # one apply log per decision field (1 per line here)
        logs = self.env['jaot.apply.log'].search(
            [('scenario_id', '=', sc.id), ('state', '=', 'applied')])
        self.assertEqual(len(logs), len(lines))

        sc.action_revert()
        self.assertEqual(sc.state, 'solved')
        self.assertFalse(sc.applied)
        for p in productions:
            p.invalidate_recordset()
            self.assertEqual(p.date_start, before[p.id])
        reverted = self.env['jaot.apply.log'].search(
            [('scenario_id', '=', sc.id), ('state', '=', 'reverted')])
        self.assertEqual(len(reverted), len(lines))

    def test_submit_requires_dataset(self):
        """No production orders -> the formulation rejects the snapshot."""
        self._ensure_config()
        sc = self._scenario()
        with self._patch_client(FakeMrpClient()):
            with self.assertRaises(UserError):
                sc.action_submit()

    def test_baseline_delta(self):
        """Fix-all baseline: pin the incumbent plan, re-solve, diff it
        against the optimized plan (SPECS 4.6). The incumbent starts
        every order on the first date, so orders 3-4 are held a day."""
        self._ensure_config()
        productions = self._dataset()
        for p in productions:
            p.date_start = '2026-10-05 06:00:00'

        sc = self._scenario()
        fake = FakeMrpClient()
        with self._patch_client(fake):
            sc.action_submit()
            self.assertEqual(sc.state, 'queued')
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        self.assertEqual(sc.state, 'solved')
        # optimized: orders 3-4 move to their deadline day
        self.assertEqual(sc.objective_value, 4 * 250.0)

        with self._patch_client(fake):
            baseline = sc.action_compare_baseline()
        self.assertTrue(baseline)
        self.assertTrue(baseline.is_baseline)
        self.assertEqual(baseline.baseline_of_id.id, sc.id)
        self.assertEqual(sc.baseline_scenario_id.id, baseline.id)

        with self._patch_client(fake):
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        self.assertEqual(baseline.state, 'solved')
        # baseline: 4 setups + one day of holding on 300 units
        self.assertEqual(baseline.objective_value,
                         4 * 250.0 + 0.5 * 300.0)

        ks = sc.kpi_summary
        self.assertIn('baseline_objective', ks)
        self.assertIn('optimized_objective', ks)
        self.assertIn('delta_vs_baseline', ks)
        self.assertEqual(ks['baseline_objective'], 1150.0)
        self.assertEqual(ks['optimized_objective'], 1000.0)
        self.assertEqual(ks['delta_vs_baseline'], 150.0)
        # per-line: only orders 3-4 changed (and their KPI swung)
        lines = {l.res_id: l for l in sc.scenario_line_ids}
        self.assertFalse(lines[productions[0].id].delta_vs_baseline)
        self.assertFalse(lines[productions[1].id].delta_vs_baseline)
        self.assertTrue(lines[productions[2].id].delta_vs_baseline)
        self.assertTrue(lines[productions[3].id].delta_vs_baseline)

    def test_infeasible_when_capacity_below_order(self):
        """An order larger than the daily capacity cannot be produced by
        its deadline: the solve is infeasible, the IIS is captured and the
        scenario fails — a finding, not a crash (SPECS 4.4)."""
        self._ensure_config()
        self._make_production(1, 100.0, '2026-10-05 17:00:00')
        binding = self.env['jaot.binding'].search([
            ('role_id.name', '=', 'resource_capacity'),
            ('company_id', '=', self._company().id)], limit=1)
        binding.constant_value = '80'
        self.assertTrue(binding)

        sc = self._scenario()
        fake = FakeMrpClient()
        with self._patch_client(fake):
            sc.action_submit()
            self.assertEqual(sc.state, 'queued')
            self.env['jaot.scenario'].reconcile_jaot_scenarios()

        self.assertEqual(sc.state, 'failed')
        self.assertEqual(sc.solver_status, 'infeasible')
        self.assertTrue(sc.infeasibility)
        self.assertEqual(fake.infeasibility_calls, 1)
