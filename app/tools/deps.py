"""Repository-backed tool base."""

from app.core.request_scope import get_db_session
from app.repositories.order_repository import OrderRepository


class RepositoryBackedTool:
    """Tools hold an optional repo for tests; production resolves the request session."""

    def __init__(self, repository: OrderRepository | None = None) -> None:
        self._repository = repository

    @property
    def repository(self) -> OrderRepository:
        if self._repository is not None:
            return self._repository
        return OrderRepository(get_db_session())
