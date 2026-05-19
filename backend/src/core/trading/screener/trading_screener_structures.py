from __future__ import annotations

from pydantic import BaseModel, Field

TRADING_SCREENER_PROVIDER_DEXSCREENER = "dexscreener"


class TradingScreenerEnvelope(BaseModel):
    provider_id: str
    payload: dict[str, object] = Field(default_factory=dict)
