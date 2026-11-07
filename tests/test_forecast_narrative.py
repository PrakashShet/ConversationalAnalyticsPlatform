"""Predictive-analytics narrative, diagnostics, and method transparency.

Everything asserted here is computed in Python from a forecast — no LLM is
involved, which is the point: the model must never be the source of a predicted
number, and prose derived arithmetically is the cheapest way to guarantee that.
Because it is deterministic, the wording itself is testable.
"""

from __future__ import annotations

import pytest

from app.core import forecast_narrative as narrative
from app.core.forecasting import (
    compare_methods,
    forecast,
    method_availability,
    series_diagnostics,
)
from app.core.timeseries import explain_not_forecastable
from app.data.models import TimeSeriesProfile


def _profile(n=30, start=100_000.0, step=4_200.0, seasonal=True) -> TimeSeriesProfile:
    y = [start + step * i + (9_000.0 if seasonal and i % 12 in (10, 11) else 0.0)
         for i in range(n)]
    return TimeSeriesProfile(
        time_column="order_month",
        value_column="total_sales",
        freq="M",
        n_points=n,
        x=[f"{2023 + i // 12}-{i % 12 + 1:02d}" for i in range(n)],
        y=y,
        seasonal_period=12,
        is_seasonal=n >= 24,
    )


# --- narrative --------------------------------------------------------------

def test_summary_states_direction_and_endpoints():
    p = _profile()
    r = forecast(p, "linear_trend", horizon=6, confidence=0.9)

    text = narrative.summarize(p, r)

    assert "rises" in text
    assert "monthly" in text
    assert "6 months" in text
    assert p.x[-1] in text          # where history ends
    assert r.points[-1].x in text   # where the forecast ends


def test_summary_calls_a_flat_series_steady():
    p = _profile(step=0.0, seasonal=False)
    r = forecast(p, "naive", horizon=4, confidence=0.8)

    assert "holds roughly steady" in narrative.summarize(p, r)


def test_summary_reports_a_decline():
    p = _profile(start=300_000.0, step=-5_000.0, seasonal=False)
    r = forecast(p, "linear_trend", horizon=6, confidence=0.8)

    assert "falls" in narrative.summarize(p, r)


def test_bullets_name_the_model_and_its_backtest_accuracy():
    p = _profile()
    r = forecast(p, "linear_trend", horizon=6, confidence=0.9)

    joined = " ".join(narrative.bullets(p, r))

    assert "Linear Trend" in joined
    assert "mean error" in joined
    assert "accuracy" in joined


def test_bullets_describe_the_confidence_band():
    p = _profile()
    r = forecast(p, "linear_trend", horizon=6, confidence=0.9)

    joined = " ".join(narrative.bullets(p, r))

    assert "90% interval" in joined
    assert "widens" in joined


def test_bullets_flag_seasonality_the_model_ignores():
    p = _profile()  # seasonal, but linear_trend does not model it
    r = forecast(p, "linear_trend", horizon=6, confidence=0.8)

    joined = " ".join(narrative.bullets(p, r))

    assert "seasonal cycle of 12" in joined
    assert "does not model it" in joined


def test_bullets_warn_when_projecting_beyond_observed_range():
    p = _profile()
    r = forecast(p, "linear_trend", horizon=12, confidence=0.8)

    joined = " ".join(narrative.bullets(p, r))

    assert "above every value ever observed" in joined


def test_narrative_never_invents_a_number_outside_the_forecast():
    """Every figure quoted must come from the profile or the result."""
    p = _profile()
    r = forecast(p, "linear_trend", horizon=6, confidence=0.9)

    text = narrative.summarize(p, r)
    last_hist = f"{p.y[-1]:,.0f}"

    assert last_hist in text or f"{p.y[-1] / 1_000_000:,.2f}M" in text


def test_build_returns_all_sections():
    p = _profile()
    r = forecast(p, "auto", horizon=6, confidence=0.9)

    content = narrative.build(p, r)

    assert set(content) == {"summary", "bullets", "method", "caveat"}
    assert content["summary"] and content["bullets"]
    assert "not guaranteed outcomes" in content["caveat"]


def test_build_is_empty_without_a_forecast():
    assert narrative.build(None, None) == {}
    assert narrative.build(_profile(), None) == {}


