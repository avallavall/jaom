# -*- coding: utf-8 -*-
# License LGPL-3
from odoo import fields, models


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    jaot_scenario_id = fields.Many2one(
        'jaot.scenario',
        string='JAOT scenario',
        copy=False,
        help='The last scenario whose applied solution wrote the start '
             'date for this production order.')
