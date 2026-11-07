"""Google Gemini API wrapper for conversational analytics.

Thin client used by the planner (NL→SQL) and analyst (rows→insight) steps.
It exposes two primitives — ``generate_json`` and ``generate_text`` — plus the
small parsing helpers those steps reuse.
"""

from __future__ import annotations

import json
import re

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from loguru import logger

from app.data.models import ChartSpec, Kpi, KpiSpec


class GeminiError(Exception):
    """Base error for the Gemini client."""


class InvalidApiKeyError(GeminiError):
    """Raised when the API key is invalid."""


class RateLimitError(GeminiError):
    """Raised when rate limited by the API."""


class AnalysisParseError(GeminiError):
    """Raised when the model response cannot be parsed."""


# Delimiter separating a plain-text summary from a JSON payload (kept for the
# split helper / its unit test; the live pipeline uses pure JSON mode).
JSON_MARKER = "===JSON==="

_STR = {"type": "STRING"}
_OBJ = {"type": "OBJECT"}
_ARR_STR = {"type": "ARRAY", "items": _STR}

SQL_PLAN_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "sql": _STR,
        "chart_intent": {
            "type": "STRING",
            "enum": ["kpi", "bar", "line", "donut", "table", "auto"],
        },
        "rationale": _STR,
        "needs_clarification": {"type": "BOOLEAN"},
        "forecast_requested": {"type": "BOOLEAN"},
    },
    "required": [
        "sql", "chart_intent", "rationale", "needs_clarification",
        "forecast_requested",
    ],
}

ANALYST_RESULT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "summary": _STR,
        "kpi_specs": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "label": _STR,
                    "aggregation": _STR,
                    "column": _STR,
                    "format": _STR,
                },
                "required": ["label", "aggregation", "column"],
            },
        },
        "kpis": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "label": _STR,
                    "value": _STR,
                    "delta": _STR,
                    "trend": _STR,
                },
                "required": ["label", "value"],
            },
        },
        "insights": _ARR_STR,
        "charts": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "kind": _STR,
                    "title": _STR,
                    "x": _ARR_STR,
                    "series": {"type": "ARRAY", "items": _OBJ},
                    "options": _OBJ,
                },
                "required": ["kind", "title"],
            },
        },
        "suggestions": _ARR_STR,
    },
    "required": ["summary", "insights", "suggestions"],
}


