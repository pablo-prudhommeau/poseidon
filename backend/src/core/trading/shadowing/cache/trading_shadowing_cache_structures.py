from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from src.api.http.api_schemas import (
    TradingShadowMetaPayload, ShadowVerdictChroniclePayload, ShadowVerdictChronicleDeltaPayload,
)
from src.core.trading.shadowing.trading_shadowing_structures import ShadowIntelligenceSnapshot


class TradingShadowingState(BaseModel):
    shadow_meta: Optional[TradingShadowMetaPayload] = None
    shadow_intelligence_snapshot: Optional[ShadowIntelligenceSnapshot] = None
    shadow_verdict_chronicle: Optional[ShadowVerdictChroniclePayload] = None
    shadow_verdict_chronicle_delta: Optional[ShadowVerdictChronicleDeltaPayload] = None
