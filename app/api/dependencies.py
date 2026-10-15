"""FastAPI dependency providers."""

from fastapi import Request

from app.services.container import AppContainer


def get_container(request: Request) -> AppContainer:
    return request.app.state.container
