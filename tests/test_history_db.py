"""Round-trip tests for conversation history persistence.

Covers both halves of a stored :class:`Analysis`:

* **descriptive** — chart data and computed KPI strings must survive verbatim,
  because replay re-renders the canvas with no Gemini call and no SQL;
* **predictive** — the computed ``ForecastResult`` is stored verbatim (the
  authoritative record of what the user saw) *and* its inputs (profile +
  settings) are stored so the controls stay interactive on replay.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.core import data_source
from app.core.forecasting import forecast
from app.data import history_db
from app.data.models import Analysis, ChartSpec, Kpi, KpiSpec, TimeSeriesProfile


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "history.sqlite"
    history_db.init_db(path)
    return path


def _monthly_profile(n: int = 24) -> TimeSeriesProfile:
    """A seasonal-ish monthly series with a trend — enough for any method."""
    x = [f"{2023 + i // 12}-{i % 12 + 1:02d}" for i in range(n)]
    y = [100.0 + 5.0 * i + (10.0 if i % 12 in (10, 11) else 0.0) for i in range(n)]
    return TimeSeriesProfile(
        time_column="order_month",
        value_column="revenue",
        freq="M",
        n_points=n,
        x=x,
        y=y,
        seasonal_period=12,
        is_seasonal=True,
    )


def _descriptive_analysis() -> Analysis:
    return Analysis(
        question="Total sales by store type",
        sql="SELECT type, SUM(sales) FROM s GROUP BY type",
        summary="Type A drives most revenue.",
        kpis=[Kpi(label="Total Sales", value="$5,391,937,860.98", trend="up")],
        kpi_specs=[
            KpiSpec(
                label="Total Sales",
                aggregation="sum",
                column="total_sales",
                format="${:,.2f}",
            )
        ],
        chart=ChartSpec(
            kind="bar",
            title="Total Sales by Store Type",
            x=["A", "B", "C"],
            series=[{"name": "total_sales", "data": [3.5, 1.4, 0.5]}],
            options={"x_column": "store_type", "y_column": "total_sales"},
        ),
        charts=[
            ChartSpec(
                kind="bar",
                title="Total Sales by Store Type",
                x=["A", "B", "C"],
                series=[{"name": "total_sales", "data": [3.5, 1.4, 0.5]}],
                options={"x_column": "store_type", "y_column": "total_sales"},
            )
        ],
        insights=["Store Type A accounts for over 64% of total sales."],
        suggestions=["How do holiday weeks compare?"],
        row_count=3,
        elapsed_ms=14531,
        created_at=datetime.now(timezone.utc),
        planner_tokens=1576,
        analyst_tokens=3068,
        tokens=4644,
    )


def _save_and_load(analysis: Analysis, db_path) -> Analysis:
    conv_id = history_db.new_conversation("test", db_path)
    analysis_id = history_db.save_analysis(conv_id, analysis, db_path)
    return history_db.get_analysis(analysis_id, db_path)


# --- descriptive ------------------------------------------------------------

def test_descriptive_fields_round_trip(db_path):
    original = _descriptive_analysis()
    loaded = _save_and_load(original, db_path)

    assert loaded.question == original.question
    assert loaded.sql == original.sql
    assert loaded.summary == original.summary
    assert loaded.insights == original.insights
    assert loaded.suggestions == original.suggestions
    assert loaded.row_count == original.row_count
    assert loaded.elapsed_ms == original.elapsed_ms
    assert loaded.tokens == original.tokens
    assert loaded.planner_tokens == original.planner_tokens
    assert loaded.analyst_tokens == original.analyst_tokens


def test_kpis_survive_as_computed_strings(db_path):
    """Replay must not recompute KPIs — the formatted value is the record."""
    loaded = _save_and_load(_descriptive_analysis(), db_path)

    assert len(loaded.kpis) == 1
    assert loaded.kpis[0].value == "$5,391,937,860.98"
    assert loaded.kpis[0].trend == "up"
    assert loaded.kpi_specs[0].aggregation == "sum"
    assert loaded.kpi_specs[0].format == "${:,.2f}"


def test_chart_data_is_embedded(db_path):
    """Charts must replay without re-running SQL, so x/series travel with them."""
    loaded = _save_and_load(_descriptive_analysis(), db_path)

    assert loaded.chart is not None
    assert loaded.chart.x == ["A", "B", "C"]
    assert loaded.chart.series == [{"name": "total_sales", "data": [3.5, 1.4, 0.5]}]
    assert loaded.chart.options["y_column"] == "total_sales"
    assert len(loaded.charts) == 1
    assert loaded.all_charts[0].title == "Total Sales by Store Type"


# --- predictive -------------------------------------------------------------

def test_non_forecastable_analysis_stays_descriptive(db_path):
    loaded = _save_and_load(_descriptive_analysis(), db_path)

    assert loaded.forecastable is False
    assert loaded.ts_profile is None
    assert loaded.forecast is None
    assert loaded.available_methods == []


def test_forecast_is_restored_on_load(db_path):
    profile = _monthly_profile()
    original = _descriptive_analysis()
    original.forecastable = True
    original.ts_profile = profile
    original.forecast = forecast(profile, "linear_trend", horizon=6, confidence=0.9)
    original.available_methods = ["auto", "linear_trend", "holt"]

    loaded = _save_and_load(original, db_path)

    assert loaded.forecastable is True
    assert loaded.forecast is not None
    assert loaded.available_methods, "method list must be recomputed from the profile"
    assert loaded.ts_profile is not None
    assert loaded.ts_profile.freq == "M"
    assert loaded.ts_profile.seasonal_period == 12
    assert loaded.ts_profile.is_seasonal is True
    assert loaded.ts_profile.x == profile.x
    assert loaded.ts_profile.y == pytest.approx(profile.y)


def test_restored_forecast_numbers_are_identical(db_path):
    """Every displayed number must survive the round trip."""
    profile = _monthly_profile()
    original = _descriptive_analysis()
    original.forecastable = True
    original.ts_profile = profile
    original.forecast = forecast(profile, "linear_trend", horizon=6, confidence=0.9)

    loaded = _save_and_load(original, db_path)

    assert loaded.forecast.method == original.forecast.method
    assert loaded.forecast.horizon == original.forecast.horizon
    assert loaded.forecast.confidence == original.forecast.confidence
    assert loaded.forecast.x == original.forecast.x
    assert loaded.forecast.yhat == pytest.approx(original.forecast.yhat)
    assert loaded.forecast.has_band == original.forecast.has_band


def test_forecast_band_fit_and_metrics_are_stored(db_path):
    """The whole result is persisted, not just the mean line."""
    profile = _monthly_profile()
    original = _descriptive_analysis()
    original.forecastable = True
    original.ts_profile = profile
    original.forecast = forecast(profile, "linear_trend", horizon=6, confidence=0.9)
    original.available_methods = ["auto", "linear_trend"]

    loaded = _save_and_load(original, db_path)

    assert len(loaded.forecast.points) == len(original.forecast.points)
    assert loaded.forecast.lower == pytest.approx(
        [v for v in original.forecast.lower if v is not None]
    )
    assert loaded.forecast.upper == pytest.approx(
        [v for v in original.forecast.upper if v is not None]
    )
    assert loaded.forecast.fitted == pytest.approx(original.forecast.fitted)
    assert set(loaded.forecast.metrics) == set(original.forecast.metrics)
    assert loaded.forecast.warnings == original.forecast.warnings


def test_stored_result_wins_over_recompute(db_path):
    """Replay shows what the user saw, even if the engine would now differ.

    Simulated by hand-editing the stored points: the loaded forecast must echo
    the stored numbers rather than silently recomputing them from the profile.
    """
    profile = _monthly_profile()
    original = _descriptive_analysis()
    original.forecastable = True
    original.ts_profile = profile
    original.forecast = forecast(profile, "linear_trend", horizon=3, confidence=0.8)

    payload = history_db._analysis_to_dict(original)
    for i, point in enumerate(payload["forecast"]["points"]):
        point["yhat"] = 1000.0 + i

    loaded = history_db._dict_to_analysis(payload)

    assert loaded.forecast.yhat == pytest.approx([1000.0, 1001.0, 1002.0])
    assert loaded.forecastable is True
    assert loaded.ts_profile is not None  # controls still interactive


def test_nan_metrics_serialise_as_null(db_path):
    """backtest returns NaN on short series; NaN is not valid JSON."""
    import json

    profile = _monthly_profile(n=8)
    original = _descriptive_analysis()
    original.forecastable = True
    original.ts_profile = profile
    original.forecast = forecast(profile, "naive", horizon=3, confidence=0.8)
    original.forecast.metrics = {"mae": float("nan"), "mape": 12.5}

    payload = history_db._analysis_to_dict(original)
    blob = json.dumps(payload)  # must not emit bare NaN

    assert "NaN" not in blob
    assert payload["forecast"]["metrics"]["mae"] is None
    assert payload["forecast"]["metrics"]["mape"] == 12.5

    loaded = history_db._dict_to_analysis(json.loads(blob))
    assert loaded.forecast.metrics["mae"] is None


def test_result_restores_without_the_forecasting_engine(db_path):
    """A stored result must rebuild from plain data — no numpy required."""
    profile = _monthly_profile()
    original = _descriptive_analysis()
    original.forecast = forecast(profile, "linear_trend", horizon=4, confidence=0.8)

    rebuilt = history_db._dict_to_forecast(
        history_db._forecast_to_dict(original.forecast)
    )

    assert rebuilt is not None
    assert rebuilt.method == original.forecast.method
    assert rebuilt.yhat == pytest.approx(original.forecast.yhat)
    assert rebuilt.has_band == original.forecast.has_band


def test_auto_method_replays_as_the_resolved_method(db_path):
    """`auto` collapses to a concrete method; that is what gets stored."""
    profile = _monthly_profile()
    original = _descriptive_analysis()
    original.forecastable = True
    original.ts_profile = profile
    original.forecast = forecast(profile, "auto", horizon=4, confidence=0.8)

    loaded = _save_and_load(original, db_path)

    assert loaded.forecast.method != "auto"
    assert loaded.forecast.method == original.forecast.method
    assert loaded.forecast.yhat == pytest.approx(original.forecast.yhat)


def test_payload_stores_both_result_and_inputs(db_path):
    """Result for fidelity, inputs for interactivity — both must be present."""
    profile = _monthly_profile()
    original = _descriptive_analysis()
    original.forecastable = True
    original.ts_profile = profile
    original.forecast = forecast(profile, "linear_trend", horizon=12, confidence=0.8)
    original.available_methods = ["auto", "linear_trend"]

    payload = history_db._analysis_to_dict(original)

    assert len(payload["forecast"]["points"]) == 12
    assert payload["forecast"]["method"] == original.forecast.method
    assert payload["ts_profile"]["freq"] == "M"
    assert payload["forecast_settings"]["horizon"] == 12
    assert payload["forecast_settings"]["confidence"] == 0.8
    assert payload["available_methods"] == ["auto", "linear_trend"]


def test_legacy_payload_without_profile_still_loads(db_path):
    """Rows written before the predictive layer was persisted must not break."""
    legacy = history_db._analysis_to_dict(_descriptive_analysis())
    for key in ("forecast", "ts_profile", "forecast_settings", "available_methods"):
        legacy.pop(key, None)

    loaded = history_db._dict_to_analysis(legacy)

    assert loaded.summary == "Type A drives most revenue."
    assert loaded.forecastable is False
    assert loaded.forecast is None


def test_inputs_only_payload_is_recomputed(db_path):
    """Payloads written before results were stored fall back to recompute."""
    profile = _monthly_profile()
    original = _descriptive_analysis()
    original.forecastable = True
    original.ts_profile = profile
    original.forecast = forecast(profile, "linear_trend", horizon=5, confidence=0.8)

    payload = history_db._analysis_to_dict(original)
    payload.pop("forecast")  # simulate the earlier inputs-only format

    loaded = history_db._dict_to_analysis(payload)

    assert loaded.forecast is not None
    assert loaded.forecast.method == original.forecast.method
    assert loaded.forecast.yhat == pytest.approx(original.forecast.yhat)


def test_corrupt_profile_degrades_to_descriptive(db_path):
    """A bad profile must never break replay of the descriptive result."""
    payload = history_db._analysis_to_dict(_descriptive_analysis())
    payload["ts_profile"] = {"freq": "M", "x": ["2024-01"], "y": ["not-a-number"]}
    payload["forecast_settings"] = {"method": "holt", "horizon": 6, "confidence": 0.8}

    loaded = history_db._dict_to_analysis(payload)

    assert loaded.summary == "Type A drives most revenue."
    assert loaded.forecast is None
    assert loaded.forecastable is False


def test_corrupt_forecast_points_degrade_to_descriptive(db_path):
    """Malformed stored points must not raise out of get_analysis()."""
    payload = history_db._analysis_to_dict(_descriptive_analysis())
    payload["forecast"] = {"method": "holt", "points": "not-a-list"}

    loaded = history_db._dict_to_analysis(payload)

    assert loaded.summary == "Type A drives most revenue."
    assert loaded.forecast is None
    assert loaded.forecastable is False


# --- data-source provenance -------------------------------------------------

def test_source_fingerprint_round_trips(db_path):
    """Without this, a replayed follow-up cannot be checked against the DB."""
    original = _descriptive_analysis()
    original.source = data_source.fingerprint(
        name="Sales DB",
        kind="postgres",
        db_url="postgresql://joe@localhost:5432/sales",
        table_defs=[{"table": "orders", "columns": [{"name": "id"}]}],
    )

    loaded = _save_and_load(original, db_path)

    assert loaded.source is not None
    assert loaded.source.name == "Sales DB"
    assert loaded.source.kind == "postgres"
    assert loaded.source.target == "postgresql://joe@localhost:5432/sales"
    assert loaded.source.schema_hash == original.source.schema_hash
    assert loaded.source.table_count == 1
    assert data_source.compare(loaded.source, original.source) is None


def test_stored_source_never_contains_a_password(db_path):
    original = _descriptive_analysis()
    original.source = data_source.fingerprint(
        name="Default",
        kind="postgres",
        db_url="postgresql://joe:hunter2@db.internal:5432/sales",
        table_defs=[{"table": "orders", "columns": [{"name": "id"}]}],
    )

    payload = history_db._analysis_to_dict(original)

    assert "hunter2" not in json.dumps(payload)
    assert payload["source"]["target"] == "postgresql://joe@db.internal:5432/sales"


def test_analysis_without_a_source_loads_as_unknown(db_path):
    """Rows saved before provenance existed must still open — and not be trusted."""
    loaded = _save_and_load(_descriptive_analysis(), db_path)
    current = data_source.fingerprint(
        name="Default", kind="postgres", db_url="postgresql://joe@h/db",
        table_defs=[{"table": "t", "columns": [{"name": "c"}]}],
    )

    assert loaded.source is None
    assert data_source.compare(loaded.source, current) == data_source.UNKNOWN_SOURCE


def test_replaying_across_databases_is_detected(db_path):
    """The scenario the gate exists for: save on DB A, ask on DB B."""
    saved = _descriptive_analysis()
    saved.source = data_source.fingerprint(
        name="Sales DB", kind="postgres",
        db_url="postgresql://joe@localhost:5432/sales",
        table_defs=[{"table": "orders", "columns": [{"name": "id"}]}],
    )
    loaded = _save_and_load(saved, db_path)

    now_connected = data_source.fingerprint(
        name="Warehouse", kind="postgres",
        db_url="postgresql://joe@localhost:5432/warehouse",
        table_defs=[{"table": "facts", "columns": [{"name": "amount"}]}],
    )

    assert loaded.suggestions, "the follow-ups that would be clicked"
    assert data_source.compare(loaded.source, now_connected) == (
        data_source.DIFFERENT_TARGET
    )


def test_clarification_flag_round_trips(db_path):
    """Drives the 'question doesn't fit this data' popup on replay."""
    original = _descriptive_analysis()
    original.needs_clarification = True

    loaded = _save_and_load(original, db_path)

    assert loaded.needs_clarification is True


# --- storage plumbing -------------------------------------------------------

def test_favorite_and_listing(db_path):
    conv_id = history_db.new_conversation("test", db_path)
    analysis_id = history_db.save_analysis(conv_id, _descriptive_analysis(), db_path)

    history_db.set_favorite(analysis_id, True, db_path)
    rows = history_db.list_all_analyses(db_path)

    assert any(r["id"] == analysis_id and r["favorite"] for r in rows)


def test_delete_conversation_removes_analyses(db_path):
    conv_id = history_db.new_conversation("test", db_path)
    history_db.save_analysis(conv_id, _descriptive_analysis(), db_path)

    history_db.delete_conversation(conv_id, db_path)

    assert history_db.get_conversation.__name__  # sanity: function exists
    assert not [
        c for c in history_db.list_conversations(db_path) if c["id"] == conv_id
    ]
