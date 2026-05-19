from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.core.trading.shadowing.trading_shadowing_structures import (
    TradingCandidateShadowingMetricEvaluation,
    TradingShadowingRegime,
)
from src.core.trading.trading_structures import TradingCandidate, TradingCortexInferenceSnapshot
from src.persistence.models import TradingShadowingProbe, TradingShadowingVerdict


def build_trading_shadowing_probe_with_verdict(
        candidate: TradingCandidate,
        rank: int,
        notional: float,
        current_time: datetime,
        shadow_can_simulate: bool,
        shadowing_regime: Optional[TradingShadowingRegime],
        take_profit_tier_1_price: float,
        take_profit_tier_2_price: float,
        stop_loss_price: float,
) -> TradingShadowingProbe:
    token = candidate.token
    market_snapshot = candidate.market_snapshot

    shadowing_metrics: Optional[list[TradingCandidateShadowingMetricEvaluation]] = None
    if shadow_can_simulate and candidate.shadowing_diagnostics.evaluated_metrics:
        shadowing_metrics = list(candidate.shadowing_diagnostics.evaluated_metrics)

    cortex_inference_summary: Optional[TradingCortexInferenceSnapshot] = None
    inference_snapshot = candidate.cortex_diagnostics.inference_snapshot
    if inference_snapshot is not None and inference_snapshot.model_ready:
        cortex_inference_summary = inference_snapshot

    return TradingShadowingProbe(
        token_symbol=token.symbol.upper(),
        blockchain_network=token.chain.value,
        token_address=str(token.token_address),
        pair_address=str(token.pair_address),
        dex_id=str(token.dex_id),
        entry_price_usd=market_snapshot.price_usd,
        candidate_rank=rank,
        quality_score=candidate.quality_score,
        token_age_hours=market_snapshot.token_age_hours,
        volume_m5_usd=market_snapshot.volume_m5_usd,
        volume_h1_usd=market_snapshot.volume_h1_usd,
        volume_h6_usd=market_snapshot.volume_h6_usd,
        volume_h24_usd=market_snapshot.volume_h24_usd,
        liquidity_usd=market_snapshot.liquidity_usd,
        price_change_percentage_m5=market_snapshot.price_change_percentage_m5,
        price_change_percentage_h1=market_snapshot.price_change_percentage_h1,
        price_change_percentage_h6=market_snapshot.price_change_percentage_h6,
        price_change_percentage_h24=market_snapshot.price_change_percentage_h24,
        transaction_count_m5=market_snapshot.transaction_count_m5,
        transaction_count_h1=market_snapshot.transaction_count_h1,
        transaction_count_h6=market_snapshot.transaction_count_h6,
        transaction_count_h24=market_snapshot.transaction_count_h24,
        buy_to_sell_ratio=market_snapshot.buy_to_sell_ratio,
        market_cap_usd=market_snapshot.market_cap_usd,
        fully_diluted_valuation_usd=market_snapshot.fully_diluted_valuation_usd,
        promotion_score=market_snapshot.promotion_score,
        order_notional_value_usd=notional,
        shadowing_regime=shadowing_regime,
        shadowing_metrics=shadowing_metrics,
        cortex_inference_summary=cortex_inference_summary,
        probed_at=current_time,
        created_at=current_time,
        verdict=TradingShadowingVerdict(
            take_profit_tier_1_price=take_profit_tier_1_price,
            take_profit_tier_2_price=take_profit_tier_2_price,
            stop_loss_price=stop_loss_price,
            created_at=current_time,
        ),
    )
