"""Smoke tests for the Gemini client (live API, gated by env var)."""

import os
from unittest.mock import MagicMock, patch

import pytest

from app.core.gemini_client import (
    GeminiClient,
    SQL_PLAN_SCHEMA,
    _to_contents,
    parse_json_payload,
)


def test_parse_json_payload_handles_fences_and_trailing_commas():
    text = """```json
{
  "sql": "SELECT 1",
  "chart_intent": "bar",
}
```"""
    payload = parse_json_payload(text)
    assert payload["sql"] == "SELECT 1"
    assert payload["chart_intent"] == "bar"


def test_parse_json_payload_uses_first_object_when_extra_text_follows():
    text = (
        '{"summary": "ok", "insights": [], "suggestions": []}'
        '\n\nNote: values are approximate.'
    )
    payload = parse_json_payload(text)
    assert payload["summary"] == "ok"


def test_parse_json_payload_rejects_non_object():
    with pytest.raises(Exception, match="Expected a JSON object"):
        parse_json_payload("[1, 2, 3]")


def test_generate_json_retries_once_on_invalid_payload():
    client = GeminiClient(api_key="test-key", model="gemini-test", max_tokens=256)
    bad = '{"sql": "SELECT * FROM t WHERE name = "foo"", "chart_intent": "bar"}'
    good = (
        '{"sql": "SELECT 1", "chart_intent": "bar", '
        '"rationale": "ok", "needs_clarification": false}'
    )
    responses = [
        MagicMock(text=bad),
        MagicMock(text=good),
    ]

    with patch.object(client, "_generate_json_response", side_effect=[
        (responses[0], 10),
        (responses[1], 12),
    ]) as mock_generate:
        payload, tokens = client.generate_json(
            "system",
            _to_contents(None, "question"),
            schema=SQL_PLAN_SCHEMA,
        )

    assert payload["sql"] == "SELECT 1"
    assert tokens == 22
    assert mock_generate.call_count == 2


@pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set",
)
def test_generate_json_returns_payload():
    client = GeminiClient(
        api_key=os.environ["GEMINI_API_KEY"],
        model="gemini-3.5-flash",
        max_tokens=512,
    )
    system = 'Return ONLY a JSON object of the form {"answer": "<text>"}.'
    payload, tokens = client.generate_json(
        system,
        _to_contents(None, "Say hello in one word."),
        schema={
            "type": "OBJECT",
            "properties": {"answer": {"type": "STRING"}},
            "required": ["answer"],
        },
    )
    assert isinstance(payload, dict)
    assert tokens > 0
