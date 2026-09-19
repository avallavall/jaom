# -*- coding: utf-8 -*-
# License LGPL-3
"""Offline stand-in client for the VRP bridge tests (PLAN P3.6).

``FakeVrpClient`` mirrors the contract of ``jaot.config.JaotClient`` but
solves the VRP deterministically: it always returns one tour that visits
every order (depot -> orders in res_id order -> depot). The base
``jaot.scenario`` reconcile then maps that tour back to one line per
picking, so the whole draft -> queued -> solved -> applied -> reverted flow
runs with no network.
"""


class FakeVrpClient:
    """Deterministic offline stand-in for ``JaotClient`` on the VRP recipe."""

    def __init__(self, solver_status='optimal', poll_status='completed'):
        self.solver_status = solver_status
        self.poll_status = poll_status
        self.task_id = 'fake-vrp-task'
        self.execution_id = 'fake-vrp-exec'
        self._problem = None
        self.poll_calls = 0
        self.cancelled = False
        self.infeasibility_calls = 0

    # -- submit / poll / cancel -----------------------------------------
    def solve_async(self, problem, solver_name=None, wait=False):
        self._problem = problem
        return {
            'task_id': self.task_id,
            'execution_id': self.execution_id,
            'status': 'queued',
            'message': 'accepted',
            'poll_url': '/api/v2/solve/async/%s' % self.task_id,
        }

    def poll_task(self, task_id):
        self.poll_calls += 1
        return {'status': self.poll_status}

    def cancel_task(self, task_id):
        self.cancelled = True
        return {'status': 'cancelled'}

    # -- terminal envelope ----------------------------------------------
    def execution(self, execution_id):
        meta = (self._problem or {}).get('metadata', {})
        orders = sorted(int(k) for k in meta.get('orders', {}))
        n = len(orders)
        # single vehicle (t=0): depot -> node1 -> ... -> noden -> depot
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
                'objective_value': 12.5,
                'gap': 0.0,
            },
        }

    def infeasibility_analysis(self, execution_id):
        self.infeasibility_calls += 1
        return {'constraints': [], 'note': 'fake IIS'}
