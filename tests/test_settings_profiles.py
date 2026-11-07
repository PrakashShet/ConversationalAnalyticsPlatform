"""Tests for multi-DB profile logic in Settings (no Qt/API needed)."""

from app.config.settings import Profile, Settings


def test_ensure_profiles_creates_default_from_flat_fields():
    s = Settings(db_url="postgresql://h/db", mcp_server_type="postgres")
    s._ensure_profiles()
    assert len(s.profiles) == 1
    assert s.profiles[0].name == "Default"
    assert s.profiles[0].db_url == "postgresql://h/db"
    assert s.profiles[0].mcp_server_type == "postgres"


def test_apply_profile_mirrors_fields_onto_settings():
    s = Settings()
    s.profiles = [
        Profile(name="Local"),
        Profile(
            name="Prod",
            mcp_server_type="postgres",
            mcp_server_command=["uvx", "mcp-server-postgres"],
            db_url="postgresql://prod/db",
            readonly=True,
            max_rows=500,
        ),
    ]
    s.apply_profile(1)
    assert s.active_profile_index == 1
    assert s.mcp_server_type == "postgres"
    assert s.db_url == "postgresql://prod/db"
    assert s.mcp_server_command == ["uvx", "mcp-server-postgres"]
    assert s.max_rows == 500


def test_apply_profile_out_of_range_is_ignored():
    s = Settings()
    s._ensure_profiles()
    s.apply_profile(99)
    assert s.active_profile_index == 0


def test_active_profile_index_clamped_on_load():
    s = Settings(active_profile_index=10)
    s._ensure_profiles()
    assert s.active_profile_index == 0
