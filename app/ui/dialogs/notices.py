"""Modal notices — the things the user must not miss.

Inline banners are easy to overlook when the canvas is scrolled, so anything
that would silently produce a misleading answer (or no answer at all) is raised
as a modal instead. Each helper returns whether the caller should continue.

Wording for data-source mismatches lives in ``app.core.data_source.explain`` so
it can be tested without Qt.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from app.core import data_source
from app.data.models import SourceFingerprint

_APP = "Conversational Analytics"


def _box(
    parent: QWidget | None,
    icon: QMessageBox.Icon,
    title: str,
    text: str,
    detail: str = "",
) -> QMessageBox:
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(f"{_APP} — {title}")
    box.setText(text)
    if detail:
        box.setInformativeText(detail)
    return box


def confirm_source_mismatch(
    parent: QWidget | None,
    reason: str,
    saved: SourceFingerprint | None,
    current: SourceFingerprint | None,
) -> bool:
    """Warn that a saved analysis belongs elsewhere. ``True`` to go ahead.

    Deliberately *not* a hard block: the question may still be valid against the
    connected database. The dialog names both sources and says how to get back
    to the original, then lets the user decide. Cancel is the default button.
    """
    headline, detail = data_source.explain(reason, saved, current)
    box = _box(parent, QMessageBox.Icon.Warning, "Different data source", headline, detail)
    ask = box.addButton("Ask anyway", QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    box.exec()
    return box.clickedButton() is ask


def not_connected(parent: QWidget | None) -> None:
    _box(
        parent,
        QMessageBox.Icon.Information,
        "Not connected",
        "Connect a database before asking this question.",
        "Choose a data source in the left panel and click Connect. Saved "
        "analyses stay readable while disconnected, but their follow-ups need "
        "a live connection to run.",
    ).exec()


def missing_api_key(parent: QWidget | None) -> bool:
    """Report the missing key. ``True`` when the user asked to open Settings."""
    box = _box(
        parent,
        QMessageBox.Icon.Warning,
        "API key required",
        "No Gemini API key is set.",
        "Questions are planned and narrated by Gemini, so a key is required. "
        "It is stored in your operating system's keychain, not on disk.",
    )
    settings = box.addButton("Open Settings", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(settings)
    box.exec()
    return box.clickedButton() is settings


def question_not_answerable(parent: QWidget | None, rationale: str) -> None:
    """The planner could not map the question onto the connected schema."""
    _box(
        parent,
        QMessageBox.Icon.Information,
        "Question doesn't fit this data",
        "That question couldn't be answered from the connected database.",
        (rationale or "").strip()
        or "The question could not be mapped to any table or column in the "
        "current schema. Try naming a table or measure you can see in the "
        "Data source panel.",
    ).exec()


def forecast_unavailable(parent: QWidget | None, reason: str) -> None:
    """The user asked for a forecast, but the result isn't a time series.

    Silence here reads as the app ignoring the request, so the specific reason
    is stated — too few periods, no date column, irregular spacing.
    """
    _box(
        parent,
        QMessageBox.Icon.Information,
        "No forecast for this result",
        "The descriptive answer is below, but no forecast could be produced.",
        (reason or "").strip()
        or "The result is not a time series, so there is nothing to project.",
    ).exec()


def analysis_failed(parent: QWidget | None, message: str) -> None:
    """A run that started but could not finish — SQL error, API error, etc."""
    text, detail = _classify_failure(message)
    _box(parent, QMessageBox.Icon.Critical, "Analysis failed", text, detail).exec()


def _classify_failure(message: str) -> tuple[str, str]:
    """Turn a raw exception string into something a user can act on."""
    raw = (message or "").strip()
    low = raw.lower()

    if "429" in low or "rate" in low or "quota" in low:
        return (
            "Gemini is rate limiting requests.",
            "Wait a few seconds and ask again. If it persists, check the quota "
            f"on your API key.\n\nDetails: {raw}",
        )
    if "401" in low or "403" in low or "api key" in low or "authentic" in low:
        return (
            "Gemini rejected the API key.",
            f"Open Settings and re-enter your key.\n\nDetails: {raw}",
        )
    if "not connected" in low or "disconnect" in low:
        return (
            "The database connection was lost.",
            f"Reconnect in the Data source panel and try again.\n\n"
            f"Details: {raw}",
        )
    if "does not exist" in low or "no such" in low or "undefined" in low:
        return (
            "The query referred to something the database doesn't have.",
            "This usually means the question was written against a different "
            "dataset, or the data has been reloaded since.\n\n"
            f"Details: {raw}",
        )
    if "only read-only" in low or "read-only" in low:
        return (
            "That question required a write, which is not allowed.",
            f"The app runs in read-only mode; only SELECT queries are "
            f"executed.\n\nDetails: {raw}",
        )
    return ("The analysis could not be completed.", raw)
