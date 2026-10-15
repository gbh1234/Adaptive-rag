"""Command-line entry point for the interactive chat client."""

from __future__ import annotations

import argparse
import asyncio

from app.cli.client import DEFAULT_BASE, DEFAULT_USER, ChatCli


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="adaptive-rag-cli", description="Adaptive-RAG 终端连续对话"
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE, help="已有 API 地址")
    parser.add_argument("--user-id", default=DEFAULT_USER)
    parser.add_argument("--local", action="store_true", help="强制本进程启动引擎，不连已有 API")
    parser.add_argument("--no-stream", action="store_true")
    parser.add_argument("--tokens", action="store_true", help="打印生成增量")
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser


async def _amain(argv: list[str] | None) -> int:
    args = build_parser().parse_args(argv)
    cli = ChatCli(
        user_id=args.user_id,
        stream=not args.no_stream,
        show_tokens=args.tokens,
        timeout=args.timeout,
        base_url=args.base_url,
        local=args.local,
    )
    try:
        await cli.loop()
    finally:
        await cli.aclose()
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the interactive chat CLI and return its exit code."""
    return asyncio.run(_amain(argv))


if __name__ == "__main__":
    raise SystemExit(main())
