from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from src.api.http.api_schemas import (
    AaveDcaStrategyPayload,
)


class AaveDcaState(BaseModel):
    aave_dca_strategies: Optional[list[AaveDcaStrategyPayload]] = None
