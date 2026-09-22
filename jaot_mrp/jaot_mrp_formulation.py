# -*- coding: utf-8 -*-
# License LGPL-3
"""Lot-sizing formulation for the production-scheduling bridge (P6.1).

Framework-free (no Odoo) so it can be unit-tested with a plain snapshot
and driven by the base ``jaot.scenario`` lifecycle. Single-machine
capacitated lot sizing over ``mrp.production`` orders: each order is
produced on one or more days at or before its deadline, subject to a
daily capacity; the objective trades per-lot setup cost against
per-unit, per-day inventory-holding cost.

Days are the distinct deadline dates present in the extracted orders —
the only days on which a due order can usefully be produced.
"""
from odoo import _
from odoo.addons.jaot_base.jaot_formulations import (
    JaotFormulation,
    register,
)


@register
class MrpLotSizing(JaotFormulation):
    """Capacitated lot sizing over production deadlines.

    Roles (set on the ``mrp`` recipe, see ``data/jaot_mrp_recipe.xml``):
      - ``order_qty`` (quantity): the order's ``product_qty``
      - ``order_due`` (date): the order's ``date_deadline``
      - ``current_start`` (date, optional): the incumbent ``date_start``
      - ``resource_capacity`` (parameter): producible units per day
      - ``setup_cost`` (parameter): cost of a lot (order-day) start
      - ``holding_cost`` (parameter): cost per unit held per day
    """

    recipe_code = 'mrp'
    _ORDER_MODEL = 'mrp.production'
    _START_FIELD = 'date_start'

    # ------------------------------------------------------------------
    @staticmethod
    def _day_key(value):
        """The calendar date (``YYYY-MM-DD``) of a deadline/start value."""
        return str(value)[:10]

    _FORECAST_MODEL = 'jaot.forecast.demand'

    def _emit_order(self, key, qty, due_day, variables, obj_terms,
                    constraints, setup_cost, holding_cost, fprefix=''):
        """Emit the lot-sizing variables and constraints for one order.

        ``key`` is the (string) order id embedded in the variable names;
        ``fprefix`` prefixes every name for the synthetic forecast orders
        so they never collide with the committed-MO names.
        """
        x = f'{fprefix}x_{key}_{{d}}'
        q = f'{fprefix}q_{key}_{{d}}'
        i = f'{fprefix}i_{key}_{{d}}'
        bal = f'{fprefix}bal_{key}_{{d}}'
        link = f'{fprefix}link_{key}_{{d}}'
        for d in range(1, due_day + 1):
            variables.append({
                'name': x.format(d=d), 'type': 'binary',
                'lower_bound': 0, 'upper_bound': 1})
            variables.append({
                'name': q.format(d=d), 'type': 'continuous',
                'lower_bound': 0, 'upper_bound': qty})
            if d < due_day:
                variables.append({
                    'name': i.format(d=d), 'type': 'continuous',
                    'lower_bound': 0, 'upper_bound': qty})
                obj_terms.append(f'{holding_cost}*{i.format(d=d)}')
                prev = i.format(d=d - 1) if d > 1 else '0'
                constraints.append({
                    'name': bal.format(d=d),
                    'expression': (
                        f'{i.format(d=d)} - {prev} - {q.format(d=d)} = 0')})
            obj_terms.append(f'{setup_cost}*{x.format(d=d)}')
        # delivery: what is held plus the due-day lot covers the order
        prev = i.format(d=due_day - 1) if due_day > 1 else '0'
        constraints.append({
            'name': f'{fprefix}deliver_{key}',
            'expression': f'{prev} + {q.format(d=due_day)} = {qty}'})
        for d in range(1, due_day + 1):
            constraints.append({
                'name': link.format(d=d),
                'expression': f'{q.format(d=d)} - {qty}*{x.format(d=d)} <= 0'})

    def formulate(self, snapshot, config_meta):
        orders = snapshot.get(self._ORDER_MODEL, {})
        forecast_rows = snapshot.get(self._FORECAST_MODEL, {})
        params = snapshot.get('_parameters', {})
        capacity = params.get('resource_capacity')
        setup_cost = params.get('setup_cost')
        holding_cost = params.get('holding_cost')
        if not orders and not forecast_rows:
            raise ValueError(
                'mrp: no production orders or forecast demand extracted')
        if capacity is None:
            raise ValueError('mrp: missing resource_capacity parameter')
        if setup_cost is None:
            raise ValueError('mrp: missing setup_cost parameter')
        if holding_cost is None:
            raise ValueError('mrp: missing holding_cost parameter')
        capacity = float(capacity)
        setup_cost = float(setup_cost)
        holding_cost = float(holding_cost)

        # Days = the distinct deadline dates of the committed orders UNION
        # the forecast period dates (index 1..D).
        day_set = {self._day_key(o['order_due']) for o in orders.values()}
        for row in forecast_rows.values():
            period = row.get('forecast_period')
            if period:
                day_set.add(self._day_key(period))
        days = sorted(day_set)
        day_index = {d: i for i, d in enumerate(days, start=1)}

        variables, obj_terms, constraints = [], [], []
        meta_orders = {}
        # committed MOs
        order_ids = sorted(orders)
        for oid in order_ids:
            o = orders[oid]
            qty = float(o.get('order_qty') or 0.0)
            due_day = day_index[self._day_key(o['order_due'])]
            start_raw = o.get('current_start')
            start_day = None
            if start_raw:
                start_day = day_index.get(self._day_key(start_raw))
            meta_orders[str(oid)] = {
                'qty': qty,
                'due_day': due_day,
                'start_day': start_day,
            }
            self._emit_order(oid, qty, due_day, variables, obj_terms,
                            constraints, setup_cost, holding_cost)
        # synthetic forecast orders (SPECS 13.5): each demand row is an
        # order due in its period; f-prefixed names keep them clear of the
        # committed-MO names.
        forecast_specs = []
        meta_forecast = {}
        for rowid in sorted(forecast_rows):
            row = forecast_rows[rowid]
            qty = float(row.get('forecast_demand') or 0.0)
            period = row.get('forecast_period')
            if qty <= 0.0 or not period:
                continue
            due_day = day_index.get(self._day_key(period))
            if due_day is None:
                continue
            forecast_specs.append((rowid, qty, due_day))
            meta_forecast[str(rowid)] = {'qty': qty, 'due_day': due_day}
            self._emit_order(rowid, qty, due_day, variables, obj_terms,
                            constraints, setup_cost, holding_cost,
                            fprefix='f')
        # daily capacity: committed + forecast orders due on or after day d
        for d in range(1, len(days) + 1):
            terms = [
                f'q_{oid}_{d}' for oid in order_ids
                if day_index[self._day_key(orders[oid]['order_due'])] >= d]
            terms += [
                f'fq_{rowid}_{d}' for rowid, _qty, due_day in forecast_specs
                if due_day >= d]
            if terms:
                constraints.append({
                    'name': f'cap_{d}',
                    'expression': ' + '.join(terms) + f' <= {capacity}'})

        # Baseline (SPECS 4.6 fix-all): pin every COMMITTED order to its
        # incumbent start day. Synthetic forecast orders are skipped — they
        # have no incumbent plan. An order whose incumbent start is missing
        # (or not on a deadline day) gets all its x variables pinned to 0,
        # so its delivery constraint is unsatisfiable — the infeasibility
        # the scenario reports as a finding, not a failure.
        if config_meta.get('is_baseline'):
            for oid in order_ids:
                meta = meta_orders[str(oid)]
                pinned = meta['start_day']
                for d in range(1, meta['due_day'] + 1):
                    pin = 1 if d == pinned else 0
                    constraints.append({
                        'name': f'fix_{oid}_{d}',
                        'expression': f'x_{oid}_{d} = {pin}'})

        metadata = {
            'days': days,
            'orders': meta_orders,
            'forecast_orders': meta_forecast,
            'forecast_model': self._FORECAST_MODEL,
            'order_model': self._ORDER_MODEL,
            'start_field': self._START_FIELD,
            'resource_capacity': capacity,
            'setup_cost': setup_cost,
            'holding_cost': holding_cost,
            'n_orders': len(order_ids),
            'n_forecast': len(forecast_specs),
            # records the plan explanation may refer to (SPECS 13.1)
            'records': {self._ORDER_MODEL: list(order_ids)},
        }

        problem = {
            'name': 'jaom_mrp_lotsizing',
            'description': ('JAOM production scheduling: capacitated lot '
                            'sizing over deadlines'),
            'variables': variables,
            'objective': {
                'sense': 'minimize',
                'expression': ' + '.join(obj_terms),
            },
            'constraints': constraints,
            'options': {
                'time_limit_seconds': config_meta.get(
                    'time_limit_seconds', 300),
                'gap_tolerance': config_meta.get('gap_tolerance', 0.05),
            },
            'metadata': metadata,
        }
        if config_meta.get('solver_name'):
            problem['solver_name'] = config_meta['solver_name']
        return problem

    # ------------------------------------------------------------------
    def map_solution(self, problem, model_values):
        meta = (problem.get('metadata', {}) or {})
        orders = meta.get('orders', {})
        days = meta.get('days', [])
        setup_cost = meta.get('setup_cost', 0.0)
        holding_cost = meta.get('holding_cost', 0.0)
        order_model = meta.get('order_model', self._ORDER_MODEL)
        start_field = meta.get('start_field', self._START_FIELD)

        lines = []
        for oid in sorted(orders, key=int):
            o = orders[oid]
            due_day = o['due_day']
            start_day = None
            setups = 0
            held = 0.0
            for d in range(1, due_day + 1):
                if model_values.get(f'x_{oid}_{d}'):
                    setups += 1
                q = model_values.get(f'q_{oid}_{d}') or 0
                if q > 1e-9:
                    if start_day is None:
                        start_day = d
                    held += (due_day - d) * q
            if start_day is None:
                start_day = due_day
            lines.append({
                'res_model': order_model,
                'res_id': int(oid),
                'decision': {
                    start_field: f'{days[start_day - 1]} 00:00:00',
                },
                'kpi_contribution': setup_cost * setups
                + holding_cost * held,
            })
        return lines

    # ------------------------------------------------------------------
    # plan explanation (SPECS 13.1)
    # ------------------------------------------------------------------
    def explain_objective(self, problem, model_values, record_names=None):
        meta = (problem.get('metadata', {}) or {})
        orders = meta.get('orders', {})
        forecast_orders = meta.get('forecast_orders', {})
        setup_cost = meta.get('setup_cost', 0.0)
        holding_cost = meta.get('holding_cost', 0.0)
        if not orders and not forecast_orders:
            return None
        setups = 0.0
        holding = 0.0
        for oid, o in orders.items():
            for d in range(1, o['due_day'] + 1):
                setups += setup_cost * (
                    model_values.get(f'x_{oid}_{d}') or 0)
                if d < o['due_day']:
                    holding += holding_cost * (
                        model_values.get(f'i_{oid}_{d}') or 0)
        # synthetic forecast orders carry the same setup/holding costs
        for foid, o in forecast_orders.items():
            for d in range(1, o['due_day'] + 1):
                setups += setup_cost * (
                    model_values.get(f'fx_{foid}_{d}') or 0)
                if d < o['due_day']:
                    holding += holding_cost * (
                        model_values.get(f'fi_{foid}_{d}') or 0)
        return [
            {'name': _('Setups'), 'value': setups},
            {'name': _('Inventory holding'), 'value': holding},
        ]

    def _order_label(self, oid, record_names):
        name = None
        if record_names:
            name = record_names.get((self._ORDER_MODEL, int(oid)))
        if name:
            return _('Order %(name)s', name=name)
        return _('An order')

    def explain_constraint(self, name, problem, record_names=None):
        meta = (problem.get('metadata', {}) or {})
        days = meta.get('days', [])
        orders = meta.get('orders', {})
        if name.startswith('cap_'):
            try:
                d = int(name.split('_', 1)[1])
            except ValueError:
                return None
            if not 1 <= d <= len(days):
                return None
            return _('Production capacity for %(day)s', day=days[d - 1])
        if name.startswith('deliver_'):
            oid = name.split('_', 1)[1]
            o = orders.get(oid)
            if o is None:
                return None
            return _('%(order)s must be delivered in full by %(day)s',
                    order=self._order_label(oid, record_names),
                    day=days[o['due_day'] - 1])
        if name.startswith('fix_'):
            parts = name.split('_')
            if len(parts) != 3:
                return None
            oid, d = parts[1], int(parts[2])
            o = orders.get(oid)
            if o is None or o.get('start_day') != d:
                return None
            return _('%(order)s keeps its current start day %(day)s',
                    order=self._order_label(oid, record_names),
                    day=days[d - 1])
        # synthetic forecast orders
        forecast_orders = meta.get('forecast_orders', {})
        if name.startswith('fdeliver_'):
            foid = name.split('_', 1)[1]
            o = forecast_orders.get(foid)
            if o is None:
                return None
            return _('Forecast demand must be produced by %(day)s',
                    day=days[o['due_day'] - 1])
        # bal / link / fbal / flink: structural flow constraints
        return None

    # -- human-readable presentation (P9.7) ----------------------------
    def objective_unit(self):
        # setup + holding cost, in the company currency
        return 'money'

    def render_line(self, decision, record_names=None):
        decision = decision or {}
        start = decision.get(self._START_FIELD)
        if start in (False, None, ''):
            return '—'
        return _('Start %(day)s', day=str(start)[:10])
