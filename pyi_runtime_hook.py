"""PyInstaller runtime: cwd, Qt WebEngine process path, crash-friendly setup."""

import os
import sys
from pathlib import Path


def _configure_webengine() -> None:
    if not getattr(sys, "frozen", False):
        return
    base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    process = base / "PySide6" / "QtWebEngineProcess.exe"
    if process.is_file():
        os.environ.setdefault("QTWEBENGINEPROCESS_PATH", str(process))
    resources = base / "PySide6" / "resources"
    if resources.is_dir():
        os.environ.setdefault("QTWEBENGINE_RESOURCES_PATH", str(resources))


if getattr(sys, "frozen", False):
    os.chdir(Path(sys.executable).resolve().parent)
    _configure_webengine()
