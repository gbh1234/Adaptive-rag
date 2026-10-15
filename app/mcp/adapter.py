"""Unify local tools and MCP tools as OpenAI-style function calling."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.core.enums import ToolRisk
from app.mcp.runtime import call_mcp_tool
from app.schemas.agent import ToolResult
from app.tools.base import Tool, ToolContext
from app.tools.registry import ToolRegistry


class MCPToolProxy(Tool):
    """Adapter: an MCP tool is a Tool. Planner/executor do not special-case transport."""

    def __init__(
        self,
        name: str,
        description: str,
        *,
        transport: str = "local",
        endpoint: str = "",
        risk: ToolRisk = ToolRisk.EXTERNAL,
    ) -> None:
        self.name = name
        self.description = description
        self.risk = risk
        self.input_model = _GenericArgs
        self._transport = transport
        self._endpoint = endpoint

    async def execute(self, parsed: BaseModel, context: ToolContext) -> ToolResult:
        payload = parsed.payload if isinstance(parsed, _GenericArgs) else {}
        output = await call_mcp_tool(
            name=self.name,
            arguments=payload,
            transport=self._transport,
            endpoint=self._endpoint,
        )
        return ToolResult(name=self.name, success=True, output=output, risk=self.risk)


class _GenericArgs(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


def merge_mcp_tools(registry: ToolRegistry, mcp_specs: list[dict[str, str]]) -> ToolRegistry:
    existing = set(registry.names())
    for spec in mcp_specs:
        name = spec["name"]
        if name in existing:
            continue
        registry.register(
            MCPToolProxy(
                name=name,
                description=spec.get("description", ""),
                transport=spec.get("transport", "local"),
                endpoint=spec.get("endpoint", ""),
            )
        )
        existing.add(name)
    return registry
