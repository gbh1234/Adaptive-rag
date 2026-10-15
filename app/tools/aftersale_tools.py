"""After-sale tools: refund, return and order cancellation."""

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
        description="订单号，如 ORD1001；不要填 refund_id 或 user_id",
    )


class RefundCreateInput(BaseModel):
    order_id: str = Field(
        min_length=3,
        max_length=32,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="要申请售后的订单号，如 ORD1001",
    )
    reason: str = Field(
        min_length=1,
        max_length=200,
        description="用户原因，1–200 字，如「尺码不合适」；不要填订单号",
    )


class GetRefundStatusTool(RepositoryBackedTool, Tool):
    name = "get_refund_status"
    description = (
        "只读查询某订单已有退款单列表（单号、状态、金额）。"
        "何时用：退款到哪了、退款单状态、退了多少钱。"
        "何时不用：尚未申请、用户要新提交退款时用 create_refund_request；查订单是否支付用 get_order。"
        "优先使用本工具当已申请、只查进度；尚未申请不要用本工具代替提交。"
        "参数 order_id：例 ORD1001，不是 refund_id（rf_…）或 user_id。"
        "返回 refunds[{refund_id, status, amount_cents}]；空列表表示尚无退款单，不要说已经退款成功。"
    )
    risk = ToolRisk.READ
    input_model = OrderIdInput

    async def execute(self, parsed: OrderIdInput, context: ToolContext) -> ToolResult:
        await self.repository.get_visible_order(parsed.order_id, context.user_id)
        refunds = await self.repository.get_refunds(parsed.order_id)
        return ToolResult(
            name=self.name,
            success=True,
            output={
                "refunds": [
                    {
                        "refund_id": row.refund_id,
                        "status": row.status,
                        "amount_cents": row.amount_cents,
                    }
                    for row in refunds
                ]
            },
        )


class CreateRefundRequestTool(RepositoryBackedTool, Tool):
    name = "create_refund_request"
    description = (
        "提交退款申请（destructive，须用户确认后才真正执行）。只退款、不创建退货单。"
        "何时用：用户明确要求退钱/申请退款，且已有订单号。"
        "何时不用：只问退款规则用 search_knowledge；只查进度用 get_refund_status；要寄回商品用 create_return_request；未发货取消订单用 cancel_order。"
        "优先：未发货取消 → cancel_order；已发货要退货 → create_return_request；只要退款不要寄回 → 本工具。"
        "参数 order_id 例 ORD1001；reason 1–200 字中文原因，如「不想要了」，不要把 order_id 填进 reason。"
        "返回 {refund_id, status:requested, order_id} 表示已受理，不代表已到账。"
    )
    risk = ToolRisk.DESTRUCTIVE
    input_model = RefundCreateInput

    async def execute(self, parsed: RefundCreateInput, context: ToolContext) -> ToolResult:
        await self.repository.get_visible_order(parsed.order_id, context.user_id)
        output = await self.repository.create_refund(
            order_id=parsed.order_id,
            reason=parsed.reason,
            trace_id=context.trace_id,
        )
        return ToolResult(name=self.name, success=True, output=output)


class CreateReturnRequestTool(RepositoryBackedTool, Tool):
    name = "create_return_request"
    description = (
        "提交退货申请（write，须用户确认后才真正执行）。只建退货单，不会自动退款。"
        "何时用：用户要退货/换货、把商品寄回。"
        "何时不用：只要退款不寄回用 create_refund_request；未发货取消用 cancel_order；问「能不能退」先用 search_knowledge 或 get_order_items（看 customized）。"
        "优先：未发货取消 → cancel_order；只要退款 → create_refund_request；要退货寄回 → 本工具。"
        "参数 order_id 例 ORD1001；reason 1–200 字，如「尺码不合适」。"
        "返回 {return_id, order_id, status:requested}；不要据此声称货款已退回。"
    )
    risk = ToolRisk.WRITE
    input_model = RefundCreateInput

    async def execute(self, parsed: RefundCreateInput, context: ToolContext) -> ToolResult:
        await self.repository.get_visible_order(parsed.order_id, context.user_id)
        output = await self.repository.create_return(
            order_id=parsed.order_id,
            reason=parsed.reason,
            trace_id=context.trace_id,
        )
        return ToolResult(name=self.name, success=True, output=output)


class CancelOrderTool(RepositoryBackedTool, Tool):
    name = "cancel_order"
    description = (
        "取消尚未发货的订单（destructive，须用户确认）。仅 status 为 created 或 paid 时可成功。"
        "何时用：用户要取消订单，且订单未发货。"
        "何时不用：已发货/已签收不要调用（会失败）；应改用 create_return_request。不要用本工具提交退款单。"
        "优先：未发货取消 → 本工具；已发货退货 → create_return_request。"
        "参数 order_id：例 ORD1001，不要填 sku。"
        "返回 {order_id, status:cancelled}；失败通常表示已发货或状态不允许取消。"
    )
    risk = ToolRisk.DESTRUCTIVE
    input_model = OrderIdInput

    async def execute(self, parsed: OrderIdInput, context: ToolContext) -> ToolResult:
        await self.repository.get_visible_order(parsed.order_id, context.user_id)
        output = await self.repository.cancel_order(parsed.order_id, trace_id=context.trace_id)
        return ToolResult(name=self.name, success=True, output=output)
