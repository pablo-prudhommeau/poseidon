from __future__ import annotations

from src.api.http.api_schemas import (
    TradePayload,
    PositionPayload,
    PortfolioPayload,
    EquityCurvePointPayload,
    AnalyticsPayload,
    AnalyticsScoresPayload,
    AnalyticsAiPayload,
    AnalyticsFundamentalsPayload,
    AnalyticsDecisionPayload,
    AnalyticsOutcomePayload,
    DcaOrderPayload,
    DcaStrategyPayload,
)
from src.core.structures.structures import EquityCurve
from src.core.utils.date_utils import format_datetime_to_local_iso
from src.core.utils.symbol_utils import get_currency_symbol
from src.integrations.aave.aave_structures import AaveLiveMetrics
from src.logging.logger import get_application_logger
from src.persistence.models import Trade, Position, PortfolioSnapshot, Analytics, DcaOrder, DcaStrategy

logger = get_application_logger(__name__)


def serialize_trade(trade: Trade) -> TradePayload:
    return TradePayload(
        id=trade.id,
        trade_side=trade.trade_side.value,
        token_symbol=trade.token_symbol,
        blockchain_network=trade.blockchain_network,
        execution_price=trade.execution_price,
        execution_quantity=trade.execution_quantity,
        transaction_fee=trade.transaction_fee,
        realized_profit_and_loss=trade.realized_profit_and_loss,
        execution_status=trade.execution_status.value,
        token_address=trade.token_address,
        pair_address=trade.pair_address,
        transaction_hash=trade.transaction_hash,
        created_at=format_datetime_to_local_iso(trade.created_at),
    )


def serialize_position(position: Position, last_price: float) -> PositionPayload:
    return PositionPayload(
        id=position.id,
        token_symbol=position.token_symbol,
        token_address=position.token_address,
        pair_address=position.pair_address,
        open_quantity=position.open_quantity,
        entry_price=position.entry_price,
        take_profit_tier_1_price=position.take_profit_tier_1_price,
        take_profit_tier_2_price=position.take_profit_tier_2_price,
        stop_loss_price=position.stop_loss_price,
        position_phase=position.position_phase.value,
        blockchain_network=position.blockchain_network,
        opened_at=format_datetime_to_local_iso(position.opened_at),
        updated_at=format_datetime_to_local_iso(position.updated_at),
        closed_at=format_datetime_to_local_iso(position.closed_at) if position.closed_at else None,
        last_price=last_price,
    )


def serialize_portfolio(
        snapshot: PortfolioSnapshot,
        equity_curve: EquityCurve,
        realized_total: float,
        realized_24h: float,
        unrealized: float,
) -> PortfolioPayload:
    return PortfolioPayload(
        total_equity_value=snapshot.total_equity_value,
        available_cash_balance=snapshot.available_cash_balance,
        active_holdings_value=snapshot.active_holdings_value,
        created_at=format_datetime_to_local_iso(snapshot.created_at),
        equity_curve=[
            EquityCurvePointPayload(timestamp_milliseconds=p.timestamp_milliseconds, total_equity_value=p.equity)
            for p in equity_curve.curve_points
        ],
        unrealized_profit_and_loss=unrealized,
        realized_profit_and_loss_total=realized_total,
        realized_profit_and_loss_24h=realized_24h,
    )


def serialize_analytics(row: Analytics) -> AnalyticsPayload:
    return AnalyticsPayload(
        id=row.id,
        token_symbol=row.token_symbol,
        blockchain_network=row.blockchain_network,
        token_address=row.token_address,
        pair_address=row.pair_address,
        evaluated_at=format_datetime_to_local_iso(row.evaluated_at),
        candidate_rank=row.candidate_rank,
        scores=AnalyticsScoresPayload(
            quality_score=row.quality_score,
            statistics_score=row.statistics_score,
            entry_score=row.entry_score,
            final_score=row.final_score,
        ),
        ai=AnalyticsAiPayload(
            ai_probability_take_profit_before_stop_loss=row.ai_probability_take_profit_before_stop_loss,
            ai_quality_score_delta=row.ai_quality_score_delta,
        ),
        fundamentals=AnalyticsFundamentalsPayload(
            token_age_hours=row.token_age_hours,
            volume_m5_usd=row.volume_m5_usd,
            volume_h1_usd=row.volume_h1_usd,
            volume_h6_usd=row.volume_h6_usd,
            volume_h24_usd=row.volume_h24_usd,
            liquidity_usd=row.liquidity_usd,
            price_change_percentage_m5=row.price_change_percentage_m5,
            price_change_percentage_h1=row.price_change_percentage_h1,
            price_change_percentage_h6=row.price_change_percentage_h6,
            price_change_percentage_h24=row.price_change_percentage_h24,
            transaction_count_m5=row.transaction_count_m5,
            transaction_count_h1=row.transaction_count_h1,
            transaction_count_h6=row.transaction_count_h6,
            transaction_count_h24=row.transaction_count_h24,
        ),
        decision=AnalyticsDecisionPayload(
            execution_decision=row.execution_decision,
            execution_decision_reason=row.execution_decision_reason,
            sizing_multiplier=row.sizing_multiplier,
            order_notional_value_usd=row.order_notional_value_usd,
            free_cash_before_execution_usd=row.free_cash_before_execution_usd,
            free_cash_after_execution_usd=row.free_cash_after_execution_usd,
        ),
        outcome=AnalyticsOutcomePayload(
            has_trade_outcome=row.has_trade_outcome,
            outcome_trade_identifier=row.outcome_trade_identifier,
            outcome_closed_at=format_datetime_to_local_iso(row.outcome_closed_at) if row.outcome_closed_at else None,
            outcome_holding_duration_minutes=row.outcome_holding_duration_minutes,
            outcome_realized_profit_and_loss_percentage=row.outcome_realized_profit_and_loss_percentage,
            outcome_realized_profit_and_loss_usd=row.outcome_realized_profit_and_loss_usd,
            outcome_was_profitable=row.outcome_was_profitable,
            outcome_exit_reason=row.outcome_exit_reason,
        ),
        raw_dexscreener_payload=row.raw_dexscreener_payload,
        raw_configuration_settings=row.raw_configuration_settings,
    )


