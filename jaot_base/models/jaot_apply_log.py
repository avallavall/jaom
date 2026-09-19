from odoo import fields, models


class JaotApplyLog(models.Model):
    _name = 'jaot.apply.log'
    _description = 'JAOT apply audit log'

    # One row per (record, field) write performed by an Apply (SPECS §5.7,
    # §7.5). The before-state is what makes a scenario revertible: Revert
    # re-applies these before_values through the same machinery.
    scenario_id = fields.Many2one(
        'jaot.scenario', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    res_model = fields.Char(string='Odoo model')
    res_id = fields.Integer(string='Odoo record id')
    field_path = fields.Char(string='Field path')
    before_value = fields.Json(string='Before value')
    after_value = fields.Json(string='After value')
    state = fields.Selection([
        ('applied', 'Applied'),
        ('reverted', 'Reverted'),
    ], default='applied', required=True)
    applied_at = fields.Datetime(copy=False)
    reverted_at = fields.Datetime(copy=False)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        copy=False)
