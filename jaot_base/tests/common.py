# -*- coding: utf-8 -*-
# License LGPL-3
"""Shared helpers for the jaot_base test suite (PLAN P2.7).

``FakeJaotClient`` is a framework-free stand-in for ``JaotClient``:
deterministic, no network. The lifecycle tests patch
``jaot.config.JaotConfig.get_client`` to return one, so the whole
draft -> queued -> solved -> applied -> reverted flow runs offline.
"""

import itertools

# One unique task id per fake client: two scenarios submitted against two
# fakes in the same test must not collide on the scenario's
# UNIQUE (jaot_task_id) constraint.
_FAKE_SEQ = itertools.count(1)


class FakeJaotClient:
    """Deterministic offline stand-in for ``JaotClient``.

    ``solve_async`` stores the problem; ``execution`` returns a terminal
    envelope whose ``result_data.model`` is a greedy knapsack over the
    problem's own ``metadata`` (the same items and capacity the real solver
    would have seen). ``model_values`` overrides the greedy result when a
    test wants a fixed solution.
    """

    def __init__(self, solver_status='optimal', poll_status='completed',
                  model_values=None, scenario_analysis_job=None,
                  solve_async_error=None, exact_analysis=None,
                  exact_analysis_error=None):
        self.solver_status = solver_status
        self.poll_status = poll_status
        self._fixed_model_values = model_values
        self._seq = next(_FAKE_SEQ)
        self.task_id = 'fake-task-%d' % self._seq
        self.execution_id = 'fake-exec-%d' % self._seq
        self._problem = None
        self.poll_calls = 0
        self.cancelled = False
        self.infeasibility_calls = 0
        self.scenario_analysis_calls = 0
        self.scenario_analysis_get_calls = 0
        self.exact_analysis_calls = 0
        self._scenario_analysis_job = scenario_analysis_job
        self._exact_analysis = exact_analysis
        # when set, solve_async raises it (JAOT down / quota / solver error)
        self.solve_async_error = solve_async_error
        self.solve_async_calls = 0
        # when set, exact_analysis raises it (analysis endpoint down)
        self.exact_analysis_error = exact_analysis_error

    # -- submit / poll / cancel -----------------------------------------
    def solve_async(self, problem, solver_name=None, wait=False):
        self.solve_async_calls += 1
        if self.solve_async_error is not None:
            raise self.solve_async_error
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
        model_values = (self._fixed_model_values
                        if self._fixed_model_values is not None
                        else self._greedy())
        return {
            'solver_status': self.solver_status,
            'solver_name': 'fake-scip',
            'execution_time_ms': 123,
            'result_data': {
                'model': model_values,
                'objective_value': self._objective(model_values),
                'gap': 0.0,
            },
        }

    def infeasibility_analysis(self, execution_id):
        self.infeasibility_calls += 1
        return {
            'iis_constraints': ['capacity'],
            'iis_variable_bounds': [],
            'conflict_type': 'constraint',
            'method': 'iis',
            'note': None,
            'explanation': None,
        }

    # -- exact-analysis (SPECS 13.1) -------------------------------------
    def exact_analysis(self, execution_id):
        self.exact_analysis_calls += 1
        if self.exact_analysis_error is not None:
            raise self.exact_analysis_error
        if self._exact_analysis is not None:
            return self._exact_analysis
        return self._default_exact()

    def _default_exact(self):
        """The exact-analysis of the greedy solution: the single
        ``capacity`` constraint, binding exactly when the greedy fill
        reaches it (contract shape, C-jaot-contract note §4)."""
        values = (self._fixed_model_values
                  if self._fixed_model_values is not None
                  else self._greedy())
        items = self._items()
        capacity = self._capacity()
        activity = sum(
            float(items[k]['weight']) for k in items
            if values.get('x_%s' % k))
        slack = round(capacity - activity, 9)
        is_binding = abs(slack) < 1e-9
        return {
            'objective_value': self._objective(values),
            'total_constraints': 1,
            'binding_count': 1 if is_binding else 0,
            'constraints': [{
                'name': 'capacity',
                'activity': activity,
                'rhs': capacity,
                'operator': '<=',
                'slack': slack,
                'is_binding': is_binding,
                'utilization': (activity / capacity) if capacity else 0.0,
                'family': 'capacity',
            }],
            'contributions': [
                {'label': 'x_%s' % k,
                 'contribution': float(items[k]['value'])}
                for k in sorted(items)
                if values.get('x_%s' % k)
            ],
            'computed': True,
        }

    # -- scenario-analysis (what-if, P4.3) --------------------------------
    def scenario_analysis(self, execution_id):
        """POST …/scenario-analysis: kick off the bodyless what-if batch."""
        self.scenario_analysis_calls += 1
        return {'status': 'running', 'progress': {'done': 0, 'planned': 3}}

    def scenario_analysis_get(self, execution_id):
        """GET …/scenario-analysis: poll the what-if job."""
        self.scenario_analysis_get_calls += 1
        if self._scenario_analysis_job is not None:
            return self._scenario_analysis_job
        base = self._objective(self._greedy())
        return {
            'status': 'completed',
            'progress': {'done': 3, 'planned': 3},
            'analysis': {
                'sense': 'minimize',
                'base_objective': base,
                'partial': True,
                'rhs_scenarios': [
                    {'constraint': 'capacity', 'family': 'capacity',
                     'operator': '<=', 'direction': 'relax',
                     'rhs': 100.0, 'rhs_new': 110.0, 'delta': 10.0,
                     'status': 'computed',
                     'objective_value': base - 2.0,
                     'objective_delta': -2.0, 'improves': True,
                     'solve_time_seconds': 0.1},
                    {'constraint': 'capacity', 'family': 'capacity',
                     'operator': '<=', 'direction': 'tighten',
                     'rhs': 100.0, 'rhs_new': 90.0, 'delta': -10.0,
                     'status': 'SKIPPED_BUDGET',
                     'objective_value': None, 'objective_delta': None,
                     'improves': None, 'solve_time_seconds': None},
                ],
                'decision_scenarios': [
                    {'variable': 'x_1', 'family': 'binary',
                     'original_value': 1, 'forced_value': 0,
                     'status': 'computed',
                     'objective_value': base + 1.0, 'regret': 1.0,
                     'solve_time_seconds': 0.1},
                ],
            },
        }

    # -- internals -------------------------------------------------------
    def _items(self):
        problem = self._problem or {}
        return (problem.get('metadata') or {}).get('items', {})

    def _capacity(self):
        problem = self._problem or {}
        return (problem.get('metadata') or {}).get('capacity', 0.0)

    def _greedy(self):
        items = self._items()
        remaining = float(self._capacity())
        order = sorted(
            items,
            key=lambda k: -float(items[k]['value'])
            / max(float(items[k]['weight']), 1e-9))
        selected = {}
        for res_id in order:
            weight = float(items[res_id]['weight'])
            if weight <= remaining:
                selected['x_%s' % res_id] = 1
                remaining -= weight
            else:
                selected['x_%s' % res_id] = 0
        for res_id in items:
            selected.setdefault('x_%s' % res_id, 0)
        return selected

    def _objective(self, model_values):
        total = 0.0
        for res_id, item in self._items().items():
            if model_values.get('x_%s' % res_id):
                total += float(item['value'])
        return total


