from __future__ import annotations

from typing import List, Optional

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
    TradingPositionsResponse,
    DcaStrategyPayload,
    AnalyticsResponse, TradingEvaluationPayload, )
from src.api.serializers import (
    serialize_dca_strategy,
    serialize_dca_order,
    serialize_trading_position,
)
from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.core.dca.dca_backtester import DcaBacktester
from src.core.dca.dca_scheduler import DcaScheduler
from src.core.structures.structures import DcaStrategyStatus, BlockchainNetwork
from src.core.trading.analytics.trading_analytics_helpers import map_trading_evaluation
from src.core.trading.cache.trading_cache import trading_cache
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.aave.aave_executor import AaveExecutor
from src.logging.logger import get_application_logger
from src.persistence import service
from src.persistence.dao.dca.dca_order_dao import DcaOrderDao
from src.persistence.dao.dca.dca_strategy_dao import DcaStrategyDao
from src.persistence.dao.trading.trading_evaluation_dao import TradingEvaluationDao
from src.persistence.dao.trading.trading_position_dao import TradingPositionDao
from src.persistence.db import get_fastapi_database_session
from src.persistence.models import DcaStrategy

router = APIRouter()
logger = get_application_logger(__name__)

aave_executor_client = AaveExecutor()


@router.get("/api/health", tags=["health"])
def get_health_status(database_session: Session = Depends(get_fastapi_database_session)) -> SystemHealthPayload:
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
def reset_paper_mode(database_session: Session = Depends(get_fastapi_database_session)) -> TradingPaperResetPayload:
    logger.debug("[HTTP][PAPER][RESET] Initiating paper mode reset process")
    service.reset_paper(database_session)

    cache_invalidator.mark_dirty(
        CacheRealm.POSITIONS,
        CacheRealm.TRADES,
        CacheRealm.PORTFOLIO,
        CacheRealm.AVAILABLE_CASH,
    )
    logger.info("[HTTP][PAPER][RESET] Cache invalidated after paper mode reset")
    return TradingPaperResetPayload(ok=True)


@router.get("/api/analytics", tags=["analytics"])
def get_analytics(
        limit_results: int = Query(50000, ge=1, le=50000),
        database_session: Session = Depends(get_fastapi_database_session),
) -> AnalyticsResponse:
    from src.core.trading.analytics.trading_analytics_service import build_analytics_response
    from src.persistence.models import PositionPhase

    logger.debug("[HTTP][ANALYTICS][FETCH] Retrieving live analytics with limit %s", limit_results)
    evaluation_dao = TradingEvaluationDao(database_session)
    position_dao = TradingPositionDao(database_session)

    evaluation_rows = evaluation_dao.retrieve_recent_evaluations(limit_count=limit_results)
    total_evaluations = evaluation_dao.count_total_evaluations()
    staled_positions = position_dao.retrieve_by_phase(PositionPhase.STALED)
    staled_token_addresses: set[str] = {position.token_address for position in staled_positions}

    analytics_records = [map_trading_evaluation(row) for row in evaluation_rows]
    analytics_response = build_analytics_response(analytics_records, total_evaluations, staled_token_addresses)

    logger.info("[HTTP][ANALYTICS][FETCH] Successfully processed live analytics")
    return analytics_response


@router.get("/api/analytics/shadow", tags=["analytics"])
def get_shadow_analytics(
        limit_results: int = Query(50000, ge=1, le=50000),
        database_session: Session = Depends(get_fastapi_database_session),
) -> AnalyticsResponse:
    from src.core.trading.analytics.trading_analytics_service import build_analytics_response
    from src.core.trading.analytics.trading_analytics_helpers import map_trading_shadowing_verdict
    from src.persistence.dao.trading.shadowing_verdict_dao import TradingShadowingVerdictDao
    from src.persistence.dao.trading.shadowing_probe_dao import TradingShadowingProbeDao

    logger.debug("[HTTP][ANALYTICS][FETCH] Retrieving shadow analytics with limit %s", limit_results)
    verdict_dao = TradingShadowingVerdictDao(database_session)
    probe_dao = TradingShadowingProbeDao(database_session)

    resolved_verdicts = verdict_dao.retrieve_recent_resolved(limit_count=limit_results)
    total_evaluations = probe_dao.count_total_probes()
    analytics_records = [map_trading_shadowing_verdict(verdict) for verdict in resolved_verdicts]

    analytics_response = build_analytics_response(analytics_records, total_evaluations, set())

    logger.info("[HTTP][ANALYTICS][FETCH] Successfully processed shadow analytics from %d resolved verdicts", len(resolved_verdicts))
    return analytics_response


