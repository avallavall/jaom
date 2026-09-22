# -*- coding: utf-8 -*-
# License LGPL-3
"""Framework-free demand-forecasting math for the forecast bridge (P9.5).

No Odoo imports, so every function is unit-testable with plain Python
sequences. It provides: item classification (ADI + ABC), the two forecast
methods (Holt exponential smoothing for smooth items, Croston with the
Syntetos-Boyd (1 - beta/2) correction for intermittent items), quantiles
via a normal approximation of the smoothed one-step error, a holdout
backtest (MAPE + bias), and safety stock at a chosen service level.
"""
import math


# ----------------------------------------------------------------------
# Normal distribution
# ----------------------------------------------------------------------
def normal_cdf(z):
    """Standard normal CDF at ``z`` (exact via ``erf``)."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def normal_ppf(p, tol=1e-12, itmax=300):
    """Standard normal quantile at probability ``p`` in (0, 1).

    Computed by bisection on :func:`normal_cdf` (which is exact), so there
    are no hand-transcribed rational-approximation coefficients to get
    wrong. The search interval is bounded to +/-50 sigma, which covers any
    service level short of 1 - 1e-13.
    """
    if p <= 0.0:
        return -50.0
    if p >= 1.0:
        return 50.0
    lo, hi = -50.0, 50.0
    for _ in range(itmax):
        mid = (lo + hi) / 2.0
        if normal_cdf(mid) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2.0


def _sample_std(values):
    """Sample standard deviation (ddof=1). 0.0 for fewer than 2 values."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(var)


# ----------------------------------------------------------------------
# Item classification
# ----------------------------------------------------------------------
def adi(series):
    """Average inter-demand interval: the mean number of periods between
    consecutive nonzero-demand periods. ``series`` is per-period demand in
    chronological order. Returns ``None`` when there are fewer than two
    nonzero periods (not enough history to judge intermittency)."""
    nz = [i for i, v in enumerate(series) if v > 0]
    if len(nz) < 2:
        return None
    gaps = [nz[i + 1] - nz[i] for i in range(len(nz) - 1)]
    return sum(gaps) / len(gaps)


def method_for(adi_value, threshold=1.32):
    """Pick the forecast method from the ADI: smooth (ADI below the
    intermittent threshold, default 1.32 per Syntetos-Boyyanidis) -> Holt
    ETS; otherwise intermittent -> Croston/SBA. ``adi_value`` of ``None``
    falls back to ETS (not enough history to call it intermittent)."""
    if adi_value is None or adi_value < threshold:
        return 'ets'
    return 'croston'


def abc_classes(values, a=0.80, b=0.95):
    """Classify products A/B/C by descending usage value (default 80/15/5).

    ``values`` is a list of per-product usage values (>= 0). Returns a list
    of the same length, aligned to the input positions (not the sorted
    order): an item is A while the cumulative share of total value (up to
    the previous item) is below ``a``, B while it is below ``b``, C beyond.
    With no positive value every item is C.
    """
    total = sum(values)
    if total <= 0:
        return ['C'] * len(values)
    order = sorted(range(len(values)), key=lambda i: values[i], reverse=True)
    classes = ['C'] * len(values)
    cum = 0.0
    for i in order:
        if cum < a:
            classes[i] = 'A'
        elif cum < b:
            classes[i] = 'B'
        cum += values[i] / total
    return classes


# ----------------------------------------------------------------------
# Forecast methods
# ----------------------------------------------------------------------
def holt(series, alpha, beta, horizon):
    """Holt linear exponential smoothing (ETS with trend).

    ``series`` is per-period demand (length >= 2). Returns
    ``(forecasts, errors)``: ``forecasts`` is a list of ``horizon``
    multi-step-ahead point forecasts (period n+1 .. n+horizon) from the
    final level/trend; ``errors`` is the one-step-ahead forecast error per
    in-sample period (used for the quantile std).
    """
    n = len(series)
    if n < 2:
        return [0.0] * horizon, []
    level = series[0]
    trend = series[1] - series[0]
    errors = []
    for t in range(1, n):
        fc = level + trend
        errors.append(series[t] - fc)
        level_new = alpha * series[t] + (1.0 - alpha) * (level + trend)
        trend = beta * (level_new - level) + (1.0 - beta) * trend
        level = level_new
    forecasts = [level + h * trend for h in range(1, horizon + 1)]
    return forecasts, errors


