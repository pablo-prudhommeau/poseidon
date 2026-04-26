from __future__ import annotations

from src.core.trading.analytics.trading_analytics_structures import AnalyticsOutcomeRecord
from src.persistence.models import TradingShadowingProbe, TradingEvaluation, TradingOutcome

DECILE_COUNT = 10
MINIMUM_POINTS_PER_BUCKET = 10
ROLLING_WINDOW_SIZE = 100


def quantile(sorted_values: list[float], quantile_fraction: float) -> float:
    length = len(sorted_values)
    if length == 0:
        return 0.0
    position = (length - 1) * quantile_fraction
    base_index = int(position)
    remainder = position - base_index
    lower_value = sorted_values[base_index]
    upper_value = sorted_values[min(base_index + 1, length - 1)]
    return lower_value + (upper_value - lower_value) * remainder


def compute_decile_edges(values: list[float | None]) -> list[float]:
    valid_values = [v for v in values if v is not None]
    if not valid_values:
        return [0.0] * (DECILE_COUNT + 1)

    sorted_values = sorted(valid_values)
    edges: list[float] = []
    for decile_index in range(DECILE_COUNT + 1):
        edges.append(quantile(sorted_values, decile_index / DECILE_COUNT))
    return edges


def assign_bucket_index(value: float | None, edges: list[float]) -> int:
    if value is None:
        return -1
    last_valid_bucket = len(edges) - 2
    for edge_index in range(len(edges) - 1):
        if edges[edge_index] <= value <= edges[edge_index + 1]:
            return min(edge_index, last_valid_bucket)
    return last_valid_bucket


def format_metric_value(value: float, unit: str) -> str:
    if unit == "percent":
        return f"{value:.1f}%"
    if unit in ("usd", "count"):
        absolute_value = abs(value)
        if absolute_value >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        if absolute_value >= 1_000:
            return f"{value / 1_000:.1f}K"
        return f"{value:,.0f}"
    if unit == "hours":
        return f"{value:,.0f}h"
    if unit == "ratio":
        return f"{value:,.2f}"
    if unit == "score":
        return f"{value:,.0f}"
    return f"{value:,.1f}"


def aggregate_evaluation_outcomes(evaluation: TradingEvaluation) -> TradingOutcome | None:
    if not evaluation.outcomes:
        return None

    if len(evaluation.outcomes) == 1:
        return evaluation.outcomes[0]

    total_profit_and_loss_usd = sum(outcome.realized_profit_and_loss_usd for outcome in evaluation.outcomes)
    average_holding_duration_minutes = sum(outcome.holding_duration_minutes for outcome in evaluation.outcomes) / len(evaluation.outcomes)
    is_profitable = total_profit_and_loss_usd > 0

    cost_basis = evaluation.order_notional_value_usd
    if cost_basis and cost_basis > 0:
        total_profit_and_loss_percentage = (total_profit_and_loss_usd / cost_basis) * 100.0
    else:
        total_profit_and_loss_percentage = sum(outcome.realized_profit_and_loss_percentage for outcome in evaluation.outcomes) / len(evaluation.outcomes)

    last_outcome = evaluation.outcomes[-1]

    return TradingOutcome(
        realized_profit_and_loss_usd=total_profit_and_loss_usd,
        realized_profit_and_loss_percentage=total_profit_and_loss_percentage,
        holding_duration_minutes=average_holding_duration_minutes,
        is_profitable=is_profitable,
        exit_reason=last_outcome.exit_reason,
        occurred_at=last_outcome.occurred_at
    )