@router.get("/api/analytics/evaluation/{evaluation_id}", tags=["analytics"])
def get_evaluation_by_id(
        evaluation_id: int,
        database_session: Session = Depends(get_fastapi_database_session),
) -> Optional[TradingEvaluationPayload]:
    from src.api.serializers import serialize_trading_evaluation

    logger.debug("[HTTP][ANALYTICS][FETCH] Retrieving evaluation by id %s", evaluation_id)
    evaluation_dao = TradingEvaluationDao(database_session)
    evaluation = evaluation_dao.retrieve_by_id(evaluation_id)

    if not evaluation:
        return None

    return serialize_trading_evaluation(evaluation)


@router.get("/api/analytics/shadow/{pair_address}", tags=["analytics"])
def get_shadow_trades_for_pair(
        pair_address: str,
        database_session: Session = Depends(get_fastapi_database_session)
) -> List[TradingEvaluationPayload]:
    from src.api.serializers import serialize_trading_evaluation
    from src.persistence.dao.trading.shadowing_verdict_dao import TradingShadowingVerdictDao
    from src.persistence.models import TradingEvaluation

    logger.debug("[HTTP][ANALYTICS][SHADOW] Retrieving shadow verdicts for pair %s", pair_address)
    verdict_dao = TradingShadowingVerdictDao(database_session)
    verdicts = verdict_dao.retrieve_resolved_for_pair(pair_address, limit_count=100)

    results = []
    for v in verdicts:
        p = v.probe
        mock_eval = TradingEvaluation(
            id=v.id,
            token_symbol=p.token_symbol,
            blockchain_network=p.blockchain_network,
            token_address=p.token_address,
            pair_address=p.pair_address,
            price_usd=p.entry_price_usd,
            candidate_rank=p.candidate_rank,
            quality_score=p.quality_score,
            token_age_hours=p.token_age_hours,
            volume_m5_usd=p.volume_m5_usd,
            volume_h1_usd=p.volume_h1_usd,
            volume_h6_usd=p.volume_h6_usd,
            volume_h24_usd=p.volume_h24_usd,
            liquidity_usd=p.liquidity_usd,
            price_change_percentage_m5=p.price_change_percentage_m5,
            price_change_percentage_h1=p.price_change_percentage_h1,
            price_change_percentage_h6=p.price_change_percentage_h6,
            price_change_percentage_h24=p.price_change_percentage_h24,
            transaction_count_m5=p.transaction_count_m5,
            transaction_count_h1=p.transaction_count_h1,
            transaction_count_h6=p.transaction_count_h6,
            transaction_count_h24=p.transaction_count_h24,
            buy_to_sell_ratio=p.buy_to_sell_ratio,
            market_cap_usd=p.market_cap_usd,
            fully_diluted_valuation_usd=p.fully_diluted_valuation_usd,
            dexscreener_boost=p.dexscreener_boost,
            evaluated_at=p.probed_at,
            execution_decision="SHADOW_BUY",
            sizing_multiplier=1.0,
            order_notional_value_usd=p.order_notional_value_usd,
        )
        results.append(serialize_trading_evaluation(mock_eval))

    return results


