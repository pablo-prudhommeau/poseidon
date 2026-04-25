from __future__ import annotations

from src.api.http.analytics_aggregation_service import METRIC_DEFINITIONS
from src.configuration.config import settings
from src.core.trading.shadowing.shadow_analytics_intelligence import find_decile_index_for_value
from src.core.trading.shadowing.shadow_trading_structures import ShadowIntelligenceSnapshot
from src.core.trading.trading_structures import TradingCandidate
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

METRIC_ACCESSOR_MAP: dict[str, object] = {
    metric_definition.key: metric_definition.accessor
    for metric_definition in METRIC_DEFINITIONS
}


def apply_shadowing_decile_toxicity_filter(
        candidates: list[TradingCandidate],
        snapshot: ShadowIntelligenceSnapshot,
) -> list[TradingCandidate]:
    if not snapshot.is_activated:
        logger.debug("[TRADING][EVALUATOR][SHADOW_TOXICITY] Shadow intelligence not activated, bypassing filter")
        return candidates

    toxic_win_rate_threshold = settings.TRADING_SHADOWING_TOXIC_WIN_RATE_THRESHOLD
    minimum_metric_influence = settings.TRADING_SHADOWING_MIN_METRIC_INFLUENCE

    high_influence_metrics = [
        metric_snapshot for metric_snapshot in snapshot.metric_snapshots
        if metric_snapshot.influence_score >= minimum_metric_influence
    ]

    if not high_influence_metrics:
        logger.debug("[TRADING][EVALUATOR][SHADOW_TOXICITY] No high-influence metrics found, bypassing filter")
        return candidates

    retained: list[TradingCandidate] = []

    for candidate in candidates:
        is_toxic = False
        toxic_reason = ""

        for metric_snapshot in high_influence_metrics:
            accessor = METRIC_ACCESSOR_MAP.get(metric_snapshot.metric_key)
            if accessor is None:
                continue

            try:
                candidate_value = _extract_metric_value_from_candidate(candidate, metric_snapshot.metric_key)
            except Exception:
                continue

            if candidate_value is None:
                continue

            decile_index = find_decile_index_for_value(candidate_value, metric_snapshot.decile_edges)
            if decile_index < len(metric_snapshot.decile_win_rates):
                decile_win_rate = metric_snapshot.decile_win_rates[decile_index]
                if decile_win_rate < toxic_win_rate_threshold:
                    is_toxic = True
                    toxic_reason = f"{metric_snapshot.metric_key} decile {decile_index} win_rate={decile_win_rate:.2f} < {toxic_win_rate_threshold:.2f} (influence={metric_snapshot.influence_score:.1f})"
                    break

        if is_toxic:
            logger.debug("[TRADING][EVALUATOR][SHADOW_TOXICITY] %s rejected — %s", candidate.token.symbol, toxic_reason)
        else:
            retained.append(candidate)

    if len(retained) < len(candidates):
        logger.info("[TRADING][EVALUATOR][SHADOW_TOXICITY] Retained %d / %d candidates", len(retained), len(candidates))
    else:
        logger.debug("[TRADING][EVALUATOR][SHADOW_TOXICITY] All %d candidates passed", len(candidates))

    return retained


def _extract_metric_value_from_candidate(candidate: TradingCandidate, metric_key: str) -> float | None:
    token_information = candidate.dexscreener_token_information
    extraction_map = {
        "quality_score": lambda: candidate.quality_score,
        "ai_adjusted_quality_score": lambda: candidate.ai_adjusted_quality_score,
        "liquidity_usd": lambda: token_information.liquidity.usd if token_information.liquidity else None,
        "market_cap_usd": lambda: token_information.market_cap,
        "volume_m5_usd": lambda: token_information.volume.m5 if token_information.volume else None,
        "volume_h1_usd": lambda: token_information.volume.h1 if token_information.volume else None,
        "volume_h6_usd": lambda: token_information.volume.h6 if token_information.volume else None,
        "volume_h24_usd": lambda: token_information.volume.h24 if token_information.volume else None,
        "price_change_m5": lambda: token_information.price_change.m5 if token_information.price_change else None,
        "price_change_h1": lambda: token_information.price_change.h1 if token_information.price_change else None,
        "price_change_h6": lambda: token_information.price_change.h6 if token_information.price_change else None,
        "price_change_h24": lambda: token_information.price_change.h24 if token_information.price_change else None,
        "token_age_hours": lambda: token_information.age_hours,
        "transaction_count_m5": lambda: token_information.transactions.m5.total_transactions if token_information.transactions and token_information.transactions.m5 else None,
        "transaction_count_h1": lambda: token_information.transactions.h1.total_transactions if token_information.transactions and token_information.transactions.h1 else None,
        "transaction_count_h6": lambda: token_information.transactions.h6.total_transactions if token_information.transactions and token_information.transactions.h6 else None,
        "transaction_count_h24": lambda: token_information.transactions.h24.total_transactions if token_information.transactions and token_information.transactions.h24 else None,
        "buy_to_sell_ratio": lambda: _compute_buy_to_sell_ratio(token_information),
        "fully_diluted_valuation_usd": lambda: token_information.fully_diluted_valuation,
        "dexscreener_boost": lambda: token_information.boost,
    }

    extractor = extraction_map.get(metric_key)
    if extractor is None:
        return None

    value = extractor()
    if value is not None and isinstance(value, (int, float)):
        return float(value)
    return None


def _compute_buy_to_sell_ratio(token_information) -> float | None:
    transactions = token_information.transactions
    if not transactions:
        return None
    reference_bucket = transactions.h1 if transactions.h1 else transactions.h24
    if not reference_bucket:
        return None
    total = reference_bucket.buys + reference_bucket.sells
    if total <= 0:
        return None
    return reference_bucket.buys / total
