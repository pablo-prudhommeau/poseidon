from __future__ import annotations

import asyncio
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.http.api_schemas import (
    CreateDcaPayload,
    HealthPayload,
    HealthComponentsPayload,
    HealthComponentPayload,
    PaperResetPayload,
    CreateDcaStrategyResponse,
    DcaStrategiesResponse,
    DcaOrdersResponse,
    AnalyticsResponse,
    PositionsResponse, DcaStrategyPayload,
)
from src.api.serializers import (
    serialize_analytics,
    serialize_dca_strategy,
    serialize_dca_order,
    serialize_position,
)
from src.api.websocket.ws_hub import schedule_full_recompute_broadcast
from src.configuration.config import settings
from src.core.dca.dca_backtester import DcaBacktester
from src.core.dca.dca_scheduler import DcaScheduler
from src.core.structures.structures import Token, DcaStrategyStatus
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.aave.aave_executor import AaveExecutor
from src.integrations.dexscreener.dexscreener_client import fetch_dexscreener_token_information_list
from src.logging.logger import get_logger
from src.persistence import service
from src.persistence.dao.analytics import retrieve_recent_analytics
from src.persistence.dao.dca_dao import DcaDao
from src.persistence.dao.portfolio_snapshots import ensure_initial_cash
from src.persistence.dao.positions import retrieve_open_positions
from src.persistence.db import get_database_session
from src.persistence.models import DcaStrategy

router = APIRouter()
logger = get_logger(__name__)

aave_executor_client = AaveExecutor()


@router.get("/api/health", tags=["health"])
async def get_health_status(db: Session = Depends(get_database_session)) -> HealthPayload:
    logger.debug("[HTTP][HEALTH][DB] Initiating health check sequence")
    current_timestamp = get_current_local_datetime().isoformat()
    is_db_connected = False

    try:
        db.execute(text("SELECT 1"))
        is_db_connected = True
        logger.info("[HTTP][HEALTH][DB] Database connectivity successfully validated")
    except Exception as exception:
        logger.exception("[HTTP][HEALTH][DB] Health check database connectivity failed", exc_info=exception)

    return HealthPayload(
        status="ok" if is_db_connected else "degraded",
        timestamp=current_timestamp,
        components=HealthComponentsPayload(
            database=HealthComponentPayload(ok=is_db_connected)
        ),
    )


@router.post("/api/paper/reset", tags=["paper"])
def reset_paper_mode(db: Session = Depends(get_database_session)) -> PaperResetPayload:
    logger.debug("[HTTP][PAPER][RESET] Initiating paper mode reset process")
    service.reset_paper(db)
    ensure_initial_cash(db)
    logger.info("[HTTP][PAPER][RESET] Paper mode has been reset and initial cash properly ensured")

    try:
        loop = asyncio.get_running_loop()
        if loop.is_running() and not loop.is_closed():
            schedule_full_recompute_broadcast()
            logger.info("[HTTP][PAPER][REBROADCAST] Scheduled immediate recompute broadcast after reset")
        else:
            logger.debug("[HTTP][PAPER][REBROADCAST] No running event loop detected, user interface will refresh on next orchestrator tick")
    except RuntimeError as exception:
        logger.debug("[HTTP][PAPER][REBROADCAST] Event loop runtime error encountered, user interface will refresh on next orchestrator tick", exc_info=exception)

    return PaperResetPayload(ok=True)


@router.get("/api/analytics", tags=["analytics"])
async def get_analytics_history(
        limit: int = Query(5000, ge=1, le=10000),
        db: Session = Depends(get_database_session),
) -> AnalyticsResponse:
    logger.debug("[HTTP][ANALYTICS][FETCH] Retrieving recent analytics history with limit %s", limit)
    analytics_rows = retrieve_recent_analytics(db, maximum_results_limit=limit)
    serialized_analytics = [serialize_analytics(analytics_row) for analytics_row in analytics_rows]
    logger.info("[HTTP][ANALYTICS][FETCH] Successfully retrieved %s analytics records", len(serialized_analytics))
    return AnalyticsResponse(analytics=serialized_analytics)


@router.get("/api/positions", tags=["positions"])
async def get_open_positions_list(db: Session = Depends(get_database_session)) -> PositionsResponse:
    logger.debug("[HTTP][POSITIONS][FETCH] Retrieving currently open positions")
    open_positions = retrieve_open_positions(db)

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
        serialized_positions.append(serialize_position(position, last_price=last_known_price))

    logger.info("[HTTP][POSITIONS][FETCH] Successfully retrieved %s open positions", len(serialized_positions))
    return PositionsResponse(positions=serialized_positions)


@router.post("/api/dca/strategies", tags=["dca"])
async def create_new_dca_strategy(
        strategy_payload: CreateDcaPayload,
        db: Session = Depends(get_database_session),
) -> CreateDcaStrategyResponse:
    logger.debug("[HTTP][DCA][STRATEGY][CREATE] Initiating DCA strategy creation for symbol %s", strategy_payload.binance_trading_pair)
    dca_dao = DcaDao(db)
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
        strategy_status=DcaStrategyStatus.ACTIVE,
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

    saved_dca_strategy = dca_dao.create_strategy(new_dca_strategy)
    scheduled_orders = DcaScheduler.generate_linear_execution_calendar(saved_dca_strategy)
    dca_dao.bulk_create_orders(scheduled_orders)

    logger.info("[HTTP][DCA][STRATEGY][CREATE] Successfully created DCA strategy with id %s generating %s orders", saved_dca_strategy.id, len(scheduled_orders))

    schedule_full_recompute_broadcast()

    return CreateDcaStrategyResponse(
        message="Strategy successfully created",
        strategy_id=saved_dca_strategy.id,
        orders_count=len(scheduled_orders),
    )


@router.get("/api/dca/strategies", tags=["dca"])
async def get_all_dca_strategies(db: Session = Depends(get_database_session)) -> DcaStrategiesResponse:
    logger.debug("[HTTP][DCA][STRATEGIES][FETCH] Retrieving all registered DCA strategies")
    dca_dao = DcaDao(db)
    all_dca_strategies = dca_dao.get_all_strategies()
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


@router.get("/api/dca/strategies/{strategy_id}/orders", tags=["dca"])
async def get_dca_strategy_orders(strategy_id: int, db: Session = Depends(get_database_session)) -> DcaOrdersResponse:
    logger.debug("[HTTP][DCA][ORDERS][FETCH] Retrieving orders mapped to DCA strategy id %s", strategy_id)
    dca_dao = DcaDao(db)
    strategy_orders = dca_dao.get_orders_for_strategy(strategy_id)
    serialized_orders = [serialize_dca_order(order) for order in strategy_orders]
    logger.info("[HTTP][DCA][ORDERS][FETCH] Successfully retrieved %s orders mapped to DCA strategy id %s", len(serialized_orders), strategy_id)
    return DcaOrdersResponse(orders=serialized_orders)
