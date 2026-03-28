from __future__ import annotations

from typing import Optional, List

from pydantic import BaseModel, Field


class ChartCaptureResult(BaseModel):
    png_bytes: bytes
    source_name: str
    timeframe_minutes: int
    lookback_minutes: int
    file_path: Optional[str] = None


class ChartCacheEntry(BaseModel):
    timestamp: float
    png_bytes: bytes
    source_name: str
    file_path: Optional[str] = None


class ChartAiOutput(BaseModel):
    take_profit_one_probability: float = Field(ge=0.0, le=1.0)
    stop_loss_before_take_profit_probability: float = Field(ge=0.0, le=1.0)
    trend_state: str
    momentum_bias: str
    quality_score_delta: float = Field(ge=-20.0, le=20.0)
    detected_patterns: List[dict]


class ChartAiSignal(BaseModel):
    take_profit_one_probability: float
    quality_score_delta: float
    source_name: str
    timeframe_minutes: int
    lookback_minutes: int
    trend_state: str
    momentum_bias: str
    detected_patterns: List[dict]
    screenshot_path: Optional[str] = None


class ChartSignalCacheEntry(BaseModel):
    timestamp: float
    signal: ChartAiSignal
