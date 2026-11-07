"""Forecasting engine — deterministic, user-selectable methods.

Pure Python over a detected :class:`TimeSeriesProfile`. ``numpy`` is required;
``statsmodels`` is an **optional** import — when it is absent the statistical
methods (Holt, Holt-Winters, SARIMA) degrade gracefully to the numpy methods
with a warning, so the app always runs. No LLM, no Qt. Predictions come from
these functions, never from the model that wrote the SQL.
"""

from __future__ import annotations

import math
from typing import Callable

import numpy as np

from app.core.timeseries import available_methods, detect_time_series, future_labels
from app.data.models import (
    ChartSpec,
    ForecastPoint,
    ForecastResult,
    TimeSeriesProfile,
)

try:  # optional dependency
    from statsmodels.tsa.holtwinters import ExponentialSmoothing, Holt
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    _HAS_STATSMODELS = True
except Exception:  # pragma: no cover - exercised only without statsmodels
    _HAS_STATSMODELS = False

FORECAST_MAX_HORIZON = 36
NUMPY_METHODS = {"naive", "seasonal_naive", "moving_average", "linear_trend"}
STATS_METHODS = {"holt", "holt_winters", "sarima"}

# z-scores for common confidence levels (avoids a scipy dependency).
_Z = {0.80: 1.2816, 0.90: 1.6449, 0.95: 1.9600, 0.99: 2.5758}

# Method result: (yhat, lower|None, upper|None, fitted|None, warnings)
MethodResult = tuple[list[float], list[float] | None, list[float] | None, list[float] | None, list[str]]

_CACHE: dict[tuple, ForecastResult] = {}


def has_statsmodels() -> bool:
    return _HAS_STATSMODELS


def supported_methods() -> set[str]:
    """Methods runnable in this environment (numpy always; statsmodels if present)."""
    base = set(NUMPY_METHODS) | {"auto", "linear_trend"}
    if _HAS_STATSMODELS:
        base |= STATS_METHODS
    return base


def _z(confidence: float) -> float:
    if confidence in _Z:
        return _Z[confidence]
    return _Z[min(_Z, key=lambda c: abs(c - confidence))]


# --- numpy methods ----------------------------------------------------------

def _naive(y, horizon, period, z, confidence) -> MethodResult:
    last = float(y[-1])
    yhat = [last] * horizon
    resid = np.diff(y)
    sigma = float(np.std(resid)) if resid.size else 0.0
    lower = [last - z * sigma * math.sqrt(h) for h in range(1, horizon + 1)]
    upper = [last + z * sigma * math.sqrt(h) for h in range(1, horizon + 1)]
    fitted = [float(y[0])] + [float(v) for v in y[:-1]]
    return yhat, lower, upper, fitted, []


