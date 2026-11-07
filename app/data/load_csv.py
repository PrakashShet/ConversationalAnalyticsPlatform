"""Load CSV files from a directory into PostgreSQL.

Usage:
    python -m app.data.load_csv <datapath> [--keep]

Behaviour:
    * Reads the connection URL from DB_URL in the environment / .env
      (default: postgresql://user@localhost:5432/mydb).
    * Unless --keep is given, WIPES the target database (drops & recreates the
      public schema) before loading.
    * Finds every *.csv under <datapath> recursively. Each file becomes a table
      named after the file. When a sub-folder is involved, the folder name is
      prefixed to avoid collisions (e.g. data/raw/sales/orders.csv -> sales_orders).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from app.data.column_normalize import apply_column_mapping
import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

DEFAULT_URL = "postgresql://user@localhost:5432/mydb"


def _resolve_db_url() -> str:
    import os

    load_dotenv()
    url = os.environ.get("DB_URL", DEFAULT_URL).strip() or DEFAULT_URL
    # Normalise to the psycopg2 driver SQLAlchemy expects.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url


def _sanitize(name: str) -> str:
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip().lower()).strip("_")
    if not name:
        name = "table"
    if name[0].isdigit():
        name = f"t_{name}"
    return name


def _safe_chunksize(n_cols: int, max_params: int = 60000, cap: int = 5000) -> int:
    """Rows per INSERT batch for a chunked, memory-safe load.

    With ``method='multi'`` pandas emits one multi-row INSERT per chunk. This
    keeps the bound-parameter count (rows × columns) safely under PostgreSQL's
    65535 limit while capping memory and SQL size per statement — which avoids
    the MemoryError that a single all-rows INSERT triggers on large CSVs.
    """
    n_cols = max(int(n_cols), 1)
    return max(1, min(cap, max_params // n_cols))


def _table_name(csv_path: Path, root: Path) -> str:
    rel = csv_path.relative_to(root)
    parts = list(rel.parts)
    stem = Path(parts[-1]).stem
    # Prefix the immediate sub-folder (if any) to disambiguate.
    if len(parts) >= 2:
        return _sanitize(f"{parts[-2]}_{stem}")
    return _sanitize(stem)


def _read_csv_any_encoding(csv_path: Path) -> "pd.DataFrame":
    """Read a CSV trying common encodings (handles non-UTF-8 retail exports)."""
    last_err: Exception | None = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return pd.read_csv(csv_path, encoding=enc)
        except (UnicodeDecodeError, UnicodeError) as exc:
            last_err = exc
            continue
    # Final fallback: replace undecodable bytes so the load still succeeds.
    logger.warning("Falling back to lenient decoding for {}", csv_path.name)
    return pd.read_csv(csv_path, encoding="latin-1", encoding_errors="replace")


def clean_database(engine) -> None:
    """Drop and recreate the public schema (removes all tables)."""
    logger.warning("Cleaning database — dropping public schema")
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


def load_directory(datapath: str | Path, clean: bool = True) -> tuple[dict[str, int], dict[str, dict[str, str]]]:
    root = Path(datapath).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Path not found: {root}")

    csv_files = sorted(root.rglob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No .csv files found under {root}")

    engine = create_engine(_resolve_db_url())
    if clean:
        clean_database(engine)

    loaded: dict[str, int] = {}
    mappings: dict[str, dict[str, str]] = {}
    for csv in csv_files:
        table = _table_name(csv, root)
        logger.info("Loading {} -> table '{}'", csv.name, table)
        df = _read_csv_any_encoding(csv)
        df, col_map = apply_column_mapping(df)
        if col_map:
            mappings[table] = col_map
        chunk = _safe_chunksize(len(df.columns))
        logger.info(
            "  {:,} rows × {} cols (inserting in batches of {})",
            len(df), len(df.columns), chunk,
        )
        df.to_sql(
            table,
            engine,
            if_exists="replace",
            index=False,
            chunksize=chunk,
            method="multi",
        )
        loaded[table] = len(df)

    engine.dispose()
    return loaded, mappings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load CSVs into PostgreSQL.")
    parser.add_argument("datapath", help="Folder containing CSV files (recursive).")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Do not wipe the database before loading.",
    )
    args = parser.parse_args(argv)

    try:
        loaded, mappings = load_directory(args.datapath, clean=not args.keep)
    except Exception as exc:  # noqa: BLE001 - surface a clean message to the CLI
        logger.error("Load failed: {}", exc)
        return 1

    total_rows = sum(loaded.values())
    print("\nLoaded {} table(s), {} rows total:".format(len(loaded), total_rows))
    for table, rows in loaded.items():
        print(f"  {table:<30} {rows:>10,} rows")
    if mappings:
        print("\nColumn mappings (original → normalized):")
        for table, col_map in mappings.items():
            print(f"  [{table}]")
            for orig, norm in col_map.items():
                if orig != norm:
                    print(f"    {orig!r} → {norm}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
