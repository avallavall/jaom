# -*- coding: utf-8 -*-
# License LGPL-3
"""Offline stand-in client for the MRP bridge tests (PLAN P6.1).

``FakeMrpClient`` mirrors the contract of ``jaot.config.JaotClient`` but
solves the lot-sizing problem deterministically, with no network. It
tracks one fake task per ``solve_async`` call (a scenario owns a unique
``jaot_task_id``), and:

* optimized solve -> each order is produced, unsplitted, on the latest
  day at or before its deadline whose daily load still fits the capacity
  (orders considered in (deadline, res_id) order);
* baseline (fix-all) solve -> the problem carries ``fix_`` constraints
  pinning the x variables to the incumbent plan, and the client honours
  them, returning exactly that pinned plan (as a real solver re-solving
  a fixed model would);
* ``infeasible`` -> no day at or before a deadline fits an order, or the
  pinned plan has no start day for an order / exceeds the capacity.

The objective value is read back from the problem metadata, so a
different plan yields a different objective and the
baseline-vs-optimized delta is meaningful.
"""


class FakeMrpClient:
    """Deterministic offline stand-in for ``JaotClient`` on the mrp recipe."""

    def __init__(self, solver_status='optimal', poll_status='completed'):
        self.solver_status = solver_status
        self.poll_status = poll_status
        self.task_id = None
        self.execution_id = None
        self.poll_calls = 0
        self.cancelled = False
        self.infeasibility_calls = 0
        self.exact_analysis_calls = 0
        self._next = 0
        self._tasks = {}  # task_id -> {'status', 'execution_id', 'problem'}

    # -- submit / poll / cancel -----------------------------------------
    def solve_async(self, problem, solver_name=None, wait=False):
        self._next += 1
        task_id = 'fake-mrp-task-%d' % self._next
        execution_id = 'fake-mrp-exec-%d' % self._next
        self.task_id = task_id
        self.execution_id = execution_id
        self._tasks[task_id] = {
            'status': self.poll_status,
            'execution_id': execution_id,
            'problem': problem,
        }
        return {
            'task_id': task_id,
            'execution_id': execution_id,
            'status': 'queued',
            'message': 'accepted',
            'poll_url': '/api/v2/solve/async/%s' % task_id,
        }

    def poll_task(self, task_id):
        self.poll_calls += 1
        entry = self._tasks.get(task_id)
        if entry is None:
            return {'status': 'pending'}
        return {'status': entry['status']}

    def cancel_task(self, task_id):
        self.cancelled = True
        return {'status': 'cancelled'}

    # -- terminal envelope ----------------------------------------------
    def execution(self, execution_id):
        entry = next((t for t in self._tasks.values()
                      if t['execution_id'] == execution_id), None)
        if entry is None:
            from odoo.addons.jaot_base.jaot_client import JaotAPIError
            raise JaotAPIError('unknown execution')
        problem = entry['problem']
        meta = problem.get('metadata', {})
        orders = meta.get('orders', {})
        capacity = meta.get('resource_capacity', 0.0)
        fixes = [c for c in problem.get('constraints', [])
                 if c['name'].startswith('fix_')]
        values = {}
        if fixes:
            for c in fixes:
                var, val = c['expression'].split(' = ')
                values[var] = int(val)
            # the pinned plan must be a real solution: one start day per
            # order and within the daily capacity — otherwise a solver
            # would report it infeasible
            load = {}
            for oid, o in orders.items():
                starts = [d for d in range(1, o['due_day'] + 1)
                          if values.get('x_%s_%d' % (oid, d))]
                if len(starts) != 1:
                    return self._infeasible()
                a = starts[0]
                load[a] = load.get(a, 0.0) + o['qty']
                values['q_%s_%d' % (oid, a)] = o['qty']
                for d in range(a, o['due_day']):
                    values['i_%s_%d' % (oid, d)] = o['qty']
            if any(v > capacity for v in load.values()):
                return self._infeasible()
        else:
            # optimized: latest day at or before the deadline with room
            load = {}
            for oid in sorted(orders, key=lambda oid: (
                    orders[oid]['due_day'], int(oid))):
                o = orders[oid]
                d = o['due_day']
                while d >= 1 and load.get(d, 0.0) + o['qty'] > capacity:
                    d -= 1
                if d < 1:
                    return self._infeasible()
                load[d] = load.get(d, 0.0) + o['qty']
                values['x_%s_%d' % (oid, d)] = 1
                values['q_%s_%d' % (oid, d)] = o['qty']
                for d2 in range(d, o['due_day']):
                    values['i_%s_%d' % (oid, d2)] = o['qty']
        entry['values'] = values
        return {
            'solver_status': self.solver_status,
            'solver_name': 'fake-scip',
            'execution_time_ms': 123,
            'result_data': {
                'model': values,
                'objective_value': self._objective(meta, values),
                'gap': 0.0,
            },
        }

    def _infeasible(self):
        return {
            'solver_status': 'infeasible',
            'solver_name': 'fake-scip',
            'execution_time_ms': 123,
            'result_data': None,
        }

    def infeasibility_analysis(self, execution_id):
        self.infeasibility_calls += 1
        entry = next((t for t in self._tasks.values()
                      if t['execution_id'] == execution_id), None)
        iis = []
        if entry is not None:
            meta = (entry['problem'].get('metadata') or {})
            if meta.get('days'):
                iis.append('cap_1')
            orders = meta.get('orders', {})
            if orders:
                iis.append('deliver_%s' % sorted(orders, key=int)[0])
        return {
            'iis_constraints': iis,
            'iis_variable_bounds': [],
            'conflict_type': 'constraint',
            'method': 'iis',
            'note': None,
            'explanation': None,
        }

    # -- exact-analysis (SPECS 13.1) -------------------------------------
    def exact_analysis(self, execution_id):
        self.exact_analysis_calls += 1
        entry = next((t for t in self._tasks.values()
                      if t['execution_id'] == execution_id), None)
        if entry is None:
            from odoo.addons.jaot_base.jaot_client import JaotAPIError
            raise JaotAPIError('unknown execution')
        meta = (entry['problem'].get('metadata') or {})
        values = entry.get('values') or {}
        days = meta.get('days', [])
        orders = meta.get('orders', {})
        capacity = meta.get('resource_capacity', 0.0)
        constraints = []
        for d in range(1, len(days) + 1):
            activity = sum(
                (values.get('q_%s_%d' % (oid, d)) or 0)
                for oid, o in orders.items() if o['due_day'] >= d)
            slack = round(capacity - activity, 9)
            constraints.append({
                'name': 'cap_%d' % d,
                'activity': activity,
                'rhs': capacity,
                'operator': '<=',
                'slack': slack,
                'is_binding': abs(slack) < 1e-9,
                'utilization': (activity / capacity) if capacity else 0.0,
                'family': 'capacity',
            })
        for oid, o in orders.items():
            constraints.append({
                'name': 'deliver_%s' % oid,
                'activity': o['qty'],
                'rhs': o['qty'],
                'operator': '=',
                'slack': 0.0,
                'is_binding': True,
                'utilization': 1.0,
                'family': 'delivery',
            })
        return {
            'objective_value': self._objective(meta, values),
            'total_constraints': len(constraints),
            'binding_count': sum(
                1 for c in constraints if c['is_binding']),
            'constraints': constraints,
            'computed': True,
        }

    # -- objective -------------------------------------------------------
    @staticmethod
    def _objective(meta, values):
        orders = meta.get('orders', {})
        setup_cost = meta.get('setup_cost', 0.0)
        holding_cost = meta.get('holding_cost', 0.0)
        total = 0.0
        for oid, o in orders.items():
            setups = sum(
                1 for d in range(1, o['due_day'] + 1)
                if values.get('x_%s_%d' % (oid, d)))
            held = sum(
                (o['due_day'] - d) * (values.get('q_%s_%d' % (oid, d)) or 0)
                for d in range(1, o['due_day'] + 1))
            total += setup_cost * setups + holding_cost * held
        return round(total, 3)
