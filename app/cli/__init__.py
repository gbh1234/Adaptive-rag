"""Interactive terminal chat client for the Adaptive-RAG API.

The CLI is split into three focused modules:

- :mod:`app.cli.render`  — pure formatting and stdout writers
- :mod:`app.cli.client`  — the stateful REPL client (HTTP or in-process)
- :mod:`app.cli.commands` — argument parsing and the ``main`` entry point

Run it with ``python -m app.cli`` or the ``adaptive-rag-cli`` script.
"""

from app.cli.client import ChatCli, ChatFailed
from app.cli.commands import build_parser, main
from app.cli.render import format_meta, parse_sse_data_line

__all__ = [
    "ChatCli",
    "ChatFailed",
    "build_parser",
    "format_meta",
    "main",
    "parse_sse_data_line",
]
