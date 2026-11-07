"""Tests for the streaming summary/JSON split helper (no API needed)."""

import json

from app.core.gemini_client import JSON_MARKER, split_summary_and_json


def test_split_separates_summary_and_json():
    text = (
        "Sales rose 12% in Q3, led by Mysore.\n"
        f"{JSON_MARKER}\n"
        '{"sql": "SELECT 1", "summary": "Sales rose 12%."}'
    )
    summary, json_part = split_summary_and_json(text)
    assert summary == "Sales rose 12% in Q3, led by Mysore."
    payload = json.loads(json_part.strip())
    assert payload["sql"] == "SELECT 1"


def test_split_without_marker_treats_all_as_json():
    text = '{"sql": "SELECT 1", "summary": "x"}'
    summary, json_part = split_summary_and_json(text)
    assert summary == ""
    assert json.loads(json_part)["summary"] == "x"


def test_split_handles_marker_at_start():
    text = f"{JSON_MARKER}\n{{\"summary\": \"x\"}}"
    summary, json_part = split_summary_and_json(text)
    assert summary == ""
    assert json.loads(json_part.strip())["summary"] == "x"
