from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from src.api.http.api_schemas import (
    TradingShadowingRegimePayload, TradingShadowingVerdictChroniclePayload, TradingShadowingVerdictChronicleDeltaPayload,
)
from src.core.trading.shadowing.trading_shadowing_structures import TradingShadowingSnapshot


class TradingShadowingState(BaseModel):
    shadowing_regime: Optional[TradingShadowingRegimePayload] = None
    shadowing_snapshot: Optional[TradingShadowingSnapshot] = None
    shadowing_verdict_chronicle: Optional[TradingShadowingVerdictChroniclePayload] = None
    shadowing_verdict_chronicle_delta: Optional[TradingShadowingVerdictChronicleDeltaPayload] = None
