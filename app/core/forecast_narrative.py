"""Predictive-analytics narrative — composed in Python, never by the LLM.

Mirrors what the analyst step does for descriptive results, but every sentence
here is derived arithmetically from a :class:`ForecastResult` and its
:class:`TimeSeriesProfile`. **No LLM, no Qt, no database.** That is deliberate:
rule two of this codebase is that the model never states a predicted number, and
the cheapest way to guarantee it is to never ask.

Everything is deterministic, so the same forecast always yields the same prose —
which also makes it assertable in tests.
"""

from __future__ import annotations

import numpy as np

from app.core.forecasting import FREQ_LABELS, METHOD_NOTES, PERIOD_NOUN
from app.data.models import ForecastResult, TimeSeriesProfile

# Below this relative change the outlook is called flat rather than up/down.
_FLAT_BAND = 0.02
# Backtest MAPE thresholds for describing confidence in the model.
_ACCURACY_BANDS = ((10.0, "strong"), (20.0, "reasonable"), (50.0, "weak"))


def _fmt(value: float) -> str:
    """Compact number formatting that survives both 3.2 and 3,200,000."""
    a = abs(value)
    if a >= 1_000_000_000:
        return f"{value / 1_000_000_000:,.2f}B"
    if a >= 1_000_000:
        return f"{value / 1_000_000:,.2f}M"
    if a >= 10_000:
        return f"{value:,.0f}"
    if a >= 1:
        return f"{value:,.1f}"
    return f"{value:,.3f}"


def _pct(value: float) -> str:
    return f"{value * 100:+.1f}%"


def _period_word(freq: str, n: int) -> str:
    noun = PERIOD_NOUN.get(freq, "period")
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _accuracy_word(mape: float | None) -> str | None:
    if mape is None or mape != mape:
        return None
    for limit, word in _ACCURACY_BANDS:
        if mape < limit:
            return word
    return "poor"


def summarize(profile: TimeSeriesProfile, result: ForecastResult) -> str:
    """One paragraph describing where the series is heading and how surely."""
    if not result.points:
        return ""

    history = np.asarray(profile.y, dtype=float)
    yhat = np.asarray(result.yhat, dtype=float)
    freq_label = FREQ_LABELS.get(profile.freq, profile.freq)
    horizon_words = _period_word(profile.freq, result.horizon)

    last = float(history[-1])
    end = float(yhat[-1])
    change = (end - last) / abs(last) if last else 0.0

    if abs(change) < _FLAT_BAND:
        direction = "holds roughly steady"
    elif change > 0:
        direction = "rises"
    else:
        direction = "falls"

    parts = [
        f"Projecting the {freq_label} {profile.value_column} forward "
        f"{horizon_words}, the series {direction} from {_fmt(last)} at "
        f"{profile.x[-1]} to {_fmt(end)} by {result.points[-1].x}"
    ]
    if abs(change) >= _FLAT_BAND:
        parts[0] += f" — a change of {_pct(change)}"
    parts[0] += "."

    # Total over the horizon, which is usually the number people act on.
    total = float(np.sum(yhat))
    hist_window = history[-result.horizon:] if len(history) >= result.horizon else history
    if len(hist_window) == result.horizon:
        prior = float(np.sum(hist_window))
        if prior:
            delta = (total - prior) / abs(prior)
            parts.append(
                f"The {horizon_words} ahead total {_fmt(total)}, "
                f"{_pct(delta)} against the last {horizon_words}."
            )
        else:
            parts.append(f"The {horizon_words} ahead total {_fmt(total)}.")
    else:
        parts.append(f"The {horizon_words} ahead total {_fmt(total)}.")

    return " ".join(parts)


def bullets(profile: TimeSeriesProfile, result: ForecastResult) -> list[str]:
    """Supporting points — the equivalent of descriptive `insights`."""
    if not result.points:
        return []

    out: list[str] = []
    yhat = np.asarray(result.yhat, dtype=float)
    history = np.asarray(profile.y, dtype=float)
    conf = int(round(result.confidence * 100))

    # 1. Which model, and how it did against held-out history.
    mape = (result.metrics or {}).get("mape")
    word = _accuracy_word(mape)
    label = result.method.replace("_", " ").title()
    if word:
        out.append(
            f"Model: {label}. Backtesting against held-out history gives "
            f"{mape:.1f}% mean error — {word} accuracy for this series."
        )
    else:
        out.append(
            f"Model: {label}. The series is too short to score a backtest, so "
            f"treat the projection as indicative only."
        )

    # 2. How wide the uncertainty is at the far end.
    if result.has_band:
        lo, hi = result.points[-1].lower, result.points[-1].upper
        if lo is not None and hi is not None:
            mid = yhat[-1]
            spread = (hi - lo) / abs(mid) if mid else 0.0
            out.append(
                f"By {result.points[-1].x} the {conf}% interval spans "
                f"{_fmt(lo)} to {_fmt(hi)} — about {spread * 100:.0f}% of the "
                f"projected value. Uncertainty widens the further out you look."
            )

    # 3. Seasonality, and whether the model uses it.
    if profile.is_seasonal and profile.seasonal_period:
        uses = result.method in ("seasonal_naive", "holt_winters", "sarima")
        out.append(
            f"A seasonal cycle of {profile.seasonal_period} periods was "
            f"detected. The chosen model "
            + ("accounts for it." if uses else
               "does not model it — a seasonal method may fit better.")
        )
    elif profile.seasonal_period:
        out.append(
            f"Not enough history to confirm seasonality: a "
            f"{profile.seasonal_period}-period cycle needs at least "
            f"{2 * profile.seasonal_period} points and there are "
            f"{profile.n_points}."
        )

    # 4. Whether the projection leaves observed territory.
    hi_seen, lo_seen = float(np.max(history)), float(np.min(history))
    if float(np.max(yhat)) > hi_seen:
        out.append(
            f"The forecast rises above every value ever observed "
            f"({_fmt(hi_seen)}), so it assumes the recent trend continues."
        )
    elif float(np.min(yhat)) < lo_seen:
        out.append(
            f"The forecast falls below every value ever observed "
            f"({_fmt(lo_seen)})."
        )

    # 5. Anything the engine itself flagged.
    for warning in (result.warnings or [])[:2]:
        out.append(warning[0].upper() + warning[1:] if warning else warning)

    return out


def method_rationale(result: ForecastResult) -> str:
    """One line on what the chosen method assumes."""
    note = METHOD_NOTES.get(result.method, "")
    label = result.method.replace("_", " ").title()
    return f"{label} — {note}" if note else label


def caveat() -> str:
    """The standing disclaimer. Shown wherever a forecast is."""
    return (
        "Forecasts are model estimates extrapolated from history, not "
        "guaranteed outcomes. They assume past patterns continue and cannot "
        "anticipate changes in the business, market or data collection."
    )


def build(profile: TimeSeriesProfile | None, result: ForecastResult | None) -> dict:
    """Everything the predictive-analytics section needs. Never raises."""
    if profile is None or result is None or not result.points:
        return {}
    try:
        return {
            "summary": summarize(profile, result),
            "bullets": bullets(profile, result),
            "method": method_rationale(result),
            "caveat": caveat(),
        }
    except Exception:  # noqa: BLE001 - narrative must never break the result
        return {}
