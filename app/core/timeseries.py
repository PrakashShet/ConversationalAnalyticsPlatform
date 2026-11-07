"""Time-series relevance detection — the predictive-analytics gate.

Pure Python (pandas + numpy); **no LLM, no Qt**. Decides whether a set of SQL
result rows form a *forecastable* time series and, if so, returns a clean,
ordered :class:`TimeSeriesProfile`. Returns ``None`` when the data is not
relevant for forecasting — e.g. a categorical breakdown ("sales by region"),
too few points, or irregular spacing. This is the gate that guarantees the
forecast UI only ever appears on relevant data.
"""

from __future__ import annotations

import re
import warnings
from typing import Any

import numpy as np
import pandas as pd

from app.data.models import ChartSpec, TimeSeriesProfile

MIN_POINTS = 6
PARSE_THRESHOLD = 0.9  # >= 90% of time cells must parse as dates to qualify
_REGULARITY = 0.6  # >= 60% of gaps must match the inferred frequency band

# Day-spacing classification: freq -> (label, low_days, high_days).
_FREQ_BANDS = (
    ("D", 0.5, 2.0),
    ("W", 5.0, 9.0),
    ("M", 26.0, 32.0),
    ("Q", 84.0, 96.0),
    ("Y", 350.0, 380.0),
)
_SEASONAL_PERIOD = {"D": 7, "W": 52, "M": 12, "Q": 4, "Y": None}
_NS_PER_DAY = 86400.0 * 1e9

_DATE_NAME_HINTS = (
    "date", "day", "month", "year", "period", "time", "week", "quarter", "dt",
)
_QUARTER_RE = re.compile(
    r"^\s*(?:(\d{4})[-/\s]*q([1-4])|q([1-4])[-/\s]*(\d{4}))\s*$", re.IGNORECASE
)


# --- value coercion ---------------------------------------------------------

def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _is_numeric_col(rows: list[dict], col: str) -> bool:
    vals = [r.get(col) for r in rows]
    ok = sum(1 for v in vals if not np.isnan(_num(v)))
    return bool(vals) and ok / len(vals) >= 0.8


def _looks_like_years(values: list) -> bool:
    nums = []
    for v in values:
        f = _num(v)
        if np.isnan(f) or f != int(f):
            return False
        nums.append(int(f))
    return bool(nums) and all(1900 <= n <= 2100 for n in nums)


def _coerce_quarter(value: Any) -> pd.Timestamp | None:
    m = _QUARTER_RE.match(str(value))
    if not m:
        return None
    if m.group(1):
        year, q = int(m.group(1)), int(m.group(2))
    else:
        q, year = int(m.group(3)), int(m.group(4))
    return pd.Timestamp(year=year, month=(q - 1) * 3 + 1, day=1)


def _parse_time(values: list) -> tuple[pd.DatetimeIndex | None, str | None]:
    """Return ``(DatetimeIndex with NaT for failures, freq_hint)``.

    Handles 4-digit years (annual), quarter strings, and general date parsing.
    """
    if not values:
        return None, None
    if _looks_like_years(values):
        idx = pd.to_datetime(
            [f"{int(_num(v))}-01-01" for v in values], errors="coerce"
        )
        return pd.DatetimeIndex(idx), "Y"
    if any(_coerce_quarter(v) is not None for v in values):
        stamps = [(_coerce_quarter(v) or pd.NaT) for v in values]
        return pd.DatetimeIndex(pd.to_datetime(stamps, errors="coerce")), "Q"
    series = pd.Series([str(v) for v in values])
    with warnings.catch_warnings():
        # Mixed-format date strings fall back to dateutil; that's intended here.
        warnings.simplefilter("ignore", UserWarning)
        idx = pd.to_datetime(series, errors="coerce")
    return pd.DatetimeIndex(idx), None


def _parse_ratio(values: list) -> float:
    idx, _ = _parse_time(values)
    if idx is None or len(idx) == 0:
        return 0.0
    return float(idx.notna().mean())


# --- column selection -------------------------------------------------------

def _best_time_column(rows: list[dict], cols: list[str]) -> str | None:
    best, best_ratio = None, 0.0
    for col in cols:
        ratio = _parse_ratio([r.get(col) for r in rows])
        hinted = any(h in col.lower() for h in _DATE_NAME_HINTS)
        score = ratio + (0.05 if hinted else 0.0)  # nudge date-named columns
        if score > best_ratio:
            best, best_ratio = col, score
    if best is None or _parse_ratio([r.get(best) for r in rows]) < PARSE_THRESHOLD:
        return None
    return best


