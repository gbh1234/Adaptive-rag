"""Order and product schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.enums import OrderStatus


class OrderItem(BaseModel):
    sku: str
    name: str
    quantity: int
    unit_price_cents: int
    customized: bool = False


class Order(BaseModel):
    order_id: str
    user_id: str
    status: OrderStatus
    items: list[OrderItem]
    total_cents: int
    created_at: datetime
    paid_at: datetime | None = None
    shipped_at: datetime | None = None
    delivered_at: datetime | None = None
    tracking_no: str | None = None
    receiver_city: str | None = None


class Product(BaseModel):
    sku: str
    name: str
    category: str
    price_cents: int
    inventory: int
    tags: list[str] = Field(default_factory=list)
    description: str = ""
