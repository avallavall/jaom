# -*- coding: utf-8 -*-
# License LGPL-3
{
    'name': 'JAOT MRP (production scheduling)',
    'summary': 'Production scheduling (lot sizing) bridge for JAOT: the '
               'lot-sizing recipe, default bindings over mrp.production, '
               'extraction and apply.',
    'description': """
JAOT MRP — production scheduling bridge
=========================================
Adds the production-scheduling domain to JAOT Base. On install it creates
the ``mrp`` recipe and its default bindings over ``mrp.production``
(orders: ``product_qty`` + ``date_deadline``), plus the parameters a
Community install has no standard source for (daily capacity, setup and
holding costs — parameter bindings, per the P1.2 finding F1 pattern).

Formulation: single-machine capacitated lot sizing. Each order is
produced on one or more days at or before its deadline, subject to a
daily capacity; the objective trades per-lot setup cost against
per-unit, per-day inventory-holding cost. A solution writes ``date_start``
on the production orders (the day the lot is produced).
""",
    'version': '1.0.0',
    'author': 'JAOM contributors',
    'category': 'Planning',
    'license': 'LGPL-3',
    'depends': ['jaot_base', 'mrp'],
    'auto_install': ['mrp'],
    'data': [
        'data/jaot_mrp_recipe.xml',
        'views/mrp_production_views.xml',
        'views/jaot_scenario_views.xml',
    ],
    'application': False,
    'installable': True,
}