def make_toys(env, company, capacity=None):
    """Create (idempotently) the ``toy_knapsack`` recipe, its roles and
    bindings, and one ``jaot.demo.item`` per generated item.

    Returns ``(recipe, items)`` where ``items`` is the recordset.
    """
    from ..jaot_data import generate_knapsack

    data = generate_knapsack()
    if capacity is not None:
        data['capacity'] = capacity

    Recipe = env['jaot.recipe']
    recipe = Recipe.search(
        [('code', '=', 'toy_knapsack'), ('company_id', '=', company.id)])
    if not recipe:
        recipe = Recipe.create({
            'code': 'toy_knapsack', 'name': 'Toy Knapsack',
            'domain': 'stock', 'company_id': company.id})
        Role = env['jaot.recipe.role']
        Binding = env['jaot.binding']

        def role(name, kind, data_type):
            r = Role.create({
                'recipe_id': recipe.id, 'name': name, 'kind': kind,
                'data_type': data_type, 'required': True})
            return r

        r_item = role('item', 'variable', 'reference')
        r_weight = role('weight', 'variable', 'quantity')
        r_value = role('value', 'variable', 'quantity')
        r_capacity = role('capacity', 'parameter', 'number')

        Binding.create({
            'recipe_id': recipe.id, 'role_id': r_item.id,
            'res_model': 'jaot.demo.item', 'field_path': 'name',
            'company_id': company.id})
        Binding.create({
            'recipe_id': recipe.id, 'role_id': r_weight.id,
            'res_model': 'jaot.demo.item', 'field_path': 'weight',
            'company_id': company.id})
        Binding.create({
            'recipe_id': recipe.id, 'role_id': r_value.id,
            'res_model': 'jaot.demo.item', 'field_path': 'value',
            'company_id': company.id})
        Binding.create({
            'recipe_id': recipe.id, 'role_id': r_capacity.id,
            'constant_value': str(data['capacity']),
            'company_id': company.id})

    Item = env['jaot.demo.item']
    Item.search([('company_id', '=', company.id)]).unlink()
    items = Item.create([
        {'name': it['name'], 'weight': it['weight'], 'value': it['value'],
         'selected': False, 'company_id': company.id}
        for it in data['items']
    ])
    return recipe, items


def make_config(env, company):
    """Create (idempotently) the per-company ``jaot.config``."""
    Config = env['jaot.config']
    cfg = Config.search([('company_id', '=', company.id)])
    if not cfg:
        cfg = Config.create({
            'company_id': company.id,
            'endpoint_url': 'http://fake-jaot.invalid'})
    return cfg