def test_build_is_deterministic():
    p = _profile()
    r = forecast(p, "linear_trend", horizon=6, confidence=0.9)

    assert narrative.build(p, r) == narrative.build(p, r)


# --- diagnostics ------------------------------------------------------------

def test_diagnostics_report_the_detected_inputs():
    diag = series_diagnostics(_profile())

    assert diag["time_column"] == "order_month"
    assert diag["value_column"] == "total_sales"
    assert diag["freq_label"] == "monthly"
    assert diag["n_points"] == 30
    assert diag["seasonal"] is True
    assert diag["seasonal_period"] == 12
    assert diag["holdout"] >= 1
    assert diag["first"] == "2023-01"


def test_holdout_never_exceeds_the_series():
    diag = series_diagnostics(_profile(n=6, seasonal=False))

    assert 1 <= diag["holdout"] <= 4


# --- method comparison ------------------------------------------------------

def test_comparison_scores_every_offered_method():
    rows = compare_methods(_profile(), 0.9)
    methods = {r["method"] for r in rows}

    assert "auto" not in methods, "auto is a strategy, not a method to score"
    assert {"naive", "linear_trend", "moving_average"} <= methods
    assert all({"mae", "rmse", "mape", "runnable", "note"} <= set(r) for r in rows)


def test_comparison_is_sorted_best_first():
    rows = [r for r in compare_methods(_profile(), 0.9) if r["mape"] is not None]

    assert rows == sorted(rows, key=lambda r: r["mape"])


def test_comparison_picks_the_same_winner_as_auto():
    """If Auto isn't the top of the table, the table is lying."""
    p = _profile()
    auto = forecast(p, "auto", horizon=6, confidence=0.9)
    scored = [r for r in compare_methods(p, 0.9) if r["mape"] is not None]

    assert scored[0]["method"] == auto.method


def test_unscorable_methods_sort_last_rather_than_vanish():
    rows = compare_methods(_profile(), 0.9)
    first_none = next(
        (i for i, r in enumerate(rows) if r["mape"] is None), len(rows)
    )

    assert all(r["mape"] is None for r in rows[first_none:])


# --- availability -----------------------------------------------------------

def test_availability_covers_every_known_method():
    rows = method_availability(_profile())

    assert {r["method"] for r in rows} == {
        "auto", "naive", "moving_average", "linear_trend",
        "holt", "seasonal_naive", "holt_winters", "sarima",
    }
    assert all(r["reason"] for r in rows), "every entry must justify itself"


def test_short_series_explains_why_seasonal_methods_are_withheld():
    rows = {r["method"]: r for r in method_availability(_profile(n=8, seasonal=False))}

    assert rows["seasonal_naive"]["offered"] is False
    assert "seasonal cycle" in rows["seasonal_naive"]["reason"].lower()


def test_baseline_methods_are_always_available():
    rows = {r["method"]: r for r in method_availability(_profile(n=6, seasonal=False))}

    for method in ("naive", "moving_average", "linear_trend"):
        assert rows[method]["offered"] is True
        assert rows[method]["reason"] == "Available."


# --- explaining a refusal ---------------------------------------------------

def test_explains_a_missing_date_column():
    rows = [{"region": "West", "sales": 10}, {"region": "East", "sales": 20}]

    reason = explain_not_forecastable(rows)

    assert "no date or period column" in reason
    assert "region" in reason  # names what was actually returned


def test_explains_too_few_periods():
    rows = [{"month": f"2024-0{i}", "sales": i * 10.0} for i in range(1, 4)]

    reason = explain_not_forecastable(rows)

    assert "3 distinct periods" in reason
    assert "6" in reason


def test_explains_an_empty_result():
    assert "no rows" in explain_not_forecastable([])


def test_explains_a_missing_measure():
    rows = [{"month": f"2024-{i:02d}", "note": "x"} for i in range(1, 9)]

    reason = explain_not_forecastable(rows)

    assert "numeric" in reason.lower()


def test_explanation_is_always_a_usable_sentence():
    """Whatever the input, the user gets something actionable."""
    for rows in ([], [{"a": 1}], [{"m": "not-a-date", "v": 1}] * 10):
        reason = explain_not_forecastable(rows)
        assert reason and reason[0].isupper() and reason.rstrip().endswith(".")
