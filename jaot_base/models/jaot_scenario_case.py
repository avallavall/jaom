# -*- coding: utf-8 -*-
# License LGPL-3
"""Named scenario cases (SPECS 13.2, PLAN P9.2).

A case is a user-defined named perturbation of a solved scenario's
parameter roles. Running it re-solves the recipe as a normal child
scenario carrying the perturbation as ``parameter_overrides`` (applied to
the snapshot before the hash), and the comparison against the parent is
stored when the run finishes. At most
``jaot.config.max_parallel_cases`` open (queued or solving) cases are
allowed per company.
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class JaotScenarioCase(models.Model):
    _name = 'jaot.scenario.case'
    _description = 'JAOT named scenario case'
    _rec_name = 'name'

    name = fields.Char(string='Case name', required=True, translate=True)
    scenario_id = fields.Many2one(
        'jaot.scenario', string='Parent scenario', required=True,
        ondelete='cascade', index=True,
        help='The solved scenario whose parameter roles this case '
             'perturbs.')
    perturbation = fields.Json(
        string='Perturbation', required=True, copy=False,
        help='List of {role_id, mode: set|scale, value} entries targeting '
             'parameter roles of the parent recipe.')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('queued', 'Queued'),
        ('solving', 'Solving'),
        ('solved', 'Solved'),
        ('applied', 'Applied'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ], compute='_compute_state', store=True, default='draft', copy=False,
        help='Mirrors the state of the case run (SPECS 13.2).')
    case_run_id = fields.Many2one(
        'jaot.scenario', string='Case run', copy=False,
        help='The child scenario this case launched.')
    # View-visible mirrors of the run's outcome (views cannot resolve a
    # plain m2o chain — only related fields).
    case_objective = fields.Float(
        related='case_run_id.objective_value', string='Objective value')
    case_gap = fields.Float(
        related='case_run_id.gap', string='Gap')
    case_solve_time = fields.Float(
        related='case_run_id.solve_time_seconds', string='Solve time (s)')
    case_solver_status = fields.Char(
        related='case_run_id.solver_status', string='Solver status')
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        copy=False)
    objective_delta_vs_parent = fields.Float(
        string='Objective delta vs parent',
        compute='_compute_objective_delta_vs_parent',
        help='Positive = improvement (sense-aware): for a minimization '
             'the parent objective minus the case objective.')
    line_changes = fields.Integer(
        string='Lines changed', compute='_compute_line_changes',
        help='Number of case-run lines whose decision differs from the '
             'comparison reference (the parent baseline, or the parent '
             'itself when it has no baseline).')

    @api.depends('case_run_id.state')
    def _compute_state(self):
        for rec in self:
            rec.state = (rec.case_run_id.state
                         if rec.case_run_id else 'draft')

    @api.depends('case_run_id.objective_value',
                'case_run_id.objective_sense',
                'case_run_id.state',
                'scenario_id.objective_value')
    def _compute_objective_delta_vs_parent(self):
        for rec in self:
            child, parent = rec.case_run_id, rec.scenario_id
            # only a finished run has a meaningful objective (a failed
            # envelope can still carry one from the solver)
            if (not child or child.state not in ('solved', 'applied')
                    or child.objective_value is None
                    or not parent or parent.objective_value is None):
                rec.objective_delta_vs_parent = False
                continue
            sense = child.objective_sense or parent.objective_sense
            if sense == 'maximize':
                rec.objective_delta_vs_parent = (
                    child.objective_value - parent.objective_value)
            else:
                rec.objective_delta_vs_parent = (
                    parent.objective_value - child.objective_value)

    @api.depends('case_run_id.scenario_line_ids.decision',
                'case_run_id.scenario_line_ids.res_model',
                'case_run_id.scenario_line_ids.res_id',
                'case_run_id.state',
                'scenario_id.baseline_scenario_id',
                'scenario_id.scenario_line_ids.decision')
    def _compute_line_changes(self):
        for rec in self:
            child, parent = rec.case_run_id, rec.scenario_id
            if not child or child.state != 'solved':
                rec.line_changes = 0
                continue
            reference = parent.baseline_scenario_id or parent
            rec.line_changes = self._count_line_changes(child, reference)

    @api.model
    def _count_line_changes(self, child, reference):
        Line = self.env['jaot.scenario.line']
        ref_lines = {
            (l.res_model, l.res_id): (l.decision or {})
            for l in Line.search([('scenario_id', '=', reference.id)])}
        count = 0
        for line in child.scenario_line_ids:
            ref_dec = ref_lines.get((line.res_model, line.res_id), {})
            if (line.decision or {}) != ref_dec:
                count += 1
        return count

    # ------------------------------------------------------------------
    # validation + run (SPECS 13.2)
    # ------------------------------------------------------------------
    def _validate_perturbation(self, recipe):
        roles_by_id = {r.id: r for r in recipe.recipe_role_ids}
        entries = self.perturbation or []
        if not isinstance(entries, list) or not entries:
            raise UserError(_(
                "A case needs a non-empty list of parameter perturbations "
                "(each {role_id, mode, value})."))
        for entry in entries:
            if not isinstance(entry, dict):
                raise UserError(_(
                    "Each perturbation entry must be an object "
                    "{role_id, mode, value}."))
            role = roles_by_id.get(int(entry.get('role_id') or 0))
            if role is None:
                raise UserError(_(
                    "Perturbation names an unknown role '%(role)s'.",
                    role=entry.get('role_id')))
            if role.kind != 'parameter':
                raise UserError(_(
                    "Perturbation names a non-parameter role '%(name)s'.",
                    name=role.name))
            mode = entry.get('mode')
            if mode not in ('set', 'scale'):
                raise UserError(_(
                    "Perturbation mode must be 'set' or 'scale', "
                    "got '%(mode)s'.", mode=mode))
            try:
                float(entry.get('value'))
            except (TypeError, ValueError):
                raise UserError(_(
                    "Perturbation value is not a number: %(value)s",
                    value=entry.get('value')))

    def action_run_case(self):
        """Run the case: create a child scenario carrying the
        perturbation as parameter overrides and submit it (SPECS 13.2).
        At most ``max_parallel_cases`` open cases per company."""
        self.ensure_one()
        parent = self.scenario_id
        parent._check_modify_access()
        if parent.state != 'solved':
            raise UserError(_(
                "A case can only be run on a solved scenario (currently "
                "'%(state)s').", state=parent.state))
        self._validate_perturbation(parent.recipe_id)
        if (self.case_run_id
                and self.state not in ('solved', 'failed', 'cancelled',
                                       'applied')):
            raise UserError(_(
                "This case is already running (%(state)s).",
                state=self.state))
        cfg = (self.env['jaot.config']
               .search([('company_id', '=', self.company_id.id)],
                       limit=1))
        limit = cfg.max_parallel_cases if cfg else 8
        open_count = self.search_count([
            ('company_id', '=', self.company_id.id),
            ('state', 'in', ['queued', 'solving']),
        ])
        if open_count >= limit:
            raise UserError(_(
                "The limit of %(limit)d open cases per company is "
                "reached.", limit=limit))
        child = self.env['jaot.scenario'].create({
            'name': _("%(parent)s · case %(name)s",
                     parent=parent.name, name=self.name),
            'recipe_id': parent.recipe_id.id,
            'company_id': self.company_id.id,
            'parameter_overrides': self.perturbation,
        })
        self.case_run_id = child.id
        child.action_submit()
        return self

    # ------------------------------------------------------------------
    # comparison (SPECS 13.2)
    # ------------------------------------------------------------------
    def _store_comparison(self):
        """Called when the case run is solved: write the per-line delta of
        the case-run plan against the comparison reference (the parent
        baseline, or the parent itself when it has none)."""
        self.ensure_one()
        child = self.case_run_id
        if not child or child.state != 'solved':
            return
        parent = self.scenario_id
        reference = parent.baseline_scenario_id or parent
        child._write_line_deltas(reference)
