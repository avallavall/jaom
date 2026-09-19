# -*- coding: utf-8 -*-
# License LGPL-3
{
    'name': 'JAOT Base',
    'summary': 'Thin client of a self-hosted JAOT optimization platform: '
               'recipes, role-based bindings, async solves, scenarios, apply.',
    'description': """
JAOT Base
=========
Brings real mathematical optimization into Odoo as a thin client of a
self-hosted JAOT instance (one per company): extract a compact problem
instance from Odoo records, formulate it from a recipe with role-based
bindings, solve asynchronously (ir.cron polling, never inside a request),
materialize the answer as an auditable scenario, and apply it to Odoo
records only on explicit human action.

No solver runs inside Odoo. No write happens without confirmation.
""",
    'version': '1.0.0',
    'author': 'JAOM contributors',
    'category': 'Productivity',
    'license': 'LGPL-3',
    'depends': ['base', 'mail'],
    'data': [
        'security/jaot_security.xml',
        'security/ir.model.access.csv',
        'security/jaot_rules.xml',
        'views/jaot_menus.xml',
        'views/jaot_recipe_views.xml',
        'views/jaot_config_views.xml',
    ],
    'application': True,
    'installable': True,
}
