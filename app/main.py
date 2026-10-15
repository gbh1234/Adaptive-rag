"""Application factory: lifespan wiring and FastAPI app creation."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles

from app.api.routes import admin, chat, health
from app.config.settings import Settings, get_settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError
from app.core.ids import new_request_id, new_trace_id
from app.observability.context import bind_request_context, reset_request_context
from app.observability.logging import configure_logging
from app.schemas.common import APIErrorBody
from app.services.container import build_container

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the container on startup and release it on shutdown."""
    settings = get_settings()
    configure_logging(settings)
    container = await build_container(settings)
    app.state.container = container
    try:
        yield
    finally:
        await container.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI application.

    Registers the routers under ``api_v1_prefix``, installs request-scoped
    context, and maps application errors to the stable JSON error envelope.

    Args:
        settings: Optional settings override; when omitted the cached settings
            are used. Passing an explicit value clears the settings cache first,
            which is what tests rely on.

    Returns:
        A fully wired FastAPI application with the container bound in ``lifespan``.
    """
    if settings is not None:
        from app.config.settings import clear_settings_cache

        clear_settings_cache()
    resolved = settings or get_settings()
    app = FastAPI(
        title="Adaptive-RAG Customer Service",
        version="0.1.0",
        lifespan=lifespan,
    )
    prefix = resolved.api_v1_prefix
    app.include_router(health.router, prefix=prefix)
    app.include_router(chat.router, prefix=prefix)
    app.include_router(admin.router, prefix=prefix)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        trace_id = request.headers.get("x-trace-id") or new_trace_id()
        request_id = request.headers.get("x-request-id") or new_request_id()
        tokens = bind_request_context(trace_id=trace_id, request_id=request_id)
        request.state.trace_id = trace_id
        request.state.request_id = request_id
        try:
            response = await call_next(request)
            response.headers["x-trace-id"] = trace_id
            response.headers["x-request-id"] = request_id
            return response
        finally:
            reset_request_context(tokens)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        body = APIErrorBody(
            error_code=exc.error_code,
            message=exc.message,
            trace_id=getattr(request.state, "trace_id", "-"),
        )
        return JSONResponse(status_code=exc.http_status, content=body.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = exc.errors() if resolved.app_env != "production" else None
        body = APIErrorBody(
            error_code=ErrorCode.INVALID_REQUEST,
            message="invalid request",
            trace_id=getattr(request.state, "trace_id", "-"),
            details={"errors": details} if details else None,
        )
        return JSONResponse(status_code=422, content=body.model_dump(mode="json"))

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, StarletteHTTPException):
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        logger.exception(
            "unhandled_error", extra={"trace_id": getattr(request.state, "trace_id", "-")}
        )
        body = APIErrorBody(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="internal error",
            trace_id=getattr(request.state, "trace_id", "-"),
        )
        return JSONResponse(status_code=500, content=body.model_dump(mode="json"))

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # A built frontend is optional for local API-only development. Docker builds it.
    frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app
