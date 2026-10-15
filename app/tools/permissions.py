"""Tool permission checks by risk level."""

from app.core.enums import ToolRisk
from app.core.exceptions import ToolPermissionError
from app.tools.base import Tool

WRITE_RISKS = {ToolRisk.WRITE, ToolRisk.DESTRUCTIVE}


def assert_permitted(tool: Tool, *, confirmed: bool) -> None:
    if tool.risk in WRITE_RISKS and not confirmed:
        raise ToolPermissionError(
            f"{tool.name} is {tool.risk.value} and requires explicit user confirmation"
        )
