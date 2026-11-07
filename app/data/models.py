"""Data models for analyses, SQL planning, and chart specs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


ChartKind = Literal["bar", "line", "donut", "table", "kpi_only", "scatter"]
ChartIntent = Literal["kpi", "bar", "line", "donut", "table", "auto"]


@dataclass(slots=True)
class ChartSpec:
    kind: ChartKind
    title: str
    x: list[str] | None = None
    series: list[dict] = field(default_factory=list)
    options: dict = field(default_factory=dict)


@dataclass(slots=True)
class Kpi:
    label: str
    value: str
    delta: str | None = None
    trend: Literal["up", "down", "flat"] | None = None


@dataclass(slots=True)
class KpiSpec:
    label: str
    aggregation: Literal[
        "sum", "mean", "count", "count_distinct", "min", "max"
    ]
    column: str
    format: str = "{:,.0f}"


@dataclass(slots=True)
class SourceFingerprint:
    """Identity of the data source an :class:`Analysis` was produced from.

    Stamped on every analysis and persisted with it, so a saved result can be
    told apart from the database that is connected *now*. ``target`` is always
    credential-free — see ``app.core.data_source.redact_url``.

    ``schema_hash`` covers table and column names, so it also changes when the
    same URL is reloaded with different CSVs (``load_data.bat`` drops and
    recreates the public schema).
    """

    name: str = ""            # profile name, e.g. "Default"
    kind: str = ""            # postgres | mysql | sqlite
    target: str = ""          # connection URL with any password redacted
    schema_hash: str = ""     # short digest of table.column names
    table_count: int = 0


@dataclass(slots=True)
class SqlPlan:
    sql: str
    chart_intent: ChartIntent
    rationale: str
    needs_clarification: bool = False
    # The user explicitly asked for a forecast/projection. The SQL still returns
    # history only — this flag tells the app to insist on the predictive layer
    # and to explain itself if the result turns out not to be forecastable.
    forecast_requested: bool = False


@dataclass(slots=True)
class ResultInsight:
    summary: str
    kpis: list[Kpi]
    kpi_specs: list[KpiSpec]
    insights: list[str]
    charts: list[ChartSpec]
    suggestions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TimeSeriesProfile:
    """A clean, ordered time series detected from SQL result rows.

    Produced by ``app.core.timeseries.detect_time_series``; ``None`` is returned
    when the result is *not* a forecastable time series (the relevance gate).
    """

    time_column: str
    value_column: str
    freq: str  # one of "D", "W", "M", "Q", "Y"
    n_points: int
    x: list[str]  # period labels, ascending
    y: list[float]  # measured values aligned to ``x``
    seasonal_period: int | None = None
    is_seasonal: bool = False


@dataclass(slots=True)
class ForecastPoint:
    x: str
    yhat: float
    lower: float | None = None
    upper: float | None = None


@dataclass(slots=True)
class ForecastResult:
    """Output of a single forecasting method over a ``TimeSeriesProfile``.

    Numbers are computed deterministically in Python (never the LLM).
    """

    method: str
    horizon: int
    points: list[ForecastPoint]
    confidence: float = 0.8
    fitted: list[float] | None = None  # in-sample fit aligned to history
    metrics: dict = field(default_factory=dict)  # {"mae","rmse","mape"} from backtest
    warnings: list[str] = field(default_factory=list)

    @property
    def x(self) -> list[str]:
        return [p.x for p in self.points]

    @property
    def yhat(self) -> list[float]:
        return [p.yhat for p in self.points]

    @property
    def lower(self) -> list[float | None]:
        return [p.lower for p in self.points]

    @property
    def upper(self) -> list[float | None]:
        return [p.upper for p in self.points]

    @property
    def has_band(self) -> bool:
        return any(p.lower is not None and p.upper is not None for p in self.points)


@dataclass(slots=True)
class Analysis:
    question: str
    sql: str
    summary: str
    kpis: list[Kpi]
    chart: ChartSpec | None
    insights: list[str]
    row_count: int
    elapsed_ms: int
    created_at: datetime
    # Which database produced this. Persisted, so a replayed analysis can be
    # compared against the live connection before acting on its follow-ups.
    source: SourceFingerprint | None = None
    # True when the planner could not map the question to the schema.
    needs_clarification: bool = False
    kpi_specs: list[KpiSpec] = field(default_factory=list)
    charts: list[ChartSpec] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    tokens: int = 0
    planner_tokens: int = 0
    analyst_tokens: int = 0
    # Predictive analytics (attached only when the result is a time series).
    forecastable: bool = False
    # The user explicitly asked for a forecast (planner flag), and — when the
    # result turned out not to be forecastable — why not.
    forecast_requested: bool = False
    forecast_note: str = ""
    ts_profile: TimeSeriesProfile | None = None
    available_methods: list[str] = field(default_factory=list)
    forecast: ForecastResult | None = None

    @property
    def all_charts(self) -> list[ChartSpec]:
        if self.charts:
            return self.charts
        return [self.chart] if self.chart else []