def croston_sba(series, alpha, beta, horizon):
    """Croston's method for intermittent demand, with the Syntetos-Boyd
    Approximation bias correction (1 - beta/2).

    ``series`` is per-period demand including zeros. Returns
    ``(forecasts, errors)``: ``forecasts`` is a list of ``horizon`` expected
    demands, each equal to the final smoothed rate ``d_hat * I_hat *
    (1 - beta/2)`` (units per period); ``errors`` is the one-step-ahead
    error per in-sample period (actual minus the expected rate then known),
    used for the quantile std.
    """
    d_hat = None
    i_hat = None
    last_nz = None
    errors = []
    for t, y in enumerate(series):
        if d_hat is not None and i_hat is not None:
            rate = d_hat * i_hat * (1.0 - beta / 2.0)
        else:
            rate = 0.0
        errors.append(y - rate)
        if y > 0:
            if d_hat is None:
                d_hat = y
                i_hat = 1.0
            else:
                d_hat = (1.0 - alpha) * d_hat + alpha * y
                interval = t - last_nz
                i_hat = (1.0 - beta) * i_hat + beta * interval
            last_nz = t
    if d_hat is not None and i_hat is not None:
        rate = d_hat * i_hat * (1.0 - beta / 2.0)
    else:
        rate = 0.0
    forecasts = [rate] * horizon
    return forecasts, errors


def forecast(series, method, alpha, beta, horizon):
    """Dispatch to the requested method. Returns ``(forecasts, errors)``."""
    if method == 'ets':
        return holt(series, alpha, beta, horizon)
    if method == 'croston':
        return croston_sba(series, alpha, beta, horizon)
    raise ValueError(f'unknown forecast method {method!r}')


def quantiles(forecast_means, errors, service_level):
    """Quantile-adjusted forecasts at ``service_level``.

    ``forecast_means`` is the list of point forecasts (one per horizon
    period); ``errors`` the one-step-ahead error series. Each value is
    ``mean_h + z * std * sqrt(h)`` where ``z = normal_ppf(service_level)``
    and ``std`` is the sample std of ``errors`` — the multi-step error is
    the one-step std scaled by the square root of the horizon (independence
    assumption), a standard, auditable approximation. With no errors the
    point forecasts are returned unchanged.
    """
    if not errors:
        return list(forecast_means)
    z = normal_ppf(service_level)
    std = _sample_std(errors)
    return [m + z * std * math.sqrt(h)
            for h, m in enumerate(forecast_means, start=1)]


# ----------------------------------------------------------------------
# Backtest
# ----------------------------------------------------------------------
def backtest(series, method, alpha, beta, holdout):
    """Holdout backtest: fit on ``series[:-holdout]``, forecast the last
    ``holdout`` periods (h-step-ahead, h = 1..holdout), and report MAPE and
    signed bias against the held-out actuals.

    Returns ``{'mape': float | None, 'bias': float | None, 'n': int}``.
    MAPE skips zero-actual periods (division by zero); when every held-out
    actual is zero, ``mape`` is ``None``. ``bias`` is the mean signed error
    (actual - forecast) over the held-out periods.
    """
    if holdout < 1 or len(series) - holdout < 2:
        return {'mape': None, 'bias': None, 'n': 0}
    train = series[:-holdout]
    test = series[-holdout:]
    fc, _ = forecast(train, method, alpha, beta, holdout)
    errs = [test[i] - fc[i] for i in range(len(test))]
    abs_pct = [abs(e) / test[i] for i, e in enumerate(errs)
               if test[i] > 1e-12]
    mape = (sum(abs_pct) / len(abs_pct)) if abs_pct else None
    bias = (sum(errs) / len(errs)) if errs else None
    return {'mape': mape, 'bias': bias, 'n': len(errs)}


# ----------------------------------------------------------------------
# Safety stock
# ----------------------------------------------------------------------
def safety_stock(mean_per_period, std_per_period, lead_time, service_level):
    """Safety stock at ``service_level``: the quantile of demand over the
    effective lead time. Lead-time demand mean is ``mean_per_period *
    lead_time``; its std is the per-period std scaled by ``sqrt(lead_time)``
    (independence assumption). Returns ``mean_lt + z * std_lt`` with
    ``z = normal_ppf(service_level)``.
    """
    if lead_time <= 0:
        return 0.0
    mean_lt = mean_per_period * lead_time
    std_lt = std_per_period * math.sqrt(lead_time)
    z = normal_ppf(service_level)
    return mean_lt + z * std_lt