def serialize_dca_order(order: DcaOrder) -> DcaOrderPayload:
    return DcaOrderPayload(
        id=order.id,
        strategy_id=order.strategy_id,
        planned_execution_date=format_datetime_to_local_iso(order.planned_execution_date),
        planned_source_asset_amount=order.planned_source_asset_amount,
        executed_source_asset_amount=order.executed_source_asset_amount,
        executed_target_asset_amount=order.executed_target_asset_amount,
        order_status=order.order_status.value,
        transaction_hash=order.transaction_hash,
        actual_execution_price=order.actual_execution_price,
        executed_at=format_datetime_to_local_iso(order.executed_at) if order.executed_at else None,
        allocation_decision_description=order.allocation_decision_description,
    )


def serialize_dca_strategy(strategy: DcaStrategy, live_metrics: AaveLiveMetrics) -> DcaStrategyPayload:
    return DcaStrategyPayload(
        id=strategy.id,
        blockchain_network=strategy.blockchain_network,
        source_asset_symbol=strategy.source_asset_symbol,
        source_asset_address=strategy.source_asset_address,
        source_asset_decimals=strategy.source_asset_decimals,
        source_asset_currency_symbol=get_currency_symbol(strategy.source_asset_symbol),
        target_asset_symbol=strategy.target_asset_symbol,
        target_asset_address=strategy.target_asset_address,
        target_asset_currency_symbol=get_currency_symbol(strategy.target_asset_symbol),
        binance_trading_pair=strategy.binance_trading_pair,
        total_allocated_budget=strategy.total_allocated_budget,
        total_planned_executions=strategy.total_planned_executions,
        amount_per_execution_order=strategy.amount_per_execution_order,
        slippage_tolerance=strategy.slippage_tolerance,
        average_unit_price_elasticity_factor=strategy.average_unit_price_elasticity_factor,
        current_cycle_index=strategy.current_cycle_index,
        previous_all_time_high_price=strategy.previous_all_time_high_price,
        previous_bull_market_amplitude_percentage=strategy.previous_bull_market_amplitude_percentage,
        curve_flattening_factor=strategy.curve_flattening_factor,
        bear_market_bottom_multiplier=strategy.bear_market_bottom_multiplier,
        minimum_bull_market_multiplier=strategy.minimum_bull_market_multiplier,
        aave_estimated_annual_percentage_yield=strategy.aave_estimated_annual_percentage_yield,
        realized_aave_yield_amount=strategy.realized_aave_yield_amount,
        last_yield_calculation_timestamp=format_datetime_to_local_iso(strategy.last_yield_calculation_timestamp),
        strategy_start_date=format_datetime_to_local_iso(strategy.strategy_start_date),
        strategy_end_date=format_datetime_to_local_iso(strategy.strategy_end_date),
        strategy_status=strategy.strategy_status.value,
        bypass_security_approval=strategy.bypass_security_approval,
        available_dry_powder=strategy.available_dry_powder,
        total_deployed_amount=strategy.total_deployed_amount,
        average_purchase_price=strategy.average_purchase_price,
        historical_backtest_payload=strategy.historical_backtest_payload,
        created_at=format_datetime_to_local_iso(strategy.created_at),
        updated_at=format_datetime_to_local_iso(strategy.updated_at),
        execution_orders=[serialize_dca_order(o) for o in (strategy.execution_orders or [])],
        live_aave_apy=live_metrics.supply_apy,
        live_market_price=live_metrics.asset_out_price_usd
    )
