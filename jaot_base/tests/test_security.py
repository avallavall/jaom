# -*- coding: utf-8 -*-
# License LGPL-3
"""Security pass (PLAN P5.2, SPECS §7): company isolation, safe_eval
negative paths and API-key handling, all offline."""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase

from ..jaot_expr import evaluate, evaluate_domain, validate_domain
from .common import make_config, make_toys


class TestCompanyIsolation(TransactionCase):

    def test_extraction_excludes_other_company(self):
        # A scenario of company A must never extract records owned by
        # company B: the extraction domain is company-filtered (SPECS 7.2).
        company_a = self.env.company
        company_b = self.env['res.company'].create({'name': 'Company B'})
        recipe, items_a = make_toys(self.env, company_a)
        make_config(self.env, company_a)
        Item = self.env['jaot.demo.item']
        items_b = Item.create([
            {'name': 'B-%d' % i, 'weight': 5.0, 'value': 10.0,
             'selected': False, 'company_id': company_b.id}
            for i in range(3)
        ])
        scenario = self.env['jaot.scenario'].create({
            'name': 'A', 'recipe_id': recipe.id,
            'company_id': company_a.id})
        snapshot, _h, _bs = scenario._extract_snapshot()
        extracted = set(snapshot.get('jaot.demo.item', {}).keys())
        self.assertTrue(set(items_a.ids) <= extracted)
        self.assertFalse(set(items_b.ids) & extracted)

    def test_scenario_never_mixed_companies(self):
        # A single scenario carries one company; a recipe whose bindings
        # belong to another company cannot be extracted for this scenario
        # (the required-role dry-run fails, an explicit error not a union).
        company_a = self.env.company
        company_b = self.env['res.company'].create({'name': 'Company B'})
        # recipe bound only for company B (no binding for A)
        recipe_b, _ = make_toys(self.env, company_b)
        make_config(self.env, company_a)
        scenario = self.env['jaot.scenario'].create({
            'name': 'A-only', 'recipe_id': recipe_b.id,
            'company_id': company_a.id})
        with self.assertRaises(UserError):
            scenario._extract_snapshot()


class TestSafeEval(TransactionCase):

    def test_expression_refuses_dangerous_builtin(self):
        with self.assertRaises(UserError):
            evaluate("__import__('os')", {})

    def test_expression_refuses_unreachable_name(self):
        with self.assertRaises(UserError):
            evaluate("open('/etc/passwd')", {})

    def test_expression_valid_evaluates(self):
        self.assertEqual(evaluate("weight * 2", {'weight': 3}), 6)
        self.assertEqual(evaluate("max(a, b)", {'a': 1, 'b': 2}), 2)

    def test_domain_refuses_dangerous(self):
        with self.assertRaises(UserError):
            validate_domain("[('name','=',__import__('os'))]")

    def test_domain_valid_parses(self):
        self.assertEqual(
            [tuple(d) for d in evaluate_domain(
                "[('name','=','x')]")],
            [('name', '=', 'x')])


class TestApiKey(TransactionCase):

    def _make(self, key):
        return self.env['jaot.config'].create({
            'company_id': self.env.company.id,
            'endpoint_url': 'http://fake',
            'api_key_input': key,
        })

    def test_key_stored_in_config_parameter(self):
        cfg = self._make('supersecret000')
        param = self.env['jaot.config']._api_key_param(cfg.company_id.id)
        value = self.env['ir.config_parameter'].get_param(param)
        self.assertEqual(value, 'supersecret000')

    def test_key_masked_never_full(self):
        cfg = self._make('supersecret000')
        self.assertTrue(cfg.api_key_set)
        self.assertNotIn('supersecret000', cfg.api_key_masked)
        # the model itself never carries the raw key
        self.assertNotIn('supersecret000', str(cfg.api_key_masked))

    def test_key_clear_removes_parameter(self):
        cfg = self._make('supersecret000')
        cfg.action_clear_api_key()
        param = self.env['jaot.config']._api_key_param(cfg.company_id.id)
        self.assertFalse(
            self.env['ir.config_parameter'].get_param(param))
        self.assertFalse(cfg.api_key_set)
