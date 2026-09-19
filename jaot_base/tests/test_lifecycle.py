# -*- coding: utf-8 -*-
# License LGPL-3
"""Lifecycle tests with a fake JAOT client (PLAN P2.7, offline).

The whole draft -> queued -> solved -> applied -> reverted flow runs with no
network: ``jaot.config.JaotConfig.get_client`` is patched to return a
``FakeJaotClient``.
"""
from unittest import mock

from odoo.tests import TransactionCase

from ..models.jaot_config import JaotConfig
from .common import FakeJaotClient, make_config, make_toys


class TestScenarioLifecycle(TransactionCase):

    def _company(self):
        return self.env.company

    def _scenario(self):
        recipe, _ = make_toys(self.env, self._company())
        make_config(self.env, self._company())
        return self.env['jaot.scenario'].create({
            'name': 'Lifecycle', 'recipe_id': recipe.id,
            'company_id': self._company().id,
        })

    def _patch_client(self, fake):
        return mock.patch.object(JaotConfig, 'get_client',
                                 return_value=fake)

    def test_full_lifecycle(self):
        items = self.env['jaot.demo.item'].search(
            [('company_id', '=', self._company().id)])
        before = {i.id: i.selected for i in items}

        sc = self._scenario()
        self.assertEqual(sc.state, 'draft')

        fake = FakeJaotClient()
        with self._patch_client(fake):
            sc.action_submit()
            self.assertEqual(sc.state, 'queued')
            self.assertEqual(sc.jaot_task_id, fake.task_id)
            self.assertEqual(sc.jaot_execution_id, fake.execution_id)
            self.assertTrue(sc.request_payload)  # captured before leaving
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        self.assertEqual(sc.state, 'solved')
        self.assertEqual(sc.solver_status, 'optimal')
        self.assertGreater(sc.line_count, 0)
        self.assertGreater(sc.objective_value, 0)
        # at least one item is selected by the stand-in solver
        self.assertTrue(any(l.decision['selected']
                            for l in sc.scenario_line_ids))

        sc.action_apply()
        self.assertEqual(sc.state, 'applied')
        self.assertTrue(sc.applied)
        self.assertTrue(sc.applied_at)
        for line in sc.scenario_line_ids:
            rec = self.env['jaot.demo.item'].browse(line.res_id)
            self.assertEqual(rec.selected, line.decision['selected'])
        # every write is audited
        logs = self.env['jaot.apply.log'].search(
            [('scenario_id', '=', sc.id), ('state', '=', 'applied')])
        self.assertEqual(len(logs), sc.line_count)

        sc.action_revert()
        self.assertEqual(sc.state, 'solved')
        self.assertFalse(sc.applied)
        for i in items:
            i.invalidate_recordset()
            self.assertEqual(i.selected, before[i.id])
        reverted = self.env['jaot.apply.log'].search(
            [('scenario_id', '=', sc.id), ('state', '=', 'reverted')])
        self.assertEqual(len(reverted), sc.line_count)

    def test_cancel_from_queued(self):
        sc = self._scenario()
        fake = FakeJaotClient()
        with self._patch_client(fake):
            sc.action_submit()
            sc.action_cancel()
        self.assertEqual(sc.state, 'cancelled')
        self.assertTrue(fake.cancelled)

    def test_infeasible_solve(self):
        sc = self._scenario()
        fake = FakeJaotClient(solver_status='infeasible')
        with self._patch_client(fake):
            sc.action_submit()
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        self.assertEqual(sc.state, 'failed')
        self.assertEqual(sc.solver_status, 'infeasible')
        self.assertIsNotNone(sc.infeasibility)
        self.assertTrue(fake.infeasibility_calls)

    def test_submit_only_from_draft(self):
        from odoo.exceptions import UserError
        sc = self._scenario()
        sc.state = 'queued'
        with self._patch_client(FakeJaotClient()):
            with self.assertRaises(UserError):
                sc.action_submit()

    def test_staleness(self):
        """SPECS 4.6: re-hashing the source flags it stale when it changes."""
        sc = self._scenario()
        items = self.env['jaot.demo.item'].search(
            [('company_id', '=', self._company().id)])
        self.assertTrue(items)
        fake = FakeJaotClient()
        with self._patch_client(fake):
            sc.action_submit()
        self.assertTrue(sc.data_snapshot_hash)
        self.assertFalse(sc.data_stale)
        # unchanged data stays current
        sc.action_check_staleness()
        self.assertFalse(sc.data_stale)
        # mutating a bound source field makes it stale
        items[0].write({'weight': items[0].weight + 1})
        sc.action_check_staleness()
        self.assertTrue(sc.data_stale)

    def test_whatif_analysis(self):
        """P4.3: request the what-if batch, reconcile it, store the rows.
        Budget-truncated rows are kept as bounds (SKIPPED_BUDGET)."""
        sc = self._scenario()
        fake = FakeJaotClient()
        with self._patch_client(fake):
            sc.action_submit()
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
            self.assertEqual(sc.state, 'solved')
            sc.action_run_whatif()
            self.assertEqual(sc.whatif_state, 'requested')
            self.assertEqual(fake.scenario_analysis_calls, 1)
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
            self.assertEqual(sc.whatif_state, 'done')
            self.assertGreaterEqual(fake.scenario_analysis_get_calls, 1)
        self.assertTrue(sc.whatif_line_ids)
        kinds = set(sc.whatif_line_ids.mapped('kind'))
        self.assertEqual(kinds, {'rhs', 'decision'})
        # a budget-truncated row is stored with its bound status
        self.assertTrue(any(w.status == 'SKIPPED_BUDGET'
                            for w in sc.whatif_line_ids))
        # a completed RHS row carries its objective delta
        self.assertTrue(any(
            w.kind == 'rhs' and w.status == 'computed'
            and w.objective_delta is not None
            for w in sc.whatif_line_ids))

    def test_whatif_requires_solved(self):
        from odoo.exceptions import UserError
        sc = self._scenario()
        with self._patch_client(FakeJaotClient()):
            with self.assertRaises(UserError):
                sc.action_run_whatif()

    def test_resolving_clears_whatif(self):
        """A fresh solve invalidates any earlier what-if (P4.3)."""
        sc = self._scenario()
        fake = FakeJaotClient()
        with self._patch_client(fake):
            sc.action_submit()
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
            sc.action_run_whatif()
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
            self.assertEqual(sc.whatif_state, 'done')
            self.assertTrue(sc.whatif_line_ids)
            # simulate a re-solve: cancel is not needed; finalize again
            sc._finalize_from_execution(
                self.env['jaot.config']._config_for(self._company()))
        self.assertEqual(sc.whatif_state, 'none')
        self.assertFalse(sc.whatif_line_ids)
