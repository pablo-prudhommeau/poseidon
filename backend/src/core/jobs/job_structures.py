from __future__ import annotations

from pydantic import BaseModel

from src.core.structures.structures import Mode


class BackgroundJobsRuntimeStatus(BaseModel):
    mode: Mode
    trading_enabled: bool
    trading_interval_seconds: int
    position_guard_interval_seconds: int
    shadowing_enabled: bool


class ApiStatusResponse(BaseModel):
    ok: bool
    status: BackgroundJobsRuntimeStatus
