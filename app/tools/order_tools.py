"""Order tools: order and item lookup."""

from pydantic import BaseModel, Field

from app.core.enums import ToolRisk
from app.schemas.agent import ToolResult
from app.tools.base import Tool, ToolContext
from app.tools.deps import RepositoryBackedTool


class OrderIdInput(BaseModel):
    order_id: str = Field(
        min_length=3,
        max_length=32,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="订单号，如 ORD1001；不要填运单号、user_id 或手机号",
    )


class GetOrderTool(RepositoryBackedTool, Tool):
    name = "get_order"
    description = (
        "按订单号查询订单头：状态、金额、支付/发货/签收时间、运单号摘要。"
        "何时用：问支付是否成功、订单状态、金额、是否已发货。"
        "何时不用：只要快递轨迹用 track_shipment；只要商品明细用 get_order_items；只要退款单用 get_refund_status。"
        "优先使用 get_order 当用户问状态/金额/是否支付；问快递到哪/轨迹则用 track_shipment。"
        "参数 order_id：3–32 位字母数字_-，例 ORD1001，不要填 SF123456 或 u_demo。"
        "返回 status、total_cents（单位分）、paid_at/shipped_at/delivered_at、tracking_no；后续若需明细再调 get_order_items。"
    )
    risk = ToolRisk.READ
    input_model = OrderIdInput

    async def execute(self, parsed: OrderIdInput, context: ToolContext) -> ToolResult:
        order = await self.repository.get_visible_order(parsed.order_id, context.user_id)
        return ToolResult(name=self.name, success=True, output=order.model_dump(mode="json"))


class GetOrderItemsTool(RepositoryBackedTool, Tool):
    name = "get_order_items"
    description = (
        "查询订单内商品明细：SKU、名称、数量、单价、是否定制。"
        "何时用：问买了什么、某件能不能退、是不是定制件、数量对不对。"
        "何时不用：只要订单状态或应付金额用 get_order。"
        "优先使用 get_order 当只要状态/金额，否则用本工具拿行项目。"
        "参数 order_id：同 get_order，例 ORD1001，不是 sku 或商品中文名。"
        "返回 items[]：sku、name、quantity、unit_price_cents（分）、customized；后续退货/退款应依据 customized 与 sku。"
    )
    risk = ToolRisk.READ
    input_model = OrderIdInput

    async def execute(self, parsed: OrderIdInput, context: ToolContext) -> ToolResult:
        order = await self.repository.get_visible_order(parsed.order_id, context.user_id)
        return ToolResult(
            name=self.name,
            success=True,
            output={"items": [item.model_dump() for item in order.items]},
        )
