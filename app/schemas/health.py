"""Health and readiness response schemas."""

from typing import Literal

from pydantic import BaseModel, Field


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"


class DependencyStatus(BaseModel):
    name: str
    ready: bool
    detail: str = ""


class ReadinessResponse(BaseModel):
    ready: bool
    dependencies: list[DependencyStatus] = Field(default_factory=list)
