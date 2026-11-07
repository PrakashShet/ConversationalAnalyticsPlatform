"""Data-source identity: fingerprinting, redaction, and mismatch detection.

This is the gate that stops a saved analysis from being followed up against a
different database, so the comparison rules are worth pinning down precisely.
No Qt here — the dialog wording is produced by ``data_source.explain`` so it can
be asserted without a running application.
"""

from __future__ import annotations

from app.core import data_source
from app.data.models import SourceFingerprint

SALES = [
    {"table": "orders", "columns": [{"name": "id"}, {"name": "order_date"}]},
    {"table": "stores", "columns": [{"name": "id"}, {"name": "type"}]},
]


def _fp(**kw) -> SourceFingerprint:
    base = {
        "name": "Default",
        "kind": "postgres",
        "db_url": "postgresql://joe@localhost:5432/sales",
        "table_defs": SALES,
    }
    base.update(kw)
    return data_source.fingerprint(**base)


# --- credential redaction ---------------------------------------------------

def test_password_is_stripped_from_target():
    fp = _fp(db_url="postgresql://joe:hunter2@db.internal:5432/sales")

    assert "hunter2" not in fp.target
    assert fp.target == "postgresql://joe@db.internal:5432/sales"


def test_redaction_leaves_passwordless_urls_alone():
    url = "postgresql://joe@localhost:5432/sales"

    assert data_source.redact_url(url) == url


def test_redaction_handles_empty_and_odd_input():
    assert data_source.redact_url("") == ""
    assert data_source.redact_url("sqlite:///data/sample.db") == (
        "sqlite:///data/sample.db"
    )


# --- schema digest ----------------------------------------------------------

def test_digest_is_order_independent():
    reordered = list(reversed(SALES))

    assert data_source.schema_digest(SALES) == data_source.schema_digest(reordered)


def test_digest_ignores_column_types():
    widened = [
        {"table": "orders", "columns": [{"name": "id", "type": "bigint"},
                                        {"name": "order_date", "type": "date"}]},
        {"table": "stores", "columns": [{"name": "id"}, {"name": "type"}]},
    ]

    assert data_source.schema_digest(widened)[0] == data_source.schema_digest(SALES)[0]


def test_digest_changes_when_a_column_is_renamed():
    renamed = [
        {"table": "orders", "columns": [{"name": "id"}, {"name": "ordered_on"}]},
        {"table": "stores", "columns": [{"name": "id"}, {"name": "type"}]},
    ]

    assert data_source.schema_digest(renamed)[0] != data_source.schema_digest(SALES)[0]


def test_digest_reports_table_count():
    digest, count = data_source.schema_digest(SALES)

    assert count == 2
    assert len(digest) == 12


def test_empty_schema_digests_to_nothing():
    assert data_source.schema_digest([]) == ("", 0)


# --- comparison -------------------------------------------------------------

def test_identical_sources_match():
    assert data_source.compare(_fp(), _fp()) is None


def test_different_database_is_flagged():
    other = _fp(db_url="postgresql://joe@localhost:5432/warehouse")

    assert data_source.compare(_fp(), other) == data_source.DIFFERENT_TARGET


def test_same_url_reloaded_with_new_data_is_flagged():
    """load_data.bat drops and recreates the schema — same URL, new tables."""
    reloaded = _fp(
        table_defs=[{"table": "walmart_sales", "columns": [{"name": "weekly_sales"}]}]
    )

    assert data_source.compare(_fp(), reloaded) == data_source.SCHEMA_CHANGED


def test_switching_engine_is_flagged_even_on_the_same_url():
    assert data_source.compare(_fp(), _fp(kind="mysql")) == (
        data_source.DIFFERENT_TARGET
    )


def test_missing_fingerprint_is_never_silently_trusted():
    assert data_source.compare(None, _fp()) == data_source.UNKNOWN_SOURCE
    assert data_source.compare(_fp(), None) == data_source.UNKNOWN_SOURCE
    assert data_source.compare(None, None) == data_source.UNKNOWN_SOURCE


def test_profile_rename_alone_does_not_trigger_a_warning():
    """The name is a label; what matters is where the data is and what's in it."""
    assert data_source.compare(_fp(), _fp(name="Production")) is None


def test_unknown_schema_hash_does_not_false_positive():
    """A fingerprint from a source that reported no tables must not alarm."""
    blank = _fp(table_defs=[])

    assert data_source.compare(blank, _fp()) is None


# --- dialog wording ---------------------------------------------------------

def test_describe_is_readable_and_credential_free():
    label = data_source.describe(_fp(db_url="postgresql://joe:pw@host:5432/sales"))

    assert "pw" not in label
    assert "Default" in label
    assert "2 tables" in label


def test_describe_handles_none():
    assert data_source.describe(None) == "an unknown data source"


def test_explain_names_both_sources_and_says_how_to_recover():
    saved = _fp(name="Sales DB")
    current = _fp(name="Warehouse", db_url="postgresql://joe@localhost:5432/wh")

    headline, detail = data_source.explain(
        data_source.DIFFERENT_TARGET, saved, current
    )

    assert "different database" in headline.lower()
    assert "sales" in detail.lower()
    assert "wh" in detail.lower()
    assert "Sales DB" in detail          # names the profile to switch back to
    assert "Connect" in detail           # tells them how


def test_explain_covers_a_reload_of_the_same_database():
    headline, detail = data_source.explain(
        data_source.SCHEMA_CHANGED, _fp(), _fp(table_defs=[])
    )

    assert "changed" in headline.lower()
    assert "reload" in detail.lower()


def test_explain_covers_an_unfingerprinted_analysis():
    headline, detail = data_source.explain(
        data_source.UNKNOWN_SOURCE, None, _fp()
    )

    assert "no record" in headline.lower()
    assert detail
