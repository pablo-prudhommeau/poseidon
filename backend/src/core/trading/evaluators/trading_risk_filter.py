from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate, TradingPreEntryDecision
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def evaluate_pre_entry_decision(candidate: TradingCandidate) -> TradingPreEntryDecision:
    symbol = candidate.token.symbol
    market_snapshot = candidate.market_snapshot
    liquidity_usd = market_snapshot.liquidity_usd
    pct_5m = market_snapshot.price_change_percentage_m5
    pct_1h = market_snapshot.price_change_percentage_h1
    buy_ratio = market_snapshot.buy_to_sell_ratio
    min_liquidity = settings.TRADING_MIN_LIQUIDITY_USD
    max_abs_5m = settings.TRADING_MAX_ABSOLUTE_PERCENT_5M
    max_abs_1h = settings.TRADING_MAX_ABSOLUTE_PERCENT_1H
    overextended_factor = settings.TRADING_RISK_OVEREXTENDED_FACTOR
    weak_buy_flow_ratio = settings.TRADING_RISK_WEAK_BUY_FLOW_RATIO
    weak_buy_flow_min_percent_5m = settings.TRADING_RISK_WEAK_BUY_FLOW_MIN_PERCENT_5M

    if liquidity_usd < min_liquidity:
        logger.debug("[TRADING][FILTER][RISK] %s rejected — low liquidity %.0f < %.0f", symbol, liquidity_usd, min_liquidity)
        return TradingPreEntryDecision(is_valid_for_entry=False, decision_reason="low_liquidity")

    if abs(pct_5m) > max_abs_5m and pct_1h > max_abs_1h * overextended_factor:
        logger.debug("[TRADING][FILTER][RISK] %s rejected — overextended spike pct5m=%.1f pct1h=%.1f", symbol, pct_5m, pct_1h)
        return TradingPreEntryDecision(is_valid_for_entry=False, decision_reason="overextended_spike")

    if buy_ratio < weak_buy_flow_ratio and pct_5m > weak_buy_flow_min_percent_5m:
        logger.debug("[TRADING][FILTER][RISK] %s rejected — weak buy flow ratio=%.2f", symbol, buy_ratio)
        return TradingPreEntryDecision(is_valid_for_entry=False, decision_reason="weak_buy_flow")

    return TradingPreEntryDecision(is_valid_for_entry=True, decision_reason="ok")


def apply_risk_filter(candidates: list[TradingCandidate]) -> list[TradingCandidate]:
    from src.core.trading.trading_service import record_skipped_trading_evaluation

    retained: list[TradingCandidate] = []
    for candidate in sorted(candidates, key=lambda candidate_item: candidate_item.quality_score, reverse=True):
        pre_decision = evaluate_pre_entry_decision(candidate)

        if pre_decision.is_valid_for_entry:
            retained.append(candidate)
        else:
            logger.debug("[TRADING][FILTER][RISK] %s — %s", candidate.token.symbol, pre_decision.decision_reason)
            record_skipped_trading_evaluation(candidate, len(retained) + 1, f"RISK:{pre_decision.decision_reason}")

    if not retained:
        logger.info("[TRADING][FILTER][RISK] Zero candidates after risk filter")
    else:
        logger.info("[TRADING][FILTER][RISK] Retained %d / %d candidates", len(retained), len(candidates))

    return retained
