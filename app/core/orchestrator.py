"""Question → SQL plan → execute → analyst → Analysis pipeline."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from loguru import logger

from app.core.forecasting import forecast_bundle
from app.core.timeseries import explain_not_forecastable
from app.core.gemini_analyst import summarize_result
from app.core.gemini_client import GeminiClient
from app.core.gemini_planner import plan_sql
from app.core.mcp_client import SyncMcpClient
from app.core.row_utils import (
    compact_rows,
    compute_kpis,
    fill_charts_from_rows,
    is_select_only,
)
from app.data.models import Analysis, ChartSpec, SourceFingerprint


def _clarification_analysis(
    question: str,
    rationale: str,
    elapsed_ms: int,
    planner_tokens: int,
    source: SourceFingerprint | None = None,
) -> Analysis:
    return Analysis(
        question=question,
        sql="",
        summary=rationale or "Could you clarify your question?",
        kpis=[],
        chart=None,
        charts=[],
        insights=[],
        row_count=0,
        elapsed_ms=elapsed_ms,
        created_at=datetime.now(timezone.utc),
        planner_tokens=planner_tokens,
        analyst_tokens=0,
        tokens=planner_tokens,
        source=source,
        needs_clarification=True,
    )


def _intent_to_kind(intent: str) -> str:
    mapping = {
        "kpi": "kpi_only",
        "bar": "bar",
        "line": "line",
        "donut": "donut",
        "table": "table",
        "auto": "bar",
    }
    return mapping.get(intent, "bar")


class Orchestrator:
    """Three-step LLM pipeline: plan SQL → execute → summarize rows."""

    MAX_EXEC_ROWS = 500

    def __init__(
        self,
        gemini: GeminiClient,
        mcp: SyncMcpClient,
        context_md: str,
        *,
        source: SourceFingerprint | None = None,
        forecast_enabled: bool = True,
        forecast_method: str = "auto",
        forecast_horizon: int = 12,
        forecast_confidence: float = 0.8,
    ) -> None:
        self._gemini = gemini
        self._mcp = mcp
        self._context_md = context_md
        self._source = source
        self._forecast_enabled = forecast_enabled
        self._forecast_method = forecast_method
        self._forecast_horizon = forecast_horizon
        self._forecast_confidence = forecast_confidence

    def set_context(self, context_md: str) -> None:
        self._context_md = context_md

    @staticmethod
    def _pick_temporal_chart(charts: list[ChartSpec]) -> ChartSpec | None:
        """Prefer a line chart (most likely temporal); else the first chart."""
        for chart in charts:
            if chart.kind == "line":
                return chart
        return charts[0] if charts else None

    def _attach_forecast(
        self,
        analysis: Analysis,
        exec_rows: list[dict],
        requested: bool = False,
    ) -> None:
        """Attach a default forecast in place — pure local compute, 0 LLM tokens.

        Reuses ``exec_rows`` already fetched: no second SQL query, no Gemini call.
        Any failure leaves the descriptive result untouched.
        """
        analysis.forecast_requested = requested
        if not self._forecast_enabled and not requested:
            logger.info("Forecast disabled in settings; skipping")
            return
        if not exec_rows:
            logger.info("Forecast skipped: no result rows")
            if requested:
                analysis.forecast_note = (
                    "The query returned no rows, so there is nothing to project."
                )
            return
        try:
            chart = self._pick_temporal_chart(analysis.all_charts)
            bundle = forecast_bundle(
                exec_rows,
                chart,
                self._forecast_method,
                self._forecast_horizon,
                self._forecast_confidence,
            )
            if bundle is None:
                logger.info(
                    "Forecast not applicable: no time series detected in result "
                    "(columns={})",
                    list(exec_rows[0].keys()) if exec_rows else [],
                )
                # Only explain when the user actually asked — otherwise silence
                # is correct, most results are not time series.
                if requested:
                    analysis.forecast_note = explain_not_forecastable(
                        exec_rows, chart
                    )
                    logger.info("Forecast requested but unavailable: {}",
                                analysis.forecast_note)
                return
            profile, methods, result = bundle
            analysis.forecastable = True
            analysis.ts_profile = profile
            analysis.available_methods = methods
            analysis.forecast = result
            logger.info(
                "Forecast attached: method={} horizon={} freq={} n={} "
                "(0 extra tokens, {} methods offered)",
                result.method, result.horizon, profile.freq,
                profile.n_points, len(methods),
            )
        except Exception as exc:  # noqa: BLE001 - never break the descriptive result
            logger.warning("Forecast attach skipped: {}", exc)
            if requested and not analysis.forecast_note:
                analysis.forecast_note = (
                    "The forecast could not be computed for this result."
                )

    def ask(self, question: str, history: list[dict], on_chunk=None) -> Analysis:
        start = time.perf_counter()
        planner_tokens = 0
        analyst_tokens = 0

        plan, planner_tokens = plan_sql(
            self._gemini, question, self._context_md, history
        )

        if plan.needs_clarification or not plan.sql.strip():
            elapsed = int((time.perf_counter() - start) * 1000)
            return _clarification_analysis(
                question, plan.rationale, elapsed, planner_tokens, self._source
            )

        if not is_select_only(plan.sql):
            elapsed = int((time.perf_counter() - start) * 1000)
            return _clarification_analysis(
                question,
                "Only read-only SELECT queries are allowed.",
                elapsed,
                planner_tokens,
                self._source,
            )

        logger.info("Executing SQL: {}", plan.sql[:200])
        rows = self._mcp.query(plan.sql)
        exec_rows = rows[: self.MAX_EXEC_ROWS]
        compact = compact_rows(exec_rows)

        if on_chunk:
            on_chunk("Analyzing results…")

        insight, analyst_tokens = summarize_result(
            self._gemini, question, plan.sql, compact
        )

        if on_chunk and insight.summary:
            on_chunk(insight.summary)

        charts = insight.charts
        if not charts and plan.chart_intent != "kpi":
            charts = [
                ChartSpec(
                    kind=_intent_to_kind(plan.chart_intent),  # type: ignore[arg-type]
                    title=question[:60],
                    options={"x_column": "", "y_column": ""},
                )
            ]

        filled_charts = fill_charts_from_rows(exec_rows, charts) if exec_rows else charts
        kpis = (
            compute_kpis(exec_rows, insight.kpi_specs, insight.kpis)
            if exec_rows and insight.kpi_specs
            else insight.kpis
        )

        elapsed = int((time.perf_counter() - start) * 1000)
        primary = filled_charts[0] if filled_charts else None

        analysis = Analysis(
            question=question,
            sql=plan.sql,
            summary=insight.summary,
            kpis=kpis,
            kpi_specs=insight.kpi_specs,
            chart=primary,
            charts=filled_charts,
            insights=insight.insights,
            suggestions=insight.suggestions,
            row_count=len(rows),
            elapsed_ms=elapsed,
            created_at=datetime.now(timezone.utc),
            planner_tokens=planner_tokens,
            analyst_tokens=analyst_tokens,
            tokens=planner_tokens + analyst_tokens,
            source=self._source,
        )
        # Predictive layer: deterministic, local, adds 0 Gemini tokens / 0 SQL.
        self._attach_forecast(analysis, exec_rows, plan.forecast_requested)
        return analysis
