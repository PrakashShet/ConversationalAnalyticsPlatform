"""Background worker for analysis pipeline."""

from __future__ import annotations

from collections.abc import Callable

from loguru import logger
from PySide6.QtCore import QObject, QRunnable, Signal

from app.core.orchestrator import Orchestrator


class WorkerSignals(QObject):
    started = Signal()
    summary_streamed = Signal(str)  # cumulative plain-text summary so far
    finished = Signal(object)
    failed = Signal(str)


class AnalysisWorker(QRunnable):
    """Runs orchestrator.ask in a background thread, streaming progress."""

    def __init__(
        self,
        orchestrator: Orchestrator,
        question: str,
        history: list[dict],
        stream: bool = True,
        *,
        connection_gen: int = 0,
        is_current: Callable[[], bool] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__()
        self._orchestrator = orchestrator
        self._question = question
        self._history = history
        self._stream = stream
        self._summary = ""
        self._connection_gen = connection_gen
        self._is_current = is_current
        # Parent the QObject so it is not GC'd while the QRunnable is running.
        self.signals = WorkerSignals(parent)

    @property
    def connection_gen(self) -> int:
        return self._connection_gen

    def _still_current(self) -> bool:
        if self._is_current is not None:
            return self._is_current()
        return True

    def _emit(self, signal: Signal, *args) -> None:
        if not self._still_current():
            return
        try:
            signal.emit(*args)
        except RuntimeError:
            # Signal source deleted (window closed / worker abandoned).
            logger.debug("Dropped analysis signal; source no longer alive")

    def _on_chunk(self, delta: str) -> None:
        if not self._still_current():
            return
        self._summary += delta
        self._emit(self.signals.summary_streamed, self._summary)

    def run(self) -> None:
        self._emit(self.signals.started)
        try:
            if not self._still_current():
                return
            on_chunk = self._on_chunk if self._stream else None
            result = self._orchestrator.ask(
                self._question, self._history, on_chunk=on_chunk
            )
            self._emit(self.signals.finished, result)
        except Exception as exc:  # noqa: BLE001 — surface to UI
            message = str(exc)
            if "not connected" in message.lower():
                message = "Database disconnected — connect again and retry."
            self._emit(self.signals.failed, message)