@router.get("/api/positions", tags=["positions"])
async def get_open_positions_list(database_session: Session = Depends(get_fastapi_database_session)) -> TradingPositionsResponse:
    logger.debug("[HTTP][POSITIONS][FETCH] Retrieving currently open positions from cache")
    trading_state = trading_cache.get_trading_state()
    cached_positions = trading_state.positions

    if cached_positions is not None:
        logger.info("[HTTP][POSITIONS][FETCH] Successfully retrieved %s open positions from cache", len(cached_positions))
        return TradingPositionsResponse(positions=cached_positions)

    logger.warning("[HTTP][POSITIONS][FETCH] Cache is empty, falling back to database fetch without current prices")
    position_dao = TradingPositionDao(database_session)
    open_positions = position_dao.retrieve_open_positions()

    serialized_positions = []
    for position in open_positions:
        serialized_positions.append(serialize_trading_position(position, last_price=position.entry_price))

    logger.info("[HTTP][POSITIONS][FETCH] Successfully retrieved %s open positions from database fallback", len(serialized_positions))
    return TradingPositionsResponse(positions=serialized_positions)


@router.post("/api/dca/strategies", tags=["dca"])
async def create_new_dca_strategy(
        strategy_payload: DcaStrategyCreatePayload,
        database_session: Session = Depends(get_fastapi_database_session),
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
        blockchain_network=strategy_payload.blockchain_network.value,
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
        historical_backtest_payload=backtest_comparative_snapshot.model_dump(mode="json"),
        created_at=current_local_time,
        updated_at=current_local_time,
    )

    saved_dca_strategy = dca_strategy_dao.save(new_dca_strategy)
    scheduled_orders = DcaScheduler.generate_linear_execution_calendar(saved_dca_strategy)
    dca_order_dao.bulk_save(scheduled_orders)

    logger.info("[HTTP][DCA][STRATEGY][CREATE] Successfully created DCA strategy with id %s generating %s orders", saved_dca_strategy.id, len(scheduled_orders))

    cache_invalidator.mark_dirty(CacheRealm.DCA_STRATEGIES)

    return DcaStrategyCreateResponse(
        message="Strategy successfully created",
        strategy_id=saved_dca_strategy.id,
        orders_count=len(scheduled_orders),
    )


@router.get("/api/dca/strategies", tags=["dca"])
async def get_all_dca_strategies(database_session: Session = Depends(get_fastapi_database_session)) -> DcaStrategiesResponse:
    logger.debug("[HTTP][DCA][STRATEGIES][FETCH] Retrieving all registered DCA strategies")
    dca_strategy_dao = DcaStrategyDao(database_session)
    all_dca_strategies = dca_strategy_dao.retrieve_all()
    dca_strategy_payloads: List[DcaStrategyPayload] = []
    for registered_strategy in all_dca_strategies:
        live_metrics = await aave_executor_client.get_live_metrics(
            chain=BlockchainNetwork(registered_strategy.blockchain_network.lower()),
            asset_in_address=registered_strategy.source_asset_address,
            asset_out_address=registered_strategy.target_asset_address,
        )
        dca_strategy_payloads.append(serialize_dca_strategy(registered_strategy, live_metrics))
    logger.info("[HTTP][DCA][STRATEGIES][FETCH] Successfully retrieved %s DCA strategies", len(dca_strategy_payloads))
    return DcaStrategiesResponse(strategies=dca_strategy_payloads)


@router.get("/api/dca/strategies/{strategy_uid}/orders", tags=["dca"])
def get_dca_strategy_orders(strategy_uid: int, database_session: Session = Depends(get_fastapi_database_session)) -> DcaOrdersResponse:
    logger.debug("[HTTP][DCA][ORDERS][FETCH] Retrieving orders mapped to DCA strategy id %s", strategy_uid)
    dca_order_dao = DcaOrderDao(database_session)
    strategy_orders = dca_order_dao.retrieve_by_strategy(strategy_uid)
    serialized_orders = [serialize_dca_order(execution_order) for execution_order in strategy_orders]
    logger.info("[HTTP][DCA][ORDERS][FETCH] Successfully retrieved %s orders mapped to DCA strategy id %s", len(serialized_orders), strategy_uid)
    return DcaOrdersResponse(orders=serialized_orders)
