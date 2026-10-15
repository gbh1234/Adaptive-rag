"""LLM structured-output repair.

Models often wrap JSON in markdown fences or prepend prose.
Never trust raw LLM text — extract, validate, optionally retry.
"""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.exceptions import LLMOutputError

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced = _FENCE.search(stripped)
    if fenced:
        stripped = fenced.group(1).strip()
    try:
        payload = json.loads(stripped)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMOutputError("LLM output did not contain a JSON object")
    try:
        payload = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMOutputError("LLM output JSON is malformed") from exc
    if not isinstance(payload, dict):
        raise LLMOutputError("LLM JSON root is not an object")
    return payload


def parse_model(text: str, model_type: type[T]) -> T:
    payload = extract_json_object(text)
    try:
        return model_type.model_validate(payload)
    except ValidationError as exc:
        raise LLMOutputError(f"LLM JSON failed schema validation: {exc}") from exc
