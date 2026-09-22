# -*- coding: utf-8 -*-
# License LGPL-3
"""Odoo tests for the demand-forecasting bridge (SPECS 13.5, PLAN P9.5).

These exercise the refresh flow (history extraction, classification,
forecast, safety stock, demand rows), the staleness check, and the recipe
role/binding data. History is seeded with done outgoing ``stock.move``
records spread over past months.
"""
import calendar
from datetime import date

from odoo import fields
from odoo.tests.common import TransactionCase


class TestForecast(TransactionCase):

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _month_back(self, n, day=15):
        """The mid-month date ``n`` months before today (n=0 -> this month)."""
        today = fields.Date.context_today(self)
        m = today.month - 1 - n
        y = today.year + m // 12
        m = m % 12 + 1
        d = min(day, calendar.monthrange(y, m)[1])
        return date(y, m, d)

    def _product(self):
        return self.env['product.product'].create(
            {'name': 'FC Widget', 'type': 'consu'})

    def _seed_move(self, product, qty, dt):
        wh = self.env.ref('stock.warehouse0')
        return self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom': product.uom_id.id,
            'product_uom_qty': qty,
            'location_id': wh.lot_stock_id.id,
            'location_dest_id': self.env.ref(
                'stock.stock_location_customers').id,
            'state': 'done',
            'date': dt,
            'company_id': self.env.company.id,
        })

    def _forecast(self, product):
        return self.env['jaot.forecast'].create({
            'product_id': product.id,
            'company_id': self.env.company.id,
        })

    # ------------------------------------------------------------------
    # recipe roles / bindings
    # ------------------------------------------------------------------
    def test_recipe_has_forecast_roles(self):
        recipe = self.env.ref('jaot_mrp.recipe_mrp')
        roles = {r.name: r for r in recipe.recipe_role_ids}
        self.assertIn('forecast_demand', roles)
        self.assertIn('forecast_period', roles)
        self.assertEqual(roles['forecast_demand'].kind, 'variable')
        self.assertFalse(roles['forecast_demand'].required)
        self.assertEqual(roles['forecast_period'].kind, 'variable')
        self.assertFalse(roles['forecast_period'].required)

    def test_default_bindings_point_at_demand_model(self):
        recipe = self.env.ref('jaot_mrp.recipe_mrp')
        bindings = {b.role_id.name: b for b in recipe.binding_ids}
        demand = bindings['forecast_demand']
        period = bindings['forecast_period']
        self.assertEqual(demand.res_model, 'jaot.forecast.demand')
        self.assertEqual(demand.field_path, 'quantity')
        self.assertEqual(period.res_model, 'jaot.forecast.demand')
        self.assertEqual(period.field_path, 'period_start')

    # ------------------------------------------------------------------
    # refresh flow
    # ------------------------------------------------------------------
    def test_refresh_smooth_is_ets(self):
        product = self._product()
        # demand in every of the last 10 months -> ADI 1.0 -> ETS
        for n in range(10):
            self._seed_move(product, 10.0, self._month_back(n))
        fc = self._forecast(product)
        fc.action_refresh()
        self.assertEqual(fc.method, 'ets')
        self.assertLess(fc.adi, 1.32)
        self.assertIn(fc.abc_class, ('A', 'B', 'C'))
        self.assertEqual(len(fc.demand_ids), fc.horizon)
        self.assertTrue(fc.run_at)
        self.assertTrue(fc.history_hash)
        self.assertFalse(fc.data_stale)
        self.assertGreaterEqual(fc.safety_stock, 0.0)

    def test_refresh_intermittent_is_croston(self):
        product = self._product()
        # demand only every third month -> ADI ~3.0 -> Croston/SBA
        for n in (0, 3, 6, 9):
            self._seed_move(product, 20.0, self._month_back(n))
        fc = self._forecast(product)
        fc.action_refresh()
        self.assertEqual(fc.method, 'croston')
        self.assertGreaterEqual(fc.adi, 1.32)

    def test_refresh_no_history(self):
        product = self._product()
        fc = self._forecast(product)
        fc.action_refresh()
        # all-zero history -> ETS fallback, zero forecasts, no crash
        self.assertEqual(fc.method, 'ets')
        self.assertTrue(fc.demand_ids)
        self.assertEqual(
            [d.quantity for d in fc.demand_ids],
            [0.0] * len(fc.demand_ids))

    def test_refresh_demand_rows_future(self):
        product = self._product()
        for n in range(6):
            self._seed_move(product, 12.0, self._month_back(n))
        fc = self._forecast(product)
        fc.action_refresh()
        rows = fc.demand_ids.sorted('period_index')
        self.assertEqual(len(rows), fc.horizon)
        # periods start the month after the window's last month
        next_month = self._month_back(0)
        next_month = date(next_month.year, next_month.month, 1)
        self.assertGreater(rows[0].period_start, next_month)
        # the first period carries the safety stock on top of the quantile
        self.assertGreaterEqual(rows[0].quantity,
                                fc.quantile_forecasts[0])
        # demand rows carry the product and company
        self.assertTrue(all(d.product_id == product
                            for d in rows))
        self.assertTrue(all(d.company_id == self.env.company
                            for d in rows))

    def test_refresh_is_idempotent(self):
        product = self._product()
        for n in range(6):
            self._seed_move(product, 12.0, self._month_back(n))
        fc = self._forecast(product)
        fc.action_refresh()
        first_count = len(fc.demand_ids)
        fc.action_refresh()
        self.assertEqual(len(fc.demand_ids), first_count)
        self.assertEqual(len(fc.demand_ids), fc.horizon)

    # ------------------------------------------------------------------
    # staleness (SPECS 4.6)
    # ------------------------------------------------------------------
    def test_staleness_check(self):
        product = self._product()
        for n in range(6):
            self._seed_move(product, 12.0, self._month_back(n))
        fc = self._forecast(product)
        fc.action_refresh()
        self.assertFalse(fc.data_stale)
        # a fresh demand row in the window changes the history
        self._seed_move(product, 40.0, self._month_back(1))
        fc.action_check_staleness()
        self.assertTrue(fc.data_stale)
        # re-refresh clears the flag
        fc.action_refresh()
        self.assertFalse(fc.data_stale)
