"""Interactive terminal chat client.

One process, keep asking. If the API is already up at ``base_url`` it is reused;
otherwise the engine is loaded in this process, which is slow on first start.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import httpx

from app.cli.render import HELP, apply_event, emit, format_meta, parse_sse_data_line
from app.core.ids import new_trace_id
from app.schemas.chat import ChatRequest

if TYPE_CHECKING:
    from app.services.container import AppContainer

DEFAULT_BASE = "http://127.0.0.1:8000"
DEFAULT_USER = "u_demo"


class ChatFailed(Exception):
    """One turn failed; the REPL should keep running."""


class ChatCli:
    """Stateful REPL client that talks to the API or an in-process engine."""

    def __init__(
        self,
        *,
        user_id: str,
        stream: bool,
        show_tokens: bool,
        timeout: float,
        base_url: str | None,
        local: bool,
    ) -> None:
        self._user_id = user_id
        self._stream = stream
        self._show_tokens = show_tokens
        self._timeout = timeout
        self._base = (base_url or DEFAULT_BASE).rstrip("/")
        self._force_local = local
        self._session_id: str | None = None
        self._pending_id: str | None = None
        self._pending_summary: str | None = None
        self._http: httpx.AsyncClient | None = None
        self._container: AppContainer | None = None

    async def setup(self) -> str:
        """Connect to a running API, or start the engine in-process, and return a banner."""
        if not self._force_local and await self._api_up():
            self._http = httpx.AsyncClient(timeout=self._timeout)
            return f"已连接 {self._base}。在这个终端里连续提问即可，/quit 退出。"
        print("正在本进程启动引擎（首次加载模型较慢）...")
        from app.config.settings import get_settings
        from app.services.container import build_container

        self._container = await build_container(get_settings())
        return "引擎已就绪。在这个终端里连续提问即可，/quit 退出。"

    async def _api_up(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{self._base}/api/v1/health")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def aclose(self) -> None:
        """Release the HTTP client or the in-process container."""
        if self._http is not None:
            await self._http.aclose()
        if self._container is not None:
            await self._container.aclose()

    async def chat(self, message: str, *, confirm: str | None = None) -> dict[str, Any]:
        """Send one turn and return the answer body."""
        if self._container is not None:
            return await self._chat_local(message, confirm=confirm)
        return await self._chat_http(message, confirm=confirm)

    async def _chat_local(self, message: str, *, confirm: str | None) -> dict[str, Any]:
        assert self._container is not None  # chat() only routes here when set
        request = ChatRequest(
            message=message,
            user_id=self._user_id,
            session_id=self._session_id,
            confirm_action_id=confirm,
        )
        if self._stream:
            stream = self._container.chat_service.stream(request, trace_id=new_trace_id())
            return await self._consume_events(stream)
        response = await self._container.chat_service.chat(request, trace_id=new_trace_id())
        return response.model_dump(mode="json")

    async def _chat_http(self, message: str, *, confirm: str | None) -> dict[str, Any]:
        assert self._http is not None
        payload = {
            "message": message,
            "user_id": self._user_id,
            "session_id": self._session_id,
            "confirm_action_id": confirm,
        }
        if self._stream:
            return await self._chat_http_stream(payload)
        response = await self._http.post(f"{self._base}/api/v1/chat", json=payload)
        return self._decode_http(response)

    async def _chat_http_stream(self, payload: dict[str, Any]) -> dict[str, Any]:
        assert self._http is not None
        http = self._http  # bind locally: the closure loses the None-narrowing

        async def events() -> AsyncIterator[dict[str, Any]]:
            async with http.stream(
                "POST", f"{self._base}/api/v1/chat/stream", json=payload
            ) as response:
                if response.status_code >= 400:
                    raw = (await response.aread()).decode("utf-8", errors="replace")
                    raise ChatFailed(f"请求失败 [{response.status_code}]: {raw[:300]}")
                async for line in response.aiter_lines():
                    event = parse_sse_data_line(line)
                    if event:
                        yield event

        return await self._consume_events(events())

    async def _consume_events(self, events: AsyncIterator[dict[str, Any]]) -> dict[str, Any]:
        answer: dict[str, Any] | None = None
        printed = False
        async for event in events:
            maybe, printed = apply_event(
                event, show_tokens=self._show_tokens, printed_nodes=printed
            )
            if maybe is not None:
                answer = maybe
        if printed:
            emit("\n")
        if answer is None:
            raise ChatFailed("这一轮没有拿到完整回答，请再试一次。")
        return answer

    def _decode_http(self, response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except json.JSONDecodeError:
            body = {"answer": response.text, "error_code": "BAD_RESPONSE"}
        if response.status_code >= 400:
            message = body.get("message") or body.get("answer") or response.text
            raise ChatFailed(
                f"请求失败 [{body.get('error_code') or response.status_code}]: {message}"
            )
        return body

    def render(self, body: dict[str, Any]) -> None:
        """Print one answer body and track session and pending-action state."""
        self._session_id = body.get("session_id") or self._session_id
        pending = body.get("pending_action")
        if isinstance(pending, dict) and pending.get("action_id"):
            self._pending_id = pending["action_id"]
            self._pending_summary = pending.get("summary") or pending.get("tool_name")
        else:
            self._pending_id = None
            self._pending_summary = None
        print()
        print(body.get("answer") or "")
        print()
        print(f"  ({format_meta(body)})")
        citations = body.get("citations") or []
        if citations:
            titles = ", ".join(
                str(item.get("section") or item.get("title") or item.get("chunk_id"))
                for item in citations[:4]
            )
            print(f"  引用: {titles}")
        if self._pending_id:
            print(f"  待确认: {self._pending_summary}")
            print("  输入 /y 确认执行，/n 取消这次确认。")
        print()

    async def loop(self) -> None:
        """Run the read-eval-print loop until the user quits."""
        banner = await self.setup()
        print(f"Adaptive-RAG  user={self._user_id}")
        print(banner)
        print("输入问题后回车即可继续问。/help 看命令。\n")
        while True:
            try:
                raw = (await asyncio.to_thread(input, "你> ")).strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见。")
                return
            if not raw:
                continue
            if raw in {"/quit", "/exit", "/q"}:
                print("再见。")
                return
            if raw == "/help":
                print(HELP)
                continue
            if raw == "/new":
                self._session_id = None
                self._pending_id = None
                print("已新开会话。\n")
                continue
            confirm: str | None = None
            message = raw
            if raw in {"/y", "/yes", "y", "Y", "确认"}:
                if not self._pending_id:
                    print("当前没有待确认操作。\n")
                    continue
                confirm = self._pending_id
                message = "确认"
            elif raw in {"/n", "/no"}:
                self._pending_id = None
                self._pending_summary = None
                print("已忽略待确认。\n")
                continue
            print("客服> ", end="", flush=True)
            try:
                body = await self.chat(message, confirm=confirm)
            except ChatFailed as exc:
                print(f"\n{exc}\n")
                continue
            except Exception as exc:
                print(f"\n出错了：{exc}\n")
                continue
            self.render(body)
