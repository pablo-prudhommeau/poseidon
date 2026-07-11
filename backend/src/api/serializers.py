from __future__ import annotations

from typing import Optional

from src.api.http.api_schemas import (
    TradingTradePayload,
    TradingPositionPayload,
    TradingPortfolioPayload,
    TradingEquityCurvePointPayload,
    TradingEvaluationPayload,
    TradingEvaluationScoresPayload,
    TradingEvaluationAiPayload,
    TradingEvaluationFundamentalsPayload,
    TradingEvaluationDecisionPayload,
    AaveDcaOrderPayload,
    AaveDcaOrderPipelineOperationsPayload,
    AaveDcaPipelineOperationPayload,
    AaveDcaStrategyPayload,
    TradingEvaluationShadowingDiagnosticsPayload,
    TradingScreenerEnvelopePayload,
    BlockchainCashBalancePayload,
)
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.screener.trading_screener_structures import TRADING_SCREENER_PROVIDER_DEXSCREENER
from src.core.trading.screener.trading_screener_structures import TradingScreenerEnvelope
from src.core.trading.trading_structures import TradingPortfolio
from src.core.trading.trading_utils import get_currency_symbol
from src.core.utils.date_utils import format_datetime_to_local_iso
from src.integrations.aave.aave_structures import AaveLiveMetrics
from src.logging.logger import get_application_logger
from src.persistence.models import (
    TradingEvaluation,
    AaveDcaOrder,
    AaveDcaStrategy,
    TradingTrade,
    TradingPosition,
    TradingShadowingVerdict,
)

logger = get_application_logger(__name__)


def serialize_trading_trade(
        trading_trade: TradingTrade,
        linked_position_id: int,
        evaluation_order_notional_value_usd: float,
) -> TradingTradePayload:
    return TradingTradePayload(
        id=trading_trade.id,
        evaluation_id=trading_trade.evaluation_id,
        trade_side=trading_trade.trade_side.value,
        token_symbol=trading_trade.token_symbol,
        blockchain_network=BlockchainNetwork(trading_trade.blockchain_network.lower()),
        execution_price=trading_trade.execution_price,
        execution_quantity=trading_trade.execution_quantity,
        transaction_fee=trading_trade.transaction_fee,
        realized_profit_and_loss=trading_trade.realized_profit_and_loss,
        execution_status=trading_trade.execution_status.value,
        token_address=trading_trade.token_address,
        pair_address=trading_trade.pair_address,
        transaction_hash=trading_trade.transaction_hash,
        dex_id=trading_trade.dex_id,
        created_at=format_datetime_to_local_iso(trading_trade.created_at),
        linked_position_id=linked_position_id,
        evaluation_order_notional_value_usd=evaluation_order_notional_value_usd,
    )


def serialize_trading_position(
        trading_position: TradingPosition,
        last_price: Optional[float],
        evaluation_order_notional_value_usd: float,
        realized_profit_and_loss_usd: float,
) -> TradingPositionPayload:
    return TradingPositionPayload(
        id=trading_position.id,
        evaluation_id=trading_position.evaluation_id,
        token_symbol=trading_position.token_symbol,
        token_address=trading_position.token_address,
        pair_address=trading_position.pair_address,
        open_quantity=trading_position.open_quantity,
        current_quantity=trading_position.current_quantity,
        entry_price=trading_position.entry_price,
        take_profit_tier_1_price=trading_position.take_profit_tier_1_price,
        take_profit_tier_2_price=trading_position.take_profit_tier_2_price,
        stop_loss_price=trading_position.stop_loss_price,
        position_phase=trading_position.position_phase.value,
        blockchain_network=BlockchainNetwork(trading_position.blockchain_network.lower()),
        dex_id=trading_position.dex_id,
        opened_at=format_datetime_to_local_iso(trading_position.opened_at),
        updated_at=format_datetime_to_local_iso(trading_position.updated_at),
        closed_at=format_datetime_to_local_iso(trading_position.closed_at) if trading_position.closed_at else None,
        last_price=last_price,
        exit_reason=trading_position.exit_reason,
        evaluation_order_notional_value_usd=evaluation_order_notional_value_usd,
        realized_profit_and_loss_usd=realized_profit_and_loss_usd,
    )


