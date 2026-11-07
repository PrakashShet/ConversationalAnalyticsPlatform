"""Background worker that recomputes a forecast locally.

Runs ``app.core.forecasting.forecast`` off the UI thread when the user changes
the method, horizon, or confidence. It touches **neither Gemini nor MCP** — the
recompute is pure local math over the in-memory ``TimeSeriesProfile``, so it
costs zero tokens and issues no SQL.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal

from app.core.forecasting import forecast
from app.data.models import TimeSeriesProfile


class ForecastSignals(QObject):
    finished = Signal(object)  # ForecastResult
    failed = Signal(str)


class ForecastWorker(QRunnable):
    """Recompute a single forecast for ``profile`` with the chosen settings."""

    def __init__(
        self,
        profile: TimeSeriesProfile,
        method: str,
        horizon: int,
        confidence: float,
    ) -> None:
        super().__init__()
        self._profile = profile
        self._method = method
        self._horizon = horizon
        self._confidence = confidence
        self.signals = ForecastSignals()

    def run(self) -> None:
        try:
            result = forecast(
                self._profile, self._method, self._horizon, self._confidence
            )
            self.signals.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 - surface to the badge, never crash
            self.signals.failed.emit(str(exc))
