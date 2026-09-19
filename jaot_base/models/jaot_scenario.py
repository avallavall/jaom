import hashlib
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..jaot_client import JaotAPIError
from ..jaot_expr import evaluate, evaluate_domain
from ..jaot_formulations import get_formulation


class JaotScenario(models.Model):
    _name = 'jaot.scenario'
    _inherit = ['mail.thread']
    _description = 'JAOT scenario'
    _rec_name = 'display_name'

    display_name = fields.Char(compute='_compute_display_name')
    name = fields.Char(required=True)
    recipe_id = fields.Many2one(
        'jaot.recipe', required=True, ondelete='cascade')
    binding_snapshot = fields.Json(
        string='Binding snapshot',
        help='The bindings used, captured at extraction time for '
             'reproducibility.')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('queued', 'Queued'),
        ('solving', 'Solving'),
        ('solved', 'Solved'),
        ('applied', 'Applied'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, copy=False)
    jaot_task_id = fields.Char(copy=False)
    jaot_execution_id = fields.Char(copy=False)
    solver_name = fields.Char(copy=False)
    solver_status = fields.Char(
        string='JAOT solver status', copy=False,
        help='Terminal solver status reported by JAOT '
             '(optimal, time_limit, infeasible, ...).')
    objective_value = fields.Float(copy=False)
    objective_sense = fields.Selection(
        [('minimize', 'Minimize'), ('maximize', 'Maximize')], copy=False)
    gap = fields.Float(copy=False)
    solve_time_seconds = fields.Float(copy=False)
    data_snapshot_hash = fields.Char(
        string='Data snapshot hash', copy=False,
        help='Hash of the extracted data; used for the staleness warning '
             '(SPECS 4.6).')
    data_stale = fields.Boolean(
        string='Solved against stale data', default=False, copy=False)
    baseline_scenario_id = fields.Many2one('jaot.scenario', copy=False)
    is_baseline = fields.Boolean(
        string='Baseline scenario', default=False, copy=False,
        help='This scenario re-solves the recipe with every decision pinned '
             'to the incumbent plan (SPECS 4.6).')
    baseline_of_id = fields.Many2one(
        'jaot.scenario', string='Baseline of', default=False, copy=False,
        help='For a baseline scenario, the optimized scenario it belongs to.')
    kpi_summary = fields.Json(string='KPI summary', copy=False)
    request_payload = fields.Json(
        string='Request payload',
        help='The full OptimizationProblem sent to JAOT (SPECS 4.5).')
    response_payload = fields.Json(
        string='Response payload',
        help='The full JAOT response envelope (SPECS 4.5).')
    jaot_error = fields.Text(string='JAOT error', copy=False)
    infeasibility = fields.Json(
        string='Infeasibility analysis', copy=False,
        help='IIS result when the solve is infeasible (SPECS 4.4).')
    whatif_state = fields.Selection([
        ('none', 'None'),
        ('requested', 'Requested'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ], default='none', copy=False)
    whatif_analysis = fields.Json(
        string='What-if analysis', copy=False,
        help='The JAOT scenario-analysis job result '
             '(SPECS 6.2 step 5, P4.3).')
    whatif_error = fields.Text(string='What-if error', copy=False)
    applied = fields.Boolean(default=False, copy=False)
    applied_at = fields.Datetime(copy=False)
    applied_by = fields.Many2one('res.users', copy=False)
    scenario_line_ids = fields.One2many(
        'jaot.scenario.line', 'scenario_id')
    whatif_line_ids = fields.One2many('jaot.scenario.whatif', 'scenario_id')
    apply_log_ids = fields.One2many('jaot.apply.log', 'scenario_id')
    line_count = fields.Integer(
        string='Lines', compute='_compute_line_count')
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)

    _task_id_uniq = models.Constraint(
        'UNIQUE (jaot_task_id)',
        'One scenario per JAOT task.')

    @api.depends('name', 'recipe_id')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.name

    @api.depends('scenario_line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.scenario_line_ids)

    @api.constrains('state', 'applied')
    def _check_applied_state(self):
        for rec in self:
            if rec.applied and rec.state != 'applied':
                raise UserError(
                    "A scenario can only be marked applied when its state "
                    "is 'applied'.")

    # ------------------------------------------------------------------
    # extraction (SPECS §4.1 step 1, §7.2 company isolation, §7.3 compact)
    # ------------------------------------------------------------------
    @api.model
    def _resolve_path(self, records, field_path):
        """Walk a dotted field path record-by-record (finding F2: read()
        does not resolve dotted paths; attribute access follows m2o)."""
        vals = []
        for rec in records:
            cur = rec
            for hop in field_path.split('.'):
                if cur is False or cur is None:
                    cur = False
                    break
                try:
                    cur = cur[hop]
                except Exception:
                    cur = False
                    break
            vals.append(cur)
        return vals

    def _extract_snapshot(self):
        """Extract the recipe's data per its bindings (company-filtered).

        Returns ``(snapshot, snapshot_hash, binding_snapshot)`` where
        ``snapshot`` is ``{res_model: {res_id: {role: value}}, '_parameters':
        {role: value}}``.
        """
        self.ensure_one()
        snapshot = {'_parameters': {}}
        binding_snapshot = []
        recipe = self.recipe_id
        bindings = recipe.binding_ids.filtered(
            lambda b: b.company_id == self.company_id)

        # dry-run validation: every required role must be covered
        for role in recipe.recipe_role_ids:
            if role.required and not bindings.filtered(
                    lambda b: b.role_id == role):
                raise UserError(_(
                    "Required role '%(r)s' of recipe '%(c)s' has no binding "
                    "for this company.", r=role.name, c=recipe.code))

        for binding in bindings:
            role = binding.role_id
            binding_snapshot.append({
                'role': role.name,
                'kind': role.kind,
                'res_model': binding.res_model,
                'field_path': binding.field_path,
                'domain': binding.domain,
                'expression': binding.expression,
                'constant_value': binding.constant_value,
            })
            if role.kind == 'parameter':
                snapshot['_parameters'][role.name] = float(
                    binding.constant_value)
                continue
            if not binding.res_model:
                continue
            try:
                model = self.env[binding.res_model]
            except KeyError as exc:
                raise UserError(_(
                    "Binding for role '%(r)s' points at unknown model "
                    "'%(m)s'.", r=role.name, m=binding.res_model)) from exc
            domain = evaluate_domain(binding.domain) if binding.domain else []
            if 'company_id' in model._fields:
                domain = domain + [
                    ('company_id', 'in', [self.company_id.id, False])]
            records = model.search(domain, order='id')
            if not records:
                continue
            if binding.field_path:
                vals = self._resolve_path(records, binding.field_path)
            else:
                vals = list(records.ids)
            if binding.expression:
                resolved = []
                for rec, _v in zip(records, vals):
                    values = {'id': rec.id}
                    if binding.field_path:
                        first = binding.field_path.split('.')[0]
                        try:
                            values[first] = rec[first]
                        except Exception:
                            pass
                    resolved.append(evaluate(
                        binding.expression, values,
                        context=f"{binding.res_model}:{role.name}"))
                vals = resolved
            target = snapshot.setdefault(binding.res_model, {})
            for rec, v in zip(records, vals):
                target.setdefault(rec.id, {})[role.name] = v

        canonical = json.dumps(snapshot, sort_keys=True, default=str)
        snap_hash = hashlib.sha256(canonical.encode()).hexdigest()
        return snapshot, snap_hash, binding_snapshot

    # ------------------------------------------------------------------
    # lifecycle (SPECS §4.4)
    # ------------------------------------------------------------------
    def action_submit(self):
        """draft -> queued: extract, formulate, capture the payload, submit
        to JAOT async (never blocks on the solve)."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Only draft scenarios can be submitted."))
        config = self.env['jaot.config']._require_config(self.company_id)
        snapshot, snap_hash, binding_snapshot = self._extract_snapshot()
        formula = get_formulation(self.recipe_id.code)
        if not formula:
            raise UserError(_(
                "No formulation is registered for recipe code '%(c)s'.",
                c=self.recipe_id.code))
        config_meta = {
            'time_limit_seconds': config.solve_time_limit,
            'gap_tolerance': config.gap_tolerance,
            'solver_name': config.default_solver or None,
            'is_baseline': self.is_baseline,
        }
        try:
            problem = formula.formulate(snapshot, config_meta)
        except ValueError as exc:
            raise UserError(_("Formulation failed: %s", exc)) from exc
        if not problem.get('variables'):
            raise UserError(_(
                "The extracted data produced no decision variables."))

        # capture before anything leaves the box (SPECS §4.4 draft, §4.5)
        self.request_payload = problem
        self.binding_snapshot = binding_snapshot
        self.data_snapshot_hash = snap_hash
        self.objective_sense = problem['objective']['sense']

        client = config.get_client()
        try:
            envelope = client.solve_async(
                problem, solver_name=config.default_solver or None)
        except JaotAPIError as exc:
            self.state = 'failed'
            self.jaot_error = str(exc)
            self.message_post(body=_("JAOT submission failed: %s", exc))
            raise UserError(_("JAOT submission failed: %s", exc)) from exc
        self.jaot_task_id = envelope.get('task_id')
        self.jaot_execution_id = envelope.get('execution_id')
        self.state = 'queued'
        self.message_post(body=_("Submitted to JAOT (task %s).",
                                 self.jaot_task_id or '?'))
        return self

    def action_compare_baseline(self):
        """Build and submit the fix-all baseline for a solved scenario
        (SPECS 4.6). A second scenario of the same recipe is created with
        every decision pinned to the incumbent plan; once it is solved, the
        KPI delta is written back onto this scenario by the reconcile."""
        self.ensure_one()
        if self.state != 'solved':
            raise UserError(_("Only a solved scenario can be baselined."))
        if self.baseline_scenario_id:
            return self.baseline_scenario_id
        baseline = self.create({
            'name': f'{self.name} (baseline)',
            'recipe_id': self.recipe_id.id,
            'company_id': self.company_id.id,
            'is_baseline': True,
            'baseline_of_id': self.id,
        })
        self.baseline_scenario_id = baseline.id
        baseline.action_submit()
        return baseline

    def action_run_whatif(self):
        """Run the JAOT what-if batch on a solved scenario (P4.3, SPECS
        §6.2 step 5): POST the bodyless scenario-analysis on the solved
        execution and mark it requested. The reconcile cron polls the job
        and stores the rows (SPECS §10.1: the re-solves run out of band)."""
        self.ensure_one()
        if self.state not in ('solved', 'applied'):
            raise UserError(_("Only a solved scenario can be analyzed."))
        if not self.jaot_execution_id:
            raise UserError(_("This scenario has no JAOT execution to "
                              "analyze."))
        config = self.env['jaot.config']._require_config(self.company_id)
        client = config.get_client()
        try:
            client.scenario_analysis(self.jaot_execution_id)
        except JaotAPIError as exc:
            self.whatif_state = 'failed'
            self.whatif_error = str(exc)
            self.message_post(body=_("What-if analysis failed to start: %s",
                                     exc))
            raise UserError(_("What-if analysis failed to start: %s", exc)) \
                from exc
        self.whatif_state = 'requested'
        self.whatif_error = False
        self.message_post(body=_("What-if analysis requested."))
        return self

    def action_cancel(self):
        """queued/solving -> cancelled: POST …/cancel on the JAOT task."""
        self.ensure_one()
        if self.state not in ('queued', 'solving'):
            raise UserError(_(
                "Only queued or solving scenarios can be cancelled."))
        config = self.env['jaot.config']._require_config(self.company_id)
        client = config.get_client()
        try:
            client.cancel_task(self.jaot_task_id)
        except JaotAPIError as exc:
            raise UserError(_("JAOT cancel failed: %s", exc)) from exc
        self.state = 'cancelled'
        self.message_post(body=_("Cancelled on JAOT."))
        return self

    def action_check_staleness(self):
        """Re-hash the extracted data and flag staleness (SPECS §4.6)."""
        self.ensure_one()
        _snap, snap_hash, _bs = self._extract_snapshot()
        stale = (snap_hash != self.data_snapshot_hash)
        self.data_stale = stale
        if stale:
            message = _("Data is stale: the source records changed after "
                       "extraction.")
            kind = 'warning'
        else:
            message = _("Data is current: the source records are unchanged.")
            kind = 'success'
        return {
            'type': 'ir.actions.client',
            'params': {
                'name': 'display_notification',
                'params': {'title': 'JAOT', 'message': message,
                           'type': kind},
            },
        }

    @api.model
    def reconcile_jaot_scenarios(self):
        """ir.cron entrypoint: poll every queued/solving scenario that has a
        JAOT task id, and time out orphaned ones. Idempotent and safe across
        worker restarts (keyed by jaot_task_id; a known task is re-polled,
        never re-submitted)."""
        scenarios = self.search([
            ('state', 'in', ('queued', 'solving')),
            ('jaot_task_id', '!=', False),
        ])
        for scenario in scenarios:
            try:
                scenario._reconcile_one()
            except Exception as exc:  # keep the cron alive
                scenario.message_post(body=_("Reconcile error: %s", exc))
        # backstop: queued but never got a task id (submit crashed) -> fail
        orphaned = self.search([
            ('state', '=', 'queued'),
            ('jaot_task_id', '=', False),
            ('write_date', '<', fields.Datetime.now()),
        ])
        for scenario in orphaned:
            scenario.state = 'failed'
            scenario.jaot_error = _("Timed out before a JAOT task was "
                                   "recorded.")
        # poll requested what-if batches (P4.3)
        whatif_pending = self.search([
            ('whatif_state', '=', 'requested'),
            ('jaot_execution_id', '!=', False),
        ])
        for scenario in whatif_pending:
            try:
                scenario._reconcile_whatif()
            except Exception as exc:  # keep the cron alive
                scenario.message_post(
                    body=_("What-if reconcile error: %s", exc))
        return len(scenarios)

    def _reconcile_one(self):
        self.ensure_one()
        if self.state not in ('queued', 'solving') or not self.jaot_task_id:
            return
        config = self.env['jaot.config']._config_for(self.company_id)
        if not config:
            return
        try:
            client = config.get_client()
            poll = client.poll_task(self.jaot_task_id)
        except JaotAPIError as exc:
            self.message_post(body=_("Poll transient error (will retry): "
                                     "%s", exc))
            return
        status = poll.get('status')
        if status == 'failed':
            self.jaot_error = str(poll.get('error') or 'solve failed')
            self.response_payload = poll
            self.state = 'failed'
            self.message_post(body=_("JAOT task failed."))
            return
        if status == 'cancelled':
            self.state = 'cancelled'
            return
        if status == 'completed':
            self._finalize_from_execution(config)
            return
        # pending / running
        if self.state == 'queued':
            self.state = 'solving'

    def _reconcile_whatif(self):
        """Poll a requested what-if job (P4.3) and store the rows when it
        completes. ``absent`` means the batch was never started (or expired)
        for this execution: re-POST it."""
        self.ensure_one()
        if self.whatif_state != 'requested' or not self.jaot_execution_id:
            return
        config = self.env['jaot.config']._config_for(self.company_id)
        if not config:
            return
        try:
            client = config.get_client()
            job = client.scenario_analysis_get(self.jaot_execution_id)
        except JaotAPIError as exc:
            self.message_post(body=_("What-if poll transient error (will "
                                     "retry): %s", exc))
            return
        status = job.get('status')
        if status == 'completed':
            self._store_whatif(job.get('analysis') or {})
            self.whatif_state = 'done'
            self.message_post(body=_("What-if analysis ready."))
        elif status == 'failed':
            self.whatif_state = 'failed'
            self.whatif_error = str(job.get('error') or 'what-if failed')
            self.message_post(body=_("What-if analysis failed."))
        elif status == 'absent':
            try:
                client.scenario_analysis(self.jaot_execution_id)
            except JaotAPIError as exc:
                self.whatif_state = 'failed'
                self.whatif_error = str(exc)
        # running -> stay requested and poll again next tick

    def _store_whatif(self, analysis):
        """Store the scenario-analysis rows (P4.3): the RHS relax/tighten
        rows and the decision-flip rows, each as a ``jaot.scenario.whatif``.
        Budget-truncated rows keep their ``SKIPPED_BUDGET`` status so the UI
        can show them as bounds (SPECS §6.2 step 5)."""
        self.ensure_one()
        self.whatif_analysis = analysis
        Whatif = self.env['jaot.scenario.whatif']
        Whatif.search([('scenario_id', '=', self.id)]).unlink()
        seq = 0
        for row in analysis.get('rhs_scenarios') or []:
            seq += 10
            Whatif.create({
                'scenario_id': self.id,
                'sequence': seq,
                'kind': 'rhs',
                'subject': row.get('constraint'),
                'family': row.get('family'),
                'direction': row.get('direction'),
                'rhs_before': row.get('rhs'),
                'rhs_after': row.get('rhs_new'),
                'rhs_delta': row.get('delta'),
                'improves': row.get('improves'),
                'status': row.get('status'),
                'objective_value': row.get('objective_value'),
                'objective_delta': row.get('objective_delta'),
                'solve_time_seconds': row.get('solve_time_seconds'),
                'company_id': self.company_id.id,
            })
        for row in analysis.get('decision_scenarios') or []:
            seq += 10
            Whatif.create({
                'scenario_id': self.id,
                'sequence': seq,
                'kind': 'decision',
                'subject': row.get('variable'),
                'family': row.get('family'),
                'original_value': row.get('original_value'),
                'forced_value': row.get('forced_value'),
                'regret': row.get('regret'),
                'status': row.get('status'),
                'objective_value': row.get('objective_value'),
                'solve_time_seconds': row.get('solve_time_seconds'),
                'company_id': self.company_id.id,
            })

    def _finalize_from_execution(self, config):
        self.ensure_one()
        # a fresh solve invalidates any earlier what-if (P4.3)
        self.whatif_state = 'none'
        self.whatif_analysis = False
        self.whatif_error = False
        self.whatif_line_ids.unlink()
        client = config.get_client()
        execution = client.execution(self.jaot_execution_id)
        solver_status = execution.get('solver_status')
        self.solver_name = execution.get('solver_name')
        self.solver_status = solver_status
        self.response_payload = execution
        self.solve_time_seconds = (execution.get('execution_time_ms') or 0) / 1000
        result_data = execution.get('result_data') or {}
        if solver_status == 'infeasible':
            try:
                self.infeasibility = client.infeasibility_analysis(
                    self.jaot_execution_id)
            except JaotAPIError as exc:
                self.infeasibility = {'note': str(exc)}
            self.jaot_error = _("Infeasible.")
            self.state = 'failed'
            self.message_post(body=_("Solve is infeasible (IIS captured)."))
            return
        model_values = result_data.get('model') or {}
        formula = get_formulation(self.recipe_id.code)
        if not formula:
            raise UserError(_(
                "No formulation registered for recipe code '%(c)s'.",
                c=self.recipe_id.code))
        lines = formula.map_solution(self.request_payload, model_values)
        Line = self.env['jaot.scenario.line']
        Line.search([('scenario_id', '=', self.id)]).unlink()
        for i, line in enumerate(lines, start=1):
            Line.create({
                'scenario_id': self.id,
                'sequence': i * 10,
                'res_model': line['res_model'],
                'res_id': line['res_id'],
                'decision': line['decision'],
                'kpi_contribution': line.get('kpi_contribution'),
                'company_id': self.company_id.id,
            })
        self.objective_value = (result_data.get('objective_value')
                                if result_data.get('objective_value') is not None
                                else execution.get('objective_value'))
        self.gap = result_data.get('gap')
        self.kpi_summary = {
            'objective_value': self.objective_value,
            'sense': self.objective_sense,
            'selected_count': sum(
                1 for l in lines
                if l['decision'].get('selected')),
        } if lines else None
        self.state = 'solved'
        self.message_post(body=_("Solved: objective %(o)s (%(s)s).",
                                 o=self.objective_value,
                                 s=solver_status or '?'))
        if self.is_baseline and self.baseline_of_id:
            self._store_baseline_delta(self.baseline_of_id)

    def _store_baseline_delta(self, parent):
        """Write the baseline-vs-optimized KPI delta onto the optimized
        scenario (the parent) once this baseline scenario is solved."""
        parent.ensure_one()
        baseline_objective = self.objective_value
        optimized_objective = parent.objective_value
        sense = parent.objective_sense
        if (baseline_objective is not None
                and optimized_objective is not None):
            delta = (baseline_objective - optimized_objective
                     if sense != 'maximize'
                     else optimized_objective - baseline_objective)
        else:
            delta = None
        parent.baseline_scenario_id = self.id
        summary = dict(parent.kpi_summary or {})
        summary.update({
            'baseline_objective': baseline_objective,
            'optimized_objective': optimized_objective,
            'delta_vs_baseline': delta,
            'sense': sense,
        })
        parent.kpi_summary = summary
        self._store_line_deltas(parent)

    def _store_line_deltas(self, parent):
        """Per-line diff of the optimized plan against the incumbent
        (SPECS 4.6 line-by-line diff): which decision fields changed and by
        how much, plus the KPI contribution swing."""
        Line = self.env['jaot.scenario.line']
        baseline_lines = {
            (l.res_model, l.res_id): l
            for l in Line.search([('scenario_id', '=', self.id)])}
        for line in Line.search([('scenario_id', '=', parent.id)]):
            base = baseline_lines.get((line.res_model, line.res_id))
            base_dec = (base.decision or {}) if base else {}
            delta = {}
            for field, opt_val in (line.decision or {}).items():
                base_val = base_dec.get(field)
                if base_val != opt_val:
                    delta[field] = {'baseline': base_val,
                                    'optimized': opt_val}
            if (base and line.kpi_contribution is not None
                    and base.kpi_contribution is not None
                    and line.kpi_contribution != base.kpi_contribution):
                delta['kpi_delta'] = (line.kpi_contribution
                                      - base.kpi_contribution)
            line.delta_vs_baseline = delta or None

    # ------------------------------------------------------------------
    # apply engine (SPECS §4.5, D6)
    # ------------------------------------------------------------------
    def _read_field_path(self, rec, field_path):
        cur = rec
        for hop in field_path.split('.'):
            if cur is False or cur is None:
                return False
            cur = cur[hop]
        return cur

    @staticmethod
    def _json_safe(value):
        """Reduce a field value to something a Json column can store:
        m2o recordsets to their id, datetimes to ISO strings."""
        from datetime import date, datetime
        if value is False or value is None:
            return value
        if hasattr(value, '_ids'):
            return value.id if len(value) == 1 else list(value.ids)
        if isinstance(value, (datetime, date)):
            return value.isoformat(sep=' ')
        return value

    def _write_field_path(self, rec, field_path, value):
        hops = field_path.split('.')
        target = rec
        for hop in hops[:-1]:
            target = target[hop]
            if target is False or target is None:
                raise UserError(_(
                    "Cannot write '%(p)s': an intermediate record is "
                    "missing.", p=field_path))
        target.write({hops[-1]: value})

    def action_apply(self):
        """solved -> applied: write every line's decision to the Odoo records
        in batches inside savepoints, logging before/after to
        jaot.apply.log (SPECS §4.5, §7.5)."""
        self.ensure_one()
        if self.state != 'solved':
            raise UserError(_("Only solved scenarios can be applied."))
        lines = self.scenario_line_ids.filtered(
            lambda l: l.decision and l.res_model and l.res_id)
        if not lines:
            raise UserError(_("This scenario has no decision lines to apply."))
        now = fields.Datetime.now()
        log_model = self.env['jaot.apply.log']
        applied = 0
        for i, line in enumerate(lines, start=1):
            rec = self.env[line.res_model].browse(line.res_id)
            if not rec.exists():
                continue
            with self.env.cr.savepoint():
                for field_path, value in line.decision.items():
                    before_raw = self._read_field_path(rec, field_path)
                    before = self._json_safe(before_raw)
                    if before != self._json_safe(value):
                        self._write_field_path(rec, field_path, value)
                    log_model.create({
                        'scenario_id': self.id,
                        'sequence': i,
                        'res_model': line.res_model,
                        'res_id': line.res_id,
                        'field_path': field_path,
                        'before_value': before,
                        'after_value': self._json_safe(value),
                        'state': 'applied',
                        'applied_at': now,
                        'company_id': self.company_id.id,
                    })
            applied += 1
        self.write({
            'applied': True,
            'applied_at': now,
            'applied_by': self.env.user.id,
            'state': 'applied',
        })
        self.message_post(body=_("Applied %(n)s line(s).", n=applied))
        return self

    def action_revert(self):
        """applied -> solved: re-apply the logged before-state through the
        same machinery (SPECS §4.5: revertible)."""
        self.ensure_one()
        if self.state != 'applied':
            raise UserError(_("Only applied scenarios can be reverted."))
        logs = self.env['jaot.apply.log'].search([
            ('scenario_id', '=', self.id),
            ('state', '=', 'applied'),
        ])
        if not logs:
            raise UserError(_("No applied changes to revert for this "
                              "scenario."))
        now = fields.Datetime.now()
        for log in logs:
            rec = self.env[log.res_model].browse(log.res_id)
            if rec.exists():
                with self.env.cr.savepoint():
                    self._write_field_path(rec, log.field_path,
                                           log.before_value)
            log.state = 'reverted'
            log.reverted_at = now
        self.write({'applied': False, 'state': 'solved'})
        self.message_post(body=_("Reverted %(n)s change(s).", n=len(logs)))
        return self


class JaotScenarioLine(models.Model):
    _name = 'jaot.scenario.line'
    _description = 'JAOT scenario line'

    scenario_id = fields.Many2one(
        'jaot.scenario', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    res_model = fields.Char(string='Odoo model')
    res_id = fields.Integer(string='Odoo record id')
    decision = fields.Json(string='Decision')
    kpi_contribution = fields.Float()
    delta_vs_baseline = fields.Json(string='Delta vs baseline')
    note = fields.Char()
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        copy=False)


class JaotScenarioWhatif(models.Model):
    """One what-if row from the JAOT scenario-analysis batch (P4.3).

    Two kinds share the table: ``rhs`` rows (a constraint's RHS relaxed or
    tightened) and ``decision`` rows (a binary flipped). Budget-truncated
    rows keep their ``SKIPPED_BUDGET`` status and a null objective so the
    view can present them as bounds, never as a silent gap.
    """

    _name = 'jaot.scenario.whatif'
    _description = 'JAOT scenario what-if row'
    _order = 'sequence, id'

    scenario_id = fields.Many2one(
        'jaot.scenario', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    kind = fields.Selection([
        ('rhs', 'Constraint RHS'),
        ('decision', 'Decision flip'),
    ], required=True)
    subject = fields.Char(string='Subject')
    family = fields.Char()
    direction = fields.Char(string='Direction')
    rhs_before = fields.Float(string='RHS (before)')
    rhs_after = fields.Float(string='RHS (after)')
    rhs_delta = fields.Float(string='RHS delta')
    improves = fields.Boolean(string='Improves')
    original_value = fields.Float(string='Original value')
    forced_value = fields.Float(string='Forced value')
    regret = fields.Float(string='Regret')
    status = fields.Char(
        string='Status',
        help='computed, infeasible, or SKIPPED_BUDGET (shown as a bound).')
    objective_value = fields.Float(string='Objective value')
    objective_delta = fields.Float(string='Objective delta')
    solve_time_seconds = fields.Float()
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        copy=False)
