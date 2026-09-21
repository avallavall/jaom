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

    def test_parameter_binding_non_numeric_constant_rejected(self):
        # A parameter binding whose constant is not a number must be
        # rejected at authoring time. Extraction does float() on the
        # constant, so a non-numeric value used to sail past the Validate
        # button and binding validation and then crash scenario submission.
        recipe, _items = make_toys(self.env, self._company())
        Role = self.env['jaot.recipe.role']
        Binding = self.env['jaot.binding']
        role = Role.create({
            'recipe_id': recipe.id, 'name': 'bad_param', 'kind': 'parameter',
            'data_type': 'number', 'required': False})
        with self.assertRaises(UserError):
            Binding.create({
                'recipe_id': recipe.id, 'role_id': role.id,
                'constant_value': 'not-a-number',
                'company_id': self._company().id})

    def test_whatif_failed_job_marks_failed(self):
        # A what-if analysis job that fails after starting must mark the
        # scenario's what-if failed (with the error) and leave the scenario
        # itself still usable in its solved state — not stuck in
        # 'requested' and not taken to failed.
        fake = FakeJaotClient(scenario_analysis_job={
            'status': 'failed', 'error': 'budget exhausted'})
        sc = self._solved(fake=fake)
        with mock.patch.object(JaotConfig, 'get_client', return_value=fake):
            sc.action_run_whatif()
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        sc.invalidate_recordset()
        self.assertEqual(sc.whatif_state, 'failed')
        self.assertTrue(sc.whatif_error)
        self.assertEqual(sc.state, 'solved')

    def test_whatif_empty_analysis_completes(self):
        # A what-if job that completes with an empty analysis must finish
        # cleanly ('done', no rows) rather than crash on the missing keys.
        fake = FakeJaotClient(scenario_analysis_job={
            'status': 'completed', 'analysis': {}})
        sc = self._solved(fake=fake)
        with mock.patch.object(JaotConfig, 'get_client', return_value=fake):
            sc.action_run_whatif()
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        sc.invalidate_recordset()
        self.assertEqual(sc.whatif_state, 'done')
        self.assertEqual(len(sc.whatif_line_ids), 0)

    def test_baseline_delta_written_to_parent(self):
        # Comparing against the current plan creates a baseline scenario;
        # once it solves, the parent must carry the baseline link and the
        # delta in its KPI summary.
        fake = FakeJaotClient()
        sc = self._solved(fake=fake)
        # The offline client returns a constant task id; a real solve
        # returns a fresh one. Bump it so the baseline scenario does not
        # collide with the parent on the unique jaot_task_id constraint.
        fake.task_id = 'fake-task-2'
        fake.execution_id = 'fake-exec-2'
        with mock.patch.object(JaotConfig, 'get_client', return_value=fake):
            baseline = sc.action_compare_baseline()
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        baseline.invalidate_recordset()
        sc.invalidate_recordset()
        self.assertEqual(baseline.state, 'solved')
        self.assertTrue(sc.baseline_scenario_id)
        summary = sc.kpi_summary or {}
        self.assertIsNotNone(summary.get('baseline_objective'))
        self.assertIn('delta_vs_baseline', summary)

    def test_write_field_path_empty_intermediate_m2o_raises(self):
        # Writing a decision through a dotted path whose intermediate
        # many2one is empty must fail cleanly, not silently no-op while
        # the audit log records the write as if it happened. (Relevant to
        # any recipe/formulation that emits a dotted decision path.)
        recipe, _items = make_toys(self.env, self._company())
        sc = self.env['jaot.scenario'].create({
            'name': 'Adv', 'recipe_id': recipe.id,
            'company_id': self._company().id})
        partner = self.env['res.partner'].create({'name': 'Adv P'})
        self.assertFalse(partner.country_id)
        with self.assertRaises(UserError):
            sc._write_field_path(partner, 'country_id.name', 'X')

    def test_scenarios_are_isolated_across_companies(self):
        # A user whose only company is B and who has the JAOT read ACL must
        # not see scenarios belonging to another company: the isolation
        # comes from the record rules, not the ACL. A positive control
        # (the user sees their own company's scenario) proves the filter is
        # company-based, not access-based.
        company_a = self._company()
        company_b = self.env['res.company'].create({'name': 'Iso B'})
        recipe_a, _ = make_toys(self.env, company_a)
        make_config(self.env, company_a)
        recipe_b, _ = make_toys(self.env, company_b)
        make_config(self.env, company_b)
        sc_a = self.env['jaot.scenario'].create({
            'name': 'Iso A', 'recipe_id': recipe_a.id,
            'company_id': company_a.id})
        sc_b = self.env['jaot.scenario'].create({
            'name': 'Iso B', 'recipe_id': recipe_b.id,
            'company_id': company_b.id})
        user_b = self.env['res.users'].create({
            'name': 'Iso B user', 'login': 'iso_b_user_xyz',
            'company_id': company_b.id,
            'company_ids': [(6, 0, [company_b.id])],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('jaot_base.group_user').id])],
        })
        env_b = self.env['jaot.scenario'].with_user(user_b)
        self.assertFalse(
            env_b.search([('id', '=', sc_a.id)]),
            'a company-B user must not see a company-A scenario')
        self.assertTrue(
            env_b.search([('id', '=', sc_b.id)]),
            'a company-B user must see their own company scenario')

    def test_submit_with_empty_dataset_is_clean_error(self):
        # Solving a scenario whose source records are all gone must raise a
        # clean UserError and leave the scenario in draft — not crash, and
        # not mark it queued/failed. (Distinct from an infeasible solve: the
        # problem simply has no decision variables.)
        recipe, _items = make_toys(self.env, self._company())
        make_config(self.env, self._company())
        sc = self.env['jaot.scenario'].create({
            'name': 'Empty', 'recipe_id': recipe.id,
            'company_id': self._company().id})
        self.env['jaot.demo.item'].search([]).unlink()
        with self.assertRaises(UserError):
            sc.action_submit()
        sc.invalidate_recordset()
        self.assertEqual(sc.state, 'draft')

    def test_state_machine_invalid_transitions(self):
        # The scenario state machine must reject the wrong actions with a
        # clean error, never a crash or a bogus transition: applying a
        # draft scenario, reverting a scenario that is not applied, and
        # resubmitting an already-solved scenario are all invalid moves a
        # user can trigger from the buttons.
        recipe, _items = make_toys(self.env, self._company())
        make_config(self.env, self._company())
        sc = self.env['jaot.scenario'].create({
            'name': 'SM', 'recipe_id': recipe.id,
            'company_id': self._company().id})
        with self.assertRaises(UserError):
            sc.action_apply()
        fake = FakeJaotClient()
        with mock.patch.object(JaotConfig, 'get_client', return_value=fake):
            sc.action_submit()
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        sc.invalidate_recordset()
        self.assertEqual(sc.state, 'solved')
        with self.assertRaises(UserError):
            sc.action_revert()
        with self.assertRaises(UserError):
            sc.action_submit()
