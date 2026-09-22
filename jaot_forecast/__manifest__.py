# -*- coding: utf-8 -*-
# License LGPL-3
{
    'name': 'JAOT Forecast (demand forecasting for MRP)',
    'summary': 'Per-product demand forecasts (ETS / Croston) that feed the '
               'lot-sizing demand, with safety stock at a chosen service '
               'level.',
    'description': """
JAOT Forecast — demand-side bridge
===================================
Adds per-product demand forecasting to JAOT Base. For each product a
``jaot.forecast`` classifies it (ADI + ABC) over a 24-month window of
``stock.move`` history, runs the matching method (Holt ETS for smooth
demand, Croston/SBA with the (1 - beta/2) correction for intermittent
demand), and produces quantile forecasts plus a safety stock at a chosen
service level. The per-product, per-period forecast quantities live on
``jaot.forecast.demand`` rows.

The production-scheduling (lot-sizing) recipe gains two optional roles,
``forecast_demand`` and ``forecast_period``, bound by default to
``jaot.forecast.demand``. When they are bound, the lot-sizing daily
demand is committed MO quantities plus forecast quantities; when they are
unbound the recipe behaves exactly as before. Refreshing a forecast is an
explicit action (+ an optional daily cron), and a stale forecast is
flagged like a stale scenario (SPECS §4.6).
""",
    'version': '1.0.0',
    'author': 'JAOM contributors',
    'category': 'Planning',
    'license': 'LGPL-3',
    'depends': ['jaot_base', 'stock', 'jaot_mrp'],
    'auto_install': ['jaot_mrp'],
    'data': [
        'security/ir.model.access.csv',
        'data/jaot_forecast_roles.xml',
        'data/jaot_forecast_cron.xml',
        'views/jaot_forecast_views.xml',
    ],
    'application': False,
    'installable': True,
}
