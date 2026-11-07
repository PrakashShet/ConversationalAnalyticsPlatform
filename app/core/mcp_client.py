"""MCP stdio client wrapper for SQL database access.

Each high-level operation opens its own short-lived MCP session (spawns the
server, runs the call, tears it down). This keeps every async context's
enter/exit inside a single task / event loop, which avoids both the
closed-loop-reuse crash and anyio "cancel scope in different task" errors that
occur when a session is cached across separate ``asyncio.run`` calls.
"""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from typing import Any

from loguru import logger
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def run_sync(coro):
    """Run a coroutine to completion on a fresh event loop.

    On Windows the Proactor loop is required for subprocess (stdio) transport.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    return asyncio.run(coro)


# --- content parsing helpers (pure) -----------------------------------------

def _text_content(content) -> str:
    parts = []
    for block in content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts)


def _first_value(row):
    if isinstance(row, dict):
        return next(iter(row.values()), None)
    return row


def _parse_table_names(content) -> list[str]:
    text = _text_content(content)
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [str(x) for x in data]
        if isinstance(data, dict) and "tables" in data:
            return [str(x) for x in data["tables"]]
    except json.JSONDecodeError:
        pass
    return [line.strip() for line in text.splitlines() if line.strip()]


def _parse_rows(content) -> list[dict]:
    text = _text_content(content)
    if not text:
        return []
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "rows" in data:
            return data["rows"]
    except json.JSONDecodeError:
        pass
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


class SyncMcpClient:
    """Synchronous facade that runs each MCP call in its own session."""

    def __init__(self) -> None:
        self._command: list[str] | None = None

    # -- session lifecycle ---------------------------------------------------

    @asynccontextmanager
    async def _session(self):
        if not self._command:
            raise RuntimeError("MCP client is not connected")
        params = StdioServerParameters(
            command=self._command[0], args=self._command[1:], env=None
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    async def _tool_names(self, session) -> set[str]:
        result = await session.list_tools()
        return {t.name for t in result.tools}

    # -- async operations ----------------------------------------------------

    async def _probe(self) -> None:
        async with self._session() as session:
            await self._tool_names(session)
        logger.info("MCP session OK for command: {}", " ".join(self._command))

    async def _list_tables(self) -> list[str]:
        async with self._session() as session:
            names = await self._tool_names(session)
            if "list_tables" in names:
                result = await session.call_tool("list_tables", {})
                return _parse_table_names(result.content)
            if "query" in names or "read_query" in names:
                candidates = [
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' ORDER BY table_name",
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name",
                ]
                for sql in candidates:
                    try:
                        rows = await self._run_query(session, names, sql)
                    except Exception:  # noqa: BLE001 - dialect mismatch
                        continue
                    found = [v for v in (_first_value(r) for r in rows) if v]
                    if found:
                        return found
                return []
            raise RuntimeError("No supported table listing tool on MCP server")

    async def _describe_table(self, name: str) -> dict:
        async with self._session() as session:
            names = await self._tool_names(session)
            if "describe_table" in names:
                result = await session.call_tool(
                    "describe_table", {"table_name": name}
                )
                text = _text_content(result.content)
                return json.loads(text) if text.startswith("{") else {"raw": text}

            info_sql = (
                "SELECT column_name, data_type FROM information_schema.columns "
                f"WHERE table_name = '{name}' ORDER BY ordinal_position"
            )
            try:
                rows = await self._run_query(session, names, info_sql)
                if rows:
                    return {
                        "table": name,
                        "columns": [
                            {
                                "name": r.get("column_name", ""),
                                "type": r.get("data_type", "TEXT"),
                                "pk": False,
                            }
                            for r in rows
                        ],
                    }
            except Exception:  # noqa: BLE001 - not Postgres/MySQL
                pass

            rows = await self._run_query(
                session, names, f"PRAGMA table_info({name})"
            )
            return {
                "table": name,
                "columns": [
                    {
                        "name": r.get("name", r.get("column_name", "")),
                        "type": r.get("type", "TEXT"),
                        "pk": bool(r.get("pk", 0)),
                    }
                    for r in rows
                ],
            }

    async def _query(self, sql: str) -> list[dict]:
        async with self._session() as session:
            names = await self._tool_names(session)
            return await self._run_query(session, names, sql)

    async def _run_query(self, session, names: set[str], sql: str) -> list[dict]:
        if "query" in names:
            result = await session.call_tool("query", {"sql": sql})
            return _parse_rows(result.content)
        if "read_query" in names:
            result = await session.call_tool("read_query", {"query": sql})
            return _parse_rows(result.content)
        raise RuntimeError("No supported query tool on MCP server")

    # -- sync API ------------------------------------------------------------

    def connect(self, command: list[str]) -> None:
        if not command:
            raise ValueError("MCP server command is empty")
        self._command = command
        run_sync(self._probe())

    def list_tables(self) -> list[str]:
        return run_sync(self._list_tables())

    def describe_table(self, name: str) -> dict:
        return run_sync(self._describe_table(name))

    def query(self, sql: str) -> list[dict]:
        return run_sync(self._query(sql))

    def close(self) -> None:
        # Sessions are short-lived, so there is nothing persistent to close.
        self._command = None