def serialize_trading_portfolio(
        portfolio: TradingPortfolio,
        blockchain_balances: list[BlockchainCashBalancePayload],
) -> TradingPortfolioPayload:
    return TradingPortfolioPayload(
        total_equity_value=portfolio.total_equity_value,
        deployable_cash_usd=portfolio.deployable_cash_usd,
        holdings_mark_to_market_usd=portfolio.holdings_mark_to_market_usd,
        wallet_auxiliary_assets_usd=portfolio.wallet_auxiliary_assets_usd,
        total_gas_refill_locked_stablecoin_usd=portfolio.total_gas_refill_locked_stablecoin_usd,
        sizing_capital_usd=portfolio.sizing_capital_usd,
        cumulative_swap_fees_usd=portfolio.cumulative_swap_fees_usd,
        created_at=format_datetime_to_local_iso(portfolio.created_at),
        equity_curve=[
            TradingEquityCurvePointPayload(
                timestamp_milliseconds=curve_point.timestamp_milliseconds,
                total_equity_value=curve_point.total_equity_value,
            )
            for curve_point in portfolio.equity_curve
        ],
        unrealized_profit_and_loss=portfolio.unrealized_profit_and_loss,
        realized_profit_and_loss_total=portfolio.realized_profit_and_loss_total,
        realized_profit_and_loss_24h=portfolio.realized_profit_and_loss_24h,
        realized_profit_and_loss_7d=portfolio.realized_profit_and_loss_7d,
        realized_profit_and_loss_30d=portfolio.realized_profit_and_loss_30d,
        blockchain_balances=blockchain_balances,
    )


def serialize_trading_screener_envelope(envelope: TradingScreenerEnvelope) -> TradingScreenerEnvelopePayload:
    return TradingScreenerEnvelopePayload(
        provider_id=envelope.provider_id,
        payload=envelope.payload,
    )


def serialize_trading_evaluation(row: TradingEvaluation) -> TradingEvaluationPayload:
    return TradingEvaluationPayload(
        id=row.id,
        token_symbol=row.token_symbol,
        blockchain_network=BlockchainNetwork(row.blockchain_network.lower()),
        token_address=row.token_address,
        pair_address=row.pair_address,
        evaluated_at=format_datetime_to_local_iso(row.evaluated_at),
        candidate_rank=row.candidate_rank,
        scores=TradingEvaluationScoresPayload(
            quality_score=row.quality_score,
            ai_adjusted_quality_score=row.ai_adjusted_quality_score,
        ),
        ai=TradingEvaluationAiPayload(
            ai_probability_take_profit_before_stop_loss=row.ai_probability_take_profit_before_stop_loss,
            ai_quality_score_delta=row.ai_quality_score_delta,
        ),
        fundamentals=TradingEvaluationFundamentalsPayload(
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
            buy_to_sell_ratio=row.buy_to_sell_ratio,
            market_cap_usd=row.market_cap_usd,
            fully_diluted_valuation_usd=row.fully_diluted_valuation_usd,
            promotion_score=row.promotion_score,
        ),
        decision=TradingEvaluationDecisionPayload(
            execution_decision=row.execution_decision,
            sizing_multiplier=row.sizing_multiplier,
            order_notional_value_usd=row.order_notional_value_usd,
            free_cash_before_execution_usd=row.free_cash_before_execution_usd,
            free_cash_after_execution_usd=row.free_cash_after_execution_usd,
        ),
        shadowing_diagnostics=TradingEvaluationShadowingDiagnosticsPayload(
            cortex_inference_summary=(
                row.cortex_inference_summary.model_dump(mode="json")
                if row.cortex_inference_summary is not None
                else None
            ),
            shadowing_regime=(
                row.shadowing_regime.model_dump(mode="json")
                if row.shadowing_regime is not None
                else None
            ),
            shadowing_metrics=(
                [metric.model_dump(mode="json") for metric in row.shadowing_metrics]
                if row.shadowing_metrics is not None
                else None
            ),
        ),
        screener_envelope=serialize_trading_screener_envelope(row.screener_envelope),
        raw_configuration_settings=row.raw_configuration_settings,
    )


