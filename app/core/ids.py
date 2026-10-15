"""Identifier and trace-id generation."""

import uuid


def new_id(prefix: str = "") -> str:
    value = uuid.uuid4().hex
    return f"{prefix}{value}" if prefix else value


def new_trace_id() -> str:
    return new_id("tr_")


def new_request_id() -> str:
    return new_id("req_")