def map_trading_evaluation(evaluation: TradingEvaluation) -> AnalyticsOutcomeRecord:
    outcome = aggregate_evaluation_outcomes(evaluation)
    has_outcome = outcome is not None
    return AnalyticsOutcomeRecord(
        token_symbol=evaluation.token_symbol,
        token_address=evaluation.token_address,
        quality_score=evaluation.quality_score,
        ai_adjusted_quality_score=evaluation.ai_adjusted_quality_score,
        liquidity_usd=evaluation.liquidity_usd,
        market_cap_usd=evaluation.market_cap_usd,
        volume_m5_usd=evaluation.volume_m5_usd,
        volume_h1_usd=evaluation.volume_h1_usd,
        volume_h6_usd=evaluation.volume_h6_usd,
        volume_h24_usd=evaluation.volume_h24_usd,
        price_change_percentage_m5=evaluation.price_change_percentage_m5,
        price_change_percentage_h1=evaluation.price_change_percentage_h1,
        price_change_percentage_h6=evaluation.price_change_percentage_h6,
        price_change_percentage_h24=evaluation.price_change_percentage_h24,
        token_age_hours=evaluation.token_age_hours,
        transaction_count_m5=evaluation.transaction_count_m5,
        transaction_count_h1=evaluation.transaction_count_h1,
        transaction_count_h6=evaluation.transaction_count_h6,
        transaction_count_h24=evaluation.transaction_count_h24,
        buy_to_sell_ratio=evaluation.buy_to_sell_ratio,
        fully_diluted_valuation_usd=evaluation.fully_diluted_valuation_usd,
        dexscreener_boost=evaluation.dexscreener_boost,

        has_outcome=has_outcome,
        realized_profit_and_loss_usd=outcome.realized_profit_and_loss_usd if has_outcome else 0.0,
        realized_profit_and_loss_percentage=outcome.realized_profit_and_loss_percentage if has_outcome else 0.0,
        holding_duration_minutes=outcome.holding_duration_minutes if has_outcome else 0.0,
        is_profitable=outcome.is_profitable if has_outcome else False,
        exit_reason=outcome.exit_reason if has_outcome else "",
        occurred_at=outcome.occurred_at if has_outcome else None,
    )


def map_trading_shadowing_probe(probe: TradingShadowingProbe) -> AnalyticsOutcomeRecord:
    verdict = probe.verdict
    has_outcome = verdict is not None and verdict.resolved_at is not None
    return AnalyticsOutcomeRecord(
        token_symbol=probe.token_symbol,
        token_address=probe.token_address,
        quality_score=probe.quality_score,
        ai_adjusted_quality_score=probe.quality_score,
        liquidity_usd=probe.liquidity_usd,
        market_cap_usd=probe.market_cap_usd,
        volume_m5_usd=probe.volume_m5_usd,
        volume_h1_usd=probe.volume_h1_usd,
        volume_h6_usd=probe.volume_h6_usd,
        volume_h24_usd=probe.volume_h24_usd,
        price_change_percentage_m5=probe.price_change_percentage_m5,
        price_change_percentage_h1=probe.price_change_percentage_h1,
        price_change_percentage_h6=probe.price_change_percentage_h6,
        price_change_percentage_h24=probe.price_change_percentage_h24,
        token_age_hours=probe.token_age_hours,
        transaction_count_m5=probe.transaction_count_m5,
        transaction_count_h1=probe.transaction_count_h1,
        transaction_count_h6=probe.transaction_count_h6,
        transaction_count_h24=probe.transaction_count_h24,
        buy_to_sell_ratio=probe.buy_to_sell_ratio,
        fully_diluted_valuation_usd=probe.fully_diluted_valuation_usd,
        dexscreener_boost=probe.dexscreener_boost,

        has_outcome=has_outcome,
        realized_profit_and_loss_usd=verdict.realized_pnl_usd if has_outcome else 0.0,
        realized_profit_and_loss_percentage=verdict.realized_pnl_percentage if has_outcome else 0.0,
        holding_duration_minutes=verdict.holding_duration_minutes if has_outcome else 0.0,
        is_profitable=verdict.is_profitable if has_outcome else False,
        exit_reason=verdict.exit_reason if has_outcome else "",
        occurred_at=verdict.resolved_at if has_outcome else None,
    )
