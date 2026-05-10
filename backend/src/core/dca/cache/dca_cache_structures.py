from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from src.api.http.api_schemas import (
    DcaStrategyPayload,
)


class DcaState(BaseModel):
    dca_strategies: Optional[list[DcaStrategyPayload]] = None
