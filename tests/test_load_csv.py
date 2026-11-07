"""Tests for CSV column normalization and loader naming."""

from pathlib import Path

import pandas as pd

from app.data.column_normalize import (
    apply_column_mapping,
    normalize_column_name,
    normalize_columns,
)
from app.data.load_csv import _resolve_db_url, _sanitize, _table_name


def test_normalize_column_name():
    assert normalize_column_name("Order Date") == "order_date"
    assert normalize_column_name("Sales") == "sales"
    assert normalize_column_name("Category") == "category"
    assert normalize_column_name("  Net-Amount  ") == "net_amount"
    assert normalize_column_name("Row ID") == "row_id"


def test_normalize_columns_uniqueness():
    names, mapping = normalize_columns(["Sales", "sales", "SALES"])
    assert len(set(names)) == 3
    assert mapping["Sales"] == "sales"
    assert mapping["sales"] == "sales_2"
    assert mapping["SALES"] == "sales_3"


def test_apply_column_mapping_superstore_headers():
    df = pd.DataFrame(columns=["Order Date", "Sales", "Category", "Sub-Category"])
    out, mapping = apply_column_mapping(df)
    assert list(out.columns) == ["order_date", "sales", "category", "sub_category"]
    assert mapping["Order Date"] == "order_date"
    assert mapping["Sub-Category"] == "sub_category"


def test_sanitize_basic():
    assert _sanitize("Orders 2026.csv") == "orders_2026_csv"
    assert _sanitize("  Net-Amount  ") == "net_amount"
    assert _sanitize("123abc") == "t_123abc"
    assert _sanitize("") == "table"


def test_table_name_top_level():
    root = Path("/data/raw")
    assert _table_name(root / "orders.csv", root) == "orders"


def test_table_name_with_subfolder_prefix():
    root = Path("/data/raw")
    assert _table_name(root / "sales" / "orders.csv", root) == "sales_orders"


def test_resolve_db_url_uses_psycopg2_driver(monkeypatch):
    monkeypatch.setenv("DB_URL", "postgresql://user@localhost:5432/mydb")
    assert _resolve_db_url().startswith("postgresql+psycopg2://")
