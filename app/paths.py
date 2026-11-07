"""Resolve paths for development and PyInstaller frozen builds."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_dir() -> Path:
    """Directory where the app reads/writes data (history, logs, context)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundle_dir() -> Path:
    """Directory containing bundled assets (QSS, prompts, vendor JS)."""
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    """Path to a file under the app package in dev or in _MEIPASS when frozen."""
    return bundle_dir().joinpath("app", *parts)


def ensure_app_cwd() -> None:
    """Run with cwd beside the executable so relative data/ paths work."""
    if is_frozen():
        import os

        os.chdir(app_dir())
