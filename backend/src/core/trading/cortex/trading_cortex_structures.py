from __future__ import annotations

import enum
import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field





class TradingCortexNamedFeatureValue(BaseModel):
    feature_name: str
    feature_value: float


class TradingCortexCandidateFeatureSnapshot(BaseModel):
    token_symbol: str
    blockchain_network: Optional[str] = None
    dex_identifier: Optional[str] = None
    pair_address: Optional[str] = None
    candidate_rank: Optional[int] = None
    quality_score: float
    token_age_hours: float
    liquidity_usd: float
    market_cap_usd: Optional[float] = None
    fully_diluted_valuation_usd: Optional[float] = None
    dexscreener_boost: Optional[float] = None
    volume_5m_usd: float
    volume_1h_usd: float
    volume_6h_usd: float
    volume_24h_usd: float
    price_change_percentage_5m: float
    price_change_percentage_1h: float
    price_change_percentage_6h: float
    price_change_percentage_24h: float
    transaction_count_5m: float
    transaction_count_1h: float
    transaction_count_6h: float
    transaction_count_24h: float
    buy_to_sell_ratio: float
    order_notional_value_usd: Optional[float] = None


class TradingCortexShadowRegimeFeatureSnapshot(BaseModel):
    meta_win_rate: Optional[float] = None
    meta_average_profit_and_loss_percentage: Optional[float] = None
    meta_average_holding_time_hours: Optional[float] = None
    meta_capital_velocity: Optional[float] = None
    meta_profit_factor: Optional[float] = None
    meta_expected_value_usd: Optional[float] = None
    chronicle_profit_factor: Optional[float] = None
    sparse_expected_value_usd: Optional[float] = None


class TradingCortexShadowMetricFeatureSnapshot(BaseModel):
    metric_key: str
    candidate_value: float
    bucket_index: Optional[int] = None
    bucket_win_rate: Optional[float] = None
    bucket_average_profit_and_loss_percentage: Optional[float] = None
    bucket_average_holding_time_hours: Optional[float] = None
    bucket_capital_velocity: Optional[float] = None
    bucket_outlier_hit_rate: Optional[float] = None
    bucket_sample_count: Optional[int] = None
    is_toxic: bool = False
    is_golden: bool = False
    normalized_influence: Optional[float] = None


class TradingCortexScoringRequest(BaseModel):
    request_identifier: Optional[str] = None
    feature_set_version: str = "poseidon_shadow_v1"
    candidate_features: TradingCortexCandidateFeatureSnapshot
    shadow_regime_features: Optional[TradingCortexShadowRegimeFeatureSnapshot] = None
    shadow_metric_features: list[TradingCortexShadowMetricFeatureSnapshot] = Field(default_factory=list)


class TradingCortexScoringBatchRequest(BaseModel):
    requests: list[TradingCortexScoringRequest]


class TradingCortexPartialPrediction(BaseModel):
    success_probability: Optional[float] = None
    toxicity_probability: Optional[float] = None
    expected_profit_and_loss_percentage: Optional[float] = None
    used_model_names: list[str] = Field(default_factory=list)


class TradingCortexPrediction(BaseModel):
    success_probability: float
    toxicity_probability: float
    expected_profit_and_loss_percentage: float


class TradingCortexFeatureVectorSnapshot(BaseModel):
    feature_set_version: str
    named_feature_values: list[TradingCortexNamedFeatureValue]
    shadow_metric_count: int
    golden_metric_count: int
    toxic_metric_count: int
    golden_metric_ratio: float
    toxic_metric_ratio: float
    regime_signal: float

    def extract_ordered_feature_values(self, ordered_feature_names: list[str]) -> list[float]:
        feature_value_lookup_by_name: dict[str, float] = {
            named_feature_value.feature_name: named_feature_value.feature_value
            for named_feature_value in self.named_feature_values
        }
        ordered_feature_values: list[float] = []
        for ordered_feature_name in ordered_feature_names:
            if ordered_feature_name in feature_value_lookup_by_name:
                ordered_feature_values.append(feature_value_lookup_by_name[ordered_feature_name])
            else:
                ordered_feature_values.append(math.nan)
        return ordered_feature_values


class TradingCortexFinalScoreBreakdown(BaseModel):
    success_signal: float
    toxicity_signal: float
    expected_profit_and_loss_signal: float
    shadow_exposure_signal: float
    regime_signal: float
    weighted_score: float
    final_trade_score: float


class TradingCortexScoringResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    request_identifier: Optional[str] = None
    token_symbol: str
    feature_set_version: str
    model_version: Optional[str] = None
    model_ready: bool
    success_probability: Optional[float] = None
    toxicity_probability: Optional[float] = None
    expected_profit_and_loss_percentage: Optional[float] = None
    final_trade_score: Optional[float] = None
    score_breakdown: Optional[TradingCortexFinalScoreBreakdown] = None
    feature_count: int
    golden_metric_count: int
    toxic_metric_count: int
    used_model_names: list[str] = Field(default_factory=list)


class TradingCortexScoringBatchResponse(BaseModel):
    responses: list[TradingCortexScoringResponse]


class TradingCortexHealthResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    ok: bool
    model_ready: bool
    model_version: Optional[str] = None
    feature_set_version: Optional[str] = None
    loaded_model_names: list[str] = Field(default_factory=list)