def _best_numeric_column(
    rows: list[dict], cols: list[str], exclude: str
) -> str | None:
    best, best_count = None, 0
    for col in cols:
        if col == exclude or not _is_numeric_col(rows, col):
            continue
        count = sum(1 for r in rows if not np.isnan(_num(r.get(col))))
        if count > best_count:
            best, best_count = col, count
    return best


# --- frequency inference ----------------------------------------------------

def _infer_freq(times: pd.DatetimeIndex) -> str | None:
    t = pd.DatetimeIndex(times).sort_values()
    if len(t) < 2:
        return None
    # Resolution-independent day gaps — works for datetime64[ns|us|ms|s] alike.
    # Avoids ``asi8``, whose integer scale depends on the datetime unit and
    # silently breaks when newer pandas parses date-only strings as [s].
    diffs = t.to_series().diff().dropna().dt.total_seconds().to_numpy() / 86400.0
    diffs = diffs[diffs > 0]
    if diffs.size == 0:
        return None
    median = float(np.median(diffs))
    for freq, lo, hi in _FREQ_BANDS:
        if lo <= median <= hi:
            within = float(np.mean((diffs >= lo) & (diffs <= hi)))
            return freq if within >= _REGULARITY else None
    return None


# --- label formatting (and inverse, for future periods) ---------------------

def _format_one(ts: pd.Timestamp, freq: str) -> str:
    if freq == "Y":
        return f"{ts.year}"
    if freq == "Q":
        return f"{ts.year}-Q{(ts.month - 1) // 3 + 1}"
    if freq == "M":
        return f"{ts.year}-{ts.month:02d}"
    return ts.strftime("%Y-%m-%d")


def _label_to_timestamp(label: str, freq: str) -> pd.Timestamp:
    if freq == "Y":
        return pd.Timestamp(year=int(label), month=1, day=1)
    if freq == "Q":
        year, q = label.split("-Q")
        return pd.Timestamp(year=int(year), month=(int(q) - 1) * 3 + 1, day=1)
    return pd.Timestamp(label)


def _advance(ts: pd.Timestamp, freq: str, k: int = 1) -> pd.Timestamp:
    if freq == "D":
        return ts + pd.Timedelta(days=k)
    if freq == "W":
        return ts + pd.Timedelta(weeks=k)
    if freq == "M":
        return ts + pd.DateOffset(months=k)
    if freq == "Q":
        return ts + pd.DateOffset(months=3 * k)
    if freq == "Y":
        return ts + pd.DateOffset(years=k)
    return ts + pd.Timedelta(days=k)


def future_labels(profile: TimeSeriesProfile, horizon: int) -> list[str]:
    """Generate the next ``horizon`` period labels after the series end."""
    last = _label_to_timestamp(profile.x[-1], profile.freq)
    out: list[str] = []
    for k in range(1, horizon + 1):
        out.append(_format_one(_advance(last, profile.freq, k), profile.freq))
    return out


# --- public API -------------------------------------------------------------

def detect_time_series(
    rows: list[dict],
    chart: ChartSpec | None = None,
    profile_hint: dict | None = None,
) -> TimeSeriesProfile | None:
    """Detect a forecastable time series in ``rows``; ``None`` if not relevant.

    Reuses rows the pipeline already fetched — performs no LLM call and no SQL.
    """
    if not rows or not isinstance(rows[0], dict):
        return None
    cols = list(rows[0].keys())

    time_col: str | None = None
    value_col: str | None = None
    if chart is not None:
        opts = chart.options or {}
        if opts.get("x_column") in cols:
            time_col = opts["x_column"]
        if opts.get("y_column") in cols:
            value_col = opts["y_column"]
    if profile_hint:
        time_col = time_col or profile_hint.get("time_column")
        value_col = value_col or profile_hint.get("value_column")

    # Validate / infer the time column.
    if time_col is None or _parse_ratio([r.get(time_col) for r in rows]) < PARSE_THRESHOLD:
        time_col = _best_time_column(rows, cols)
    if time_col is None:
        return None

    idx, hint = _parse_time([r.get(time_col) for r in rows])
    if idx is None or float(idx.notna().mean()) < PARSE_THRESHOLD:
        return None

    # Validate / infer the numeric value column.
    if (
        value_col is None
        or value_col == time_col
        or not _is_numeric_col(rows, value_col)
    ):
        value_col = _best_numeric_column(rows, cols, exclude=time_col)
    if value_col is None:
        return None

    frame = pd.DataFrame(
        {"t": idx, "y": [_num(r.get(value_col)) for r in rows]}
    ).dropna(subset=["t", "y"])
    if frame.empty:
        return None

    # One value per period (sum same-period rows), ascending.
    frame = frame.groupby("t", as_index=False)["y"].sum().sort_values("t")
    if len(frame) < MIN_POINTS:
        return None

    freq = hint or _infer_freq(pd.DatetimeIndex(frame["t"]))
    if freq is None:
        return None

    period = _SEASONAL_PERIOD.get(freq)
    n = len(frame)
    is_seasonal = period is not None and n >= 2 * period
    labels = [_format_one(ts, freq) for ts in frame["t"]]
    y = [float(v) for v in frame["y"].tolist()]

    return TimeSeriesProfile(
        time_column=time_col,
        value_column=value_col,
        freq=freq,
        n_points=n,
        x=labels,
        y=y,
        seasonal_period=period,
        is_seasonal=is_seasonal,
    )


