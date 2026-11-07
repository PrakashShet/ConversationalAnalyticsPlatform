"""Application settings persistence."""

import json
from pathlib import Path
from typing import Literal

from platformdirs import user_config_dir
from pydantic import BaseModel, Field


DEFAULT_DB_URL = "postgresql://user@localhost:5432/mydb"


def _default_mcp_command() -> list[str]:
    # Reference read-only Postgres MCP server (exposes a `query` tool).
    # The connection string is passed as the final argument.
    return ["npx", "-y", "@modelcontextprotocol/server-postgres", DEFAULT_DB_URL]


class Profile(BaseModel):
    """A named database connection profile."""

    name: str = "Default"
    mcp_server_type: Literal["sqlite", "postgres", "mysql"] = "postgres"
    mcp_server_command: list[str] = Field(default_factory=_default_mcp_command)
    db_url: str = DEFAULT_DB_URL
    ssl_mode: str = "disable"
    readonly: bool = True
    max_rows: int = 10000


class Settings(BaseModel):
    """Non-secret application configuration."""

    gemini_model: str = "gemini-3.5-flash"
    max_tokens: int = 4096
    # Active connection fields (mirror of the selected profile; kept flat so the
    # rest of the app keeps reading settings.mcp_server_command etc unchanged).
    mcp_server_type: Literal["sqlite", "postgres", "mysql"] = "postgres"
    mcp_server_command: list[str] = Field(default_factory=_default_mcp_command)
    db_url: str = DEFAULT_DB_URL
    ssl_mode: str = "disable"
    readonly: bool = True
    max_rows: int = 10000
    theme: str = "paper"
    history_db_path: str = "./data/history.sqlite"
    # Named connection profiles + which one is active.
    profiles: list[Profile] = Field(default_factory=list)
    active_profile_index: int = 0
    # Predictive analytics (forecasting) defaults.
    forecast_default_method: str = "auto"
    forecast_default_horizon: int = 12
    forecast_confidence: float = 0.8
    forecast_enabled_by_default: bool = True

    @classmethod
    def config_path(cls) -> Path:
        config_dir = Path(user_config_dir("conv-analytics"))
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "config.json"

    @classmethod
    def load(cls) -> "Settings":
        path = cls.config_path()
        if not path.exists():
            settings = cls()
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
            settings = cls.model_validate(data)
        settings._ensure_profiles()
        return settings

    def _ensure_profiles(self) -> None:
        """Guarantee at least one profile, derived from the active fields."""
        if not self.profiles:
            self.profiles = [
                Profile(
                    name="Default",
                    mcp_server_type=self.mcp_server_type,
                    mcp_server_command=list(self.mcp_server_command),
                    db_url=self.db_url,
                    ssl_mode=self.ssl_mode,
                    readonly=self.readonly,
                    max_rows=self.max_rows,
                )
            ]
        self.active_profile_index = max(
            0, min(self.active_profile_index, len(self.profiles) - 1)
        )

    def active_profile(self) -> Profile:
        self._ensure_profiles()
        return self.profiles[self.active_profile_index]

    def apply_profile(self, index: int) -> None:
        """Make profile ``index`` active and mirror its fields onto self."""
        if not (0 <= index < len(self.profiles)):
            return
        self.active_profile_index = index
        p = self.profiles[index]
        self.mcp_server_type = p.mcp_server_type
        self.mcp_server_command = list(p.mcp_server_command)
        self.db_url = p.db_url
        self.ssl_mode = p.ssl_mode
        self.readonly = p.readonly
        self.max_rows = p.max_rows

    def save(self) -> None:
        path = self.config_path()
        path.write_text(
            self.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def mcp_command_string(self) -> str:
        return " ".join(self.mcp_server_command)

    def set_mcp_command_string(self, value: str) -> None:
        self.mcp_server_command = value.split() if value.strip() else []
