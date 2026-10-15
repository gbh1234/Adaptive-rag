"""Tool registry construction."""

from app.retrieval.hybrid import HybridRetriever
from app.tools.aftersale_tools import (
    CancelOrderTool,
    CreateRefundRequestTool,
    CreateReturnRequestTool,
    GetRefundStatusTool,
)
from app.tools.base import Tool
from app.tools.knowledge_tools import (
    EscalateToHumanTool,
    GetCouponTool,
    GetWarrantyTool,
    SearchKnowledgeTool,
)
from app.tools.logistics_tools import TrackShipmentTool
from app.tools.order_tools import GetOrderItemsTool, GetOrderTool
from app.tools.product_tools import (
    CheckInventoryTool,
    GetProductDetailTool,
    RecommendProductsTool,
    SearchProductsTool,
)
from app.tools.registry import ToolRegistry


def build_tool_registry(retriever: HybridRetriever) -> ToolRegistry:
    """Process-scoped registry. DB-backed tools resolve the request session lazily."""
    registry = ToolRegistry()
    # Explicit annotation: the concrete classes mix RepositoryBackedTool with Tool,
    # so an unannotated list literal widens to `object` and fails type checking.
    tools: list[Tool] = [
        GetOrderTool(),
        GetOrderItemsTool(),
        TrackShipmentTool(),
        GetRefundStatusTool(),
        CreateRefundRequestTool(),
        CreateReturnRequestTool(),
        CancelOrderTool(),
        SearchProductsTool(),
        GetProductDetailTool(),
        RecommendProductsTool(),
        GetCouponTool(),
        CheckInventoryTool(),
        GetWarrantyTool(),
        SearchKnowledgeTool(retriever),
        EscalateToHumanTool(),
    ]
    for tool in tools:
        registry.register(tool)
    return registry
