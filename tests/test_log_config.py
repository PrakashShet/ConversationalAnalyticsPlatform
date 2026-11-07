"""Log sinks must never write local variable values — they can hold API keys."""

from __future__ import annotations

import sys

import pytest
from loguru import logger

from app.log_config import configure_logging

# Built at runtime so this file never contains a key-shaped literal (which the
# pre-commit hook and GitHub push protection would rightly reject).
FAKE_KEY = "AIza" + "Q" * 35


@pytest.fixture
def restore_loguru():
    yield
    logger.remove()
    logger.add(sys.stderr)  # loguru's default sink


def _call_gemini(api_key: str) -> None:
    headers = {"x-goog-api-key": api_key}  # noqa: F841 - in scope on purpose
    raise RuntimeError("404 model not found")


def test_exception_log_keeps_stack_but_not_secret_values(tmp_path, capsys, restore_loguru):
    log_file = configure_logging(tmp_path)
    try:
        _call_gemini(FAKE_KEY)
    except RuntimeError:
        logger.exception("Analysis failed")
    logger.remove()  # flush and release the file before reading it

    text = log_file.read_text(encoding="utf-8")
    assert "Analysis failed" in text
    assert "_call_gemini" in text  # the traceback itself is still there
    assert "404 model not found" in text
    assert FAKE_KEY not in text
    assert FAKE_KEY not in capsys.readouterr().err


def test_log_file_lives_in_the_given_directory(tmp_path, restore_loguru):
    log_file = configure_logging(tmp_path / "logs")
    assert log_file == tmp_path / "logs" / "app.log"
    logger.info("hello")
    logger.remove()
    assert "hello" in log_file.read_text(encoding="utf-8")
