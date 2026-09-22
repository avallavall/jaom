# -*- coding: utf-8 -*-
# License LGPL-3
"""Pure-Python tests for the demand-forecasting math (P9.5).

No Odoo, no database: the module is framework-free, so it is driven with
plain sequences.
"""
from odoo.tests.common import BaseCase

from ..jaot_forecast_math import (
    _sample_std,
    abc_classes,
    adi,
    backtest,
    croston_sba,
    forecast,
    holt,
    method_for,
    normal_cdf,
    normal_ppf,
    quantiles,
    safety_stock,
)


class TestForecastMath(BaseCase):

    # -- normal distribution --------------------------------------------
    def test_normal_cdf_known_points(self):
        self.assertAlmostEqual(normal_cdf(0.0), 0.5, places=12)
        self.assertAlmostEqual(normal_cdf(1.96), 0.975, places=3)
        self.assertAlmostEqual(normal_cdf(-1.96), 0.025, places=3)

    def test_normal_ppf_roundtrip(self):
        # ppf is the exact inverse of cdf (bisection on the exact cdf)
        self.assertAlmostEqual(normal_ppf(0.975), 1.959964, places=4)
        self.assertAlmostEqual(normal_ppf(0.5), 0.0, places=12)
        self.assertAlmostEqual(normal_cdf(normal_ppf(0.95)), 0.95,
                              places=9)

    def test_sample_std(self):
        self.assertEqual(_sample_std([]), 0.0)
        self.assertEqual(_sample_std([5.0]), 0.0)
        self.assertAlmostEqual(_sample_std([1.0, 2.0, 3.0]), 1.0, places=9)
        # ddof=1: squared deviations sum to 32, so std is sqrt(32/7)
        self.assertAlmostEqual(_sample_std([2, 4, 4, 4, 5, 5, 7, 9]),
                               2.13809, places=4)

    # -- classification -------------------------------------------------
    def test_adi(self):
        self.assertAlmostEqual(adi([1, 0, 0, 2, 0, 0, 3]), 3.0, places=12)
        # consecutive demand -> ADI 1.0
        self.assertAlmostEqual(adi([1, 1, 1, 1]), 1.0, places=12)
        # fewer than two nonzero periods -> not enough history
        self.assertIsNone(adi([0, 0, 5]))
        self.assertIsNone(adi([0, 0, 0]))

    def test_method_for(self):
        self.assertEqual(method_for(1.0), 'ets')
        self.assertEqual(method_for(2.0), 'croston')
        self.assertEqual(method_for(1.32), 'croston')  # not *below* 1.32
        self.assertEqual(method_for(1.31), 'ets')
        self.assertEqual(method_for(None), 'ets')

    def test_abc_classes(self):
        self.assertEqual(abc_classes([100, 50, 10, 5, 5]),
                         ['A', 'A', 'B', 'B', 'C'])
        # aligned to input order, not the sorted order
        self.assertEqual(abc_classes([5, 100]), ['C', 'A'])
        # no positive value -> all C
        self.assertEqual(abc_classes([0, 0]), ['C', 'C'])

    # -- methods --------------------------------------------------------
    def test_holt_linear(self):
        fc, errors = holt([10, 12, 14, 16], 0.5, 0.3, 3)
        self.assertEqual(fc, [18, 20, 22])
        self.assertEqual(errors, [0.0, 0.0, 0.0])

    def test_holt_short_series(self):
        fc, errors = holt([4], 0.5, 0.3, 2)
        self.assertEqual(fc, [0.0, 0.0])
        self.assertEqual(errors, [])

    def test_croston_sba_rate(self):
        fc, errors = croston_sba([0, 5, 0, 0, 7, 0, 0, 6], 0.4, 0.3, 3)
        self.assertAlmostEqual(fc[0], 10.096, places=3)
        # constant expected rate over the horizon
        self.assertEqual(fc, [fc[0]] * 3)
        self.assertEqual(len(errors), 8)

    def test_croston_no_demand(self):
        fc, _ = croston_sba([0, 0, 0], 0.4, 0.3, 2)
        self.assertEqual(fc, [0.0, 0.0])

    def test_forecast_dispatch(self):
        self.assertEqual(forecast([1, 2, 3], 'ets', 0.5, 0.3, 1)[0],
                         holt([1, 2, 3], 0.5, 0.3, 1)[0])
        self.assertEqual(forecast([0, 1, 0], 'croston', 0.5, 0.3, 1)[0],
                         croston_sba([0, 1, 0], 0.5, 0.3, 1)[0])
        with self.assertRaises(ValueError):
            forecast([1, 2], 'bogus', 0.5, 0.3, 1)

    # -- quantiles ------------------------------------------------------
    def test_quantiles(self):
        q = quantiles([10.0, 11.0], [1.0, -1.0, 2.0, -2.0], 0.95)
        self.assertAlmostEqual(q[0], 13.003, places=3)
        self.assertAlmostEqual(q[1], 15.247, places=3)

    def test_quantiles_no_errors(self):
        self.assertEqual(quantiles([10.0, 11.0], [], 0.95),
                         [10.0, 11.0])

    # -- backtest -------------------------------------------------------
    def test_backtest_exact_linear(self):
        # Holt tracks a perfectly linear series, so the holdout is exact
        result = backtest([10, 12, 14, 16, 18, 20], 'ets', 0.5, 0.3, 2)
        self.assertEqual(result['n'], 2)
        self.assertAlmostEqual(result['mape'], 0.0, places=9)
        self.assertAlmostEqual(result['bias'], 0.0, places=9)

    def test_backtest_too_short(self):
        result = backtest([1, 2], 'ets', 0.5, 0.3, 1)
        self.assertIsNone(result['mape'])
        self.assertEqual(result['n'], 0)

    def test_backtest_zero_actuals(self):
        # held-out actuals are all zero -> MAPE undefined
        result = backtest([5, 0, 0, 0, 0, 0], 'ets', 0.5, 0.3, 2)
        self.assertIsNone(result['mape'])
        self.assertEqual(result['n'], 2)

    # -- safety stock ---------------------------------------------------
    def test_safety_stock(self):
        self.assertAlmostEqual(safety_stock(10.0, 2.0, 5, 0.95), 57.356,
                              places=3)
        self.assertEqual(safety_stock(10.0, 2.0, 0, 0.95), 0.0)
        # zero variance -> just the lead-time demand mean
        self.assertAlmostEqual(safety_stock(10.0, 0.0, 5, 0.95), 50.0,
                              places=9)
