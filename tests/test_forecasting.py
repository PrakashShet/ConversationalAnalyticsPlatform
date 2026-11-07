"""Tests for the forecasting engine (deterministic, local methods)."""

import math

from app.core import forecasting as F
from app.core.timeseries import detect_time_series
from app.data.models import ChartSpec

try:
    import statsmodels  # noqa: F401

    HAS_STATSMODELS = True
except Exception:
    HAS_STATSMODELS = False

NUMPY_METHODS = ["naive", "seasonal_naive", "moving_average", "linear_trend"]


def _profile(n=36, seasonal=True):
    rows = []
    for i in range(n):
        month = i % 12 + 1
        season = 20 * math.sin(2 * math.pi * month / 12) if seasonal else 0
        rows.append({"t": f"{2019 + i // 12}-{month:02d}", "y": 100 + 3 * i + season})
    return detect_time_series(rows)


def test_numpy_methods_produce_ordered_ci():
    p = _profile()
    for method in NUMPY_METHODS:
        r = F.forecast(p, method, 6, 0.9)
        assert r.method == method
        assert r.horizon == 6 and len(r.points) == 6
        for pt in r.points:
            assert pt.lower is None or pt.lower <= pt.yhat <= pt.upper


def test_backtest_metrics_are_finite():
    p = _profile()
    m = F.backtest(p.y, "linear_trend", p.seasonal_period, 0.8)
    assert math.isfinite(m["mae"])
    assert math.isfinite(m["rmse"])
    assert math.isfinite(m["mape"])


def test_auto_resolves_to_a_concrete_method():
    p = _profile()
    r = F.forecast(p, "auto", 6, 0.8)
    assert r.method != "auto"
    assert r.method in F.supported_methods()


def test_horizon_is_capped():
    p = _profile()
    r = F.forecast(p, "linear_trend", 9999, 0.8)
    assert r.horizon == F.FORECAST_MAX_HORIZON


def test_unavailable_method_falls_back_gracefully():
    p = _profile()
    r = F.forecast(p, "sarima", 6, 0.8)
    if HAS_STATSMODELS:
        assert r.method == "sarima"
    else:
        assert r.method == "linear_trend"
        assert any("statsmodels" in w for w in r.warnings)


def test_non_negative_series_clamps_lower_band():
    rows = [
        {"t": f"2020-{m:02d}", "y": v}
        for m, v in zip(range(1, 13), [5, 3, 6, 2, 7, 1, 8, 2, 6, 3, 5, 1])
    ]
    p = detect_time_series(rows)
    r = F.forecast(p, "naive", 6, 0.95)
    assert all(pt.lower is None or pt.lower >= 0.0 for pt in r.points)


def test_forecast_overlay_serialization():
    p = _profile()
    r = F.forecast(p, "linear_trend", 6, 0.9)
    overlay = F.forecast_overlay(r)
    assert len(overlay["x"]) == len(overlay["yhat"]) == 6
    assert "lower" in overlay and "upper" in overlay  # linear_trend has a band


def test_bundle_gates_on_relevance():
    chart = ChartSpec(kind="line", title="", options={"x_column": "t", "y_column": "y"})
    rows = [{"t": f"2020-{m:02d}", "y": m} for m in range(1, 13)]
    assert F.forecast_bundle(rows, chart, "auto", 6, 0.8) is not None
    categorical = [{"c": x, "y": i} for i, x in enumerate("abcdefg")]
    assert F.forecast_bundle(categorical, None) is None


def test_statsmodels_methods_run_when_available():
    if not HAS_STATSMODELS:
        return  # skipped without statsmodels (numpy-only environment)
    p = _profile()
    for method in ("holt", "holt_winters", "sarima"):
        r = F.forecast(p, method, 6, 0.8)
        assert r.method == method
        assert len(r.points) == 6
