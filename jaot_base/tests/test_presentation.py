# -*- coding: utf-8 -*-
# License LGPL-3
"""Human-readable presentation tests (P9.7, offline).

Drives a toy scenario to the ``solved`` state with a deterministic fake
client and checks the manager-facing computes: the plain-language
``decision_text`` / ``record_label`` / ``change_preview`` on the scenario
lines, and the unit-labelled ``kpi_headline`` on the scenario.
"""
from unittest import mock

from odoo.tests import TransactionCase

from ..models.jaot_config import JaotConfig
from .common import FakeJaotClient, make_config, make_toys


class TestScenarioPresentation(TransactionCase):

    def _company(self):
        return self.env.company

    def _scenario(self):
        recipe, items = make_toys(self.env, self._company())
        make_config(self.env, self._company())
        scenario = self.env['jaot.scenario'].create({
            'name': 'Presentation', 'recipe_id': recipe.id,
            'company_id': self._company().id,
        })
        return scenario, items

    def _patch_client(self, fake):
        return mock.patch.object(JaotConfig, 'get_client',
                                 return_value=fake)

    def _solve(self, scenario, fake):
        with self._patch_client(fake):
            scenario.action_submit()
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        self.assertEqual(scenario.state, 'solved')
        return scenario

    # -- scenario lines -------------------------------------------------
    def test_lines_are_plain_language(self):
        scenario, items = self._scenario()
        a = items[0]
        # a deterministic solution: item a is selected, the rest are not
        fake = FakeJaotClient(model_values={'x_%d' % a.id: 1})
        scenario = self._solve(scenario, fake)

        a_line = scenario.scenario_line_ids.filtered(
            lambda l: l.res_id == a.id)
        b_line = scenario.scenario_line_ids.filtered(
            lambda l: l.res_id == items[1].id)

        # decision text is plain language, not the raw decision dict
        self.assertEqual(a_line.decision_text, 'Selected')
        self.assertNotIn('{', a_line.decision_text)
        self.assertEqual(b_line.decision_text, 'Not selected')
        # the record is labelled with its display name
        self.assertEqual(a_line.record_label, a.display_name)

    def test_change_preview_before_and_after_apply(self):
        scenario, items = self._scenario()
        a = items[0]
        fake = FakeJaotClient(model_values={'x_%d' % a.id: 1})
        scenario = self._solve(scenario, fake)

        # the current plan differs from the recommendation: everything is
        # currently off, item a is recommended on
        items.write({'selected': False})
        scenario.scenario_line_ids.invalidate_recordset()
        a_line = scenario.scenario_line_ids.filtered(
            lambda l: l.res_id == a.id)
        b_line = scenario.scenario_line_ids.filtered(
            lambda l: l.res_id == items[1].id)
        self.assertIn('->', a_line.change_preview)
        self.assertNotEqual(a_line.change_preview, 'Unchanged')
        self.assertEqual(b_line.change_preview, 'Unchanged')

        scenario.action_apply()
        self.assertEqual(scenario.state, 'applied')
        # once applied the recommendation matches the records: no change
        scenario.scenario_line_ids.invalidate_recordset()
        self.assertTrue(all(
            l.change_preview == 'Unchanged'
            for l in scenario.scenario_line_ids))

    def test_change_preview_missing_record(self):
        scenario, items = self._scenario()
        a = items[0]
        fake = FakeJaotClient(model_values={'x_%d' % a.id: 1})
        scenario = self._solve(scenario, fake)
        items.unlink()
        scenario.scenario_line_ids.invalidate_recordset()
        self.assertTrue(all(
            'no longer exists' in l.change_preview
            for l in scenario.scenario_line_ids))

    # -- kpi headline ---------------------------------------------------
    def test_objective_unit_and_headline_objective_only(self):
        scenario, items = self._scenario()
        fake = FakeJaotClient(model_values={'x_%d' % items[0].id: 1})
        scenario = self._solve(scenario, fake)

        # the toy knapsack objective is unitless
        self.assertEqual(scenario.objective_unit, '')
        # no baseline yet: the headline states the objective only, in the
        # maximise sense
        self.assertIn('maximized', scenario.kpi_headline)
        self.assertNotIn('versus your current plan', scenario.kpi_headline)

    def _headline_for(self, scenario, kpi):
        scenario.kpi_summary = kpi
        scenario.invalidate_recordset()
        return scenario.kpi_headline

    def test_headline_improvement_branches(self):
        scenario, items = self._scenario()
        fake = FakeJaotClient(model_values={'x_%d' % items[0].id: 1})
        scenario = self._solve(scenario, fake)

        # minimise: better than baseline -> "Saves"
        self.assertTrue(self._headline_for(scenario, {
            'baseline_objective': 100.0, 'optimized_objective': 80.0,
            'delta_vs_baseline': 20.0, 'sense': 'minimize'
        }).startswith('Saves 20.00 (20.0%) versus your current plan'))
        # maximise: better than baseline -> "Gains"
        self.assertTrue(self._headline_for(scenario, {
            'baseline_objective': 100.0, 'optimized_objective': 120.0,
            'delta_vs_baseline': 20.0, 'sense': 'maximize'
        }).startswith('Gains 20.00 (20.0%) versus your current plan'))
        # worse than baseline -> "Worse by"
        self.assertTrue(self._headline_for(scenario, {
            'baseline_objective': 100.0, 'optimized_objective': 120.0,
            'delta_vs_baseline': -20.0, 'sense': 'minimize'
        }).startswith('Worse by 20.00 (20.0%) than your current plan'))
