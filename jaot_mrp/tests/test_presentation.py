# -*- coding: utf-8 -*-
# License LGPL-3
"""Presentation access tests for MRP scenarios (P9.7).

A scenario line that points at an ``mrp.production`` must stay readable for a
user who can read the scenario but NOT the manufacturing order (no MRP group):
the presentation computes degrade to safe, id-free labels instead of leaking a
machine identifier or raising ``AccessError``. The admin still sees the real
record name (no over-redaction). The ``mrp`` recipe and ``mrp.production`` only
exist once this module is loaded, so these tests live here rather than in
``jaot_base``.

The two assertions run in separate test methods: the presentation fields are
non-stored computes whose value depends on the reading user, so they are
accessed once per method in a clean environment (each ``TransactionCase``
method rolls back to its own savepoint and cache).
"""
from odoo.tests import TransactionCase


class TestMrpPresentationAccess(TransactionCase):

    def _company(self):
        return self.env.company

    def _line_with_mo(self):
        company = self._company()
        recipe = self.env['jaot.recipe'].search(
            [('code', '=', 'mrp'), ('company_id', '=', company.id)], limit=1)
        self.assertTrue(recipe, 'mrp recipe missing from installed data')
        product = self.env['product.product'].create({
            'name': 'Acc prod', 'type': 'consu'})
        mo = self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': 1,
            'date_start': '2026-10-06 08:00:00',
            'company_id': company.id})
        mo.action_confirm()
        scenario = self.env['jaot.scenario'].create({
            'name': 'Access', 'recipe_id': recipe.id,
            'company_id': company.id})
        line = self.env['jaot.scenario.line'].create({
            'scenario_id': scenario.id, 'sequence': 10,
            'res_model': 'mrp.production', 'res_id': mo.id,
            'decision': {'date_start': '2026-10-06 08:00:00'},
            'company_id': company.id})
        return line, mo

    def test_admin_sees_real_record_name(self):
        # the admin (full access) sees the real record name and a rendered
        # decision — the safe fallback must not over-redact
        line, mo = self._line_with_mo()
        self.assertEqual(line.record_label, mo.display_name)
        self.assertEqual(line.decision_text, 'Start 2026-10-06')
        self.assertNotIn('{', line.decision_text)

    def test_viewer_sees_safe_id_free_labels(self):
        # a user with only the JAOT read group cannot read the MO: the three
        # presentation fields must not raise and must be id-free
        line, mo = self._line_with_mo()
        user = self.env['res.users'].create({
            'name': 'Acc reader', 'login': 'acc_reader_xyz',
            'company_id': self._company().id,
            'company_ids': [(6, 0, [self._company().id])],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('jaot_base.group_user').id])],
        })
        vline = self.env['jaot.scenario.line'].with_user(user).browse(line.id)
        self.assertNotIn(str(mo.id), vline.record_label)
        self.assertNotIn(str(mo.id), vline.decision_text)
        self.assertNotIn(str(mo.id), vline.change_preview)
        self.assertTrue(vline.record_label)
