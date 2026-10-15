"""Local and remote MCP backends behind the same call_tool contract."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.exceptions import ToolExecutionError

LOCAL_CATALOG: list[dict[str, str]] = [
    {
        "name": "mcp_store_hours",
        "description": (
            "查询客服营业时间与夜间是否审核退款。"
            "何时用：客服几点上班、周末时段、夜间退款会不会审。"
            "何时不用：仓库截单/当日发货用 mcp_warehouse_cutoff；退款规则用 search_knowledge；退款进度用 get_refund_status。"
            "优先：营业时间/夜间审核 → 本工具；截单发货 → mcp_warehouse_cutoff。"
            "无需必填参数，payload 可空。"
            "返回 weekday、weekend（如 09:00-21:00）与 night_refund_review（bool）；false 表示夜间不审退款，不要承诺夜间立即退款。"
        ),
        "transport": "local",
    },
    {
        "name": "mcp_warehouse_cutoff",
        "description": (
            "查询仓库截单与当日发货截止时间。"
            "何时用：今天下单几点前能发货、截单时间、能否当日发。"
            "何时不用：快递轨迹/运单号用 track_shipment；客服上班时间用 mcp_store_hours；配送政策用 search_knowledge。"
            "优先：截单/当日发货 → 本工具；物流轨迹 → track_shipment；客服时段 → mcp_store_hours。"
            "无需必填参数，payload 可空。"
            "返回 cutoff、same_day_if_paid_before（HH:MM）；表示支付须早于该时刻才可能当日发，不保证一定发出。"
        ),
        "transport": "local",
    },
]

_LOCAL_HANDLERS: dict[str, dict[str, Any]] = {
    "mcp_store_hours": {
        "weekday": "09:00-21:00",
        "weekend": "10:00-18:00",
        "night_refund_review": False,
        "source": "mcp_local",
    },
    "mcp_warehouse_cutoff": {
        "cutoff": "16:00",
        "same_day_if_paid_before": "16:00",
        "source": "mcp_local",
    },
}


async def call_mcp_tool(
    *,
    name: str,
    arguments: dict[str, Any],
    transport: str,
    endpoint: str = "",
) -> dict[str, Any]:
    if transport == "local":
        if name not in _LOCAL_HANDLERS:
            raise ToolExecutionError(f"unknown local MCP tool: {name}")
        return {**_LOCAL_HANDLERS[name], "arguments": arguments}
    if not endpoint:
        raise ToolExecutionError(f"remote MCP tool {name} has no endpoint")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                endpoint,
                json={"name": name, "arguments": arguments},
                headers={"content-type": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise ToolExecutionError(f"remote MCP transport error: {name}") from exc
    if response.status_code >= 400:
        raise ToolExecutionError(f"remote MCP HTTP {response.status_code}")
    body = response.json()
    if not isinstance(body, dict):
        raise ToolExecutionError("remote MCP returned non-object JSON")
    return body
