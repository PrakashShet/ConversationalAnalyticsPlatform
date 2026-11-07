"""Tests for the split NL→SQL planner + row utilities pipeline."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.orchestrator import Orchestrator
from app.core.row_utils import compact_rows, compute_kpis, fill_chart_from_rows, is_select_only
from app.data.models import ChartSpec, Kpi, KpiSpec, ResultInsight, SqlPlan


def test_is_select_only_accepts_select_and_with():
    assert is_select_only("SELECT 1")
    assert is_select_only("  WITH cte AS (SELECT 1) SELECT * FROM cte")
    assert not is_select_only("DELETE FROM t")
    assert not is_select_only("INSERT INTO t VALUES (1)")


def test_compact_rows_caps_size():
    rows = [{"a": i, "b": "x" * 100} for i in range(200)]
    out = compact_rows(rows, max_rows=100, max_chars=4000)
    assert len(out) <= 100
    assert len(str(out)) <= 5000


def test_fill_chart_from_rows_uses_sql_data():
    rows = [
        {"category": "A", "sales": 10},
        {"category": "B", "sales": 20},
    ]
    spec = ChartSpec(
        kind="bar",
        title="Sales",
        options={"x_column": "category", "y_column": "sales"},
        series=[{"name": "Sales", "data": []}],
    )
    filled = fill_chart_from_rows(rows, spec)
    assert filled.x == ["A", "B"]
    assert filled.series[0]["data"] == [10.0, 20.0]


def test_fill_chart_from_rows_defaults_missing_series_name():
    rows = [
        {"date": "2024-01-01", "total_weekly_sales": 10},
        {"date": "2024-01-08", "total_weekly_sales": 20},
    ]
    spec = ChartSpec(
        kind="line",
        title="Weekly sales",
        options={"x_column": "date", "y_column": "total_weekly_sales"},
        series=[{"data": []}],
    )
    filled = fill_chart_from_rows(rows, spec)
    assert filled.series[0]["name"] == "total_weekly_sales"
    assert filled.series[0]["data"] == [10.0, 20.0]


def test_compute_kpis_from_rows():
    rows = [{"sales": 10}, {"sales": 20}, {"sales": 30}]
    specs = [KpiSpec(label="Total", aggregation="sum", column="sales", format="${:,.0f}")]
    kpis = compute_kpis(rows, specs, [Kpi("Total", "")])
    assert kpis[0].value == "$60"


@patch("app.core.orchestrator.plan_sql")
@patch("app.core.orchestrator.summarize_result")
def test_orchestrator_clarification_skips_sql(mock_summarize, mock_plan):
    mock_plan.return_value = (
        SqlPlan(sql="", chart_intent="auto", rationale="Please specify a date range.", needs_clarification=True),
        100,
    )
    orch = Orchestrator(MagicMock(), MagicMock(), "ctx")
    result = orch.ask("sales?", [])
    assert result.sql == ""
    assert "date range" in result.summary.lower()
    mock_summarize.assert_not_called()


@patch("app.core.orchestrator.plan_sql")
@patch("app.core.orchestrator.summarize_result")
def test_orchestrator_rejects_non_select(mock_summarize, mock_plan):
    mock_plan.return_value = (
        SqlPlan(sql="DROP TABLE t", chart_intent="auto", rationale="", needs_clarification=False),
        50,
    )
    orch = Orchestrator(MagicMock(), MagicMock(), "ctx")
    result = orch.ask("drop it", [])
    assert "read-only" in result.summary.lower()
    mock_summarize.assert_not_called()


@patch("app.core.orchestrator.plan_sql")
@patch("app.core.orchestrator.summarize_result")
def test_orchestrator_pipeline_fills_chart_from_rows(mock_summarize, mock_plan):
    mock_plan.return_value = (
        SqlPlan(
            sql="SELECT category, SUM(sales) AS sales FROM t GROUP BY category LIMIT 5",
            chart_intent="bar",
            rationale="",
            needs_clarification=False,
        ),
        120,
    )
    mock_summarize.return_value = (
        ResultInsight(
            summary="Top categories by sales.",
            kpis=[],
            kpi_specs=[],
            insights=["Furniture leads."],
            charts=[
                ChartSpec(
                    kind="bar",
                    title="By category",
                    options={"x_column": "category", "y_column": "sales"},
                    series=[{"name": "Sales", "data": []}],
                )
            ],
            suggestions=["By region", "Over time", "Top products"],
        ),
        200,
    )
    mcp = MagicMock()
    mcp.query.return_value = [
        {"category": "Furniture", "sales": 100},
        {"category": "Tech", "sales": 80},
    ]
    orch = Orchestrator(MagicMock(), mcp, "ctx")
    result = orch.ask("top categories", [])
    assert result.row_count == 2
    assert result.planner_tokens == 120
    assert result.analyst_tokens == 200
    assert result.charts[0].series[0]["data"] == [100.0, 80.0]
    assert len(result.suggestions) == 3
