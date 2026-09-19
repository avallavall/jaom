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
        fixes = [c for c in problem.get('constraints', [])
                 if c['name'].startswith('fix_')]
        if fixes:
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
        return {'constraints': [], 'note': 'fake IIS'}

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
