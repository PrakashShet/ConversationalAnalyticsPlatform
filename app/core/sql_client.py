"""Direct SQL client (no MCP subprocess).

Connects straight to PostgreSQL/MySQL/SQLite via SQLAlchemy. Exposes the same
interface as ``SyncMcpClient`` (connect / list_tables / describe_table / query /
close) so it is a drop-in replacement, but with no external server process —
which avoids the Windows npx/uvx subprocess problems entirely.
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

_READONLY_PREFIXES = ("select", "with")


def _normalize_url(db_url: str) -> str:
    url = (db_url or "").strip()
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url


class DirectSqlClient:
    """Synchronous SQL client over a SQLAlchemy engine."""

    def __init__(self, readonly: bool = True, max_rows: int = 10000) -> None:
        self._engine: Engine | None = None
        self._readonly = readonly
        self._max_rows = max_rows

    def connect(self, db_url: str) -> None:
        if not db_url or not db_url.strip():
            raise ValueError("Connection URL is empty — set it in Settings.")
        self._engine = create_engine(_normalize_url(db_url), pool_pre_ping=True)
        # Validate the connection eagerly so failures surface at Connect time.
        with self._engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Direct SQL connection established")

    def list_tables(self) -> list[str]:
        rows = self.query(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )
        return [r["table_name"] for r in rows if r.get("table_name")]

    def describe_table(self, name: str) -> dict:
        rows = self.query(
            "SELECT column_name, data_type FROM information_schema.columns "
            f"WHERE table_name = '{name}' ORDER BY ordinal_position"
        )
        return {
            "table": name,
            "columns": [
                {"name": r["column_name"], "type": r["data_type"], "pk": False}
                for r in rows
            ],
        }

    def query(self, sql: str) -> list[dict]:
        if self._engine is None:
            raise RuntimeError("SQL client is not connected")
        statement = sql.strip().rstrip(";")
        if self._readonly and not statement.lower().lstrip("(").startswith(
            _READONLY_PREFIXES
        ):
            raise RuntimeError("Read-only mode: only SELECT queries are allowed.")
        with self._engine.connect() as conn:
            result = conn.execute(text(statement))
            rows = result.mappings().fetchmany(self._max_rows)
            return [dict(r) for r in rows]

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
