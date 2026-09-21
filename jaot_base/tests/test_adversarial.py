# -*- coding: utf-8 -*-
# License LGPL-3
"""Adversarial tests: the edge cases and error paths the happy-path suite
does not exercise — apply atomicity and applying with missing target
records. These assert the behaviour the apply engine must have (all-or-
nothing, and never 'applied' when nothing was written), so they fail while
the engine is still broken and guard the fix."""
from unittest import mock

from odoo.exceptions import UserError
from odoo.tests import TransactionCase

from ..models.jaot_config import JaotConfig
from ..models.jaot_scenario import JaotScenario
from .common import FakeJaotClient, make_config, make_toys


class TestAdversarial(TransactionCase):

    def _company(self):
        return self.env.company

    def _solved(self, fake=None):
        recipe, _items = make_toys(self.env, self._company())
        make_config(self.env, self._company())
        sc = self.env['jaot.scenario'].create({
            'name': 'Adv', 'recipe_id': recipe.id,
            'company_id': self._company().id})
        fake = fake or FakeJaotClient()
        with mock.patch.object(JaotConfig, 'get_client', return_value=fake):
            sc.action_submit()
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        sc.invalidate_recordset()
        self.assertEqual(sc.state, 'solved')
        return sc

    def test_apply_no_target_records_does_not_apply(self):
        # Every target record is gone before apply: nothing can be written,
        # so the scenario must NOT be marked applied (no logs, and there is
        # nothing to revert). Previously it transitioned to 'applied' with
        # zero changes.
        sc = self._solved()
        self.assertTrue(sc.scenario_line_ids)
        self.env['jaot.demo.item'].search([]).unlink()
        with self.assertRaises(UserError):
            sc.action_apply()
        sc.invalidate_recordset()
        self.assertEqual(sc.state, 'solved')
        self.assertFalse(sc.applied)
        self.assertEqual(len(sc.apply_log_ids), 0)

    def test_apply_is_atomic_on_write_failure(self):
        # A write failure on a middle line must roll back the WHOLE apply:
        # no partial plan, the scenario stays 'solved', and there is nothing
        # to revert. Previously the earlier lines were already committed,
        # leaving a partial, un-revertable apply.
        sc = self._solved()
        self.assertGreaterEqual(len(sc.scenario_line_ids), 2)
        first = sc.scenario_line_ids[0]
        target = self.env[first.res_model].browse(first.res_id)
        before = target.selected
        calls = {'n': 0}
        real = JaotScenario._write_field_path

        def flaky(self_rec, rec, field_path, value):
            calls['n'] += 1
            if calls['n'] == 2:
                raise UserError('simulated write failure')
            return real(self_rec, rec, field_path, value)

        with mock.patch.object(JaotScenario, '_write_field_path', flaky):
            with self.assertRaises(UserError):
                sc.action_apply()
        sc.invalidate_recordset()
        self.assertEqual(sc.state, 'solved')
        self.assertFalse(sc.applied)
        self.assertEqual(len(sc.apply_log_ids), 0)
        target.invalidate_recordset()
        self.assertEqual(target.selected, before)

    def test_revert_is_atomic_on_write_failure(self):
        # A revert write failure on a middle change must roll the WHOLE
        # revert back: no change is restored, no log is marked reverted,
        # and the scenario stays applied. Previously the earlier changes
        # were already restored and their logs marked reverted, leaving a
        # partial, half-reverted plan.
        sc = self._solved()
        self.assertTrue(sc.scenario_line_ids)
        sc.action_apply()
        self.assertEqual(sc.state, 'applied')
        self.assertTrue(
            self.env['jaot.apply.log'].search(
                [('scenario_id', '=', sc.id), ('state', '=', 'applied')]))
        calls = {'n': 0}
        real = JaotScenario._write_field_path

        def flaky(self_rec, rec, field_path, value):
            calls['n'] += 1
            if calls['n'] >= 2:
                raise UserError('simulated revert write failure')
            return real(self_rec, rec, field_path, value)

        with mock.patch.object(JaotScenario, '_write_field_path', flaky):
            with self.assertRaises(UserError):
                sc.action_revert()
        sc.invalidate_recordset()
        self.assertEqual(sc.state, 'applied')
        self.assertFalse(
            self.env['jaot.apply.log'].search(
                [('scenario_id', '=', sc.id), ('state', '=', 'reverted')]))

    def test_revert_with_missing_target_record(self):
        # Apply, delete the target record, then revert: the missing target
        # is skipped (nothing to restore) but the revert still completes and
        # the scenario returns to solved. No crash, no stuck state.
        sc = self._solved()
        sc.action_apply()
        self.assertEqual(sc.state, 'applied')
        self.assertTrue(
            self.env['jaot.apply.log'].search(
                [('scenario_id', '=', sc.id), ('state', '=', 'applied')]))
        self.env['jaot.demo.item'].search([]).unlink()
        sc.action_revert()
        sc.invalidate_recordset()
        self.assertEqual(sc.state, 'solved')
        self.assertFalse(sc.applied)
