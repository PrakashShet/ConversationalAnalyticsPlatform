"""SQLite persistence for conversation history.

Stores each :class:`Analysis` as a JSON blob so replaying a history item
re-renders the canvas with **no Gemini call and no SQL**.

Descriptive results are stored verbatim (chart data and computed KPI strings
are embedded).

The predictive layer is stored **both ways**:

* the :class:`ForecastResult` itself — every point, band, fitted value, metric
  and warning — so the record of what the user actually saw is authoritative
  and survives any later change to the forecasting code;
* its *inputs* (the detected ``TimeSeriesProfile`` and the resolved
  method/horizon/confidence) — so the forecast controls stay interactive on a
  replayed item and the user can change method or horizon without re-querying.

On load the stored result is restored verbatim; the profile is only used to
recompute when a payload predates result storage. Restoring the stored result
needs no numpy, so history replays even in a stripped environment.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from loguru import logger

from app.data.models import (
    Analysis,
    ChartSpec,
    ForecastPoint,
    ForecastResult,
    Kpi,
    KpiSpec,
    SourceFingerprint,
    TimeSeriesProfile,
)


def _source_to_dict(source: SourceFingerprint | None) -> dict | None:
    """Persist which database produced the analysis.

    ``target`` is credential-free by construction (``data_source.redact_url``),
    so this never writes a password into the history database.
    """
    if source is None:
        return None
    return {
        "name": source.name,
        "kind": source.kind,
        "target": source.target,
        "schema_hash": source.schema_hash,
        "table_count": int(source.table_count or 0),
    }


def _dict_to_source(data: dict | None) -> SourceFingerprint | None:
    if not data:
        return None
    return SourceFingerprint(
        name=data.get("name", ""),
        kind=data.get("kind", ""),
        target=data.get("target", ""),
        schema_hash=data.get("schema_hash", ""),
        table_count=int(data.get("table_count") or 0),
    )


class _Encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


# --- predictive layer (result stored verbatim + inputs for interactivity) ---

def _num(value) -> float | None:
    """JSON-safe float. NaN/Inf become ``null`` — both consumers guard on None.

    ``backtest`` returns NaN metrics when a series is too short to score, and
    ``NaN`` is not valid JSON.
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None

def _profile_to_dict(profile: TimeSeriesProfile | None) -> dict | None:
    if profile is None:
        return None
    return {
        "time_column": profile.time_column,
        "value_column": profile.value_column,
        "freq": profile.freq,
        "n_points": profile.n_points,
        "x": list(profile.x),
        "y": [float(v) for v in profile.y],
        "seasonal_period": profile.seasonal_period,
        "is_seasonal": profile.is_seasonal,
    }


def _dict_to_profile(data: dict | None) -> TimeSeriesProfile | None:
    if not data or not data.get("x") or not data.get("y"):
        return None
    return TimeSeriesProfile(
        time_column=data.get("time_column", ""),
        value_column=data.get("value_column", ""),
        freq=data.get("freq", "M"),
        n_points=int(data.get("n_points", len(data["x"]))),
        x=list(data["x"]),
        y=[float(v) for v in data["y"]],
        seasonal_period=data.get("seasonal_period"),
        is_seasonal=bool(data.get("is_seasonal", False)),
    )


def _forecast_settings(analysis: Analysis) -> dict | None:
    """The forecast *inputs* worth persisting.

    ``method`` is the **resolved** method (``auto`` has already collapsed to the
    method the backtest picked), so a recompute reproduces what was shown.
    """
    fc = analysis.forecast
    if fc is None:
        return None
    return {
        "method": fc.method,
        "horizon": int(fc.horizon),
        "confidence": float(fc.confidence),
    }


def _forecast_to_dict(forecast: ForecastResult | None) -> dict | None:
    """Serialise the computed forecast — points, band, fit, metrics, warnings.

    This is the authoritative record of what the user was shown. It is stored
    in addition to the inputs so the displayed numbers never drift if the
    forecasting code changes later.
    """
    if forecast is None:
        return None
    return {
        "method": forecast.method,
        "horizon": int(forecast.horizon),
        "confidence": float(forecast.confidence),
        "points": [
            {
                "x": p.x,
                "yhat": _num(p.yhat),
                "lower": _num(p.lower),
                "upper": _num(p.upper),
            }
            for p in forecast.points
        ],
        "fitted": (
            [_num(v) for v in forecast.fitted] if forecast.fitted is not None else None
        ),
        "metrics": {k: _num(v) for k, v in (forecast.metrics or {}).items()},
        "warnings": list(forecast.warnings or []),
    }