def split_summary_and_json(text: str) -> tuple[str, str]:
    """Split text into (summary_prose, json_part) around ``===JSON===``.

    If the delimiter is absent, the summary is empty and the whole text is
    treated as the JSON part.
    """
    marker_at = text.find(JSON_MARKER)
    if marker_at < 0:
        return "", text
    return text[:marker_at].strip(), text[marker_at + len(JSON_MARKER):]


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _remove_trailing_commas(text: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", text)


def _extract_first_json_object(text: str) -> str:
    """Return the first balanced ``{...}`` object in *text*."""
    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text[start:]


def parse_json_payload(text: str) -> dict:
    """Parse model JSON with light recovery for common formatting mistakes."""
    candidates = []
    stripped = _strip_json_fences(text)
    candidates.append(stripped)
    candidates.append(_extract_first_json_object(stripped))
    candidates.append(_remove_trailing_commas(stripped))
    candidates.append(_remove_trailing_commas(_extract_first_json_object(stripped)))

    seen: set[str] = set()
    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if not isinstance(payload, dict):
            raise AnalysisParseError("Expected a JSON object")
        return payload

    if last_error is not None:
        raise AnalysisParseError(f"Invalid JSON: {last_error}") from last_error
    raise AnalysisParseError("Empty JSON response")


def _parse_kpi(data: dict) -> Kpi:
    return Kpi(
        label=data.get("label", ""),
        value=str(data.get("value", "")),
        delta=data.get("delta"),
        trend=data.get("trend"),
    )


def _parse_chart(data: dict | None) -> ChartSpec | None:
    if not data:
        return None
    return ChartSpec(
        kind=data.get("kind", "table"),
        title=data.get("title", ""),
        x=data.get("x"),
        series=data.get("series", []),
        options=data.get("options", {}),
    )


def _parse_kpi_specs(data: list | None) -> list[KpiSpec]:
    specs = []
    for item in data or []:
        specs.append(KpiSpec(
            label=item.get("label", ""),
            aggregation=item.get("aggregation", "count"),
            column=item.get("column", ""),
            format=item.get("format", "{:,.0f}"),
        ))
    return specs


def _usage_tokens(response) -> int:
    um = getattr(response, "usage_metadata", None)
    if um is None:
        return 0
    total = getattr(um, "total_token_count", None)
    if total:
        return total
    # Some responses report the parts but not the total — sum them.
    parts = (
        getattr(um, "prompt_token_count", 0) or 0,
        getattr(um, "candidates_token_count", 0) or 0,
        getattr(um, "thoughts_token_count", 0) or 0,
    )
    return sum(parts)


def _to_contents(history: list[dict] | None, question: str) -> list[types.Content]:
    """Convert chat history (role/content dicts) into Gemini Content objects."""
    contents: list[types.Content] = []
    for msg in history or []:
        role = "model" if msg.get("role") == "assistant" else "user"
        contents.append(
            types.Content(role=role, parts=[types.Part(text=str(msg.get("content", "")))])
        )
    contents.append(types.Content(role="user", parts=[types.Part(text=question)]))
    return contents


class GeminiClient:
    """Sync wrapper around the Google Gemini generateContent API."""

    def __init__(self, api_key: str, model: str, max_tokens: int) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._last_tokens = 0

    def generate_text(self, system: str, user_text: str) -> tuple[str, int]:
        """Single-turn text generation. Returns (text, tokens)."""
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=[types.Content(role="user", parts=[types.Part(text=user_text)])],
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=self._max_tokens,
                ),
            )
        except genai_errors.APIError as exc:
            self._raise_api_error(exc)
        tokens = _usage_tokens(response)
        self._last_tokens = tokens
        return response.text or "", tokens

    def generate_json(
        self,
        system: str,
        contents: list[types.Content],
        *,
        schema: dict | None = None,
    ) -> tuple[dict, int]:
        """JSON-mode generation. Returns (payload, tokens)."""
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=self._max_tokens,
            response_mime_type="application/json",
        )
        if schema is not None:
            config.response_schema = schema

        response, tokens = self._generate_json_response(contents, config)
        text = response.text or ""
        try:
            return parse_json_payload(text), tokens
        except AnalysisParseError as first_exc:
            logger.warning("JSON parse failed, retrying once: {}", first_exc)
            repair_contents = [
                *contents,
                types.Content(role="model", parts=[types.Part(text=text)]),
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            text=(
                                "That response was not valid JSON. Reply with ONLY one "
                                "corrected JSON object matching the requested schema. "
                                "Escape double quotes inside string values. "
                                "No markdown fences or commentary."
                            )
                        )
                    ],
                ),
            ]
            response2, retry_tokens = self._generate_json_response(
                repair_contents, config
            )
            tokens += retry_tokens
            self._last_tokens = tokens
            try:
                return parse_json_payload(response2.text or ""), tokens
            except AnalysisParseError:
                logger.debug("Invalid JSON payload (first attempt): {}", text[:500])
                raise first_exc from None

    def _generate_json_response(
        self,
        contents: list[types.Content],
        config: types.GenerateContentConfig,
    ) -> tuple[object, int]:
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )
        except genai_errors.APIError as exc:
            self._raise_api_error(exc)
        tokens = _usage_tokens(response)
        self._last_tokens = tokens
        return response, tokens

    @staticmethod
    def _raise_api_error(exc: genai_errors.APIError) -> None:
        code = getattr(exc, "code", None)
        if code in (401, 403):
            raise InvalidApiKeyError(str(exc)) from exc
        if code == 429:
            raise RateLimitError(str(exc)) from exc
        raise GeminiError(str(exc)) from exc
