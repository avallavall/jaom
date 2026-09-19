# -*- coding: utf-8 -*-
# License LGPL-3
from odoo import fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    jaot_vehicle_id = fields.Many2one(
        'fleet.vehicle',
        string='JAOT vehicle',
        copy=False,
        help='Vehicle assigned to this picking by an applied JAOT routing '
             'solution.')
    jaot_route_sequence = fields.Integer(
        string='JAOT route position',
        default=0,
        copy=False,
        help='Position of this picking in its vehicle route (0 = not '
             'assigned by a routing solution).')
    jaot_scenario_id = fields.Many2one(
        'jaot.scenario',
        string='JAOT scenario',
        copy=False,
        help='The last scenario whose applied solution wrote the routing '
              'fields for this picking.')
