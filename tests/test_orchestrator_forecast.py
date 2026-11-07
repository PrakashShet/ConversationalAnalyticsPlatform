"""Integration: forecasts attach to time-series results at zero extra cost.

These tests exercise the same ``forecast_bundle`` entry point the Orchestrator
calls in ``_attach_forecast``. They deliberately avoid importing the full
Orchestrator (which pulls in Gemini/MCP) so they can also prove that the
forecast path imports neither — i.e. it adds no LLM tokens and no SQL.
"""

import sys

from app.core.forecasting import forecast_bundle
from app.data.models import ChartSpec


def _monthly_rows(n=36):
    return [
        {"order_month": f"{2019 + i // 12}-{i % 12 + 1:02d}", "sales": 100 + 2 * i}
        for i in range(n)
    ]


def test_bundle_attaches_for_timeseries():
    chart = ChartSpec(
        kind="line", title="", options={"x_column": "order_month", "y_column": "sales"}
    )
    bundle = forecast_bundle(_monthly_rows(36), chart, "auto", 12, 0.8)
    assert bundle is not None
    profile, methods, result = bundle
    assert profile.freq == "M"
    assert methods and methods[0] == "auto"
    assert result.horizon == 12
    assert len(result.points) == 12


def test_no_forecast_for_categorical_result():
    rows = [
        {"region": r, "sales": v}
        for r, v in [
            ("West", 1), ("East", 2), ("South", 3), ("North", 4),
            ("A", 5), ("B", 6), ("C", 7),
        ]
    ]
    chart = ChartSpec(
        kind="bar", title="", options={"x_column": "region", "y_column": "sales"}
    )
    assert forecast_bundle(rows, chart, "auto", 12, 0.8) is None


def test_forecast_path_imports_no_gemini_or_mcp():
    forecast_bundle(_monthly_rows(36), None, "auto", 6, 0.8)
    assert "google.genai" not in sys.modules
    assert "mcp" not in sys.modules
