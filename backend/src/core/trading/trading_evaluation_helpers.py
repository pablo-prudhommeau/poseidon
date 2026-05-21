from __future__ import annotations

from typing import Optional

from src.api.http.api_schemas import TradingShadowingRegimePayload
from src.configuration.config import _to_dict, settings
from src.core.trading.shadowing.cache.trading_shadowing_cache import trading_shadowing_cache
from src.core.trading.shadowing.trading_shadowing_structures import TradingShadowingRegime
from src.core.trading.trading_structures import TradingCandidate, TradingCortexInferenceSnapshot
from src.core.utils.date_utils import get_current_local_datetime
from src.persistence.models import TradingEvaluation


def resolve_shadowing_regime_from_cache() -> Optional[TradingShadowingRegime]:
    if not settings.TRADING_SHADOWING_ENABLED:
        return None

    cached_snapshot = trading_shadowing_cache.get_shadowing_snapshot()
    if cached_snapshot is not None:
        return cached_snapshot.regime

    cached_shadowing_regime: Optional[TradingShadowingRegimePayload] = (
        trading_shadowing_cache.get_trading_shadowing_regime_state()
    )
    if cached_shadowing_regime is None:
        return None
    return TradingShadowingRegime.model_validate(cached_shadowing_regime.model_dump(mode="json"))


def build_trading_evaluation(
        candidate: TradingCandidate,
        rank: int,
        decision: str,
        sizing_multiplier: float,
        order_notional_usd: float,
        free_cash_before_usd: float,
        free_cash_after_usd: float,
) -> TradingEvaluation:
    token = candidate.token
    market_snapshot = candidate.market_snapshot

    shadowing_metrics = None
    if candidate.shadowing_diagnostics.evaluated_metrics and settings.TRADING_SHADOWING_ENABLED:
        shadowing_metrics = list(candidate.shadowing_diagnostics.evaluated_metrics)

    cortex_inference_summary: Optional[TradingCortexInferenceSnapshot] = None
    inference_snapshot = candidate.cortex_diagnostics.inference_snapshot
    if inference_snapshot is not None and inference_snapshot.model_ready:
        cortex_inference_summary = inference_snapshot

    return TradingEvaluation(
        token_symbol=token.symbol.upper(),
        blockchain_network=token.chain.value,
        token_address=str(token.token_address),
        pair_address=str(token.pair_address),
        price_usd=market_snapshot.price_usd,
        price_native=market_snapshot.price_native,
        candidate_rank=rank,
        quality_score=candidate.quality_score,
        ai_adjusted_quality_score=candidate.ai_analysis.adjusted_quality_score,
        ai_probability_take_profit_before_stop_loss=candidate.ai_analysis.buy_probability,
        ai_quality_score_delta=candidate.ai_analysis.quality_delta,
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
        evaluated_at=get_current_local_datetime(),
        execution_decision=decision.upper(),
        sizing_multiplier=sizing_multiplier,
        order_notional_value_usd=order_notional_usd,
        free_cash_before_execution_usd=free_cash_before_usd,
        free_cash_after_execution_usd=free_cash_after_usd,
        shadowing_regime=resolve_shadowing_regime_from_cache(),
        shadowing_metrics=shadowing_metrics,
        cortex_inference_summary=cortex_inference_summary,
        screener_envelope=candidate.screener_envelope,
        raw_configuration_settings=_to_dict(settings),
    )
