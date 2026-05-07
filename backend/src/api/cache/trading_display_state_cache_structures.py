from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from src.api.http.api_schemas import (
    TradingPositionPayload,
    TradingTradePayload,
    TradingPortfolioPayload,
    DcaStrategyPayload,
)


class TradingDisplayState(BaseModel):
    positions: Optional[list[TradingPositionPayload]] = None
    trades: Optional[list[TradingTradePayload]] = None
    portfolio: Optional[TradingPortfolioPayload] = None
