"""Gemini NL→SQL planning (no row data)."""

from __future__ import annotations

from loguru import logger

from app.core.gemini_client import SQL_PLAN_SCHEMA, GeminiClient, _to_contents
from app.data.models import SqlPlan
from app.paths import resource_path

_PROMPT = resource_path("resources", "prompts", "sql_planner.md")


def plan_sql(
    client: GeminiClient,
    question: str,
    context_md: str,
    history: list[dict] | None = None,
) -> tuple[SqlPlan, int]:
    """Plan SQL from question + context only. Returns (plan, tokens_used)."""
    system = f"{_PROMPT.read_text(encoding='utf-8')}\n\n# Data context\n\n{context_md}"
    contents = _to_contents(history, question)

    payload, tokens = client.generate_json(system, contents, schema=SQL_PLAN_SCHEMA)
    logger.info("SQL planner tokens: {}", tokens)

    intent = payload.get("chart_intent", "auto")
    if intent not in ("kpi", "bar", "line", "donut", "table", "auto"):
        intent = "auto"

    plan = SqlPlan(
        sql=payload.get("sql", ""),
        chart_intent=intent,
        rationale=payload.get("rationale", ""),
        needs_clarification=bool(payload.get("needs_clarification", False)),
        forecast_requested=bool(payload.get("forecast_requested", False)),
    )
    return plan, tokens
