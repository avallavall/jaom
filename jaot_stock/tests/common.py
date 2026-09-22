# -*- coding: utf-8 -*-
# License LGPL-3
"""Offline stand-in client for the VRP bridge tests (PLAN P3.6 / P4.1).

``FakeVrpClient`` mirrors the contract of ``jaot.config.JaotClient`` but
solves the VRP deterministically, with no network. It tracks one fake task
per ``solve_async`` call (a scenario owns a unique ``jaot_task_id``), and:

* optimized solve -> one tour that visits every order
  (depot -> orders in res_id order -> depot);
* baseline (fix-all) solve -> the problem carries ``fix_`` constraints pinning
  the x arcs to the incumbent plan, and the client honours them, returning
  exactly that pinned tour (as a real solver re-solving a fixed model would).

The objective value is the haversine length of the tour read back from the
problem metadata, so a different tour yields a different objective and the
baseline-vs-optimized delta is meaningful.
"""

import math


class FakeVrpClient:
    """Deterministic offline stand-in for ``JaotClient`` on the VRP recipe."""

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
        task_id = 'fake-vrp-task-%d' % self._next
        execution_id = 'fake-vrp-exec-%d' % self._next
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
        orders = sorted(int(k) for k in
                        problem.get('metadata', {}).get('orders', {}))
        n = len(orders)
        pins = [c for c in problem.get('constraints', [])
                if c['name'].startswith('pin_')]
        fixes = [c for c in problem.get('constraints', [])
                 if c['name'].startswith('fix_')]
        if pins:
            # re-route (SPECS 13.4): walk the pinned prefix arcs
            # (depot -> served stops); the remaining orders are appended in
            # node order, the rest of the tour is free
            next_node = {}
            for c in pins:
                _p, t, i, j = c['expression'].split(' = ')[0].split('_')
                next_node[(int(t), int(i))] = int(j)
            n_veh = len(problem.get('metadata', {}).get('vehicles', []))
            tours = {}
            pinned_nodes = set()
            for t in range(n_veh):
                node = 0
                tour = []
                while True:
                    nxt = next_node.get((t, node))
                    if nxt is None:
                        break
                    tour.append(nxt)
                    pinned_nodes.add(nxt)
                    node = nxt
                tours[t] = tour
            remaining = [k for k in range(1, n + 1)
                         if k not in pinned_nodes]
            # a vehicle with no chain takes the first remaining order, the
            # first vehicle takes the rest (deterministic stand-in)
            for t in range(n_veh):
                if not tours[t] and remaining:
                    tours[t].append(remaining.pop(0))
            if remaining:
                tours[0].extend(remaining)
            values = {}
            for t in range(n_veh):
                nodes = [0] + tours[t] + [0]
                for a, b in zip(nodes, nodes[1:]):
                    values['x_%d_%d_%d' % (t, a, b)] = 1
                for pos, k in enumerate(tours[t], start=1):
                    values['u_%d_%d' % (t, k)] = pos
        elif fixes:
            # baseline: return the pinned plan as-is
            values = {c['expression'].split(' = ')[0]:
                      int(c['expression'].split(' = ')[1])
                      for c in fixes}
        else:
            # optimized: single vehicle (t=0): depot -> 1 -> ... -> n -> depot
            nodes = [0] + list(range(1, n + 1)) + [0]
            values = {}
            for a, b in zip(nodes, nodes[1:]):
                values['x_0_%d_%d' % (a, b)] = 1
            for i in range(1, n + 1):
                values['u_0_%d' % i] = i
        entry['values'] = values
        return {
            'solver_status': self.solver_status,
            'solver_name': 'fake-cplex',
            'execution_time_ms': 123,
            'result_data': {
                'model': values,
                'objective_value': self._objective(problem, values),
                'gap': 0.0,
            },
        }

    def infeasibility_analysis(self, execution_id):
        self.infeasibility_calls += 1
        entry = next((t for t in self._tasks.values()
                      if t['execution_id'] == execution_id), None)
        iis = []
        if entry is not None:
            problem = entry['problem']
            fixes = [c for c in problem.get('constraints', [])
                     if c['name'].startswith('fix_')]
            orders = problem.get('metadata', {}).get('orders', {})
            order_ids = sorted(orders, key=int)
            fixed_nodes = set()
            for c in fixes:
                var = c['expression'].split(' = ')[0]
                if var.startswith('x_'):
                    _x, _t, i, j = var.split('_')
                    if 1 <= int(i) <= len(order_ids):
                        fixed_nodes.add(int(i))
            for k in range(1, len(order_ids) + 1):
                if k not in fixed_nodes:
                    iis.append('visit_%d' % k)
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
        problem = entry['problem']
        meta = problem.get('metadata', {})
        values = entry.get('values') or {}
        orders = meta.get('orders', {})
        order_ids = sorted(orders, key=int)
        n = len(order_ids)
        vehicles = meta.get('vehicles', [])
        constraints = []
        # visit_k: equality constraints, always binding in a feasible tour
        for k in range(1, n + 1):
            constraints.append({
                'name': 'visit_%d' % k,
                'activity': 1.0,
                'rhs': 1.0,
                'operator': '=',
                'slack': 0.0,
                'is_binding': True,
                'utilization': 1.0,
                'family': 'visit',
            })
        # capacity_t: rhs parsed back out of the constraint expression
        for t in range(len(vehicles)):
            load = 0.0
            for k in range(1, n + 1):
                demand = orders[str(order_ids[k - 1])]['demand']
                for i in range(n + 1):
                    if i != k and values.get('x_%d_%d_%d' % (t, i, k)):
                        load += demand
            rhs = self._capacity_rhs(problem, t)
            slack = round(rhs - load, 9)
            constraints.append({
                'name': 'capacity_%d' % t,
                'activity': load,
                'rhs': rhs,
                'operator': '<=',
                'slack': slack,
                'is_binding': abs(slack) < 1e-9,
                'utilization': (load / rhs) if rhs else 0.0,
                'family': 'capacity',
            })
        return {
            'objective_value': self._objective(problem, values),
            'total_constraints': len(constraints),
            'binding_count': sum(
                1 for c in constraints if c['is_binding']),
            'constraints': constraints,
            'computed': True,
        }

    @staticmethod
    def _capacity_rhs(problem, t):
        for c in problem.get('constraints', []):
            if c['name'] == 'capacity_%d' % t:
                return float(c['expression'].rsplit('<=', 1)[1].strip())
        return 0.0

    # -- objective -------------------------------------------------------
    def _objective(self, problem, values):
        meta = problem.get('metadata', {})
        depot = meta.get('depot', {})
        orders = meta.get('orders', {})
        order_ids = sorted(orders, key=int)

        def coords(node):
            if node == 0:
                return depot.get('lat'), depot.get('lng')
            o = orders[str(order_ids[node - 1])]
            return o['lat'], o['lng']

        total = 0.0
        for var, v in values.items():
            if v != 1 or not var.startswith('x_'):
                continue
            _x, _t, i, j = var.split('_')
            lat1, lng1 = coords(int(i))
            lat2, lng2 = coords(int(j))
            total += self._haversine(lat1, lng1, lat2, lng2)
        return round(total, 3)

    @staticmethod
    def _haversine(lat1, lng1, lat2, lng2):
        r = 6371.0
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlmb = math.radians(lng2 - lng1)
        a = (math.sin(dphi / 2) ** 2
             + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2)
        return 2 * r * math.asin(math.sqrt(a))
