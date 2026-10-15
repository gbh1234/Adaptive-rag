"""ASGI entrypoint exposing the module-level FastAPI app."""

from app.main import create_app

app = create_app()
