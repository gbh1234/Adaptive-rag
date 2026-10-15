"""Product tools: search, detail, recommendation and inventory."""

from pydantic import BaseModel, Field

from app.core.enums import ToolRisk
from app.core.exceptions import InvalidRequestError
from app.schemas.agent import ToolResult
from app.tools.base import Tool, ToolContext
from app.tools.deps import RepositoryBackedTool


class SearchInput(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=80,
        description="商品关键词，如「降噪耳机」；不要填 sku 或订单号",
    )


class SkuInput(BaseModel):
    sku: str = Field(
        min_length=2,
        max_length=32,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="商品 SKU，如 SKU-A1；不要填商品中文名或 order_id",
    )


class RecommendInput(BaseModel):
    category: str | None = Field(
        default=None,
        max_length=32,
        description="可选品类，如「数码」；不要填 sku",
    )
    query: str = Field(
        default="",
        max_length=80,
        description="可选需求描述，如「送女朋友的礼物」；可与 category 二选一",
    )


class SearchProductsTool(RepositoryBackedTool, Tool):
    name = "search_products"
    description = (
        "按关键词搜索商品目录，最多返回约 5 条匹配商品。"
        "何时用：用户给出具体商品名、品类词或属性词要找货，如「无线耳机」「跑步鞋」。"
        "何时不用：已知 sku 用 get_product_detail；「推荐/不知道买什么」用 recommend_products；政策问题用 search_knowledge。"
        "优先使用 search_products 当有明确关键词；模糊需求或推荐语气则用 recommend_products。"
        "参数 query：1–80 字搜索词，不是 sku。例 query=「降噪耳机」，不要填 SKU-A1 或 ORD1001。"
        "返回 products[]：sku、name、category、price_cents（分）、inventory；后续详情用返回的 sku 调 get_product_detail。"
    )
    risk = ToolRisk.READ
    input_model = SearchInput

    async def execute(self, parsed: SearchInput, context: ToolContext) -> ToolResult:
        products = await self.repository.search_products(parsed.query)
        return ToolResult(
            name=self.name,
            success=True,
            output={"products": [p.model_dump() for p in products]},
        )


class GetProductDetailTool(RepositoryBackedTool, Tool):
    name = "get_product_detail"
    description = (
        "按 SKU 查询单品详情：名称、品类、价格、库存、标签、描述。"
        "何时用：已知 sku，问规格、价格、介绍、这件是什么。"
        "何时不用：还不知道 sku 时先 search_products；只要库存数量用 check_inventory；保修条款用 get_warranty。"
        "优先：仅问有没有货 → check_inventory；还要价格/规格/介绍 → 本工具（已含 inventory）。"
        "参数 sku：2–32 位字母数字_-，例 SKU-A1；不要把商品中文名或 order_id 当 sku。"
        "返回 sku、name、category、price_cents（分）、inventory、tags、description。"
    )
    risk = ToolRisk.READ
    input_model = SkuInput

    async def execute(self, parsed: SkuInput, context: ToolContext) -> ToolResult:
        product = await self.repository.get_product(parsed.sku)
        if product is None:
            raise InvalidRequestError(f"product not found: {parsed.sku}")
        return ToolResult(name=self.name, success=True, output=product.model_dump())


class RecommendProductsTool(RepositoryBackedTool, Tool):
    name = "recommend_products"
    description = (
        "按品类或需求推荐最多 3 个商品，适合不确定买什么的场景。"
        "何时用：用户说推荐、随便看看、按场景/预算选、不知道买哪款。"
        "何时不用：已有明确搜索词用 search_products；已知 sku 用 get_product_detail。"
        "优先使用 search_products 当用户给出具体商品关键词；否则用本工具。"
        "参数 category 可选品类如「数码」；query 可选需求如「送女朋友的礼物」。至少填一个，都空则按「热销」召回。不要填 sku。"
        "返回 products 最多 3 条，字段同 search_products；不是个性化实时推荐。"
    )
    risk = ToolRisk.READ
    input_model = RecommendInput

    async def execute(self, parsed: RecommendInput, context: ToolContext) -> ToolResult:
        query = parsed.category or parsed.query or "热销"
        products = await self.repository.search_products(query)
        return ToolResult(
            name=self.name,
            success=True,
            output={"products": [p.model_dump() for p in products[:3]]},
        )


class CheckInventoryTool(RepositoryBackedTool, Tool):
    name = "check_inventory"
    description = (
        "按 SKU 只查询库存数量，不含价格与规格。"
        "何时用：已知 sku，只问有货吗、库存多少。"
        "何时不用：还要价格/规格/介绍用 get_product_detail；不知 sku 先 search_products。"
        "优先：仅库存 → 本工具；同时要价格或详情 → get_product_detail（无需再调本工具）。"
        "参数 sku：例 SKU-A1，不是商品中文名。"
        "返回 {sku, inventory}；0 表示无货，不要编造补货日期。"
    )
    risk = ToolRisk.READ
    input_model = SkuInput

    async def execute(self, parsed: SkuInput, context: ToolContext) -> ToolResult:
        product = await self.repository.get_product(parsed.sku)
        if product is None:
            raise InvalidRequestError(f"product not found: {parsed.sku}")
        return ToolResult(
            name=self.name,
            success=True,
            output={"sku": product.sku, "inventory": product.inventory},
        )
