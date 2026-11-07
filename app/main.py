"""Application entry point."""

import sys
import traceback
from pathlib import Path

from loguru import logger
from PySide6.QtWidgets import QApplication

from app.log_config import configure_logging
from app.paths import app_dir, ensure_app_cwd
from app.ui.main_window import MainWindow
from app.ui.theme import apply_app_theme


def _configure_logging() -> None:
    configure_logging(app_dir() / "data" / "logs")


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