def explain_not_forecastable(
    rows: list[dict], chart: ChartSpec | None = None
) -> str:
    """Why :func:`detect_time_series` returned ``None``, in the user's terms.

    Only called when the user *asked* for a forecast, so silence would look
    like the app ignored them. Re-walks the same checks and reports the first
    one that fails; never raises.
    """
    if not rows or not isinstance(rows[0], dict):
        return "The query returned no rows, so there is nothing to project."

    cols = list(rows[0].keys())
    time_col = _best_time_column(rows, cols)
    if time_col is None:
        return (
            "This result has no date or period column, so there is no time "
            f"axis to project along. Columns returned: {', '.join(cols)}. "
            "Try asking for the measure grouped by day, week, month or year."
        )

    ratio = _parse_ratio([r.get(time_col) for r in rows])
    if ratio < PARSE_THRESHOLD:
        return (
            f"The column “{time_col}” could not be read as dates — only "
            f"{ratio:.0%} of its values parsed, and at least "
            f"{PARSE_THRESHOLD:.0%} is needed."
        )

    value_col = _best_numeric_column(rows, cols, exclude=time_col)
    if value_col is None:
        return (
            "No numeric measure was returned alongside the dates, so there is "
            "nothing to forecast. Ask for a total, count or average by period."
        )

    idx, _ = _parse_time([r.get(time_col) for r in rows])
    if idx is None:
        return f"The column “{time_col}” could not be read as dates."

    frame = pd.DataFrame(
        {"t": idx, "y": [_num(r.get(value_col)) for r in rows]}
    ).dropna(subset=["t", "y"])
    frame = frame.groupby("t", as_index=False)["y"].sum().sort_values("t")
    n = len(frame)
    if n < MIN_POINTS:
        return (
            f"Only {n} distinct period{'' if n == 1 else 's'} came back, and at "
            f"least {MIN_POINTS} are needed to establish a pattern. Try a finer "
            "grain (weekly instead of yearly) or a wider date range."
        )

    if _infer_freq(pd.DatetimeIndex(frame["t"])) is None:
        return (
            "The periods are spaced too irregularly to project — they do not "
            "fall into a consistent daily, weekly, monthly, quarterly or yearly "
            "rhythm. Grouping with DATE_TRUNC usually fixes this."
        )

    return (
        "The result could not be read as a single time series. Try asking for "
        "one measure grouped by one time period, with no other breakdown."
    )


def available_methods(profile: TimeSeriesProfile) -> list[str]:
    """Forecasting methods valid for this series (data-driven; auto first)."""
    methods = ["auto", "naive", "moving_average", "linear_trend"]
    if profile.n_points >= 6:
        methods.append("holt")
    if profile.is_seasonal:
        methods += ["seasonal_naive", "holt_winters"]
    if (
        profile.seasonal_period
        and profile.seasonal_period <= 24  # skip SARIMA for heavy periods (e.g. weekly=52)
        and profile.n_points >= max(2 * profile.seasonal_period, 16)
    ):
        methods.append("sarima")
    seen: set[str] = set()
    ordered: list[str] = []
    for m in methods:
        if m not in seen:
            seen.add(m)
            ordered.append(m)
    return ordered
