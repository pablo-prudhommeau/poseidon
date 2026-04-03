from __future__ import annotations

from typing import Optional

from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate, TradingPreEntryDecision, TradingRiskDiagnostics
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def _estimate_buy_ratio(candidate: TradingCandidate) -> float:
    transactions = candidate.dexscreener_token_information.transactions
    if transactions and (transactions.h1 or transactions.h24):
        bucket = transactions.h1 if transactions.h1 else transactions.h24
        buys = bucket.buys
        sells = bucket.sells
        total = buys + sells
        return (buys / total) if total > 0 else 0.5
    return 0.5


def _build_risk_diagnostics(
        liquidity_usd: float,
        percent_5m: Optional[float],
        percent_1h: Optional[float],
        percent_6h: Optional[float],
        percent_24h: Optional[float],
        buy_ratio: float,
) -> TradingRiskDiagnostics:
    return TradingRiskDiagnostics(
        liquidity_usd=liquidity_usd,
        percent_change_5m=percent_5m or 0.0,
        percent_change_1h=percent_1h or 0.0,
        percent_change_6h=percent_6h or 0.0,
        percent_change_24h=percent_24h or 0.0,
        buy_to_sell_ratio=buy_ratio,
    )


def evaluate_pre_entry_decision(candidate: TradingCandidate) -> TradingPreEntryDecision:
    token_information = candidate.dexscreener_token_information
    symbol = token_information.base_token.symbol
    liquidity_usd = token_information.liquidity.usd if token_information.liquidity and token_information.liquidity.usd is not None else 0.0

    pct_5m_raw = token_information.price_change.m5
    pct_1h_raw = token_information.price_change.h1
    pct_6h_raw = token_information.price_change.h6
    pct_24h_raw = token_information.price_change.h24

    pct_5m = float(pct_5m_raw) if isinstance(pct_5m_raw, (int, float)) else None
    pct_1h = float(pct_1h_raw) if isinstance(pct_1h_raw, (int, float)) else None
    pct_6h = float(pct_6h_raw) if isinstance(pct_6h_raw, (int, float)) else None
    pct_24h = float(pct_24h_raw) if isinstance(pct_24h_raw, (int, float)) else None

    buy_ratio = _estimate_buy_ratio(candidate)
    min_liquidity = settings.TRADING_MIN_LIQUIDITY_USD
    max_abs_5m = settings.TRADING_MAX_ABSOLUTE_PERCENT_5M
    max_abs_1h = settings.TRADING_MAX_ABSOLUTE_PERCENT_1H
    overextended_factor = settings.TRADING_RISK_OVEREXTENDED_FACTOR
    weak_buy_flow_ratio = settings.TRADING_RISK_WEAK_BUY_FLOW_RATIO
    weak_buy_flow_min_percent_5m = settings.TRADING_RISK_WEAK_BUY_FLOW_MIN_PERCENT_5M

    if liquidity_usd < min_liquidity:
        logger.debug("[TRADING][FILTER][RISK] %s rejected — low liquidity %.0f < %.0f", symbol, liquidity_usd, min_liquidity)
        diagnostics = _build_risk_diagnostics(liquidity_usd, pct_5m, pct_1h, pct_6h, pct_24h, buy_ratio)
        return TradingPreEntryDecision(is_valid_for_entry=False, decision_reason="low_liquidity", risk_diagnostics_map=diagnostics.as_plain_dict())

    if pct_5m is not None and abs(pct_5m) > max_abs_5m and (pct_1h or 0.0) > max_abs_1h * overextended_factor:
        logger.debug("[TRADING][FILTER][RISK] %s rejected — overextended spike pct5m=%.1f pct1h=%.1f", symbol, pct_5m or -1.0, pct_1h or -1.0)
        diagnostics = _build_risk_diagnostics(liquidity_usd, pct_5m, pct_1h, pct_6h, pct_24h, buy_ratio)
        return TradingPreEntryDecision(is_valid_for_entry=False, decision_reason="overextended_spike", risk_diagnostics_map=diagnostics.as_plain_dict())

    if buy_ratio < weak_buy_flow_ratio and (pct_5m or 0.0) > weak_buy_flow_min_percent_5m:
        logger.debug("[TRADING][FILTER][RISK] %s rejected — weak buy flow ratio=%.2f", symbol, buy_ratio)
        diagnostics = _build_risk_diagnostics(liquidity_usd, pct_5m, pct_1h, pct_6h, pct_24h, buy_ratio)
        return TradingPreEntryDecision(is_valid_for_entry=False, decision_reason="weak_buy_flow", risk_diagnostics_map=diagnostics.as_plain_dict())

    diagnostics = _build_risk_diagnostics(liquidity_usd, pct_5m, pct_1h, pct_6h, pct_24h, buy_ratio)
    return TradingPreEntryDecision(is_valid_for_entry=True, decision_reason="ok", risk_diagnostics_map=diagnostics.as_plain_dict())


def apply_risk_filter(candidates: list[TradingCandidate]) -> list[TradingCandidate]:
    from src.core.trading.analytics.trading_analytics_recorder import TradingAnalyticsRecorder

    retained: list[TradingCandidate] = []
    for candidate in sorted(candidates, key=lambda candidate_item: candidate_item.statistics_score, reverse=True):
        pre_decision = evaluate_pre_entry_decision(candidate)

        if pre_decision.is_valid_for_entry:
            retained.append(candidate)
        else:
            logger.debug("[TRADING][FILTER][RISK] %s — %s", candidate.dexscreener_token_information.base_token.symbol, pre_decision.decision_reason)
            TradingAnalyticsRecorder.persist_and_broadcast_skip(candidate, len(retained) + 1, f"RISK:{pre_decision.decision_reason}")

    if not retained:
        logger.info("[TRADING][FILTER][RISK] Zero candidates after risk filter")
    else:
        logger.info("[TRADING][FILTER][RISK] Retained %d / %d candidates", len(retained), len(candidates))

    return retained
