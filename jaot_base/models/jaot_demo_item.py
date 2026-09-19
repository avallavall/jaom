from odoo import fields, models


class JaotDemoItem(models.Model):
    _name = 'jaot.demo.item'
    _description = 'JAOT toy item (knapsack fixture)'
    _rec_name = 'name'

    # Self-contained test fixture for the base-module gate (PLAN P2.8) and
    # the fast unit tests (P2.7): a 0/1 knapsack item. It is deliberately
    # not a production domain model; it exists so the base machinery
    # (extract -> formulate -> solve -> lines -> apply -> revert) can be
    # exercised end-to-end with zero domain logic.
    name = fields.Char(required=True)
    weight = fields.Float()
    value = fields.Float()
    selected = fields.Boolean(default=False)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
