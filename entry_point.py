"""PyInstaller entry point — with startup diagnostics.

A windowed (``console=False``) build has no stdout and no stderr. If anything
fails before the Qt event loop starts, the process disappears with no message
and no log, which is indistinguishable from "the exe does nothing". So this
module writes a boot log *before* it imports the application, and captures
``BaseException`` rather than ``Exception`` so a failure during import is
recorded too.

Run the built exe with ``--selftest`` to import everything, write a report to
``data/logs/selftest.log`` and exit without showing a window. That turns a
silent failure into a readable one; ``run_build.bat`` does this automatically
after every build.
"""

import faulthandler
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


def _log_dir() -> Path:
    base = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )
    return base / "data" / "logs"


def _write(name: str, text: str) -> Path | None:
    """Best-effort write into the log directory; never raises."""
    try:
        directory = _log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_text(text, encoding="utf-8")
        return path
    except OSError:
        return None


def _environment() -> str:
    return "\n".join([
        f"time         {datetime.now().isoformat(timespec='seconds')}",
        f"frozen       {getattr(sys, 'frozen', False)}",
        f"executable   {sys.executable}",
        f"_MEIPASS     {getattr(sys, '_MEIPASS', '(not frozen)')}",
        f"cwd          {os.getcwd()}",
        f"python       {sys.version.split()[0]}",
        f"argv         {sys.argv}",
    ])


def _selftest() -> int:
    """Import every heavy dependency and report what worked. No UI."""
    lines = [_environment(), ""]
    failures = 0

    checks = [
        ("PySide6.QtWidgets", "Qt widgets"),
        ("PySide6.QtWebEngineWidgets", "Qt WebEngine (interactive charts)"),
        ("PySide6.QtWebChannel", "Qt WebChannel (chart drill-down)"),
        ("google.genai", "Gemini client"),
        ("sqlalchemy", "SQL client"),
        ("psycopg2", "PostgreSQL driver"),
        ("keyring", "OS keychain"),
        ("pandas", "pandas"),
        ("numpy", "numpy"),
        ("loguru", "logging"),
        ("statsmodels.tsa.holtwinters", "statsmodels (optional)"),
        ("app.main", "application entry"),
        ("app.core.orchestrator", "pipeline"),
        ("app.core.forecasting", "forecasting engine"),
        ("app.ui.main_window", "main window"),
    ]
    for module, label in checks:
        optional = "optional" in label
        try:
            __import__(module)
            lines.append(f"  OK    {label:38s} ({module})")
        except BaseException as exc:  # noqa: BLE001 - report, do not abort
            lines.append(
                f"  {'WARN ' if optional else 'FAIL '} {label:38s} ({module})"
                f"\n          {type(exc).__name__}: {exc}"
            )
            if not optional:
                failures += 1

    for name, parts in [
        ("stylesheet", ("ui", "styles.qss")),
        ("chart shell", ("ui", "charts", "chart_shell.html")),
        ("planner prompt", ("resources", "prompts", "sql_planner.md")),
        ("analyst prompt", ("resources", "prompts", "analyst.md")),
        ("echarts bundle", ("resources", "vendor", "echarts.min.js")),
    ]:
        try:
            from app.paths import resource_path

            target = resource_path(*parts)
            ok = target.is_file()
            lines.append(f"  {'OK   ' if ok else 'FAIL '} asset {name:30s} {target}")
            failures += 0 if ok else 1
        except BaseException as exc:  # noqa: BLE001
            lines.append(f"  FAIL  asset {name:30s} {type(exc).__name__}: {exc}")
            failures += 1

    lines.append("")
    lines.append("RESULT: " + ("PASS" if failures == 0 else f"{failures} FAILURE(S)"))
    report = "\n".join(lines)
    _write("selftest.log", report)
    if sys.stdout is not None:
        print(report)
    return 0 if failures == 0 else 1


def main() -> int:
    # A crash inside Qt or Chromium kills the process with no Python traceback;
    # faulthandler at least leaves the C-level stack behind.
    try:
        directory = _log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        faulthandler.enable(open(directory / "faulthandler.log", "w", buffering=1))
    except OSError:
        pass

    _write("boot.log", _environment() + "\n\nreached entry_point.main()\n")

    if "--selftest" in sys.argv:
        return _selftest()

    from app.main import main as run_app

    return run_app()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 - last resort; must not vanish silently
        _write("crash.log", _environment() + "\n\n" + traceback.format_exc())
        raise
