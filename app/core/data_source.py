"""Data-source identity — which database an analysis came from.

Pure Python; **no LLM, no Qt, no database access**. Builds a
:class:`~app.data.models.SourceFingerprint` from the active settings plus the
schema that was just introspected, and compares two fingerprints so the UI can
warn before acting on a saved analysis that belongs to a different database.

The fingerprint deliberately covers two independent things:

* **where the data lives** (``kind`` + ``target``) — catches switching
  databases or profiles;
* **what is in it** (``schema_hash``) — catches the same URL being reloaded
  with different CSVs, which ``load_data.bat`` does routinely by dropping and
  recreating the public schema.

``target`` is always credential-free. Fingerprints are persisted in the history
database, so a password must never reach one.
"""

from __future__ import annotations

import hashlib
import re

from app.data.models import SourceFingerprint

# Mismatch codes, ordered most to least severe.
DIFFERENT_TARGET = "different_target"
SCHEMA_CHANGED = "schema_changed"
UNKNOWN_SOURCE = "unknown_source"

_URL_CREDENTIALS = re.compile(r"^(?P<scheme>[^:]+://)(?P<user>[^:/@]+):(?P<pw>[^@]*)@")


def redact_url(url: str) -> str:
    """Strip the password from a connection URL, keeping it human-readable.

    ``postgresql://joe:s3cret@host:5432/db`` → ``postgresql://joe@host:5432/db``
    """
    return _URL_CREDENTIALS.sub(r"\g<scheme>\g<user>@", (url or "").strip())


def schema_digest(table_defs: list[dict]) -> tuple[str, int]:
    """Hash table and column names. Returns ``(digest, table_count)``.

    Order-independent and type-independent: renaming a column or adding a table
    changes the digest, but reordering the introspection results or a column
    widening from ``int4`` to ``int8`` does not.
    """
    entries: list[str] = []
    for table in table_defs or []:
        name = str(table.get("table") or table.get("name") or "").strip().lower()
        if not name:
            continue
        columns = sorted(
            str(col.get("name", "")).strip().lower()
            for col in table.get("columns", [])
            if col.get("name")
        )
        entries.append(f"{name}({','.join(columns)})")
    entries.sort()
    if not entries:
        return "", 0
    digest = hashlib.sha256("|".join(entries).encode("utf-8")).hexdigest()[:12]
    return digest, len(entries)


def fingerprint(
    *,
    name: str,
    kind: str,
    db_url: str,
    table_defs: list[dict],
) -> SourceFingerprint:
    """Build a fingerprint from the active profile and introspected schema."""
    digest, count = schema_digest(table_defs)
    return SourceFingerprint(
        name=name or "Default",
        kind=kind or "",
        target=redact_url(db_url),
        schema_hash=digest,
        table_count=count,
    )


def describe(source: SourceFingerprint | None) -> str:
    """One-line human label for a fingerprint, for use in dialogs."""
    if source is None:
        return "an unknown data source"
    bits = [source.name] if source.name else []
    if source.target:
        bits.append(source.target)
    label = " — ".join(bits) if bits else (source.kind or "unknown source")
    if source.table_count:
        plural = "" if source.table_count == 1 else "s"
        label += f" ({source.table_count} table{plural})"
    return label


def same_target(a: SourceFingerprint, b: SourceFingerprint) -> bool:
    return (a.kind or "") == (b.kind or "") and (a.target or "") == (b.target or "")


def compare(
    saved: SourceFingerprint | None,
    current: SourceFingerprint | None,
) -> str | None:
    """Why *saved* and *current* differ, or ``None`` when they match.

    Returns one of :data:`DIFFERENT_TARGET`, :data:`SCHEMA_CHANGED`,
    :data:`UNKNOWN_SOURCE`, or ``None``.

    A missing fingerprint on either side is reported as
    :data:`UNKNOWN_SOURCE` rather than treated as a match — analyses saved
    before fingerprinting existed cannot be vouched for.
    """
    if saved is None or current is None:
        return UNKNOWN_SOURCE
    if not same_target(saved, current):
        return DIFFERENT_TARGET
    # Same place; did its contents change under us?
    if saved.schema_hash and current.schema_hash:
        if saved.schema_hash != current.schema_hash:
            return SCHEMA_CHANGED
    return None


def explain(
    reason: str,
    saved: SourceFingerprint | None,
    current: SourceFingerprint | None,
) -> tuple[str, str]:
    """Render a mismatch as ``(headline, detail)`` for a dialog.

    Kept here rather than in the UI so the wording is testable without Qt.
    """
    saved_label = describe(saved)
    current_label = describe(current)

    if reason == DIFFERENT_TARGET:
        return (
            "This follow-up belongs to a different database.",
            f"The saved analysis came from {saved_label}, but you are connected "
            f"to {current_label}.\n\nAsking it now will answer using the "
            f"connected database, not the one the question was written for. "
            f"Column and table names may not even exist there.\n\n"
            f"To get a comparable answer, select “{saved.name if saved else ''}” "
            f"in the Data source panel and click Connect first.",
        )
    if reason == SCHEMA_CHANGED:
        return (
            "The data has changed since this analysis was saved.",
            f"You are still connected to {current_label}, but its tables or "
            f"columns are no longer the same as when this analysis ran — the "
            f"database was most likely reloaded.\n\nThe follow-up may fail, or "
            f"return numbers that are not comparable with what you see above.",
        )
    return (
        "This analysis has no record of where it came from.",
        f"It was saved before the app started tracking data sources, so it "
        f"cannot be matched against {current_label}.\n\nIf it came from a "
        f"different database, the answer will not be comparable.",
    )
