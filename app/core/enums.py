"""Domain enums for intent, complexity, strategy, order status and risk."""

from enum import Enum


class AppEnv(str, Enum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


class IntentLabel(str, Enum):
    GREETING = "greeting"
    CHITCHAT = "chitchat"
    FAQ_POLICY = "faq_policy"
    ORDER_INQUIRY = "order_inquiry"
    LOGISTICS = "logistics"
    REFUND = "refund"
    RETURN_EXCHANGE = "return_exchange"
    CANCEL_ORDER = "cancel_order"
    PRODUCT_CONSULT = "product_consult"
    RECOMMENDATION = "recommendation"
    COUPON = "coupon"
    COMPLAINT = "complaint"
    HUMAN_HANDOFF = "human_handoff"
    OUT_OF_SCOPE = "out_of_scope"


class RetrievalStrategy(str, Enum):
    """Adaptive-RAG routing targets.

    DIRECT: parametric / greeting answers, no retrieval.
    SINGLE: one-shot hybrid retrieval.
    MULTI: Self-RAG iterative retrieval for multi-hop questions.
    AGENT: planner + tools, optionally with retrieval.
    REFUSE: query boundary / policy refusal.
    """

    DIRECT = "direct"
    SINGLE = "single"
    MULTI = "multi"
    AGENT = "agent"
    REFUSE = "refuse"


class QueryComplexity(str, Enum):
    SIMPLE = "simple"
    SINGLE_HOP = "single_hop"
    MULTI_HOP = "multi_hop"
    TOOL_REQUIRED = "tool_required"
    OUT_OF_SCOPE = "out_of_scope"


class OrderStatus(str, Enum):
    CREATED = "created"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDING = "refunding"
    REFUNDED = "refunded"


class ToolRisk(str, Enum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    EXTERNAL = "external"


class CompressionLevel(str, Enum):
    NONE = "none"
    SOFT_TRUNCATE = "soft_truncate"
    HARD_COMPRESS = "hard_compress"
    AUTO_COMPACT = "auto_compact"


class DocumentCategory(str, Enum):
    FAQ = "faq"
    RETURN_POLICY = "return_policy"
    SHIPPING = "shipping"
    WARRANTY = "warranty"
    COUPON = "coupon"
    PRODUCT = "product"
    PAYMENT = "payment"
    ACCOUNT = "account"
    AFTERSALE = "aftersale"
