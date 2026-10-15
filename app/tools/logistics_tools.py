"""Logistics tools: shipment tracking."""

from typing import Any

from pydantic import BaseModel, Field

from app.core.enums import ToolRisk
from app.schemas.agent import ToolResult
from app.tools.base import Tool, ToolContext
from app.tools.deps import RepositoryBackedTool


class TrackInput(BaseModel):
    order_id: str = Field(
        min_length=3,
        max_length=32,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="订单号，如 ORD1001；不要填运单号 tracking_no",
    )


class TrackShipmentTool(RepositoryBackedTool, Tool):
    name = "track_shipment"
    description = (
        "按订单号查询物流事件与运单号（仓库/在途/签收）。"
        "何时用：快递到哪了、物流轨迹、运单号、是否签收、催物流。"
        "何时不用：问支付/金额/订单状态用 get_order；问配送政策时效用 search_knowledge；仓库截单用 mcp_warehouse_cutoff。"
        "优先使用 track_shipment 当强调物流轨迹；强调订单状态/金额则用 get_order。"
        "参数 order_id：例 ORD1001；不要把运单号（如 SF123456）填进 order_id。"
        "返回 tracking_no、city、events[{status, at, tracking_no?}]，status 为 warehouse/in_transit/delivered；events 为空表示尚未出库，不能据此说已签收。"
    )
    risk = ToolRisk.READ
    input_model = TrackInput

    async def execute(self, parsed: TrackInput, context: ToolContext) -> ToolResult:
        order = await self.repository.get_visible_order(parsed.order_id, context.user_id)
        events: list[dict[str, Any]] = []
        if order.paid_at:
            events.append({"status": "warehouse", "at": order.paid_at.isoformat()})
        if order.shipped_at:
            events.append(
                {
                    "status": "in_transit",
                    "tracking_no": order.tracking_no,
                    "at": order.shipped_at.isoformat(),
                }
            )
        if order.delivered_at:
            events.append({"status": "delivered", "at": order.delivered_at.isoformat()})
        return ToolResult(
            name=self.name,
            success=True,
            output={
                "order_id": order.order_id,
                "tracking_no": order.tracking_no,
                "city": order.receiver_city,
                "events": events,
            },
        )
