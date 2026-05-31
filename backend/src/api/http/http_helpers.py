from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from src.api.http.api_schemas import (
    AnalyticsResponse,
    DcaOrdersResponse,
    DcaStrategiesResponse,
    DcaStrategyCreatePayload,
    DcaStrategyCreateResponse,
    TradingEvaluationPayload,
    TradingPositionPayload,
    TradingPositionsResponse,
)
from src.api.serializers import (
    serialize_dca_order,
    serialize_dca_strategy,
    serialize_shadowing_verdict_as_trading_evaluation_payload,
    serialize_trading_evaluation,
    serialize_trading_position,
)
from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.core.dca.dca_backtester import DcaBacktester
from src.core.dca.dca_scheduler import DcaScheduler
from src.core.dca.dca_structures import DcaStrategyStatus
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.analytics.trading_analytics_helpers import (
    build_exit_reason_by_evaluation_id,
    map_trading_evaluation,
    map_trading_shadowing_verdict,
)
from src.core.trading.analytics.trading_analytics_service import build_analytics_response
from src.core.trading.cache.trading_cache import trading_cache
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.aave.aave_executor import AaveExecutor
from src.logging.logger import get_application_logger
from src.persistence.dao.dca_order_dao import DcaOrderDao
from src.persistence.dao.dca_strategy_dao import DcaStrategyDao
from src.persistence.dao.trading_evaluation_dao import TradingEvaluationDao
from src.persistence.dao.trading_position_dao import TradingPositionDao
from src.persistence.dao.trading_shadowing_probe_dao import TradingShadowingProbeDao
from src.persistence.dao.trading_shadowing_verdict_dao import TradingShadowingVerdictDao
from src.persistence.models import DcaStrategy, PositionPhase

logger = get_application_logger(__name__)

aave_executor_client = AaveExecutor()


def build_live_trading_analytics_response(
        database_session: Session,
        limit_results: int,
) -> AnalyticsResponse:
    evaluation_dao = TradingEvaluationDao(database_session)
    position_dao = TradingPositionDao(database_session)

    evaluation_rows = evaluation_dao.retrieve_recent_evaluations(limit_count=limit_results)
    total_evaluations = evaluation_dao.count_total_evaluations()
    staled_positions = position_dao.retrieve_by_phase(PositionPhase.STALED)
    staled_token_addresses: set[str] = {position.token_address for position in staled_positions}

    evaluation_ids = [evaluation_row.id for evaluation_row in evaluation_rows]
    linked_positions = position_dao.retrieve_by_evaluation_ids(evaluation_ids)
    exit_reason_by_evaluation_id = build_exit_reason_by_evaluation_id(linked_positions)

    analytics_records = [
        map_trading_evaluation(
            evaluation_row,
            exit_reason=exit_reason_by_evaluation_id.get(evaluation_row.id, ""),
        )
        for evaluation_row in evaluation_rows
    ]
    return build_analytics_response(analytics_records, total_evaluations, staled_token_addresses)


def build_shadow_trading_analytics_response(
        database_session: Session,
        limit_results: int,
) -> AnalyticsResponse:
    verdict_dao = TradingShadowingVerdictDao(database_session)
    probe_dao = TradingShadowingProbeDao(database_session)

    resolved_verdicts = verdict_dao.retrieve_recent_resolved(limit_count=limit_results)
    total_evaluations = probe_dao.count_total_probes()
    analytics_records = [map_trading_shadowing_verdict(verdict) for verdict in resolved_verdicts]
    return build_analytics_response(analytics_records, total_evaluations, set())


def build_trading_evaluation_payload_for_evaluation_id(
        evaluation_id: int,
        database_session: Session,
) -> Optional[TradingEvaluationPayload]:
    evaluation_dao = TradingEvaluationDao(database_session)
    evaluation = evaluation_dao.retrieve_by_id(evaluation_id)
    if evaluation is None:
        return None

    evaluation_payload = serialize_trading_evaluation(evaluation)
    linked_position = resolve_linked_position_payload_for_evaluation(evaluation_id, database_session)
    if linked_position is not None:
        return evaluation_payload.model_copy(update={"linked_position": linked_position})
    return evaluation_payload


def build_shadow_evaluation_payloads_for_pair(
        pair_address: str,
        database_session: Session,
        limit_count: int = 100,
) -> List[TradingEvaluationPayload]:
    verdict_dao = TradingShadowingVerdictDao(database_session)
    resolved_verdicts = verdict_dao.retrieve_resolved_for_pair(pair_address, limit_count=limit_count)
    return [
        serialize_shadowing_verdict_as_trading_evaluation_payload(verdict)
        for verdict in resolved_verdicts
    ]


def build_open_positions_response(database_session: Session) -> TradingPositionsResponse:
    trading_state = trading_cache.get_trading_state()
    cached_positions = trading_state.positions

    if cached_positions is not None:
        return TradingPositionsResponse(positions=cached_positions)

    position_dao = TradingPositionDao(database_session)
    open_positions = position_dao.retrieve_open_positions()
    serialized_positions = [
        serialize_trading_position(position, last_price=position.entry_price)
        for position in open_positions
    ]
    return TradingPositionsResponse(positions=serialized_positions)


