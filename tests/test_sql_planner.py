"""Unit tests for SQL planner parsing (mocked Gemini)."""

from unittest.mock import MagicMock

from app.core.gemini_planner import plan_sql
from app.data.models import SqlPlan


def test_plan_sql_parses_bar_intent():
    client = MagicMock()
    client.generate_json.return_value = (
        {
            "sql": (
                "SELECT state, SUM(sales) AS total FROM orders "
                "GROUP BY state ORDER BY total DESC LIMIT 5"
            ),
            "chart_intent": "bar",
            "rationale": "Top states by sales.",
            "needs_clarification": False,
        },
        88,
    )

    plan, tokens = plan_sql(
        client,
        "top 5 states by sales",
        "# context\n## orders\n| sales | numeric |",
        [],
    )
    assert isinstance(plan, SqlPlan)
    assert "LIMIT 5" in plan.sql.upper()
    assert plan.chart_intent == "bar"
    assert tokens == 88