def _seasonal_naive(y, horizon, period, z, confidence) -> MethodResult:
    m = period or 1
    season = y[-m:]
    yhat = [float(season[(h - 1) % m]) for h in range(1, horizon + 1)]
    if len(y) > m:
        resid = y[m:] - y[:-m]
        sigma = float(np.std(resid))
    else:
        sigma = float(np.std(np.diff(y))) if len(y) > 1 else 0.0
    cycles = [(h - 1) // m + 1 for h in range(1, horizon + 1)]
    lower = [yhat[i] - z * sigma * math.sqrt(cycles[i]) for i in range(horizon)]
    upper = [yhat[i] + z * sigma * math.sqrt(cycles[i]) for i in range(horizon)]
    fitted = [float(v) for v in y[:m]] + [float(v) for v in y[:-m]]
    return yhat, lower, upper, fitted, []


def _moving_average(y, horizon, period, z, confidence) -> MethodResult:
    window = max(1, min(period or 3, len(y)))
    ma = float(np.mean(y[-window:]))
    yhat = [ma] * horizon
    fitted = [float(np.mean(y[max(0, i - window + 1): i + 1])) for i in range(len(y))]
    resid = y - np.asarray(fitted)
    sigma = float(np.std(resid))
    lower = [ma - z * sigma] * horizon
    upper = [ma + z * sigma] * horizon
    return yhat, lower, upper, fitted, []


def _linear_trend(y, horizon, period, z, confidence) -> MethodResult:
    n = len(y)
    x = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    resid = y - fitted
    dof = max(n - 2, 1)
    s = float(np.sqrt(np.sum(resid ** 2) / dof))
    xbar = float(x.mean())
    sxx = float(np.sum((x - xbar) ** 2)) or 1.0
    yhat, lower, upper = [], [], []
    for h in range(1, horizon + 1):
        xf = n - 1 + h
        pred = float(slope * xf + intercept)
        se = s * math.sqrt(1.0 + 1.0 / n + (xf - xbar) ** 2 / sxx)
        yhat.append(pred)
        lower.append(pred - z * se)
        upper.append(pred + z * se)
    return yhat, lower, upper, [float(v) for v in fitted], []


# --- statsmodels methods (called only when _HAS_STATSMODELS) ----------------

def _resid_band(yhat, sigma, z, horizon, widen=True):
    lower = [yhat[i] - z * sigma * (math.sqrt(i + 1) if widen else 1) for i in range(horizon)]
    upper = [yhat[i] + z * sigma * (math.sqrt(i + 1) if widen else 1) for i in range(horizon)]
    return lower, upper


def _holt(y, horizon, period, z, confidence) -> MethodResult:
    model = Holt(np.asarray(y, dtype=float), initialization_method="estimated").fit()
    fc = [float(v) for v in model.forecast(horizon)]
    fitted = [float(v) for v in model.fittedvalues]
    sigma = float(np.std(y - np.asarray(fitted)))
    lower, upper = _resid_band(fc, sigma, z, horizon)
    return fc, lower, upper, fitted, []


def _holt_winters(y, horizon, period, z, confidence) -> MethodResult:
    m = period or 2
    model = ExponentialSmoothing(
        np.asarray(y, dtype=float),
        trend="add",
        seasonal="add",
        seasonal_periods=m,
        initialization_method="estimated",
    ).fit()
    fc = [float(v) for v in model.forecast(horizon)]
    fitted = [float(v) for v in model.fittedvalues]
    sigma = float(np.std(y - np.asarray(fitted)))
    lower, upper = _resid_band(fc, sigma, z, horizon)
    return fc, lower, upper, fitted, []


def _sarima(y, horizon, period, z, confidence) -> MethodResult:
    m = period or 0
    seasonal_order = (1, 1, 0, m) if m and len(y) >= 2 * m else (0, 0, 0, 0)
    model = SARIMAX(
        np.asarray(y, dtype=float),
        order=(1, 1, 1),
        seasonal_order=seasonal_order,
        enforce_stationarity=False,
        enforce_invertibility=False,
    ).fit(disp=False)
    res = model.get_forecast(horizon)
    mean = [float(v) for v in res.predicted_mean]
    ci = np.asarray(res.conf_int(alpha=1.0 - confidence))
    lower = [float(ci[i, 0]) for i in range(horizon)]
    upper = [float(ci[i, 1]) for i in range(horizon)]
    fitted = [float(v) for v in model.fittedvalues]
    return mean, lower, upper, fitted, []


_REGISTRY: dict[str, Callable[..., MethodResult]] = {
    "naive": _naive,
    "seasonal_naive": _seasonal_naive,
    "moving_average": _moving_average,
    "linear_trend": _linear_trend,
    "holt": _holt,
    "holt_winters": _holt_winters,
    "sarima": _sarima,
}


def _run_method(method, y, horizon, period, z, confidence) -> MethodResult:
    fn = _REGISTRY.get(method, _linear_trend)
    return fn(np.asarray(y, dtype=float), horizon, period, z, confidence)


# --- backtest & auto-select -------------------------------------------------

def backtest(y, method, period, confidence, holdout: int | None = None) -> dict:
    """Hold out the tail, fit on the rest, score the forecast (MAE/RMSE/MAPE)."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    nan = {"mae": float("nan"), "rmse": float("nan"), "mape": float("nan")}
    if holdout is None:
        holdout = min(6, max(1, n // 4), period or 6)
    holdout = min(holdout, n - 2)
    if holdout < 1:
        return nan
    train, test = y[:-holdout], y[-holdout:]
    try:
        yhat, *_ = _run_method(method, train, holdout, period, _z(confidence), confidence)
    except Exception:
        return nan
    pred = np.asarray(yhat[:holdout], dtype=float)
    err = test - pred
    denom = np.where(np.abs(test) < 1e-9, np.nan, test)
    return {
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "mape": float(np.nanmean(np.abs(err / denom)) * 100.0),
    }


def _auto_select(profile: TimeSeriesProfile, confidence: float) -> tuple[str, list[str]]:
    candidates = [m for m in available_methods(profile) if m != "auto"]
    if not _HAS_STATSMODELS:
        candidates = [m for m in candidates if m not in STATS_METHODS]
    y, period = np.asarray(profile.y, dtype=float), profile.seasonal_period
    best, best_score = None, float("inf")
    for m in candidates:
        score = backtest(y, m, period, confidence).get("mape", float("nan"))
        if score == score and score < best_score:  # not NaN
            best, best_score = m, score
    if best is None:
        return "linear_trend", ["auto-selected linear_trend (no scorable methods)"]
    return best, [f"auto-selected {best} (backtest MAPE {best_score:.1f}%)"]


# --- public API -------------------------------------------------------------

def _compute(profile, method, horizon, confidence) -> ForecastResult:
    horizon = int(max(1, min(horizon, FORECAST_MAX_HORIZON)))
    confidence = float(confidence)
    y = np.asarray(profile.y, dtype=float)
    period = profile.seasonal_period
    warnings: list[str] = []

    chosen = method
    if method == "auto":
        chosen, auto_warn = _auto_select(profile, confidence)
        warnings += auto_warn
    if chosen in STATS_METHODS and not _HAS_STATSMODELS:
        warnings.append(f"statsmodels unavailable; used linear_trend instead of {chosen}.")
        chosen = "linear_trend"

    z = _z(confidence)
    try:
        yhat, lower, upper, fitted, mwarn = _run_method(chosen, y, horizon, period, z, confidence)
        warnings += mwarn
    except Exception as exc:  # never raise to the caller
        warnings.append(f"{chosen} failed ({type(exc).__name__}); fell back to linear_trend.")
        chosen = "linear_trend"
        yhat, lower, upper, fitted, _ = _linear_trend(y, horizon, period, z, confidence)

    if lower is not None and float(np.min(y)) >= 0:
        lower = [max(0.0, v) for v in lower]  # non-negative series: clamp band at 0

    metrics = backtest(y, chosen, period, confidence)
    labels = future_labels(profile, horizon)
    points = [
        ForecastPoint(
            x=labels[i],
            yhat=float(yhat[i]),
            lower=(float(lower[i]) if lower is not None else None),
            upper=(float(upper[i]) if upper is not None else None),
        )
        for i in range(horizon)
    ]
    return ForecastResult(
        method=chosen,
        horizon=horizon,
        points=points,
        confidence=confidence,
        fitted=[float(v) for v in fitted] if fitted is not None else None,
        metrics=metrics,
        warnings=warnings,
    )


def forecast(
    profile: TimeSeriesProfile,
    method: str = "auto",
    horizon: int = 12,
    confidence: float = 0.8,
) -> ForecastResult:
    """Forecast ``profile`` with ``method``; cached so UI toggles are instant."""
    key = (
        tuple(profile.y),
        profile.freq,
        profile.x[-1] if profile.x else "",
        profile.seasonal_period,
        method,
        int(max(1, min(horizon, FORECAST_MAX_HORIZON))),
        round(float(confidence), 4),
    )
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    result = _compute(profile, method, horizon, confidence)
    if len(_CACHE) > 128:
        _CACHE.clear()
    _CACHE[key] = result
    return result


def forecast_bundle(
    rows: list[dict],
    chart: ChartSpec | None,
    method: str = "auto",
    horizon: int = 12,
    confidence: float = 0.8,
) -> tuple[TimeSeriesProfile, list[str], ForecastResult] | None:
    """Detect + forecast in one call (no LLM, no SQL). ``None`` if not relevant.

    Used by the orchestrator and the UI worker; reuses already-fetched rows.
    """
    profile = detect_time_series(rows, chart)
    if profile is None:
        return None
    methods = [m for m in available_methods(profile) if m in supported_methods()]
    if not methods:
        methods = ["linear_trend"]
    if method != "auto" and method not in methods:
        method = methods[0]
    result = forecast(profile, method, horizon, confidence)
    return profile, methods, result


# --- transparency: how methods were chosen, and why some are missing --------

# What each method assumes, for the parameter help in the UI.
METHOD_NOTES = {
    "auto": "Backtests every eligible method and keeps the lowest error.",
    "naive": "Repeats the last observed value. The baseline any method should beat.",
    "seasonal_naive": "Repeats the equivalent period from the last full cycle.",
    "moving_average": "Averages recent periods. Steady, ignores trend.",
    "linear_trend": "Fits a straight line through history and extends it.",
    "holt": "Exponential smoothing with a trend term. No seasonality.",
    "holt_winters": "Exponential smoothing with trend and seasonality.",
    "sarima": "Seasonal ARIMA. Most flexible, needs the most history.",
}


def compare_methods(
    profile: TimeSeriesProfile, confidence: float = 0.8
) -> list[dict]:
    """Backtest every runnable method so 'Auto' can be audited.

    Returns one row per method, sorted best-first by MAPE, each
    ``{method, mae, rmse, mape, runnable}``. Pure local compute over history
    already in memory — no LLM, no SQL. Unscorable methods sort last with
    ``None`` metrics rather than being hidden.
    """
    period = profile.seasonal_period
    y = np.asarray(profile.y, dtype=float)
    rows: list[dict] = []
    for method in available_methods(profile):
        if method == "auto":
            continue
        runnable = method in supported_methods()
        metrics = backtest(y, method, period, confidence) if runnable else {}

        def _clean(key: str):
            v = metrics.get(key)
            return None if v is None or v != v else float(v)

        rows.append({
            "method": method,
            "mae": _clean("mae"),
            "rmse": _clean("rmse"),
            "mape": _clean("mape"),
            "runnable": runnable,
            "note": METHOD_NOTES.get(method, ""),
        })
    rows.sort(key=lambda r: (r["mape"] is None, r["mape"] if r["mape"] is not None else 0))
    return rows


def method_availability(profile: TimeSeriesProfile) -> list[dict]:
    """Every known method with whether it is offered here, and why not.

    Makes the shrinking method list explicable instead of arbitrary.
    """
    offered = set(available_methods(profile))
    n = profile.n_points
    period = profile.seasonal_period
    out: list[dict] = []

    for method in ("auto", "naive", "moving_average", "linear_trend",
                   "holt", "seasonal_naive", "holt_winters", "sarima"):
        if method in offered and method in supported_methods():
            reason = "Available."
        elif method in STATS_METHODS and not _HAS_STATSMODELS:
            reason = "Needs statsmodels, which is not installed."
        elif method == "holt" and n < 6:
            reason = f"Needs at least 6 periods; this series has {n}."
        elif method in ("seasonal_naive", "holt_winters") and not profile.is_seasonal:
            reason = (
                f"Needs a full seasonal cycle. At {profile.freq} frequency that "
                f"is {period or '—'} periods twice over; this series has {n}."
            )
        elif method == "sarima":
            if period and period > 24:
                reason = (
                    f"Seasonal period of {period} is too long to fit reliably."
                )
            elif period:
                reason = (
                    f"Needs at least {max(2 * period, 16)} periods; "
                    f"this series has {n}."
                )
            else:
                reason = "No seasonal period was detected for this frequency."
        else:
            reason = "Not applicable to this series."

        out.append({
            "method": method,
            "offered": method in offered and method in supported_methods(),
            "reason": reason,
            "note": METHOD_NOTES.get(method, ""),
        })
    return out


def series_diagnostics(profile: TimeSeriesProfile) -> dict:
    """The detected inputs behind a forecast, for display."""
    y = np.asarray(profile.y, dtype=float)
    holdout = min(6, max(1, profile.n_points // 4), profile.seasonal_period or 6)
    holdout = max(1, min(holdout, profile.n_points - 2))
    return {
        "time_column": profile.time_column,
        "value_column": profile.value_column,
        "freq": profile.freq,
        "freq_label": FREQ_LABELS.get(profile.freq, profile.freq),
        "n_points": profile.n_points,
        "first": profile.x[0] if profile.x else "",
        "last": profile.x[-1] if profile.x else "",
        "seasonal": profile.is_seasonal,
        "seasonal_period": profile.seasonal_period,
        "holdout": holdout,
        "mean": float(np.mean(y)) if y.size else 0.0,
        "min": float(np.min(y)) if y.size else 0.0,
        "max": float(np.max(y)) if y.size else 0.0,
    }


FREQ_LABELS = {
    "D": "daily", "W": "weekly", "M": "monthly", "Q": "quarterly", "Y": "yearly",
}

# Singular period noun per frequency, for horizon help text.
PERIOD_NOUN = {
    "D": "day", "W": "week", "M": "month", "Q": "quarter", "Y": "year",
}


def forecast_overlay(result: ForecastResult) -> dict:
    """Serialize a forecast for the chart layer (dashed mean + optional band).

    ``lower``/``upper`` are included only when a full confidence band exists, so
    the renderer can safely assume numeric band values when present.
    """
    overlay = {
        "x": result.x,
        "yhat": result.yhat,
        "method": result.method,
        "confidence": result.confidence,
    }
    if result.has_band:
        overlay["lower"] = [float(p.lower) for p in result.points]
        overlay["upper"] = [float(p.upper) for p in result.points]
    return overlay
