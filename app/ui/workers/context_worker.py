"""Background worker that builds a lean data-context document via Gemini."""

from __future__ import annotations

import re
from collections.abc import Callable

from loguru import logger
from PySide6.QtCore import QObject, QRunnable, Signal

from app.core.gemini_analyst import build_data_context

_MAX_TABLES = 12
_SAMPLE_ROWS = 5
_SAFE_TABLE = re.compile(r"^[a-z][a-z0-9_]*$")


class ContextSignals(QObject):
    ready = Signal(str)
    failed = Signal(str)


class ContextWorker(QRunnable):
    """Profiles columns + 5 sample rows per table, then asks Gemini for context."""

    def __init__(
        self,
        gemini,
        client,
        schema_md: str,
        tables: list[str],
        *,
        connection_gen: int = 0,
        is_current: Callable[[], bool] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__()
        self._gemini = gemini
        self._client = client
        self._schema_md = schema_md
        self._tables = tables
        self._connection_gen = connection_gen
        self._is_current = is_current
        self.signals = ContextSignals(parent)

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
            logger.debug("Dropped context signal; source no longer alive")

    def run(self) -> None:
        try:
            if not self._still_current():
                return
            samples: dict[str, list[dict]] = {}
            for table in self._tables[:_MAX_TABLES]:
                if not self._still_current():
                    return
                if not _SAFE_TABLE.match(table):
                    logger.warning("Skipping unsafe table name: {}", table)
                    continue
                try:
                    samples[table] = self._client.query(
                        f"SELECT * FROM {table} LIMIT {_SAMPLE_ROWS}"
                    )
                except Exception:  # noqa: BLE001
                    samples[table] = []
            md, tokens = build_data_context(
                self._gemini, self._schema_md, samples
            )
            logger.info("Data context built ({} chars, {} tokens)", len(md), tokens)
            self._emit(self.signals.ready, md)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Data-context build failed")
            self._emit(self.signals.failed, str(exc))
