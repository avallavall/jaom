# -*- coding: utf-8 -*-
# License LGPL-3
"""Demand forecasting bridge (SPECS §13.5, PLAN P9.5).

``jaot.forecast`` classifies a product (ADI + ABC) over a 24-month window
of ``stock.move`` history and runs the matching method (Holt ETS or
Croston/SBA) to produce quantile forecasts plus a safety stock at a
chosen service level. The per-period forecast quantities live on
``jaot.forecast.demand`` rows, which the lot-sizing recipe reads through
its ``forecast_demand`` / ``forecast_period`` roles.
"""
import hashlib
import json
from collections import defaultdict
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..jaot_forecast_math import (
    _sample_std,
    abc_classes,
    adi as adi_value,
    backtest,
    forecast,
    method_for,
    quantiles,
    safety_stock,
)


class JaotForecast(models.Model):
    _name = 'jaot.forecast'
    _description = 'JAOT demand forecast'

    name = fields.Char(
        compute='_compute_name', store=False, readonly=True)
    product_id = fields.Many2one(
        'product.product', required=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)

    # item classification (filled by the refresh)
    method = fields.Selection([
        ('ets', 'ETS (Holt)'),
        ('croston', 'Croston/SBA'),
    ], default='ets')
    adi = fields.Float(
        string='ADI',
        help='Average inter-demand interval: mean number of periods '
             'between consecutive nonzero-demand periods.')
    abc_class = fields.Selection([
        ('A', 'A'), ('B', 'B'), ('C', 'C'),
    ])

    # model inputs (planner-tunable, used by the refresh)
    alpha = fields.Float(
        default=0.4, help='Level / demand-size smoothing parameter.')
    beta = fields.Float(
        default=0.3, help='Trend / inter-demand-interval smoothing '
                          'parameter.')
    horizon = fields.Integer(
        default=12, help='Number of future periods to forecast.')
    window_months = fields.Integer(
        default=24, help='History window (months) used for the '
                         'classification and the forecast.')
    service_level = fields.Float(
        default=0.95, help='Service level for the forecast quantiles and '
                           'the safety stock.')
    lead_time = fields.Float(
        default=1.0, help='Effective lead time (in periods) used for the '
                          'safety stock.')

    # results (filled by the refresh)
    point_forecasts = fields.Json(
        string='Point forecasts',
        help='Per-period point forecasts (list, one per horizon period).')
    quantile_forecasts = fields.Json(
        string='Quantile forecasts',
        help='Per-period forecasts at the chosen service level (list).')
    mape = fields.Float(
        string='Backtest MAPE',
        help='Mean absolute percentage error over the held-out tail.')
    bias = fields.Float(
        string='Backtest bias',
        help='Mean signed error (actual - forecast) over the held-out '
             'tail.')
    safety_stock = fields.Float(
        string='Safety stock',
        help='Quantile of demand over the effective lead time at the '
             'chosen service level.')
    run_at = fields.Datetime(
        string='Run at', help='When the forecast was last refreshed.')

    # staleness (SPECS §4.6)
    history_hash = fields.Char(
        string='History hash', copy=False,
        help='Hash of the demand history used for the last refresh; '
             'compared by the staleness check.')
    data_stale = fields.Boolean(
        string='Stale', default=False, copy=False,
        help='The demand history changed after the last refresh.')

    demand_ids = fields.One2many(
        'jaot.forecast.demand', 'forecast_id')
    demand_count = fields.Integer(
        string='Demand rows', compute='_compute_demand_count')

    _product_company_uniq = models.Constraint(
        'UNIQUE (product_id, company_id)',
        'One forecast per product per company.')

    @api.depends('product_id')
    def _compute_name(self):
        for rec in self:
            rec.name = rec.product_id.name

    @api.depends('demand_ids')
    def _compute_demand_count(self):
        for rec in self:
            rec.demand_count = len(rec.demand_ids)

    # ------------------------------------------------------------------
    # history extraction
    # ------------------------------------------------------------------
    def _window_months_list(self, ref_date, window_months):
        """The (year, month) pairs of the last ``window_months`` months
        ending at ``ref_date``'s month, oldest first."""
        y, m = ref_date.year, ref_date.month
        months = []
        for _ in range(window_months):
            months.append((y, m))
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        months.reverse()
        return months

    def _window_range(self, ref_date, window_months):
        """The [start, end) date range of the history window."""
        months = self._window_months_list(ref_date, window_months)
        start = date(months[0][0], months[0][1], 1)
        end_next = self._add_months(date(ref_date.year, ref_date.month, 1), 1)
        return start, end_next

    @staticmethod
    def _add_months(first_of_month, n):
        """The first day of the month ``n`` months after ``first_of_month``."""
        m = first_of_month.month - 1 + n
        y = first_of_month.year + m // 12
        m = m % 12 + 1
        return date(y, m, 1)

    def _outgoing_moves_domain(self, product_id, ref_date, window_months):
        start, end = self._window_range(ref_date, window_months)
        domain = [
            ('product_id', '=', product_id),
            ('state', '=', 'done'),
            ('location_dest_id.usage', '=', 'customer'),
            ('date', '>=', start),
            ('date', '<', end),
        ]
        if self.company_id:
            domain += [('company_id', 'in', [self.company_id.id, False])]
        return domain

    def _monthly_demand(self, product, ref_date=None):
        """Per-month outgoing demand (units) over the window, oldest
        first, aligned to calendar months."""
        if ref_date is None:
            ref_date = fields.Date.context_today(self)
        window = self.window_months
        domain = self._outgoing_moves_domain(product.id, ref_date, window)
        moves = self.env['stock.move'].search(domain)
        series = [0.0] * window
        month_index = {
            (y, m): i for i, (y, m) in enumerate(
                self._window_months_list(ref_date, window))}
        for mv in moves:
            d = mv.date
            if isinstance(d, str):
                d = date.fromisoformat(d[:10])
            key = (d.year, d.month)
            if key in month_index:
                series[month_index[key]] += float(mv.product_qty or 0.0)
        return series

    def _usage_values(self, ref_date=None):
        """Per-product outgoing usage (units) over the window, for the
        company: ``{product_id: total_qty}``."""
        if ref_date is None:
            ref_date = fields.Date.context_today(self)
        start, end = self._window_range(ref_date, self.window_months)
        domain = [
            ('state', '=', 'done'),
            ('location_dest_id.usage', '=', 'customer'),
            ('date', '>=', start),
            ('date', '<', end),
        ]
        if self.company_id:
            domain += [('company_id', 'in', [self.company_id.id, False])]
        moves = self.env['stock.move'].search(domain)
        usage = defaultdict(float)
        for mv in moves:
            usage[mv.product_id.id] += float(mv.product_qty or 0.0)
        return usage

    def _abc_class_for(self, product, ref_date=None):
        """The ABC class of ``product`` relative to every other product
        with outgoing usage in the window (usage = units moved out)."""
        if ref_date is None:
            ref_date = fields.Date.context_today(self)
        usage = self._usage_values(ref_date)
        usage[product.id] += 0.0  # keep the target in the set even if zero
        ids = sorted(usage)
        values = [usage[pid] for pid in ids]
        classes = abc_classes(values)
        return classes[ids.index(product.id)]

    @staticmethod
    def _history_hash(payload):
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    # ------------------------------------------------------------------
    # refresh
    # ------------------------------------------------------------------
    def action_refresh(self):
        """Recompute this forecast from the demand history (SPECS §13.5).

        Idempotent: the demand rows are rebuilt from scratch on every run.
        """
        self.ensure_one()
        product = self.product_id
        ref_date = fields.Date.context_today(self)
        window = self.window_months
        horizon = self.horizon
        alpha = self.alpha
        beta = self.beta
        service_level = self.service_level
        lead_time = self.lead_time

        series = self._monthly_demand(product, ref_date)
        adi_v = adi_value(series)
        method = method_for(adi_v)
        abc = self._abc_class_for(product, ref_date)

        point, errors = forecast(series, method, alpha, beta, horizon)
        quant = quantiles(point, errors, service_level)
        bt = backtest(series, method, alpha, beta, min(horizon, len(series) // 2))

        mean = (sum(series) / len(series)) if series else 0.0
        std = _sample_std(series)
        ss = safety_stock(mean, std, lead_time, service_level)

        # Demand rows: period k (1..horizon) starts the month after the
        # window's last month. The first period carries the safety stock
        # as an initial buffer build.
        next_month = self._add_months(
            date(ref_date.year, ref_date.month, 1), 1)
        demand_vals = []
        for k in range(1, horizon + 1):
            period_start = self._add_months(next_month, k - 1)
            qty = float(quant[k - 1])
            if k == 1:
                qty += float(ss)
            demand_vals.append({
                'forecast_id': self.id,
                'product_id': product.id,
                'company_id': self.company_id.id,
                'period_index': k,
                'period_start': period_start,
                'quantity': qty,
            })

        payload = {
            'product_id': product.id,
            'window_months': window,
            'horizon': horizon,
            'alpha': alpha,
            'beta': beta,
            'service_level': service_level,
            'lead_time': lead_time,
            'series': series,
        }
        self.write({
            'method': method,
            'adi': adi_v,
            'abc_class': abc,
            'point_forecasts': point,
            'quantile_forecasts': quant,
            'mape': bt['mape'],
            'bias': bt['bias'],
            'safety_stock': ss,
            'run_at': fields.Datetime.now(),
            'data_stale': False,
            'history_hash': self._history_hash(payload),
        })
        self.demand_ids.unlink()
        if demand_vals:
            self.env['jaot.forecast.demand'].create(demand_vals)
        return self

    @api.model
    def refresh_all(self):
        """ir.cron entrypoint: refresh every forecast (all companies)."""
        for rec in self.search([]):
            try:
                rec.action_refresh()
            except Exception as exc:  # keep the cron alive
                rec.message_post(body=_("Refresh error: %s", exc))
        return self

    # ------------------------------------------------------------------
    # staleness (SPECS §4.6)
    # ------------------------------------------------------------------
    def action_check_staleness(self):
        """Re-extract the demand history and flag staleness (§4.6)."""
        self.ensure_one()
        product = self.product_id
        ref_date = fields.Date.context_today(self)
        series = self._monthly_demand(product, ref_date)
        payload = {
            'product_id': product.id,
            'window_months': self.window_months,
            'horizon': self.horizon,
            'alpha': self.alpha,
            'beta': self.beta,
            'service_level': self.service_level,
            'lead_time': self.lead_time,
            'series': series,
        }
        stale = (self._history_hash(payload) != self.history_hash)
        self.data_stale = stale
        if stale:
            message = _("Forecast is stale: the demand history changed "
                       "after the last refresh.")
            kind = 'warning'
        else:
            message = _("Forecast is current: the demand history is "
                       "unchanged.")
            kind = 'success'
        return {
            'type': 'ir.actions.client',
            'params': {
                'name': 'display_notification',
                'params': {'title': 'JAOT', 'message': message,
                           'type': kind},
            },
        }

    def action_show_demand(self):
        """Open this forecast's demand rows (stat button on the form)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Forecast demand for %(name)s', name=self.name),
            'res_model': 'jaot.forecast.demand',
            'view_mode': 'list',
            'domain': [('forecast_id', '=', self.id)],
            'context': {'default_forecast_id': self.id},
        }


class JaotForecastDemand(models.Model):
    _name = 'jaot.forecast.demand'
    _description = 'JAOT forecast demand row'
    _order = 'forecast_id, period_index'

    forecast_id = fields.Many2one(
        'jaot.forecast', required=True, ondelete='cascade')
    product_id = fields.Many2one(
        'product.product', required=True)
    company_id = fields.Many2one('res.company', required=True)
    period_index = fields.Integer()
    period_start = fields.Date(
        help='Start of the forecast period this row covers.')
    quantity = fields.Float(
        help='Forecast demand at the chosen service level; the first '
             'period includes the safety stock as an initial buffer.')
