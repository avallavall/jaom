# Seed script for the `e2e` database.
#
# Run from the odoo container (repo root is RO-mounted at /mnt/extra-addons):
#
#   docker compose -f dev/docker-compose.yml run --rm odoo \
#     odoo shell -d e2e --no-http < dev/e2e/seed_e2e.py
#
# Idempotent: every record is found-or-created, so re-running it never
# duplicates data (the previous version re-created fleet vehicles on every
# run because `fleet.vehicle.name` is a computed field — brand/model/plate —
# and therefore could not be used as a lookup key). The VRP recipe binds the
# whole active fleet, so orphan vehicles would silently change the routing
# problem; this now keeps exactly two active vehicles.
#
# The odoo shell always rolls back on exit, so the seed commits explicitly.
from datetime import datetime

# ---------------------------------------------------------------- users
# The manager needs write access to the operational records the scenarios
# write to when applied (mrp.production, stock.picking) and read access to
# fleet.vehicle, on top of JAOT management.
mgr_groups = [
    env.ref('base.group_user').id,
    env.ref('jaot_base.group_manager').id,
    env.ref('base.group_multi_company').id,
    env.ref('stock.group_stock_user').id,
    env.ref('mrp.group_mrp_user').id,
    env.ref('fleet.fleet_group_user').id,
]
viewer_groups = [
    env.ref('base.group_user').id,
    env.ref('jaot_base.group_user').id,
]
admin_groups = [
    env.ref('base.group_user').id,
    env.ref('base.group_system').id,
    env.ref('base.group_multi_company').id,
]
for login, name, groups in [
    ('jaotmgr', 'E2E Manager', mgr_groups),
    ('jaotview', 'E2E Viewer', viewer_groups),
    # System admin: positive control for the group_system-only fields
    # (expression column, JAOT identifiers, payloads tab).
    ('e2eadmin', 'E2E Admin', admin_groups),
]:
    user = env['res.users'].search([('login', '=', login)], limit=1)
    if not user:
        user = env['res.users'].create({
            'login': login, 'name': name, 'email': f'{login}@e2e.local',
            'group_ids': [(6, 0, groups)],
        })
    else:
        user.write({'group_ids': [(6, 0, groups)]})
    # Odoo 19: the login password is a crypt hash stored via
    # _set_encrypted_password; res.users.password is a compute field and drops
    # plain writes.
    ctx = user._crypt_context()
    user._set_encrypted_password(user.id, ctx.hash('JaotE2e-1!'))
    print('user', login, '->', user.id, 'groups:',
          user.group_ids.mapped('name'))

# ---------------------------------------------------------------- company B
comp_b = env['res.company'].search([('name', '=', 'E2E B')], limit=1)
if not comp_b:
    comp_b = env['res.company'].create({'name': 'E2E B'})
mgr = env['res.users'].search([('login', '=', 'jaotmgr')], limit=1)
if 'company_ids' in mgr._fields and comp_b not in mgr.company_ids:
    mgr.company_ids = [(4, comp_b.id)]
print('company B:', comp_b.id, '| mgr companies:',
      mgr.company_ids.mapped('name'))

# ---------------------------------------------------------------- product
product = env['product.product'].search(
    [('name', '=', 'E2E Widget')], limit=1)
if not product:
    product = env['product.product'].create(
        {'name': 'E2E Widget', 'type': 'consu', 'weight': 10.0})
print('product:', product.id, 'weight:', product.weight)

# ---------------------------------------------------------------- MRP orders
wh = env.ref('stock.warehouse0')
mo_specs = [
    (100.0, '2026-10-05'), (100.0, '2026-10-05'),
    (150.0, '2026-10-06'), (150.0, '2026-10-06'),
]
incumbent = datetime(2026, 10, 5, 6, 0, 0)
for i, (qty, due) in enumerate(mo_specs, start=1):
    mo = env['mrp.production'].search(
        [('name', '=', f'E2E MO {i}')], limit=1)
    if not mo:
        mo = env['mrp.production'].create({
            'name': f'E2E MO {i}',
            'product_id': product.id, 'product_qty': qty,
            'warehouse_id': wh.id,
        })
        mo.action_confirm()
    mo.date_start = incumbent
    mo.move_finished_ids.date_deadline = due
    print('mo:', mo.id, 'qty:', mo.product_qty, 'state:', mo.state,
          'start:', mo.date_start,
          'deadline:', mo.move_finished_ids.date_deadline)

# ---------------------------------------------------------------- routing
wh.partner_id.partner_latitude = 40.4168
wh.partner_id.partner_longitude = -3.7038
print('depot geo:', wh.partner_id.partner_latitude,
      wh.partner_id.partner_longitude)

brand = env['fleet.vehicle.model.brand'].search(
    [('name', '=', 'E2E Brand')], limit=1)
if not brand:
    brand = env['fleet.vehicle.model.brand'].create({'name': 'E2E Brand'})
model = env['fleet.vehicle.model'].search(
    [('name', '=', 'E2E Van Model')], limit=1)
if not model:
    model = env['fleet.vehicle.model'].create(
        {'name': 'E2E Van Model', 'brand_id': brand.id})

# Exactly two active vehicles of the E2E model: dedupe by model (never by the
# computed name), archive the surplus, top up if short.
WANT_VEHICLES = 2
model_vehicles = env['fleet.vehicle'].search(
    [('model_id', '=', model.id), ('active', '=', True)], order='id')
for v in model_vehicles.with_context(active_test=False)[WANT_VEHICLES:]:
    v.active = False
vehicles = env['fleet.vehicle'].search(
    [('model_id', '=', model.id), ('active', '=', True)], order='id')
for _ in range(WANT_VEHICLES - len(vehicles)):
    vehicles |= env['fleet.vehicle'].create({'model_id': model.id})
for v in vehicles:
    print('vehicle:', v.id, v.name, 'active:', v.active)

pickings = []
for i in range(4):
    part = env['res.partner'].search(
        [('name', '=', f'E2E Customer {i + 1}')], limit=1)
    if not part:
        part = env['res.partner'].create({
            'name': f'E2E Customer {i + 1}',
            'partner_latitude': 40.4168 + 0.01 * (i + 1),
            'partner_longitude': -3.7038 + 0.01 * (i + 1),
        })
    pick = env['stock.picking'].search(
        [('partner_id', '=', part.id),
         ('picking_type_code', '=', 'outgoing')],
        limit=1)
    if not pick:
        pick = env['stock.picking'].create({
            'picking_type_id': wh.out_type_id.id,
            'location_id': wh.lot_stock_id.id,
            'partner_id': part.id,
        })
        env['stock.move'].create({
            'picking_id': pick.id, 'product_id': product.id,
            'product_uom': product.uom_id.id,
            'product_uom_qty': 20,
            'location_id': wh.lot_stock_id.id,
            'location_dest_id': env['stock.location'].search(
                [('name', '=', 'Customers'),
                 ('usage', '=', 'customer')], limit=1).id,
        })
        pick.action_confirm()
    pickings.append(pick)
    print('picking:', pick.id, 'state:', pick.state,
          'partner:', pick.partner_id.name,
          'geo:', pick.partner_id.partner_latitude,
          pick.partner_id.partner_longitude,
          'weight:', pick.shipping_weight)

print('=== seed done ===')
env.cr.commit()
print('committed')