def serialize_shadowing_verdict_as_trading_evaluation_payload(
        verdict: TradingShadowingVerdict,
) -> TradingEvaluationPayload:
    probe = verdict.probe
    return TradingEvaluationPayload(
        id=verdict.id,
        token_symbol=probe.token_symbol,
        blockchain_network=BlockchainNetwork(probe.blockchain_network.lower()),
        token_address=probe.token_address,
        pair_address=probe.pair_address,
        evaluated_at=format_datetime_to_local_iso(probe.probed_at),
        candidate_rank=probe.candidate_rank,
        scores=TradingEvaluationScoresPayload(
            quality_score=probe.quality_score,
            ai_adjusted_quality_score=probe.quality_score,
        ),
        ai=TradingEvaluationAiPayload(
            ai_probability_take_profit_before_stop_loss=0.0,
            ai_quality_score_delta=0.0,
        ),
        fundamentals=TradingEvaluationFundamentalsPayload(
            token_age_hours=probe.token_age_hours,
            volume_m5_usd=probe.volume_m5_usd,
            volume_h1_usd=probe.volume_h1_usd,
            volume_h6_usd=probe.volume_h6_usd,
            volume_h24_usd=probe.volume_h24_usd,
            liquidity_usd=probe.liquidity_usd,
            price_change_percentage_m5=probe.price_change_percentage_m5,
            price_change_percentage_h1=probe.price_change_percentage_h1,
            price_change_percentage_h6=probe.price_change_percentage_h6,
            price_change_percentage_h24=probe.price_change_percentage_h24,
            transaction_count_m5=probe.transaction_count_m5,
            transaction_count_h1=probe.transaction_count_h1,
            transaction_count_h6=probe.transaction_count_h6,
            transaction_count_h24=probe.transaction_count_h24,
            buy_to_sell_ratio=probe.buy_to_sell_ratio,
            market_cap_usd=probe.market_cap_usd,
            fully_diluted_valuation_usd=probe.fully_diluted_valuation_usd,
            promotion_score=probe.promotion_score,
        ),
        decision=TradingEvaluationDecisionPayload(
            execution_decision="SHADOW_BUY",
            sizing_multiplier=1.0,
            order_notional_value_usd=probe.order_notional_value_usd,
            free_cash_before_execution_usd=0.0,
            free_cash_after_execution_usd=0.0,
        ),
        shadowing_diagnostics=TradingEvaluationShadowingDiagnosticsPayload(
            cortex_inference_summary=(
                probe.cortex_inference_summary.model_dump(mode="json")
                if probe.cortex_inference_summary is not None
                else None
            ),
            shadowing_regime=(
                probe.shadowing_regime.model_dump(mode="json")
                if probe.shadowing_regime is not None
                else None
            ),
            shadowing_metrics=(
                [metric.model_dump(mode="json") for metric in probe.shadowing_metrics]
                if probe.shadowing_metrics is not None
                else None
            ),
        ),
        screener_envelope=TradingScreenerEnvelopePayload(
            provider_id=TRADING_SCREENER_PROVIDER_DEXSCREENER,
            payload={},
        ),
        raw_configuration_settings={},
    )


def serialize_aave_dca_order(order: AaveDcaOrder) -> AaveDcaOrderPayload:
    serialized_pipeline_operations: Optional[AaveDcaOrderPipelineOperationsPayload] = None
    if order.pipeline_operations is not None:
        serialized_pipeline_operations = AaveDcaOrderPipelineOperationsPayload.model_validate(order.pipeline_operations)

    return AaveDcaOrderPayload(
        id=order.id,
        strategy_id=order.strategy_id,
        planned_execution_date=format_datetime_to_local_iso(order.planned_execution_date),
        planned_source_asset_amount=order.planned_source_asset_amount,
        executed_source_asset_amount=order.executed_source_asset_amount,
        executed_target_asset_amount=order.executed_target_asset_amount,
        order_status=order.order_status.value,
        actual_execution_price=order.actual_execution_price,
        executed_at=format_datetime_to_local_iso(order.executed_at) if order.executed_at else None,
        allocation_decision=order.allocation_decision,
        allocation_multiplier=order.allocation_multiplier,
        dry_powder_delta=order.dry_powder_delta,
        reference_market_price=order.reference_market_price,
        pipeline_operations=serialized_pipeline_operations,
        pipeline_attempt_count=order.pipeline_attempt_count,
        next_attempt_at=format_datetime_to_local_iso(order.next_attempt_at) if order.next_attempt_at else None,
        suspension_reason=order.suspension_reason,
    )


def serialize_aave_dca_strategy(strategy: AaveDcaStrategy, live_metrics: AaveLiveMetrics) -> AaveDcaStrategyPayload:
    return AaveDcaStrategyPayload(
        id=strategy.id,
        blockchain_network=BlockchainNetwork(strategy.blockchain_network.lower()),
        source_asset_symbol=strategy.source_asset_symbol,
        source_asset_address=strategy.source_asset_address,
        source_asset_decimals=strategy.source_asset_decimals,
        source_asset_currency_symbol=get_currency_symbol(strategy.source_asset_symbol),
        target_asset_symbol=strategy.target_asset_symbol,
        target_asset_address=strategy.target_asset_address,
        target_asset_decimals=strategy.target_asset_decimals,
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
        execution_orders=[serialize_aave_dca_order(execution_order) for execution_order in (strategy.execution_orders or [])],
        live_aave_apy=live_metrics.supply_apy,
        live_market_price=live_metrics.asset_out_price_usd
    )
