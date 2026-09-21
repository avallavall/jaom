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

    def formulate(self, snapshot, config_meta):
        orders = snapshot.get(self._ORDER_MODEL, {})
        params = snapshot.get('_parameters', {})
        capacity = params.get('resource_capacity')
        setup_cost = params.get('setup_cost')
        holding_cost = params.get('holding_cost')
        if not orders:
            raise ValueError('mrp: no production orders extracted')
        if capacity is None:
            raise ValueError('mrp: missing resource_capacity parameter')
        if setup_cost is None:
            raise ValueError('mrp: missing setup_cost parameter')
        if holding_cost is None:
            raise ValueError('mrp: missing holding_cost parameter')
        capacity = float(capacity)
        setup_cost = float(setup_cost)
        holding_cost = float(holding_cost)

        # Days = the distinct deadline dates, sorted (index 1..D).
        days = sorted({self._day_key(o['order_due']) for o in orders.values()})
        day_index = {d: i for i, d in enumerate(days, start=1)}

        order_ids = sorted(orders)
        n = len(order_ids)
        variables, obj_terms, constraints = [], [], []
        meta_orders = {}
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
            for d in range(1, due_day + 1):
                variables.append({
                    'name': f'x_{oid}_{d}', 'type': 'binary',
                    'lower_bound': 0, 'upper_bound': 1})
                variables.append({
                    'name': f'q_{oid}_{d}', 'type': 'continuous',
                    'lower_bound': 0, 'upper_bound': qty})
                if d < due_day:
                    variables.append({
                        'name': f'i_{oid}_{d}', 'type': 'continuous',
                        'lower_bound': 0, 'upper_bound': qty})
                    obj_terms.append(f'{holding_cost}*i_{oid}_{d}')
                    prev = f'i_{oid}_{d - 1}' if d > 1 else '0'
                    constraints.append({
                        'name': f'bal_{oid}_{d}',
                        'expression': (
                            f'i_{oid}_{d} - {prev} - q_{oid}_{d} = 0')})
                obj_terms.append(f'{setup_cost}*x_{oid}_{d}')
            # delivery: what is held plus the due-day lot covers the order
            prev = f'i_{oid}_{due_day - 1}' if due_day > 1 else '0'
            constraints.append({
                'name': f'deliver_{oid}',
                'expression': f'{prev} + q_{oid}_{due_day} = {qty}'})
            for d in range(1, due_day + 1):
                constraints.append({
                    'name': f'link_{oid}_{d}',
                    'expression': f'q_{oid}_{d} - {qty}*x_{oid}_{d} <= 0'})
        # daily capacity: the orders due on or after day d
        for d in range(1, len(days) + 1):
            terms = [
                f'q_{oid}_{d}' for oid in order_ids
                if day_index[self._day_key(orders[oid]['order_due'])] >= d]
            if terms:
                constraints.append({
                    'name': f'cap_{d}',
                    'expression': ' + '.join(terms) + f' <= {capacity}'})

        # Baseline (SPECS 4.6 fix-all): pin every order to its incumbent
        # start day. An order whose incumbent start is missing (or not on
        # a deadline day) gets all its x variables pinned to 0, so its
        # delivery constraint is unsatisfiable — the infeasibility the
        # scenario reports as a finding, not a failure.
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
            'order_model': self._ORDER_MODEL,
            'start_field': self._START_FIELD,
            'resource_capacity': capacity,
            'setup_cost': setup_cost,
            'holding_cost': holding_cost,
            'n_orders': n,
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
        setup_cost = meta.get('setup_cost', 0.0)
        holding_cost = meta.get('holding_cost', 0.0)
        if not orders:
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
        # bal / link: structural flow constraints, nothing for a manager
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