def _dict_to_forecast(data: dict | None) -> ForecastResult | None:
    """Rebuild a stored :class:`ForecastResult`. Needs no numpy."""
    if not data or not data.get("points"):
        return None
    points = [
        ForecastPoint(
            x=str(p.get("x", "")),
            yhat=float(p.get("yhat") or 0.0),
            lower=(None if p.get("lower") is None else float(p["lower"])),
            upper=(None if p.get("upper") is None else float(p["upper"])),
        )
        for p in data["points"]
    ]
    fitted = data.get("fitted")
    return ForecastResult(
        method=data.get("method", "linear_trend"),
        horizon=int(data.get("horizon", len(points))),
        points=points,
        confidence=float(data.get("confidence", 0.8)),
        fitted=([float(v) for v in fitted if v is not None] if fitted else None),
        metrics={k: v for k, v in (data.get("metrics") or {}).items()},
        warnings=list(data.get("warnings") or []),
    )


def _method_list(profile: TimeSeriesProfile | None, stored: list | None) -> list[str]:
    """Methods to offer in the forecast controls.

    Recomputed from the profile when possible (it reflects what this machine can
    actually run — statsmodels may be absent), falling back to the stored list.
    """
    if profile is not None:
        try:
            # Lazy: keeps history_db importable without numpy/statsmodels.
            from app.core.forecasting import supported_methods
            from app.core.timeseries import available_methods

            methods = [
                m for m in available_methods(profile) if m in supported_methods()
            ]
            if methods:
                return methods
        except Exception as exc:  # noqa: BLE001 - fall back to what was stored
            logger.debug("Method list recompute unavailable: {}", exc)
    return list(stored or []) or ["linear_trend"]


def _restore_forecast(analysis: Analysis, data: dict) -> None:
    """Restore the predictive layer in place. Never raises.

    Prefers the **stored** :class:`ForecastResult` so replay shows exactly the
    numbers the user saw. Only falls back to recomputing from the profile when
    a payload predates result storage. Either way there is no Gemini call and
    no SQL, and any failure leaves the descriptive result fully intact — the
    same contract as ``Orchestrator._attach_forecast`` on the live path.
    """
    if not data.get("ts_profile") and not data.get("forecast"):
        return
    settings = data.get("forecast_settings") or {}
    try:
        # Parsing is inside the guard: a malformed payload must degrade to a
        # descriptive-only replay, never raise out of get_analysis().
        profile = _dict_to_profile(data.get("ts_profile"))
        stored = _dict_to_forecast(data.get("forecast"))

        if stored is not None:
            result = stored
        elif profile is not None:
            # Legacy payload: inputs only. Recompute — deterministic, so this
            # reproduces the original numbers.
            from app.core.forecasting import forecast as _forecast

            result = _forecast(
                profile,
                settings.get("method", "auto"),
                int(settings.get("horizon", 12)),
                float(settings.get("confidence", 0.8)),
            )
        else:
            return

        analysis.ts_profile = profile
        analysis.available_methods = _method_list(
            profile, data.get("available_methods")
        )
        analysis.forecast = result
        # Controls need a profile to recompute against; without one the forecast
        # is display-only, so do not advertise it as interactive.
        analysis.forecastable = profile is not None
    except Exception as exc:  # noqa: BLE001 - never break history replay
        logger.warning("Forecast restore skipped for stored analysis: {}", exc)


def _analysis_to_dict(analysis: Analysis) -> dict:
    return {
        "question": analysis.question,
        "sql": analysis.sql,
        "summary": analysis.summary,
        "kpis": [
            {"label": k.label, "value": k.value, "delta": k.delta, "trend": k.trend}
            for k in analysis.kpis
        ],
        "kpi_specs": [
            {
                "label": s.label,
                "aggregation": s.aggregation,
                "column": s.column,
                "format": s.format,
            }
            for s in analysis.kpi_specs
        ],
        "chart": {
            "kind": analysis.chart.kind,
            "title": analysis.chart.title,
            "x": analysis.chart.x,
            "series": analysis.chart.series,
            "options": analysis.chart.options,
        } if analysis.chart else None,
        "charts": [
            {
                "kind": c.kind,
                "title": c.title,
                "x": c.x,
                "series": c.series,
                "options": c.options,
            }
            for c in analysis.charts
        ],
        "suggestions": analysis.suggestions,
        "insights": analysis.insights,
        "row_count": analysis.row_count,
        "elapsed_ms": analysis.elapsed_ms,
        "tokens": analysis.tokens,
        "planner_tokens": analysis.planner_tokens,
        "analyst_tokens": analysis.analyst_tokens,
        "created_at": analysis.created_at.isoformat(),
        # Predictive layer: the computed result (authoritative record of what
        # was shown) plus its inputs (so the controls stay interactive).
        "forecast": _forecast_to_dict(analysis.forecast),
        "ts_profile": _profile_to_dict(analysis.ts_profile),
        "forecast_settings": _forecast_settings(analysis),
        "available_methods": list(analysis.available_methods or []),
        # Which database this came from, so a replayed analysis can be checked
        # against the live connection before its follow-ups are run.
        "source": _source_to_dict(analysis.source),
        "needs_clarification": bool(analysis.needs_clarification),
        "forecast_requested": bool(analysis.forecast_requested),
        "forecast_note": analysis.forecast_note or "",
    }


