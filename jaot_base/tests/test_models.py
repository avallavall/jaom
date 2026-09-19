# -*- coding: utf-8 -*-
# License LGPL-3
"""Per-model tests for jaot_base (PLAN P2.7): validation, constraints and
key masking, all offline."""
from psycopg2 import IntegrityError
from odoo.exceptions import UserError
from odoo.tests import TransactionCase

from .common import make_config, make_toys


class TestConfig(TransactionCase):

    def _company(self):
        return self.env.company

    def test_api_key_stored_and_masked(self):
        cfg = self.env['jaot.config'].create({
            'company_id': self._company().id,
            'endpoint_url': 'http://fake',
            'api_key_input': 'secretkey123',
        })
        self.assertTrue(cfg.api_key_set)
        self.assertEqual(cfg.api_key_masked, 'secr…y123')
        # the raw key never lives on the model
        self.assertNotIn('secretkey123', cfg.api_key_masked)

    def test_key_cleared(self):
        cfg = self.env['jaot.config'].create({
            'company_id': self._company().id,
            'endpoint_url': 'http://fake',
            'api_key_input': 'secretkey123',
        })
        cfg.action_clear_api_key()
        self.assertFalse(cfg.api_key_set)

    def test_one_config_per_company(self):
        self.env['jaot.config'].create({
            'company_id': self._company().id,
            'endpoint_url': 'http://a'})
        with self.assertRaises(IntegrityError):
            self.env['jaot.config'].create({
                'company_id': self._company().id,
                'endpoint_url': 'http://b'})


class TestRecipeAndBinding(TransactionCase):

    def _recipe_with_role(self, kind, data_type='number'):
        recipe, _ = make_toys(self.env, self._company())
        role = self.env['jaot.recipe.role'].search(
            [('recipe_id', '=', recipe.id), ('kind', '=', kind)])
        return recipe, role

    def _company(self):
        return self.env.company

    def test_parameter_role_needs_constant_value(self):
        recipe, role = make_toys(self.env, self._company())
        capacity_role = self.env['jaot.recipe.role'].search(
            [('recipe_id', '=', recipe.id), ('name', '=', 'capacity')])
        with self.assertRaises(UserError):
            self.env['jaot.binding'].create({
                'recipe_id': recipe.id,
                'role_id': capacity_role.id,
                'company_id': self._company().id,
            })

    def test_variable_role_needs_source_model(self):
        recipe, _ = make_toys(self.env, self._company())
        weight_role = self.env['jaot.recipe.role'].search(
            [('recipe_id', '=', recipe.id), ('name', '=', 'weight')])
        with self.assertRaises(UserError):
            self.env['jaot.binding'].create({
                'recipe_id': recipe.id,
                'role_id': weight_role.id,
                'company_id': self._company().id,
            })

    def test_bad_expression_rejected(self):
        recipe, _ = make_toys(self.env, self._company())
        weight_role = self.env['jaot.recipe.role'].search(
            [('recipe_id', '=', recipe.id), ('name', '=', 'weight')])
        with self.assertRaises(UserError):
            self.env['jaot.binding'].create({
                'recipe_id': recipe.id,
                'role_id': weight_role.id,
                'res_model': 'jaot.demo.item',
                'field_path': 'weight',
                'expression': '1 +',
                'company_id': self._company().id,
            })

    def test_bad_domain_rejected(self):
        recipe, _ = make_toys(self.env, self._company())
        weight_role = self.env['jaot.recipe.role'].search(
            [('recipe_id', '=', recipe.id), ('name', '=', 'weight')])
        with self.assertRaises(UserError):
            self.env['jaot.binding'].create({
                'recipe_id': recipe.id,
                'role_id': weight_role.id,
                'res_model': 'jaot.demo.item',
                'domain': "[('name','=',1",
                'company_id': self._company().id,
            })

    def test_one_binding_per_role_per_company(self):
        company = self._company()
        # A fresh recipe + role with no binding, so the first create is
        # clean and only the second one hits the unique constraint.
        recipe = self.env['jaot.recipe'].create({
            'code': 'uniq_recipe', 'name': 'Uniq', 'domain': 'stock',
            'company_id': company.id})
        role = self.env['jaot.recipe.role'].create({
            'recipe_id': recipe.id, 'name': 'x', 'kind': 'variable',
            'data_type': 'number', 'required': True})
        self.env['jaot.binding'].create({
            'recipe_id': recipe.id,
            'role_id': role.id,
            'res_model': 'jaot.demo.item',
            'field_path': 'name',
            'company_id': company.id,
        })
        with self.assertRaises(IntegrityError):
            self.env['jaot.binding'].create({
                'recipe_id': recipe.id,
                'role_id': role.id,
                'res_model': 'jaot.demo.item',
                'field_path': 'name',
                'company_id': company.id,
            })


class TestScenario(TransactionCase):

    def _company(self):
        return self.env.company

    def test_applied_requires_applied_state(self):
        recipe, _ = make_toys(self.env, self._company())
        make_config(self.env, self._company())
        with self.assertRaises(UserError):
            self.env['jaot.scenario'].create({
                'name': 'bad', 'recipe_id': recipe.id,
                'company_id': self._company().id,
                'state': 'solved', 'applied': True,
            })

    def test_draft_scenario_valid(self):
        recipe, _ = make_toys(self.env, self._company())
        make_config(self.env, self._company())
        sc = self.env['jaot.scenario'].create({
            'name': 'ok', 'recipe_id': recipe.id,
            'company_id': self._company().id,
        })
        self.assertEqual(sc.state, 'draft')
        self.assertFalse(sc.applied)
