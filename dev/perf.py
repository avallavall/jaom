# -*- coding: utf-8 -*-
# License LGPL-3
"""P5.3 performance harness (SPECS 10.1, 10.2). Run inside the odoo shell:

    Get-Content dev/perf.py | docker compose -f dev/docker-compose.yml \
        run --rm odoo odoo shell -d <db> --no-http

It seeds a 50 k-order VRP dataset (uncommitted, so it rolls back on exit),
invalidates the ORM cache so the extraction is measured cold (the realistic
worker case), then measures a 1,000-line apply and the cron reconcile load,
and prints ``PERF <label>: <seconds>s`` lines for docs/PERF.md. It never
commits.
"""
import time

from unittest import mock

from odoo.addons.jaot_base.models.jaot_config import JaotConfig

N_ORDERS = 50000
N_APPLY = 1000
N_CRON = 100


def _mark(label, t0):
    print('PERF %s: %.2fs' % (label, time.perf_counter() - t0))


env = env
company = env.company

# --------------------------------------------------------------------------
# seed: 50 k partners (geo) + 50 k confirmed outgoing pickings (+ a vehicle)
# --------------------------------------------------------------------------
t0 = time.perf_counter()
product = env['product.product'].create({
    'name': 'Perf Product', 'default_code': 'PERF-PROD',
    'company_id': company.id})
ptype = env['stock.picking.type'].search(
    [('code', '=', 'outgoing'), ('company_id', 'in', [company.id, False])],
    limit=1)
cust_loc = env['stock.location'].search(
    [('usage', '=', 'customer')], order='id', limit=1)
ware = env['stock.warehouse'].search(
    [('company_id', 'in', [company.id, False])], order='id', limit=1)
stock_loc = ware.lot_stock_id
brand = env['fleet.vehicle.model.brand'].create({'name': 'PerfBrand'})
vmodel = env['fleet.vehicle.model'].create(
    {'name': 'PerfVan', 'brand_id': brand.id})
vehicle = env['fleet.vehicle'].create(
    {'name': 'PerfVan 1', 'model_id': vmodel.id, 'company_id': company.id})

partners = env['res.partner'].create([
    {'name': 'Perf C%d' % i,
     'partner_latitude': 40.4 + (i % 500) * 0.001,
     'partner_longitude': -3.7 - (i % 500) * 0.001,
     'company_id': company.id}
    for i in range(N_ORDERS)
])
picks = env['stock.picking'].create([
    {
        'name': 'Perf P%d' % i,
        'picking_type_id': ptype.id,
        'location_id': stock_loc.id,
        'location_dest_id': cust_loc.id,
        'partner_id': partners[i].id,
        'company_id': company.id,
        'state': 'confirmed',
        'move_ids': [(0, 0, {
            'product_id': product.id, 'product_uom': product.uom_id.id,
            'quantity': 1.0, 'location_id': stock_loc.id,
            'location_dest_id': cust_loc.id})],
    } for i in range(N_ORDERS)
])
picks.write({'shipping_weight': 50.0})
matched = env['stock.picking'].search_count([
    ('picking_type_code', '=', 'outgoing'),
    ('state', 'in', ('confirmed', 'assigned'))])
_mark('seed_%d_pickings' % matched, t0)
print('PERF seed matched domain: %d pickings' % matched)

# make the cache cold so the extraction hits the DB like a real worker
picks.invalidate_recordset()
partners.invalidate_recordset()

# --------------------------------------------------------------------------
# 1. extraction at 50 k (SPECS 10.2)
# --------------------------------------------------------------------------
recipe = env['jaot.recipe'].search(
    [('code', '=', 'vrp'), ('company_id', '=', company.id)], limit=1)
if not env['jaot.config'].search([('company_id', '=', company.id)]):
    env['jaot.config'].create({'company_id': company.id,
                               'endpoint_url': 'http://perf.invalid'})
sc = env['jaot.scenario'].create({
    'name': 'Perf Extract', 'recipe_id': recipe.id,
    'company_id': company.id})
t0 = time.perf_counter()
snapshot, _hash, _bs = sc._extract_snapshot()
_mark('extract_50k_cold', t0)
print('PERF extract orders=%d vehicles=%d params=%s'
      % (len(snapshot.get('stock.picking', {})),
         len(snapshot.get('fleet.vehicle', {})),
         snapshot.get('_parameters')))

# --------------------------------------------------------------------------
# 2. apply of 1,000 lines (SPECS 10.1, target < 60 s)
# --------------------------------------------------------------------------
Line = env['jaot.scenario.line']
for i, p in enumerate(picks[:N_APPLY], start=1):
    Line.create({
        'scenario_id': sc.id, 'sequence': i * 10,
        'res_model': 'stock.picking', 'res_id': p.id,
        'decision': {'jaot_vehicle_id': vehicle.id,
                     'jaot_route_sequence': i},
        'company_id': company.id})
sc.write({'state': 'solved'})
t0 = time.perf_counter()
sc.action_apply()
_mark('apply_1000_lines', t0)
print('PERF apply logs=%d' % env['jaot.apply.log'].search_count([
    ('scenario_id', '=', sc.id), ('state', '=', 'applied')]))

# --------------------------------------------------------------------------
# 3. cron reconcile load (SPECS 10.4: idempotent + logged)
# --------------------------------------------------------------------------
class _FakeClient(object):
    def poll_task(self, task_id):
        return {'status': 'running'}


env['jaot.scenario'].create([
    {'name': 'Perf Cron %d' % i, 'recipe_id': recipe.id,
     'company_id': company.id, 'state': 'queued',
     'jaot_task_id': 'perf-task-%d' % i}
    for i in range(N_CRON)
])
t0 = time.perf_counter()
with mock.patch.object(JaotConfig, 'get_client', return_value=_FakeClient()):
    env['jaot.scenario'].reconcile_jaot_scenarios()
_mark('cron_reconcile_%d' % N_CRON, t0)
