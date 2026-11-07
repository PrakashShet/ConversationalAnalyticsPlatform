"""Row compaction and chart data helpers (no LLM)."""

from __future__ import annotations

import json
from typing import Any

from app.data.models import ChartSpec, Kpi, KpiSpec


def is_select_only(sql: str) -> bool:
    stmt = sql.strip().rstrip(";").lstrip("(").lower()
    return stmt.startswith("select") or stmt.startswith("with")


def compact_rows(rows: list[dict], max_rows: int = 100, max_chars: int = 4000) -> list[dict]:
    """Cap rows for LLM input."""
    capped = rows[:max_rows]
    while capped:
        text = json.dumps(capped, default=str)
        if len(text) <= max_chars:
            return capped
        capped = capped[: max(1, len(capped) // 2)]
    return []


def aggregate(values: list[Any], agg: str) -> float | int:
    nums = [v for v in values if isinstance(v, (int, float))]
    if agg == "sum":
        return sum(nums)
    if agg == "mean":
        return sum(nums) / len(nums) if nums else 0
    if agg == "count":
        return len(values)
    if agg == "count_distinct":
        return len(set(values))
    if agg == "min":
        return min(nums) if nums else 0
    if agg == "max":
        return max(nums) if nums else 0
    return 0


def compute_kpis(
    rows: list[dict],
    kpi_specs: list[KpiSpec],
    kpi_templates: list[Kpi],
) -> list[Kpi]:
    kpis = []
    for i, spec in enumerate(kpi_specs):
        col_values = [r.get(spec.column) for r in rows if spec.column in r]
        raw = aggregate(col_values, spec.aggregation)
        try:
            formatted = spec.format.format(raw)
        except (ValueError, KeyError):
            formatted = str(raw)
        template = kpi_templates[i] if i < len(kpi_templates) else Kpi(spec.label, "")
        kpis.append(Kpi(
            label=spec.label or template.label,
            value=formatted,
            delta=template.delta,
            trend=template.trend,
        ))
    return kpis


def fill_chart_from_rows(rows: list[dict], chart: ChartSpec) -> ChartSpec:
    """Replace chart series data from SQL rows using options x_column/y_column."""
    if not rows or chart.kind in ("kpi_only", "table"):
        return chart

    x_key = chart.options.get("x_column")
    y_key = chart.options.get("y_column")
    if not x_key or not y_key:
        keys = list(rows[0].keys())
        if len(keys) >= 2:
            x_key = x_key or keys[0]
            y_key = y_key or keys[1]

    if not x_key or not y_key:
        return chart

    labels = [str(r.get(x_key, "")) for r in rows]
    series_out = []
    y_columns = chart.options.get("y_columns") or [y_key]

    if len(chart.series) > 1 or len(y_columns) > 1:
        for i, s in enumerate(chart.series or [{"name": y_key}]):
            col = y_columns[i] if i < len(y_columns) else y_key
            values = [float(r.get(col, 0) or 0) for r in rows]
            series_name = s.get("name", col) if isinstance(s, dict) else col
            series_out.append({"name": series_name, "data": values})
    else:
        values = [float(r.get(y_key, 0) or 0) for r in rows]
        first_series = chart.series[0] if chart.series else {}
        name = first_series.get("name", y_key) if isinstance(first_series, dict) else y_key
        series_out = [{"name": name, "data": values}]

    return ChartSpec(
        kind=chart.kind,
        title=chart.title,
        x=labels,
        series=series_out,
        options=chart.options,
    )


def fill_charts_from_rows(rows: list[dict], charts: list[ChartSpec]) -> list[ChartSpec]:
    return [fill_chart_from_rows(rows, c) for c in charts if c.kind != "kpi_only"]
