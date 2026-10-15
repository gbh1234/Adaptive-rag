"""Admin routes for tool and skill introspection."""

import hmac

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_container
from app.core.exceptions import UnauthorizedError
from app.services.container import AppContainer
from app.skills.loader import load_skills

router = APIRouter(prefix="/admin", tags=["admin"])


async def require_admin(request: Request, container: AppContainer = Depends(get_container)) -> None:
    token = container.settings.admin_api_token.get_secret_value()
    if not token:
        if container.settings.app_env == "production":
            raise UnauthorizedError("admin API is disabled")
        return
    provided = request.headers.get("x-admin-token", "")
    if not hmac.compare_digest(provided, token):
        raise UnauthorizedError("invalid admin token")


@router.get("/tools", dependencies=[Depends(require_admin)])
async def list_tools(container: AppContainer = Depends(get_container)) -> dict:
    names = container.chat_service.registry.names()
    return {"tools": names, "count": len(names)}


@router.get("/skills", dependencies=[Depends(require_admin)])
async def list_skills() -> dict:
    return {"skills": load_skills()}
