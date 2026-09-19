# -*- coding: utf-8 -*-
# License LGPL-3
{
    'name': 'JAOT Stock (delivery routing)',
    'summary': 'Delivery routing (VRP) bridge for JAOT: the VRP recipe, '
               'default bindings over stock/fleet, extraction and apply.',
    'description': """
JAOT Stock — delivery routing bridge
=====================================
Adds the delivery-routing (VRP) domain to JAOT Base. On install it creates
the ``vrp`` recipe and its default bindings over ``stock.picking`` (orders),
``stock.warehouse`` (depot geo) and ``fleet.vehicle`` (fleet), and extends
``stock.picking`` with the fields an applied solution writes to
(``jaot_vehicle_id``, ``jaot_route_sequence``).

Formulation: arc-flow + MTZ vehicle routing, minimising total distance
(haversine). v1 uses haversine distance; a real road-distance provider
(OSRM) is a P5+ enhancement and a dependency decision, not a default.
""",
    'version': '1.0.0',
    'author': 'JAOM contributors',
    'category': 'Planning',
    'license': 'LGPL-3',
    'depends': ['jaot_base', 'stock', 'fleet'],
    'auto_install': ['stock', 'fleet'],
    'data': [
        'data/jaot_vrp_recipe.xml',
        'views/stock_picking_views.xml',
        'views/jaot_scenario_views.xml',
    ],
    'application': False,
    'installable': True,
}
