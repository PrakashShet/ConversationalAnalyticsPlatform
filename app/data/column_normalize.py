"""Normalize CSV / DataFrame column names for SQL-safe identifiers."""

from __future__ import annotations

import re

import pandas as pd


def normalize_column_name(name: str) -> str:
    """Lowercase, strip, replace non-alphanumeric runs with '_'."""
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        s = "col"
    if s[0].isdigit():
        s = f"col_{s}"
    return s


def normalize_columns(columns: list[str]) -> tuple[list[str], dict[str, str]]:
    """Return new column names and original→normalized mapping (unique)."""
    mapping: dict[str, str] = {}
    used: set[str] = set()
    result: list[str] = []
    for col in columns:
        base = normalize_column_name(col)
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        used.add(candidate)
        mapping[col] = candidate
        result.append(candidate)
    return result, mapping


def apply_column_mapping(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """Rename DataFrame columns using normalize_columns."""
    new_names, mapping = normalize_columns(list(df.columns))
    out = df.copy()
    out.columns = new_names
    return out, mapping
