"""Tool base classes and execution context."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from app.core.enums import ToolRisk
from app.core.exceptions import InvalidRequestError, ToolExecutionError
from app.schemas.agent import ToolResult


class ToolContext(BaseModel):
    """Per-call context passed to every tool.

    Attributes:
        user_id: Owner of the conversation; scopes data access.
        session_id: Conversation session the call belongs to.
        trace_id: Correlation id shared across the request.
        confirmed_action_id: Set once a human has confirmed a write action.
        idempotency_key: Deduplication key so a retried write runs once.
    """

    user_id: str
    session_id: str
    trace_id: str
    confirmed_action_id: str | None = None
    idempotency_key: str | None = None


class BaseTool(Protocol):
    """Structural contract every tool must satisfy."""

    name: str
    description: str
    risk: ToolRisk
    input_model: type[BaseModel]

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        """Run the tool against raw arguments and return a structured result."""
        ...


class Tool:
    """Base class for concrete tools.

    Subclasses declare ``name``, ``description``, ``risk`` and ``input_model``,
    then implement :meth:`execute`. The base class validates arguments and wraps
    unexpected failures into :class:`ToolExecutionError` so the graph can degrade
    gracefully instead of crashing the turn.
    """

    name: str
    description: str
    risk: ToolRisk = ToolRisk.READ
    input_model: type[BaseModel]

    def parse(self, arguments: dict[str, Any]) -> BaseModel:
        """Validate raw arguments against ``input_model``.

        Raises:
            InvalidRequestError: If the arguments do not match the schema.
        """
        try:
            return self.input_model.model_validate(arguments)
        except ValidationError as exc:
            raise InvalidRequestError(f"invalid arguments for {self.name}: {exc}") from exc

    async def run(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        """Validate, then execute, mapping unexpected errors to a tool failure."""
        parsed = self.parse(arguments)
        try:
            return await self.execute(parsed, context)
        except InvalidRequestError:
            raise
        except Exception as exc:
            raise ToolExecutionError(f"{self.name} failed") from exc

    async def execute(self, parsed: BaseModel, context: ToolContext) -> ToolResult:
        """Perform the tool's work. Subclasses must override this."""
        raise NotImplementedError

    def openai_schema(self) -> dict[str, Any]:
        """Return the OpenAI function-calling schema for this tool."""
        schema = self.input_model.model_json_schema()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }
