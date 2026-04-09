from __future__ import annotations

import asyncio
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.http.api_schemas import (
    DcaStrategyCreatePayload,
    SystemHealthPayload,
    SystemHealthComponentsPayload,
    SystemHealthComponentPayload,
    TradingPaperResetPayload,
    DcaStrategyCreateResponse,
    DcaStrategiesResponse,
    DcaOrdersResponse,
    TradingEvaluationsResponse,
    TradingPositionsResponse, 
    DcaStrategyPayload,
    AnalyticsAggregatedResponse,
)
from src.api.serializers import (
    serialize_trading_evaluation,
    serialize_dca_strategy,
    serialize_dca_order,
    serialize_trading_position,
)
from src.api.websocket.websocket_hub import schedule_full_recompute_broadcast
from src.configuration.config import settings
from src.core.dca.dca_backtester import DcaBacktester
from src.core.dca.dca_scheduler import DcaScheduler
from src.core.structures.structures import Token, DcaStrategyStatus
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.aave.aave_executor import AaveExecutor
from src.integrations.dexscreener.dexscreener_client import fetch_dexscreener_token_information_list
from src.logging.logger import get_application_logger
from src.persistence import service
from src.persistence.dao.dca.dca_order_dao import DcaOrderDao
from src.persistence.dao.dca.dca_strategy_dao import DcaStrategyDao
from src.persistence.dao.trading.trading_evaluation_dao import TradingEvaluationDao
from src.persistence.dao.trading.trading_portfolio_snapshot_dao import TradingPortfolioSnapshotDao
from src.persistence.dao.trading.trading_position_dao import TradingPositionDao
from src.persistence.db import get_database_session
from src.persistence.models import DcaStrategy

router = APIRouter()
logger = get_application_logger(__name__)

aave_executor_client = AaveExecutor()


@router.get("/api/health", tags=["health"])
async def get_health_status(database_session: Session = Depends(get_database_session)) -> SystemHealthPayload:
    logger.debug("[HTTP][HEALTH][DB] Initiating health check sequence")
    current_timestamp = get_current_local_datetime().isoformat()
    is_database_connected = False

    try:
        database_session.execute(text("SELECT 1"))
        is_database_connected = True
        logger.info("[HTTP][HEALTH][DB] Database connectivity successfully validated")
    except Exception as exception:
        logger.exception("[HTTP][HEALTH][DB] Health check database connectivity failed: %s", exception)

    return SystemHealthPayload(
        status="ok" if is_database_connected else "degraded",
        timestamp=current_timestamp,
        components=SystemHealthComponentsPayload(
            database=SystemHealthComponentPayload(ok=is_database_connected)
        ),
    )


@router.post("/api/paper/reset", tags=["paper"])
def reset_paper_mode(database_session: Session = Depends(get_database_session)) -> TradingPaperResetPayload:
    logger.debug("[HTTP][PAPER][RESET] Initiating paper mode reset process")
    service.reset_paper(database_session)
    
    portfolio_dao = TradingPortfolioSnapshotDao(database_session)
    if not portfolio_dao.retrieve_latest_snapshot():
        portfolio_dao.create_snapshot(
            equity=settings.PAPER_STARTING_CASH,
            cash=settings.PAPER_STARTING_CASH,
            holdings=0.0
        )
        
    logger.info("[HTTP][PAPER][RESET] Paper mode has been reset and initial cash properly ensured")

    try:
        event_loop = asyncio.get_running_loop()
        if event_loop.is_running() and not event_loop.is_closed():
            schedule_full_recompute_broadcast()
            logger.info("[HTTP][PAPER][REBROADCAST] Scheduled immediate recompute broadcast after reset")
        else:
            logger.debug("[HTTP][PAPER][REBROADCAST] No running event loop detected, user interface will refresh on next orchestrator tick")
    except RuntimeError as exception:
        logger.debug("[HTTP][PAPER][REBROADCAST] Event loop runtime error encountered, user interface will refresh on next orchestrator tick: %s", exception)

    return TradingPaperResetPayload(ok=True)


@router.get("/api/analytics", tags=["analytics"])
async def get_analytics_history(
        limit_results: int = Query(5000, ge=1, le=10000),
        database_session: Session = Depends(get_database_session),
) -> TradingEvaluationsResponse:
    logger.debug("[HTTP][ANALYTICS][FETCH] Retrieving recent analytics history with limit %s", limit_results)
    evaluation_dao = TradingEvaluationDao(database_session)
    evaluation_rows = evaluation_dao.retrieve_recent_evaluations(limit_count=limit_results)
    serialized_evaluations = [serialize_trading_evaluation(evaluation_row) for evaluation_row in evaluation_rows]
    logger.info("[HTTP][EVALUATION][FETCH] Successfully retrieved %s evaluation records", len(serialized_evaluations))
    return TradingEvaluationsResponse(evaluations=serialized_evaluations)


@router.get("/api/analytics/aggregated", tags=["analytics"])
async def get_aggregated_analytics(
        limit_results: int = Query(5000, ge=1, le=10000),
        database_session: Session = Depends(get_database_session),
) -> AnalyticsAggregatedResponse:
    from src.api.http.analytics_aggregation_service import build_aggregated_analytics
    from src.persistence.models import PositionPhase

    logger.debug("[HTTP][ANALYTICS][AGGREGATED] Retrieving and aggregating analytics with limit %s", limit_results)
    evaluation_dao = TradingEvaluationDao(database_session)
    position_dao = TradingPositionDao(database_session)

    evaluation_rows = evaluation_dao.retrieve_recent_evaluations(limit_count=limit_results)

    staled_positions = position_dao.retrieve_by_phase(PositionPhase.STALED)
    staled_token_addresses: set[str] = {position.token_address for position in staled_positions}

    aggregated_response = build_aggregated_analytics(evaluation_rows, staled_token_addresses)
    logger.info("[HTTP][ANALYTICS][AGGREGATED] Successfully aggregated %s evaluations", len(evaluation_rows))
    return aggregated_response


@router.get("/api/positions", tags=["positions"])
async def get_open_positions_list(database_session: Session = Depends(get_database_session)) -> TradingPositionsResponse:
    logger.debug("[HTTP][POSITIONS][FETCH] Retrieving currently open positions")
    position_dao = TradingPositionDao(database_session)
    open_positions = position_dao.retrieve_open_positions()

    tokens_list: List[Token] = [
        Token(
            chain=position.blockchain_network,
            symbol=position.token_symbol,
            token_address=position.token_address,
            pair_address=position.pair_address
        )
        for position in open_positions
    ]
    token_information_list = await fetch_dexscreener_token_information_list(tokens_list)

    serialized_positions = []
    for position in open_positions:
        last_known_price = next(
            (
                token_information.price_usd for token_information in token_information_list
                if token_information.chain_id == position.blockchain_network
                   and token_information.base_token.address == position.token_address
                   and token_information.pair_address == position.pair_address
            ),
            None,
        )
        serialized_positions.append(serialize_trading_position(position, last_price=last_known_price))

    logger.info("[HTTP][POSITIONS][FETCH] Successfully retrieved %s open positions", len(serialized_positions))
    return TradingPositionsResponse(positions=serialized_positions)


