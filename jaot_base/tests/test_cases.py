# -*- coding: utf-8 -*-
# License LGPL-3
"""Offline tests for named scenario cases (SPECS 13.2, PLAN P9.2).

A case perturbs a solved scenario's parameter roles (set/scale), re-solves
as a normal child scenario, mirrors the run state, and stores the line
comparison against the parent baseline (or the parent).
"""
from unittest import mock

from odoo.exceptions import UserError
from odoo.tests import TransactionCase

from ..models.jaot_config import JaotConfig
from .common import FakeJaotClient, make_config, make_toys


class TestNamedCases(TransactionCase):

    def _company(self):
        return self.env.company

    def _solved_parent(self):
        recipe, _items = make_toys(self.env, self._company())
        make_config(self.env, self._company())
        parent = self.env['jaot.scenario'].create({
            'name': 'Case parent', 'recipe_id': recipe.id,
            'company_id': self._company().id,
        })
        fake = FakeJaotClient()
        with mock.patch.object(JaotConfig, 'get_client',
                               return_value=fake):
            parent.action_submit()
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        self.assertEqual(parent.state, 'solved')
        return parent

    def _capacity_role(self, parent):
        return self.env['jaot.recipe.role'].search([
            ('recipe_id', '=', parent.recipe_id.id),
            ('name', '=', 'capacity'),
        ])

    def _item_role(self, parent):
        return self.env['jaot.recipe.role'].search([
            ('recipe_id', '=', parent.recipe_id.id),
            ('name', '=', 'item'),
        ])

    def _case(self, parent, perturbation, name='Case A'):
        return self.env['jaot.scenario.case'].create({
            'name': name,
            'scenario_id': parent.id,
            'perturbation': perturbation,
            'company_id': self._company().id,
        })

    # -- run guards ------------------------------------------------------
    def test_run_requires_solved_parent(self):
        recipe, _items = make_toys(self.env, self._company())
        make_config(self.env, self._company())
        draft = self.env['jaot.scenario'].create({
            'name': 'Draft parent', 'recipe_id': recipe.id,
            'company_id': self._company().id,
        })
        role = self.env['jaot.recipe.role'].search([
            ('recipe_id', '=', recipe.id), ('name', '=', 'capacity')])
        case = self._case(draft, [{'role_id': role.id,
                                   'mode': 'set', 'value': 100}])
        with self.assertRaises(UserError):
            case.action_run_case()
        self.assertFalse(case.case_run_id)

    def test_rejects_non_parameter_role(self):
        parent = self._solved_parent()
        case = self._case(
            parent, [{'role_id': self._item_role(parent).id,
                      'mode': 'set', 'value': 1}])
        with self.assertRaises(UserError):
            case.action_run_case()

    def test_rejects_unknown_role(self):
        parent = self._solved_parent()
        case = self._case(
            parent, [{'role_id': 999999, 'mode': 'set', 'value': 1}])
        with self.assertRaises(UserError):
            case.action_run_case()

    def test_rejects_bad_mode_or_value(self):
        parent = self._solved_parent()
        role = self._capacity_role(parent)
        for bad in ([{'role_id': role.id, 'mode': 'nudge', 'value': 1}],
                    [{'role_id': role.id, 'mode': 'set', 'value': 'many'}]):
            case = self._case(parent, bad, name='bad %s' % bad)
            with self.assertRaises(UserError):
                case.action_run_case()
        # a list of non-objects persists fine as JSON but is rejected
        # (an empty list cannot be persisted at all — the ORM maps it to
        # NULL and required rejects it at create)
        case = self._case(parent, [42], name='bad [42]')
        with self.assertRaises(UserError):
            case.action_run_case()

    # -- parameter overrides in extraction -------------------------------
    def test_overrides_set_and_scale(self):
        parent = self._solved_parent()
        role = self._capacity_role(parent)
        base_snapshot, _h, _b = parent._extract_snapshot()
        self.assertEqual(base_snapshot['_parameters']['capacity'], 50.0)

        set_sc = self.env['jaot.scenario'].create({
            'name': 'set', 'recipe_id': parent.recipe_id.id,
            'company_id': self._company().id,
            'parameter_overrides': [
                {'role_id': role.id, 'mode': 'set', 'value': 555}],
        })
        snap, _h, _b = set_sc._extract_snapshot()
        self.assertEqual(snap['_parameters']['capacity'], 555.0)

        scale_sc = self.env['jaot.scenario'].create({
            'name': 'scale', 'recipe_id': parent.recipe_id.id,
            'company_id': self._company().id,
            'parameter_overrides': [
                {'role_id': role.id, 'mode': 'scale', 'value': 2}],
        })
        snap, _h, _b = scale_sc._extract_snapshot()
        self.assertEqual(snap['_parameters']['capacity'], 100.0)

    def test_overrides_scale_requires_current_value(self):
        parent = self._solved_parent()
        role = self.env['jaot.recipe.role'].create({
            'recipe_id': parent.recipe_id.id, 'name': 'unbound_param',
            'kind': 'parameter', 'data_type': 'number', 'required': False})
        sc = self.env['jaot.scenario'].create({
            'name': 'scale missing', 'recipe_id': parent.recipe_id.id,
            'company_id': self._company().id,
            'parameter_overrides': [
                {'role_id': role.id, 'mode': 'scale', 'value': 2}],
        })
        with self.assertRaises(UserError):
            sc._extract_snapshot()

    # -- run + reconcile ---------------------------------------------------
    def test_case_lifecycle(self):
        parent = self._solved_parent()
        role = self._capacity_role(parent)
        # a very large capacity: the greedy stand-in selects everything,
        # so the case is never worse than the parent (maximize)
        case = self._case(
            parent, [{'role_id': role.id, 'mode': 'set', 'value': 10000}],
            name='Big capacity')
        self.assertEqual(case.state, 'draft')
        fake = FakeJaotClient()
        with mock.patch.object(JaotConfig, 'get_client',
                               return_value=fake):
            case.action_run_case()
        child = case.case_run_id
        self.assertTrue(child)
        self.assertEqual(child.parameter_overrides, case.perturbation)
        self.assertIn('case Big capacity', child.name)
        self.assertEqual(child.state, 'queued')
        self.assertEqual(case.state, 'queued')  # state mirrors the run
        # the case run's snapshot hash differs from the parent's (the
        # override changed the data before the hash)
        self.assertNotEqual(child.data_snapshot_hash,
                            parent.data_snapshot_hash)
        with mock.patch.object(JaotConfig, 'get_client',
                               return_value=fake):
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        self.assertEqual(child.state, 'solved')
        self.assertEqual(case.state, 'solved')
        # the case selects every item
        self.assertTrue(all(l.decision.get('selected')
                            for l in child.scenario_line_ids))
        self.assertGreaterEqual(case.objective_delta_vs_parent, 0.0)
        # lines the parent left unselected are exactly the changed ones,
        # and the line deltas were written against the parent (there is
        # no baseline for it)
        parent_unselected = sum(
            1 for l in parent.scenario_line_ids
            if not l.decision.get('selected'))
        self.assertEqual(case.line_changes, parent_unselected)
        for line in child.scenario_line_ids.filtered(
                lambda l: l.delta_vs_baseline):
            self.assertIn('selected', line.delta_vs_baseline)

    def test_failed_run_mirrors_and_keeps_zero_deltas(self):
        parent = self._solved_parent()
        role = self._capacity_role(parent)
        case = self._case(
            parent, [{'role_id': role.id, 'mode': 'set', 'value': 0}])
        fake = FakeJaotClient(solver_status='infeasible')
        with mock.patch.object(JaotConfig, 'get_client',
                               return_value=fake):
            case.action_run_case()
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
        self.assertEqual(case.state, 'failed')
        self.assertEqual(case.case_run_id.state, 'failed')
        self.assertEqual(case.line_changes, 0)
        self.assertFalse(case.objective_delta_vs_parent)

    # -- parallelism cap (SPECS 13.2) -------------------------------------
    def test_max_parallel_cases(self):
        parent = self._solved_parent()
        role = self._capacity_role(parent)
        cfg = self.env['jaot.config'].search(
            [('company_id', '=', self._company().id)])
        cfg.max_parallel_cases = 2
        cases = self.env['jaot.scenario.case']
        # a fresh fake per submit: one task id per scenario (the mock
        # replaces the class attribute, so it is called unbound — no self)
        patch = mock.patch.object(
            JaotConfig, 'get_client',
            side_effect=lambda *args: FakeJaotClient())
        with patch:
            for i in range(2):
                case = cases.create({
                    'name': 'open %d' % i, 'scenario_id': parent.id,
                    'perturbation': [
                        {'role_id': role.id, 'mode': 'set',
                         'value': 100 + i}],
                    'company_id': self._company().id,
                })
                case.action_run_case()
            self.assertEqual(
                cases.search_count([('state', 'in',
                                    ('queued', 'solving'))]), 2)
            third = cases.create({
                'name': 'third', 'scenario_id': parent.id,
                'perturbation': [
                    {'role_id': role.id, 'mode': 'set', 'value': 102}],
                'company_id': self._company().id,
            })
            with self.assertRaises(UserError):
                third.action_run_case()
        # once one run finishes, the slot frees up
        with patch:
            self.env['jaot.scenario'].reconcile_jaot_scenarios()
            third.action_run_case()
        self.assertTrue(third.case_run_id)
