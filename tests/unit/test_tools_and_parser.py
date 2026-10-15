import pytest

from app.core.enums import ToolRisk
from app.core.exceptions import ToolPermissionError
from app.providers.json_parser import extract_json_object, parse_model
from app.schemas.agent import IntentResult
from app.tools.base import Tool
from app.tools.permissions import assert_permitted


class _Dummy(Tool):
    name = "cancel_order"
    description = "x"
    risk = ToolRisk.DESTRUCTIVE
    input_model = IntentResult  # unused


def test_destructive_requires_confirmation() -> None:
    with pytest.raises(ToolPermissionError):
        assert_permitted(_Dummy(), confirmed=False)
    assert_permitted(_Dummy(), confirmed=True)


def test_json_parser_strips_fence() -> None:
    text = """当然可以：
```json
{"label":"refund","confidence":0.9,"rationale":"x","prompt_version":"intent_v2"}
```
"""
    parsed = parse_model(text, IntentResult)
    assert parsed.label.value == "refund"


def test_json_parser_rejects_garbage() -> None:
    with pytest.raises(Exception):
        extract_json_object("sorry I cannot")