@router.post("/api/dca/strategies", tags=["dca"])
async def create_new_dca_strategy(
        strategy_payload: DcaStrategyCreatePayload,
        database_session: Session = Depends(get_database_session),
) -> DcaStrategyCreateResponse:
    logger.debug("[HTTP][DCA][STRATEGY][CREATE] Initiating DCA strategy creation for symbol %s", strategy_payload.binance_trading_pair)
    dca_strategy_dao = DcaStrategyDao(database_session)
    dca_order_dao = DcaOrderDao(database_session)
    
    amount_per_order = strategy_payload.total_allocated_budget / strategy_payload.total_planned_executions if strategy_payload.total_planned_executions > 0 else 0.0

    backtest_comparative_snapshot = await DcaBacktester.generate_comparative_snapshot(
        symbol=strategy_payload.binance_trading_pair,
        start_date=strategy_payload.bear_market_start_date,
        end_date=strategy_payload.bear_market_end_date,
        total_budget=strategy_payload.total_allocated_budget,
        total_execution_cycles=strategy_payload.total_planned_executions,
        price_elasticity_aggressiveness=strategy_payload.average_unit_price_elasticity_factor,
    )

    current_local_time = get_current_local_datetime()
    new_dca_strategy = DcaStrategy(
        blockchain_network=strategy_payload.blockchain_network.lower(),
        source_asset_symbol=strategy_payload.source_asset_symbol,
        source_asset_address=strategy_payload.source_asset_address,
        source_asset_decimals=strategy_payload.source_asset_decimals,
        target_asset_symbol=strategy_payload.target_asset_symbol,
        target_asset_address=strategy_payload.target_asset_address,
        binance_trading_pair=strategy_payload.binance_trading_pair,
        total_allocated_budget=strategy_payload.total_allocated_budget,
        total_planned_executions=strategy_payload.total_planned_executions,
        amount_per_execution_order=amount_per_order,
        slippage_tolerance=strategy_payload.slippage_tolerance,
        average_unit_price_elasticity_factor=strategy_payload.average_unit_price_elasticity_factor,
        current_cycle_index=settings.MACRO_CURRENT_CYCLE_INDEX,
        previous_all_time_high_price=settings.MACRO_PREVIOUS_ATH,
        previous_bull_market_amplitude_percentage=settings.MACRO_PREVIOUS_BULL_AMPLITUDE_PCT,
        curve_flattening_factor=settings.MACRO_FLATTENING_FACTOR,
        bear_market_bottom_multiplier=settings.MACRO_BEAR_BOTTOM_MULTIPLIER,
        minimum_bull_market_multiplier=settings.MACRO_MINIMUM_BULL_MULTIPLIER,
        aave_estimated_annual_percentage_yield=settings.AAVE_ESTIMATED_APY,
        strategy_start_date=strategy_payload.strategy_start_date,
        strategy_end_date=strategy_payload.strategy_end_date,
        strategy_status=DcaStrategyStatus.ACTIVE.value,
        bypass_security_approval=strategy_payload.bypass_security_approval,
        available_dry_powder=0.0,
        total_deployed_amount=0.0,
        average_purchase_price=0.0,
        realized_aave_yield_amount=0.0,
        last_yield_calculation_timestamp=current_local_time,
        historical_backtest_payload=backtest_comparative_snapshot.model_dump(mode="json"),
        created_at=current_local_time,
        updated_at=current_local_time,
    )

    saved_dca_strategy = dca_strategy_dao.save(new_dca_strategy)
    scheduled_orders = DcaScheduler.generate_linear_execution_calendar(saved_dca_strategy)
    dca_order_dao.bulk_save(scheduled_orders)

    logger.info("[HTTP][DCA][STRATEGY][CREATE] Successfully created DCA strategy with id %s generating %s orders", saved_dca_strategy.id, len(scheduled_orders))

    schedule_full_recompute_broadcast()

    return DcaStrategyCreateResponse(
        message="Strategy successfully created",
        strategy_id=saved_dca_strategy.id,
        orders_count=len(scheduled_orders),
    )


@router.get("/api/dca/strategies", tags=["dca"])
async def get_all_dca_strategies(database_session: Session = Depends(get_database_session)) -> DcaStrategiesResponse:
    logger.debug("[HTTP][DCA][STRATEGIES][FETCH] Retrieving all registered DCA strategies")
    dca_strategy_dao = DcaStrategyDao(database_session)
    all_dca_strategies = dca_strategy_dao.retrieve_all()
    dca_strategy_payloads: List[DcaStrategyPayload] = []
    for registered_strategy in all_dca_strategies:
        live_metrics = await aave_executor_client.get_live_metrics(
            chain=registered_strategy.blockchain_network,
            asset_in_address=registered_strategy.source_asset_address,
            asset_out_address=registered_strategy.target_asset_address,
        )
        dca_strategy_payloads.append(serialize_dca_strategy(registered_strategy, live_metrics))
    logger.info("[HTTP][DCA][STRATEGIES][FETCH] Successfully retrieved %s DCA strategies", len(dca_strategy_payloads))
    return DcaStrategiesResponse(strategies=dca_strategy_payloads)


@router.get("/api/dca/strategies/{strategy_uid}/orders", tags=["dca"])
async def get_dca_strategy_orders(strategy_uid: int, database_session: Session = Depends(get_database_session)) -> DcaOrdersResponse:
    logger.debug("[HTTP][DCA][ORDERS][FETCH] Retrieving orders mapped to DCA strategy id %s", strategy_uid)
    dca_order_dao = DcaOrderDao(database_session)
    strategy_orders = dca_order_dao.retrieve_by_strategy(strategy_uid)
    serialized_orders = [serialize_dca_order(execution_order) for execution_order in strategy_orders]
    logger.info("[HTTP][DCA][ORDERS][FETCH] Successfully retrieved %s orders mapped to DCA strategy id %s", len(serialized_orders), strategy_uid)
    return DcaOrdersResponse(orders=serialized_orders)
