"""Gemini data-context builder and result analyst."""

from __future__ import annotations

import json

from google.genai import types
from loguru import logger

from app.core.gemini_client import ANALYST_RESULT_SCHEMA, GeminiClient, _parse_chart, _parse_kpi, _parse_kpi_specs
from app.data.models import ChartSpec, ResultInsight
from app.paths import resource_path

_CONTEXT_SYSTEM = (
    "You are a senior data analyst. Produce a compact Markdown data dictionary. "
    "For each table: one-line purpose, column table (name, type, meaning), "
    "observed categorical values or ranges from samples only, and 3 example questions. "
    "Use ONLY the schema and sample rows provided. Be concise."
)

_ANALYST_PROMPT = resource_path("resources", "prompts", "analyst.md")
_SAMPLE_CHAR_CAP = 4000


def build_data_context(
    client: GeminiClient, schema_md: str, samples: dict
) -> tuple[str, int]:
    """Build data_context.md from schema + sample rows. Returns (markdown, tokens)."""
    sample_text = json.dumps(samples, default=str)
    if len(sample_text) > _SAMPLE_CHAR_CAP:
        sample_text = sample_text[:_SAMPLE_CHAR_CAP] + "…"
    user = f"# Schema\n\n{schema_md}\n\n# Sample rows (max 5 per table)\n\n{sample_text}"

    response, tokens = client.generate_text(_CONTEXT_SYSTEM, user)
    logger.info("Context build tokens: {}", tokens)
    return response, tokens


def _parse_charts(data: list | None) -> list[ChartSpec]:
    charts = []
    for item in data or []:
        c = _parse_chart(item)
        if c and c.kind != "kpi_only":
            charts.append(c)
    return charts


def summarize_result(
    client: GeminiClient,
    question: str,
    sql: str,
    compact_rows: list[dict],
) -> tuple[ResultInsight, int]:
    """Turn executed SQL rows into narrative + chart specs. Returns (insight, tokens)."""
    system = _ANALYST_PROMPT.read_text(encoding="utf-8")
    rows_json = json.dumps(compact_rows, default=str)
    user = (
        f"Question: {question}\n\nSQL executed:\n{sql}\n\n"
        f"Result rows ({len(compact_rows)} shown):\n{rows_json}"
    )
    contents = [types.Content(role="user", parts=[types.Part(text=user)])]
    payload, tokens = client.generate_json(system, contents, schema=ANALYST_RESULT_SCHEMA)
    logger.info("Analyst tokens: {}", tokens)

    insight = ResultInsight(
        summary=payload.get("summary", ""),
        kpis=[_parse_kpi(k) for k in payload.get("kpis", [])],
        kpi_specs=_parse_kpi_specs(payload.get("kpi_specs")),
        insights=payload.get("insights", []),
        charts=_parse_charts(payload.get("charts")),
        suggestions=(payload.get("suggestions") or [])[:3],
    )
    return insight, tokens