def resolve_linked_position_payload_for_evaluation(
        evaluation_id: int,
        database_session: Session,
) -> Optional[TradingPositionPayload]:
    trading_state = trading_cache.get_trading_state()
    cached_positions = trading_state.positions
    if cached_positions is not None:
        for cached_position in cached_positions:
            if cached_position.evaluation_id == evaluation_id:
                return cached_position

    position_dao = TradingPositionDao(database_session)
    position_record = position_dao.retrieve_latest_by_evaluation_id(evaluation_id)
    if position_record is None:
        return None

    last_price_candidate: Optional[float] = None
    if trading_state.position_prices is not None:
        for position_price_entry in trading_state.position_prices:
            if position_price_entry.position_id == position_record.id:
                last_price_candidate = position_price_entry.last_price
                break

    return serialize_trading_position(position_record, last_price=last_price_candidate)


def compute_dca_amount_per_execution_order(strategy_payload: DcaStrategyCreatePayload) -> float:
    if strategy_payload.total_planned_executions <= 0:
        return 0.0
    return strategy_payload.total_allocated_budget / strategy_payload.total_planned_executions


def build_dca_strategy_entity(
        strategy_payload: DcaStrategyCreatePayload,
        historical_backtest_payload: dict,
        current_local_time: datetime,
) -> DcaStrategy:
    return DcaStrategy(
        blockchain_network=strategy_payload.blockchain_network.value,
        source_asset_symbol=strategy_payload.source_asset_symbol,
        source_asset_address=strategy_payload.source_asset_address,
        source_asset_decimals=strategy_payload.source_asset_decimals,
        target_asset_symbol=strategy_payload.target_asset_symbol,
        target_asset_address=strategy_payload.target_asset_address,
        binance_trading_pair=strategy_payload.binance_trading_pair,
        total_allocated_budget=strategy_payload.total_allocated_budget,
        total_planned_executions=strategy_payload.total_planned_executions,
        amount_per_execution_order=compute_dca_amount_per_execution_order(strategy_payload),
        slippage_tolerance=strategy_payload.slippage_tolerance,
        average_unit_price_elasticity_factor=strategy_payload.average_unit_price_elasticity_factor,
        current_cycle_index=strategy_payload.current_cycle_index,
        previous_all_time_high_price=strategy_payload.previous_all_time_high_price,
        previous_bull_market_amplitude_percentage=strategy_payload.previous_bull_market_amplitude_percentage,
        curve_flattening_factor=strategy_payload.curve_flattening_factor,
        bear_market_bottom_multiplier=strategy_payload.bear_market_bottom_multiplier,
        minimum_bull_market_multiplier=strategy_payload.minimum_bull_market_multiplier,
        aave_estimated_annual_percentage_yield=strategy_payload.aave_estimated_annual_percentage_yield,
        strategy_start_date=strategy_payload.strategy_start_date,
        strategy_end_date=strategy_payload.strategy_end_date,
        strategy_status=DcaStrategyStatus.ACTIVE.value,
        bypass_security_approval=strategy_payload.bypass_security_approval,
        available_dry_powder=0.0,
        total_deployed_amount=0.0,
        average_purchase_price=0.0,
        realized_aave_yield_amount=0.0,
        last_yield_calculation_timestamp=current_local_time,
        historical_backtest_payload=historical_backtest_payload,
        created_at=current_local_time,
        updated_at=current_local_time,
    )


async def create_dca_strategy_from_payload(
        database_session: Session,
        strategy_payload: DcaStrategyCreatePayload,
) -> DcaStrategyCreateResponse:
    dca_strategy_dao = DcaStrategyDao(database_session)
    dca_order_dao = DcaOrderDao(database_session)

    backtest_comparative_snapshot = await DcaBacktester.generate_comparative_snapshot(
        symbol=strategy_payload.binance_trading_pair,
        start_date=strategy_payload.bear_market_start_date,
        end_date=strategy_payload.bear_market_end_date,
        total_budget=strategy_payload.total_allocated_budget,
        total_execution_cycles=strategy_payload.total_planned_executions,
        price_elasticity_aggressiveness=strategy_payload.average_unit_price_elasticity_factor,
    )

    current_local_time = get_current_local_datetime()
    new_dca_strategy = build_dca_strategy_entity(
        strategy_payload,
        backtest_comparative_snapshot.model_dump(mode="json"),
        current_local_time,
    )

    saved_dca_strategy = dca_strategy_dao.save(new_dca_strategy)
    scheduled_orders = DcaScheduler.generate_linear_execution_calendar(saved_dca_strategy)
    dca_order_dao.bulk_save(scheduled_orders)

    cache_invalidator.mark_dirty(CacheRealm.DCA_STRATEGIES)

    return DcaStrategyCreateResponse(
        message="Strategy successfully created",
        strategy_id=saved_dca_strategy.id,
        orders_count=len(scheduled_orders),
    )


async def build_dca_strategies_response(database_session: Session) -> DcaStrategiesResponse:
    dca_strategy_dao = DcaStrategyDao(database_session)
    registered_strategies = dca_strategy_dao.retrieve_all()
    strategy_payloads = []
    for registered_strategy in registered_strategies:
        live_metrics = await aave_executor_client.get_live_metrics(
            chain=BlockchainNetwork(registered_strategy.blockchain_network.lower()),
            asset_in_address=registered_strategy.source_asset_address,
            asset_out_address=registered_strategy.target_asset_address,
        )
        strategy_payloads.append(serialize_dca_strategy(registered_strategy, live_metrics))
    return DcaStrategiesResponse(strategies=strategy_payloads)


def build_dca_orders_response(database_session: Session, strategy_uid: int) -> DcaOrdersResponse:
    dca_order_dao = DcaOrderDao(database_session)
    strategy_orders = dca_order_dao.retrieve_by_strategy(strategy_uid)
    serialized_orders = [serialize_dca_order(execution_order) for execution_order in strategy_orders]
    return DcaOrdersResponse(orders=serialized_orders)
