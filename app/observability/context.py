"""Request-scoped context variables for logs and traces."""

from contextvars import Token

from app.observability.logging import request_id_var, trace_id_var


def bind_request_context(*, trace_id: str, request_id: str) -> tuple[Token, Token]:
    return trace_id_var.set(trace_id), request_id_var.set(request_id)


def reset_request_context(tokens: tuple[Token, Token]) -> None:
    trace_id_var.reset(tokens[0])
    request_id_var.reset(tokens[1])
