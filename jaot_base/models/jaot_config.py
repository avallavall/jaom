# -*- coding: utf-8 -*-
# License LGPL-3
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..jaot_client import JaotClient, JaotAPIError


class JaotConfig(models.Model):
    _name = 'jaot.config'
    _inherit = ['mail.thread']
    _description = 'JAOT connection (one per company)'
    _rec_name = 'endpoint_url'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    endpoint_url = fields.Char(
        string='JAOT base URL', required=True,
        help='Base URL of the self-hosted JAOT instance, e.g. '
             'http://jaot.example.com — the API lives under /api/v2.')
    # The API key never lives on this model: it is stored in
    # ir.config_parameter "jaot.api_key.<company_id>" (SPECS §5.1/§7.1)
    # and only a masked form is ever exposed.
    api_key_set = fields.Boolean(
        string='API key set', readonly=True, compute='_compute_api_key')
    api_key_masked = fields.Char(
        string='API key (masked)', readonly=True, compute='_compute_api_key')
    api_key_input = fields.Char(
        string='New API key', store=False, required=False,
        help='Paste a new JAOT API key and save the form; it is stored in '
             'ir.config_parameter, never on this record.')
    poll_interval = fields.Selection(
        [('5', '5 s'), ('10', '10 s'), ('30', '30 s')],
        string='Poll interval', default='10',
        help='How often the ir.cron polls JAOT for running scenarios '
             '(SPECS §4.4, default 10 s).')
    solve_time_limit = fields.Integer(
        string='Solve time limit (s)', default=300,
        help='Forwarded to JAOT options.time_limit_seconds (SPECS §5.1, '
             'default 300).')
    gap_tolerance = fields.Float(
        string='Gap tolerance', default=0.05,
        help='Forwarded to JAOT options.gap_tolerance (default 0.05).')
    default_solver = fields.Char(
        string='Default solver',
        help='Solver name from JAOT GET /solvers/available (scip, highs, '
             'cbc, glpk on v3.9.0); empty = let the server choose. A '
             'Char rather than a Selection: the solver set is dynamic per '
             'JAOT version, a static list would lie.')
    max_parallel_cases = fields.Integer(
        string='Max parallel cases', default=8,
        help='Maximum number of named scenario cases running (queued or '
             'solving) at once, per company (SPECS 13.2, default 8).')

    _company_id_uniq = models.Constraint(
        'UNIQUE (company_id)',
        'One JAOT connection per company (SPECS §5.1).',
    )

    # ------------------------------------------------------------------
    # api key storage (ir.config_parameter, never on the model)
    # ------------------------------------------------------------------
    @api.model
    def _api_key_param(self, company_id=None):
        company_id = company_id or (self.env.company.id
                                    if self.env.company else None)
        return f"jaot.api_key.{company_id}"

    @api.depends('company_id')
    def _compute_api_key(self):
        # The key lives in a system parameter that non-admins cannot read
        # directly; the compute must not depend on the caller's ACL.
        icp = self.env['ir.config_parameter'].sudo()
        for rec in self:
            key = icp.get_param(self._api_key_param(rec.company_id.id)) \
                if rec.company_id else False
            rec.api_key_set = bool(key)
            if key and len(key) >= 8:
                rec.api_key_masked = f"{key[:4]}…{key[-4:]}"
            elif key:
                rec.api_key_masked = "••••"
            else:
                rec.api_key_masked = False

    @api.model_create_multi
    def create(self, vals_list):
        stored = False
        for vals in vals_list:
            key = (vals.get('api_key_input') or '').strip()
            vals.pop('api_key_input', None)
            if key:
                company_id = vals.get('company_id') \
                    or self.env.company.id
                # Scoped system-parameter write; the manager setting the
                # key through this form is not a system admin, so the
                # write must not depend on the caller's ir.config_parameter
                # ACL.
                self.env['ir.config_parameter'].sudo().set_param(
                    self._api_key_param(company_id), key)
                stored = True
        recs = super().create(vals_list)
        if stored:
            recs.invalidate_recordset(['api_key_set', 'api_key_masked'])
            recs.message_post(body=_("API key stored."))
        return recs

    def write(self, vals):
        if 'api_key_input' in vals:
            self.ensure_one()
            key = (vals.get('api_key_input') or '').strip()
            vals = dict(vals)
            vals.pop('api_key_input', None)
            if key:
                self.env['ir.config_parameter'].sudo().set_param(
                    self._api_key_param(self.company_id.id), key)
                self.invalidate_recordset(
                    ['api_key_set', 'api_key_masked'])
                self.message_post(body=_("API key stored."))
        return super().write(vals)

    def action_clear_api_key(self):
        self.ensure_one()
        self.env['ir.config_parameter'].sudo().set_param(
            self._api_key_param(self.company_id.id), False)
        self.invalidate_recordset(['api_key_set', 'api_key_masked'])
        self.message_post(body=_("API key removed."))
        return True

    # ------------------------------------------------------------------
    # client + connectivity (SPECS §6.1)
    # ------------------------------------------------------------------
    @api.model
    def _config_for(self, company=None):
        company = company or self.env.company
        return self.search([('company_id', '=', company.id)], limit=1)

    @api.model
    def _require_config(self, company=None):
        config = self._config_for(company)
        if not config:
            raise UserError(_(
                "No JAOT connection configured for this company. Create "
                "one in JAOT > Configuration > Connections."))
        return config

    def get_client(self):
        """Build the HTTP client for this connection (SPECS §6.1: Bearer
        key, per-company instance)."""
        self.ensure_one()
        icp = self.env['ir.config_parameter'].sudo()
        key = icp.get_param(self._api_key_param(self.company_id.id))
        if not key:
            raise UserError(_(
                "No API key stored for this connection. Set it in the "
                "connection form."))
        return JaotClient(self.endpoint_url, key)

    def action_test_connection(self):
        """Connectivity check (SPECS §6.1): health/status +
        solvers/available with the key; reports version and checks."""
        self.ensure_one()
        client = self.get_client()
        try:
            health = client.health_status()
            solvers = client.solvers_available()
        except JaotAPIError as exc:
            raise UserError(_(
                "JAOT connection failed: %(exc)s. Detail: %(detail)s",
                exc=exc, detail=exc.detail)) from exc
        names = ", ".join(
            s.get('name', '?') for s in solvers.get('solvers', []))
        message = _("%(status)s %(version)s — %(passed)s/%(total)s health "
                    "checks. Solvers available: %(solvers)s.",
                    status=health.get('status', '?'),
                    version=health.get('version', '?'),
                    passed=health.get('checks_passed', '?'),
                    total=health.get('checks_total', '?'),
                    solvers=names or '?')
        if self.default_solver and self.default_solver not in names:
            message += _(" WARNING: configured default solver '%(s)s' is "
                         "not in the live list.", s=self.default_solver)
        return {
            'type': 'ir.actions.client',
            'params': {
                'name': 'display_notification',
                'params': {
                    'title': 'JAOT',
                    'message': message,
                    'type': 'success' if 'WARNING' not in message
                    else 'warning',
                },
            },
        }
