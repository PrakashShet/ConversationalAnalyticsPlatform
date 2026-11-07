"""Application entry point."""

import sys
import traceback
from pathlib import Path

from loguru import logger
from PySide6.QtWidgets import QApplication

from app.paths import app_dir, ensure_app_cwd
from app.ui.main_window import MainWindow
from app.ui.theme import apply_app_theme


def _configure_logging() -> None:
    log_dir = app_dir() / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    if sys.stderr is not None:
        logger.add(sys.stderr, level="INFO")
    logger.add(
        str(log_dir / "app.log"),
        rotation="1 MB",
        retention=5,
        level="DEBUG",
        encoding="utf-8",
    )


def main() -> int:
    ensure_app_cwd()
    _configure_logging()
    logger.info("Starting AI-Powered Conversational Analytics Platform")
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("AI-Powered Conversational Analytics Platform")
        apply_app_theme(app)

        window = MainWindow()
        window.show()
        logger.info("Main window shown")
        return app.exec()
    except Exception:
        crash_log = app_dir() / "data" / "logs" / "crash.log"
        crash_log.parent.mkdir(parents=True, exist_ok=True)
        crash_log.write_text(traceback.format_exc(), encoding="utf-8")
        logger.exception("Fatal startup error")
        raise


if __name__ == "__main__":
    sys.exit(main())
