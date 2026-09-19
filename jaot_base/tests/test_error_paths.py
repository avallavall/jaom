# -*- coding: utf-8 -*-
# License LGPL-3
"""Error-path tests (PLAN P5.4): JAOT down, quota, solver error, infeasible
IIS, worker restart mid-solve and the cancel race. All offline via a fake
client that can be made to fail at each seam."""
from unittest import mock

from odoo.exceptions import UserError
from odoo.tests import TransactionCase

from ..jaot_client import JaotAPIError
from ..models.jaot_config import JaotConfig
from .common import FakeJaotClient, make_config, make_toys


class TestErrorPaths(TransactionCase):

    def _company(self):
        return self.env.company

    def _scenario(self):
        recipe, _ = make_toys(self.env, self._company())
        make_config(self.env, self._company())
        return self.env['jaot.scenario'].create({
            'name': 'Err', 'recipe_id': recipe.id,
            'company_id': self._company().id})

    def _patch_client(self, fake):
        return mock.patch.object(JaotConfig, 'get_client',
                                  return_value=fake)

    def test_submit_jaot_down(self):
        # 503 on submit: the failure surfaces to the user as a clear
        # UserError carrying the JAOT code (SPECS 4.4). The scenario is
        # marked failed in the same branch (verified in the odoo shell).
        sc = self._scenario()
        fake = FakeJaotClient(solve_async_error=JaotAPIError(
            503, 'unavailable', 'JAOT is down',
            detail={'code': 'unavailable'}))
        with self._patch_client(fake):
            with self.assertRaises(UserError) as ctx:
                sc.action_submit()
        self.assertIn('JAOT HTTP 503', str(ctx.exception))
        self.assertIn('unavailable', str(ctx.exception))
        self.assertEqual(fake.solve_async_calls, 1)

    def test_submit_quota_exceeded(self):
        # a quota error also surfaces to the user, not a silent retry
        sc = self._scenario()
        fake = FakeJaotClient(solve_async_error=JaotAPIError(
            402, 'quota_exceeded', 'quota exceeded',
            detail={'code': 'quota_exceeded'}))
        with self._patch_client(fake):
            with self.assertRaises(UserError) as ctx:
                sc.action_submit()
        self.assertIn('quota_exceeded', str(ctx.exception))
        self.assertEqual(fake.solve_async_calls, 1)

    def test_solver_error_on_poll(self):
        # a solve that fails on JAOT (poll status failed) -> scenario failed
        sc = self._scenario()
        fake = FakeJaotClient(poll_status='failed')
        with self._patch_client(fake):
            sc.action_submit()
            self.assertEqual(sc.state, 'queued')
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        sc.invalidate_recordset()
        self.assertEqual(sc.state, 'failed')
        self.assertTrue(sc.jaot_error)

    def test_infeasible_iis_captured(self):
        # infeasible: the IIS is captured and surfaced (the view shows it)
        sc = self._scenario()
        fake = FakeJaotClient(solver_status='infeasible')
        with self._patch_client(fake):
            sc.action_submit()
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        sc.invalidate_recordset()
        self.assertEqual(sc.state, 'failed')
        self.assertEqual(sc.solver_status, 'infeasible')
        self.assertIsNotNone(sc.infeasibility)
        self.assertTrue(fake.infeasibility_calls)

    def test_reconcile_idempotent_across_restart(self):
        # worker restart mid-solve: a known task is re-polled, never
        # re-submitted (the reconcile is keyed by jaot_task_id)
        sc = self._scenario()
        fake = FakeJaotClient(poll_status='running')
        with self._patch_client(fake):
            sc.action_submit()
            self.assertEqual(sc.state, 'queued')
            task_id = sc.jaot_task_id
            self.env['jaot.scenario'].reconcile_jaot_scenarios()  # poll 1
            self.env['jaot.scenario'].reconcile_jaot_scenarios()  # poll 2
        sc.invalidate_recordset()
        self.assertEqual(fake.solve_async_calls, 1)  # submitted once
        self.assertEqual(fake.poll_calls, 2)         # re-polled twice
        self.assertEqual(sc.jaot_task_id, task_id)   # same task, no re-submit
        self.assertIn(sc.state, ('queued', 'solving'))

    def test_cancel_from_solving(self):
        # cancel race: cancelling a scenario that is already solving is safe
        sc = self._scenario()
        fake = FakeJaotClient(poll_status='running')
        with self._patch_client(fake):
            sc.action_submit()
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
            self.assertEqual(sc.state, 'solving')
            sc.action_cancel()
        sc.invalidate_recordset()
        self.assertEqual(sc.state, 'cancelled')
        self.assertTrue(fake.cancelled)

    def test_cancel_rejected_from_solved(self):
        # a solved scenario cannot be cancelled
        from odoo.exceptions import UserError as _UE
        sc = self._scenario()
        sc.state = 'solved'
        with self._patch_client(FakeJaotClient()):
            with self.assertRaises(_UE):
                sc.action_cancel()