def _dict_to_analysis(data: dict) -> Analysis:
    chart_data = data.get("chart")
    chart = None
    if chart_data:
        chart = ChartSpec(
            kind=chart_data.get("kind", "table"),
            title=chart_data.get("title", ""),
            x=chart_data.get("x"),
            series=chart_data.get("series", []),
            options=chart_data.get("options", {}),
        )
    charts = [
        ChartSpec(
            kind=c.get("kind", "bar"),
            title=c.get("title", ""),
            x=c.get("x"),
            series=c.get("series", []),
            options=c.get("options", {}),
        )
        for c in data.get("charts", [])
    ]
    created = data.get("created_at")
    if isinstance(created, str):
        created_at = datetime.fromisoformat(created)
    else:
        created_at = datetime.now()
    analysis = Analysis(
        question=data.get("question", ""),
        sql=data.get("sql", ""),
        summary=data.get("summary", ""),
        kpis=[Kpi(**k) for k in data.get("kpis", [])],
        kpi_specs=[KpiSpec(**s) for s in data.get("kpi_specs", [])],
        chart=chart,
        charts=charts,
        insights=data.get("insights", []),
        suggestions=data.get("suggestions", []),
        row_count=data.get("row_count", 0),
        elapsed_ms=data.get("elapsed_ms", 0),
        tokens=data.get("tokens", 0),
        planner_tokens=data.get("planner_tokens", 0),
        analyst_tokens=data.get("analyst_tokens", 0),
        created_at=created_at,
        source=_dict_to_source(data.get("source")),
        needs_clarification=bool(data.get("needs_clarification", False)),
        forecast_requested=bool(data.get("forecast_requested", False)),
        forecast_note=data.get("forecast_note", ""),
    )
    # Rows saved before the predictive layer was persisted simply have no
    # ts_profile — they replay as descriptive-only, which is correct.
    _restore_forecast(analysis, data)
    return analysis


def init_db(path: str | Path) -> None:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            analysis_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            favorite INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );
    """)
    # Migration: add `favorite` to pre-existing databases.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(analyses)").fetchall()}
    if "favorite" not in cols:
        conn.execute(
            "ALTER TABLE analyses ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0"
        )
    conn.commit()
    conn.close()


def new_conversation(title: str, path: str | Path) -> int:
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO conversations (title, created_at) VALUES (?, ?)",
        (title, datetime.now().isoformat()),
    )
    conv_id = cur.lastrowid
    conn.commit()
    conn.close()
    return conv_id


def save_analysis(conv_id: int, analysis: Analysis, path: str | Path) -> int:
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    payload = json.dumps(_analysis_to_dict(analysis), cls=_Encoder)
    cur.execute(
        "INSERT INTO analyses (conversation_id, question, analysis_json, created_at) "
        "VALUES (?, ?, ?, ?)",
        (conv_id, analysis.question, payload, analysis.created_at.isoformat()),
    )
    analysis_id = cur.lastrowid
    conn.commit()
    conn.close()
    return analysis_id


def list_conversations(path: str | Path) -> list[dict]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, title, created_at FROM conversations ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_conversation(conv_id: int, path: str | Path) -> dict:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conv = conn.execute(
        "SELECT id, title, created_at FROM conversations WHERE id = ?",
        (conv_id,),
    ).fetchone()
    analyses = conn.execute(
        "SELECT id, question, analysis_json, created_at FROM analyses "
        "WHERE conversation_id = ? ORDER BY id",
        (conv_id,),
    ).fetchall()
    conn.close()
    return {
        "id": conv["id"],
        "title": conv["title"],
        "created_at": conv["created_at"],
        "analyses": [dict(a) for a in analyses],
    }


def get_analysis(analysis_id: int, path: str | Path) -> Analysis:
    conn = sqlite3.connect(path)
    row = conn.execute(
        "SELECT analysis_json FROM analyses WHERE id = ?",
        (analysis_id,),
    ).fetchone()
    conn.close()
    if not row:
        raise KeyError(f"Analysis {analysis_id} not found")
    return _dict_to_analysis(json.loads(row[0]))


def delete_conversation(conv_id: int, path: str | Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM analyses WHERE conversation_id = ?", (conv_id,))
    conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    conn.commit()
    conn.close()


def list_all_analyses(path: str | Path) -> list[dict]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT a.id, a.question, a.created_at, a.conversation_id, "
        "a.favorite, c.title AS conv_title "
        "FROM analyses a JOIN conversations c ON a.conversation_id = c.id "
        "ORDER BY a.favorite DESC, a.id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_favorite(analysis_id: int, favorite: bool, path: str | Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "UPDATE analyses SET favorite = ? WHERE id = ?",
        (1 if favorite else 0, analysis_id),
    )
    conn.commit()
    conn.close()


def delete_analysis(analysis_id: int, path: str | Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))
    conn.commit()
    conn.close()
