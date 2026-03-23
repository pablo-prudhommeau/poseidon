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
    PositionsResponse,
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
from src.integrations.dexscreener.dexscreener_client import fetch_dexscreener_token_information_list
from src.logging.logger import get_logger
from src.persistence import service
from src.persistence.dao.analytics import get_recent_analytics
from src.persistence.dao.dca_dao import DcaDao
from src.persistence.dao.portfolio_snapshots import ensure_initial_cash
from src.persistence.dao.positions import get_open_positions
from src.persistence.db import get_db
from src.persistence.models import DcaStrategy

router = APIRouter()
logger = get_logger(__name__)


@router.get("/api/health", tags=["health"])
async def get_health(db: Session = Depends(get_db)) -> HealthPayload:
    current_timestamp = get_current_local_datetime().isoformat()
    database_ok = False
    try:
        db.execute(text("SELECT 1"))
        database_ok = True
        logger.debug("[HTTP][HEALTH] Database connectivity validated")
    except Exception:
        logger.exception("[HTTP][HEALTH] Health check database connectivity failed")

    return HealthPayload(
        status="ok" if database_ok else "degraded",
        timestamp=current_timestamp,
        components=HealthComponentsPayload(
            database=HealthComponentPayload(ok=database_ok)
        ),
    )


@router.post("/api/paper/reset")
def reset_paper(db: Session = Depends(get_db)) -> PaperResetPayload:
    service.reset_paper(db)
    ensure_initial_cash(db)
    logger.info("[HTTP][PAPER][RESET] Paper mode has been reset and initial cash ensured")

    try:
        loop = asyncio.get_running_loop()
        if loop.is_running() and not loop.is_closed():
            schedule_full_recompute_broadcast()
            logger.debug("[HTTP][PAPER][REBROADCAST] Scheduled immediate recompute after reset")
        else:
            logger.debug("[HTTP][PAPER][REBROADCAST] No running loop, UI will refresh on next orchestrator tick")
    except RuntimeError:
        logger.debug("[HTTP][PAPER][REBROADCAST] No running loop, UI will refresh on next orchestrator tick")

    return PaperResetPayload(ok=True)


@router.get("/api/analytics", tags=["analytics"])
async def get_analytics(
        limit: int = Query(5000, ge=1, le=10000),
        db: Session = Depends(get_db),
) -> AnalyticsResponse:
    rows = get_recent_analytics(db, limit=limit)
    payload = [serialize_analytics(a) for a in rows]
    logger.info("[HTTP][ANALYTICS][FETCH] rows=%s", len(payload))
    return AnalyticsResponse(analytics=payload)


@router.get("/api/positions", tags=["positions"])
async def get_positions(db: Session = Depends(get_db)) -> PositionsResponse:
    positions = get_open_positions(db)
    tokens: List[Token] = [
        Token(chain=p.chain, symbol=p.symbol, tokenAddress=p.tokenAddress, pairAddress=p.pairAddress)
        for p in positions
    ]
    token_information_list = await fetch_dexscreener_token_information_list(tokens)

    payload = []
    for position in positions:
        price = next(
            (t.price_usd for t in token_information_list
             if t.chain_id == position.chain
             and t.base_token.address == position.tokenAddress
             and t.pair_address == position.pairAddress),
            None,
        )
        payload.append(serialize_position(position, last_price=price))

    logger.info("[HTTP][POSITIONS][FETCH] positions=%s", len(payload))
    return PositionsResponse(positions=payload)


@router.post("/api/dca/strategies", tags=["dca"])
async def create_dca_strategy(
        payload: CreateDcaPayload,
        db: Session = Depends(get_db),
) -> CreateDcaStrategyResponse:
    dao = DcaDao(db)
    amount_per_order = payload.total_budget / payload.total_executions if payload.total_executions > 0 else 0.0

    backtest_data = await DcaBacktester.generate_comparative_snapshot(
        symbol=payload.binance_pair,
        start_date=payload.bear_market_start_date,
        end_date=payload.bear_market_end_date,
        total_budget=payload.total_budget,
        executions_count=payload.total_executions,
        pru_elasticity_factor=payload.pru_elasticity_factor,
    )

    current_time = get_current_local_datetime()
    strategy = DcaStrategy(
        chain=payload.chain.lower(),
        asset_in_symbol=payload.asset_in_symbol,
        asset_in_address=payload.asset_in_address,
        asset_in_decimals=payload.asset_in_decimals,
        asset_out_symbol=payload.asset_out_symbol,
        asset_out_address=payload.asset_out_address,
        binance_pair=payload.binance_pair,
        total_budget=payload.total_budget,
        total_executions=payload.total_executions,
        amount_per_order=amount_per_order,
        slippage=payload.slippage,
        pru_elasticity_factor=payload.pru_elasticity_factor,
        cycle_index=settings.MACRO_CURRENT_CYCLE_INDEX,
        previous_ath=settings.MACRO_PREVIOUS_ATH,
        previous_bull_amplitude_pct=settings.MACRO_PREVIOUS_BULL_AMPLITUDE_PCT,
        flattening_factor=settings.MACRO_FLATTENING_FACTOR,
        bear_bottom_multiplier=settings.MACRO_BEAR_BOTTOM_MULTIPLIER,
        minimum_bull_multiplier=settings.MACRO_MINIMUM_BULL_MULTIPLIER,
        aave_estimated_apy=settings.AAVE_ESTIMATED_APY,
        start_date=payload.start_date,
        end_date=payload.end_date,
        status=DcaStrategyStatus.ACTIVE,
        bypass_approval=payload.bypass_approval,
        dry_powder=0.0,
        deployed_amount=0.0,
        average_purchase_price=0.0,
        realized_aave_yield=0.0,
        last_yield_calculation_at=current_time,
        backtest_payload=backtest_data.model_dump(mode="json"),
        created_at=current_time,
        updated_at=current_time,
    )

    saved_strategy = dao.create_strategy(strategy)
    orders = DcaScheduler.generate_calendar(saved_strategy)
    dao.bulk_create_orders(orders)

    logger.info("[HTTP][DCA] Created strategy %s successfully with %d orders.", saved_strategy.id, len(orders))
    return CreateDcaStrategyResponse(
        message="Strategy successfully created",
        strategy_id=saved_strategy.id,
        orders_count=len(orders),
    )


@router.get("/api/dca/strategies", tags=["dca"])
async def get_dca_strategies(db: Session = Depends(get_db)) -> DcaStrategiesResponse:
    dao = DcaDao(db)
    strategies = dao.get_all_strategies()
    return DcaStrategiesResponse(strategies=[serialize_dca_strategy(s) for s in strategies])


@router.get("/api/dca/strategies/{strategy_id}/orders", tags=["dca"])
async def get_dca_orders(strategy_id: int, db: Session = Depends(get_db)) -> DcaOrdersResponse:
    dao = DcaDao(db)
    orders = dao.get_orders_for_strategy(strategy_id)
    return DcaOrdersResponse(orders=[serialize_dca_order(o) for o in orders])
