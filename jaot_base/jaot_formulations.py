# -*- coding: utf-8 -*-
# License LGPL-3
"""Formulation registry (SPECS §4.1: extract -> formulate -> enqueue).

Framework-free on purpose (no Odoo imports) so the unit tests can drive a
formulation with a plain snapshot dict and the P2.8 gate can run it without
a live JAOT. A formulation turns an extracted snapshot into a JAOT
``OptimizationProblem`` (field names per docs/research/C-jaot-contract.md
§4) and maps a solution back to ``jaot.scenario.line`` rows.

The snapshot shape is produced by ``jaot.scenario._extract_snapshot``::

    {
        "<res_model>": {res_id: {role_name: value, ...}, ...},
        "_parameters": {role_name: value, ...},
    }
"""
from odoo import _


def _fmt_decision_value(value):
    """Render one decision value for a human: a missing/empty value
    (False, None, an empty list, or 0) as a dash, everything else as-is."""
    if value is False or value is None:
        return '—'
    if isinstance(value, (list, tuple)) and not value:
        return '—'
    if value == 0:
        return '—'
    return str(value)


class JaotFormulation:
    """Base class. Subclasses set ``recipe_code`` and implement the two
    methods below."""

    recipe_code = None

    def formulate(self, snapshot, config_meta):
        """Build the ``OptimizationProblem`` request dict.

        ``config_meta`` carries the solve options (time limit, gap, solver)
        from ``jaot.config``. Returns a dict matching the frozen request
        shape (variables / objective / constraints / options / metadata).
        """
        raise NotImplementedError

    def map_solution(self, problem, model_values):
        """Map a solved variable dict ``{name: value}`` back to scenario
        line dicts ``{res_model, res_id, decision, kpi_contribution}``.

        ``problem`` is the stored request payload (its ``metadata`` carries
        the per-record data needed to compute KPI contributions).
        """
        raise NotImplementedError

    def explain_objective(self, problem, model_values, record_names=None):
        """Decompose the objective into named terms (SPECS 13.1): pure
        post-processing of the incumbent solution against the extracted
        data — no solver call.

        Returns a list of ``{'name': str, 'value': float}`` dicts whose
        values sum to the objective, or ``None`` when the formulation has
        no meaningful split. ``record_names`` (when provided) maps
        ``(res_model, res_id)`` to a display name for the term labels.
        """
        return None

    def explain_constraint(self, name, problem, record_names=None):
        """Plain-language name for a constraint machine name as it comes
        back from the JAOT exact-analysis (SPECS 13.1), e.g.
        ``cap_2`` -> "Production capacity for 2026-10-06".

        Returns the label string, or ``None`` for structural constraints
        a manager should not see. ``record_names`` is as in
        :meth:`explain_objective`.
        """
        return None

    # -- human-readable presentation (P9.7) ----------------------------
    def objective_unit(self):
        """A key for the objective's unit, resolved by the scenario into a
        display unit: ``''`` (none), ``'distance'`` (kilometres), or
        ``'money'`` (the company currency). A key, not a symbol, so this
        stays framework-free."""
        return ''

    def referenced_records(self, decision):
        """The ``(res_model, res_id)`` pairs a decision references, for
        labelling (e.g. the vehicle a VRP line assigns). Empty by default."""
        return []

    def render_line(self, decision, record_names=None):
        """A plain-language rendering of a decision dict for a non-expert
        (P9.7). ``record_names`` maps ``(res_model, res_id)`` to a display
        name. The base falls back to a compact ``field=value`` list."""
        decision = decision or {}
        if not decision:
            return ''
        return ', '.join(
            '%s=%s' % (key, _fmt_decision_value(value))
            for key, value in decision.items())


_REGISTRY = {}


def register(cls):
    _REGISTRY[cls.recipe_code] = cls
    return cls


def get_formulation(recipe_code):
    cls = _REGISTRY.get(recipe_code)
    return cls() if cls else None


@register
class ToyKnapsack(JaotFormulation):
    """0/1 knapsack over ``jaot.demo.item`` (PLAN P2.8 gate, P2.7 tests).

    Roles (set on the ``toy_knapsack`` recipe):
      - ``item`` (reference): the record set + identity field
      - ``weight`` (quantity): per-item weight
      - ``value`` (quantity): per-item value (the objective coefficient)
      - ``capacity`` (parameter): the knapsack bound
    """

    recipe_code = 'toy_knapsack'
    _MODEL = 'jaot.demo.item'

    def formulate(self, snapshot, config_meta):
        items = snapshot.get(self._MODEL, {})
        capacity = (snapshot.get('_parameters', {})
                    .get('capacity'))
        if not items:
            raise ValueError('toy_knapsack: no items extracted')
        if capacity is None:
            raise ValueError('toy_knapsack: missing capacity parameter')

        variables, obj_terms, weight_terms = [], [], []
        meta_items = {}
        for res_id in sorted(items):
            item = items[res_id]
            weight = float(item.get('weight') or 0.0)
            value = float(item.get('value') or 0.0)
            var = f"x_{res_id}"
            variables.append({
                'name': var, 'type': 'binary',
                'lower_bound': 0, 'upper_bound': 1,
            })
            obj_terms.append(f"{value}*{var}")
            weight_terms.append(f"{weight}*{var}")
            meta_items[str(res_id)] = {
                'name': item.get('item'),
                'weight': weight, 'value': value,
            }

        options = {
            'time_limit_seconds': config_meta.get('time_limit_seconds', 300),
            'gap_tolerance': config_meta.get('gap_tolerance', 0.05),
        }
        problem = {
            'name': 'jaom_toy_knapsack',
            'description': 'Toy 0/1 knapsack (JAOM base gate)',
            'variables': variables,
            'objective': {
                'sense': 'maximize',
                'expression': ' + '.join(obj_terms),
            },
            'constraints': [{
                'name': 'capacity',
                'expression': ' + '.join(weight_terms) + f" <= {capacity}",
            }],
            'options': options,
            'metadata': {'items': meta_items, 'capacity': float(capacity)},
        }
        if config_meta.get('solver_name'):
            problem['solver_name'] = config_meta['solver_name']
        return problem

    def map_solution(self, problem, model_values):
        items = (problem.get('metadata', {}) or {}).get('items', {})
        lines = []
        for res_id_str in sorted(items, key=int):
            var = f"x_{res_id_str}"
            selected = bool(model_values.get(var))
            item = items[res_id_str]
            lines.append({
                'res_model': self._MODEL,
                'res_id': int(res_id_str),
                'decision': {'selected': selected},
                'kpi_contribution': float(item.get('value') or 0.0)
                if selected else 0.0,
            })
        return lines

    def objective_unit(self):
        # value (unitless) is maximised
        return ''

    def render_line(self, decision, record_names=None):
        decision = decision or {}
        if not decision:
            return ''
        return _('Selected') if decision.get('selected') else _('Not selected')
