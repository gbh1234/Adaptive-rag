"""Structured JSON logging setup."""

from __future__ import annotations

import logging
from contextvars import ContextVar

try:
    from pythonjsonlogger.jsonlogger import JsonFormatter
except ImportError:  # python-json-logger >= 3
    from pythonjsonlogger.json import JsonFormatter

from app.config.settings import Settings
from app.core.security import mask_pii

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_var.get()
        record.request_id = request_id_var.get()
        if isinstance(getattr(record, "msg", None), str):
            record.msg = mask_pii(record.msg)
        return True


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler()
    formatter = JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s %(trace_id)s %(request_id)s"
    )
    handler.setFormatter(formatter)
    handler.addFilter(ContextFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
