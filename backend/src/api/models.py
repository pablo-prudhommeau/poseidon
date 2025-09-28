from typing import Dict, List

from pydantic import BaseModel, Field


class OhlcvCandle(BaseModel):
    """Single OHLCV candle with timestamp in epoch milliseconds."""
    t: int = Field(..., description="Timestamp, epoch milliseconds.")
    o: float = Field(..., description="Open price.")
    h: float = Field(..., description="High price.")
    l: float = Field(..., description="Low price.")
    c: float = Field(..., description="Close price.")
    v: float = Field(0.0, description="Base volume for the interval.")

class OhlcvResponse(BaseModel):
    """Structured response for OHLCV data."""
    meta: Dict[str, str] = Field(..., description="Contextual metadata.")
    candles: List[OhlcvCandle] = Field(default_factory=list, description="Ordered candles.")