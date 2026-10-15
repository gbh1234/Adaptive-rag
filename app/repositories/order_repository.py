"""Order, refund and return queries."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import OrderStatus
from app.core.exceptions import DatabaseError, InvalidRequestError
from app.core.ids import new_id
from app.repositories.models import AuditLogRow, OrderRow, ProductRow, RefundRow, ReturnRow
from app.schemas.order import Order, OrderItem, Product


def escape_like(term: str) -> str:
    """Escape LIKE wildcards so user input cannot broaden a search."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_order(self, order_id: str) -> Order | None:
        try:
            result = await self._session.execute(
                select(OrderRow)
                .options(selectinload(OrderRow.items))
                .where(OrderRow.order_id == order_id)
            )
            row = result.scalar_one_or_none()
        except Exception as exc:
            raise DatabaseError("failed to load order") from exc
        if row is None:
            return None
        return _to_order(row)

    async def get_visible_order(self, order_id: str, user_id: str) -> Order:
        """Return only an order owned by the supplied user, hiding others as not-found."""
        order = await self.get_order(order_id)
        if order is None:
            raise InvalidRequestError(f"order not found: {order_id}")
        if order.user_id != user_id:
            raise InvalidRequestError(f"order not found: {order_id}")
        return order

    async def list_orders_for_user(self, user_id: str, *, limit: int = 10) -> list[Order]:
        result = await self._session.execute(
            select(OrderRow)
            .options(selectinload(OrderRow.items))
            .where(OrderRow.user_id == user_id)
            .order_by(OrderRow.created_at.desc())
            .limit(limit)
        )
        return [_to_order(row) for row in result.scalars().all()]

    async def update_status(self, order_id: str, status: OrderStatus) -> None:
        order = await self._session.get(OrderRow, order_id)
        if order is None:
            return
        order.status = status.value

    async def create_refund(
        self,
        *,
        order_id: str,
        reason: str,
        trace_id: str,
    ) -> dict:
        """Insert refund + mark order refunding in the same Unit of Work.

        The request session commits in ChatService; this method only flushes.
        If either write fails, the outer rollback drops both.
        """
        order = await self.get_order(order_id)
        if order is None:
            raise InvalidRequestError(f"order not found: {order_id}")
        refund_id = new_id("rf_")[:16]
        try:
            self._session.add(
                RefundRow(
                    refund_id=refund_id,
                    order_id=order.order_id,
                    status="requested",
                    amount_cents=order.total_cents,
                    reason=reason,
                )
            )
            await self.update_status(order.order_id, OrderStatus.REFUNDING)
            await self.write_audit(trace_id, "create_refund", order.order_id)
            await self._session.flush()
        except InvalidRequestError:
            raise
        except Exception as exc:
            raise DatabaseError("failed to create refund") from exc
        return {"refund_id": refund_id, "status": "requested", "order_id": order.order_id}

    async def create_return(
        self,
        *,
        order_id: str,
        reason: str,
        trace_id: str,
    ) -> dict:
        order = await self.get_order(order_id)
        if order is None:
            raise InvalidRequestError(f"order not found: {order_id}")
        return_id = new_id("rt_")[:16]
        try:
            self._session.add(
                ReturnRow(
                    return_id=return_id,
                    order_id=order.order_id,
                    status="requested",
                    reason=reason,
                )
            )
            await self.write_audit(trace_id, "create_return", order.order_id)
            await self._session.flush()
        except Exception as exc:
            raise DatabaseError("failed to create return") from exc
        return {"return_id": return_id, "order_id": order.order_id, "status": "requested"}

    async def cancel_order(self, order_id: str, *, trace_id: str) -> dict:
        order = await self.get_order(order_id)
        if order is None:
            raise InvalidRequestError(f"order not found: {order_id}")
        if order.status not in {OrderStatus.CREATED, OrderStatus.PAID}:
            raise InvalidRequestError("only unpaid or paid-unshipped orders can be cancelled")
        try:
            await self.update_status(order.order_id, OrderStatus.CANCELLED)
            await self.write_audit(trace_id, "cancel_order", order.order_id)
            await self._session.flush()
        except InvalidRequestError:
            raise
        except Exception as exc:
            raise DatabaseError("failed to cancel order") from exc
        return {"order_id": order.order_id, "status": "cancelled"}

    async def write_audit(self, trace_id: str, action: str, order_id: str) -> None:
        self._session.add(AuditLogRow(trace_id=trace_id, action=action, payload=order_id))

    async def get_product(self, sku: str) -> Product | None:
        row = await self._session.get(ProductRow, sku)
        if row is None:
            return None
        return Product(
            sku=row.sku,
            name=row.name,
            category=row.category,
            price_cents=row.price_cents,
            inventory=row.inventory,
            tags=[tag for tag in row.tags.split(",") if tag],
            description=row.description,
        )

    async def search_products(self, query: str, *, limit: int = 5) -> list[Product]:
        pattern = f"%{escape_like(query)}%"
        result = await self._session.execute(
            select(ProductRow)
            .where(
                or_(
                    ProductRow.name.ilike(pattern),
                    ProductRow.category.ilike(pattern),
                    ProductRow.tags.ilike(pattern),
                )
            )
            .limit(limit)
        )
        return [
            Product(
                sku=row.sku,
                name=row.name,
                category=row.category,
                price_cents=row.price_cents,
                inventory=row.inventory,
                tags=[tag for tag in row.tags.split(",") if tag],
                description=row.description,
            )
            for row in result.scalars().all()
        ]

    async def get_refunds(self, order_id: str) -> list[RefundRow]:
        result = await self._session.execute(
            select(RefundRow).where(RefundRow.order_id == order_id)
        )
        return list(result.scalars().all())


def _to_order(row: OrderRow) -> Order:
    return Order(
        order_id=row.order_id,
        user_id=row.user_id,
        status=OrderStatus(row.status),
        items=[
            OrderItem(
                sku=item.sku,
                name=item.name,
                quantity=item.quantity,
                unit_price_cents=item.unit_price_cents,
                customized=item.customized,
            )
            for item in row.items
        ],
        total_cents=row.total_cents,
        created_at=row.created_at,
        paid_at=row.paid_at,
        shipped_at=row.shipped_at,
        delivered_at=row.delivered_at,
        tracking_no=row.tracking_no,
        receiver_city=row.receiver_city,
    )
