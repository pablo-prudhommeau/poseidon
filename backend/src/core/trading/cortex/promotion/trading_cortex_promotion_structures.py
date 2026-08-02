from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class TradingCortexForwardSelectionMetrics(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_version: str
    evaluated_record_count: int
    selected_record_count: int
    selected_average_profit_and_loss_percentage: float
    selected_win_rate: float
    selected_fragility_rate: float
    success_probability_threshold: float
    toxicity_probability_threshold: float


class TradingCortexPromotionEvaluation(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    champion_metrics: TradingCortexForwardSelectionMetrics
    challenger_metrics: TradingCortexForwardSelectionMetrics
    average_profit_and_loss_uplift_percentage: float
    fragility_rate_increase: float
    promoted: bool
    rejection_reason: Optional[str] = None
