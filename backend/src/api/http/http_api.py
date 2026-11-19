from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.http.api_schemas import (
    AaveDcaOrdersResponse,
    AaveDcaStrategiesResponse,
    AaveDcaStrategyCreatePayload,
    AaveDcaStrategyCreateResponse,
    AaveDcaStrategyStatusUpdatePayload,
    AaveDcaStrategyStatusUpdateResponse,
    SystemHealthComponentPayload,
    SystemHealthComponentsPayload,
    SystemHealthPayload,
)
from src.api.http.http_helpers import (
    build_aave_dca_orders_response,
    build_aave_dca_strategies_response,
    create_aave_dca_strategy_from_payload,
    update_aave_dca_strategy_status_from_payload,
)
from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.core.aavedca.aave_dca_structures import (
    AaveDcaActiveStrategyConflictError,
    AaveDcaInsufficientNativeGasError,
    AaveDcaStrategyNotFoundError,
    AaveDcaStrategyStatusTransitionError,
)
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_application_logger
from src.persistence.database_session_manager import get_fastapi_database_session

router = APIRouter()
logger = get_application_logger(__name__)


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


@router.post("/api/dca/strategies", tags=["dca"])
async def create_new_aave_dca_strategy(
        strategy_payload: AaveDcaStrategyCreatePayload,
        database_session: Session = Depends(get_fastapi_database_session),
) -> AaveDcaStrategyCreateResponse:
    logger.debug("[HTTP][AAVEDCA][STRATEGY][CREATE] Initiating DCA strategy creation for symbol %s", strategy_payload.binance_trading_pair)
    try:
        create_response = await create_aave_dca_strategy_from_payload(database_session, strategy_payload)
    except AaveDcaActiveStrategyConflictError as exception:
        logger.info("[HTTP][AAVEDCA][STRATEGY][CREATE] DCA strategy creation refused: %s", exception)
        raise HTTPException(status_code=409, detail="Another DCA strategy is already active on this blockchain") from exception
    except AaveDcaInsufficientNativeGasError as exception:
        logger.info("[HTTP][AAVEDCA][STRATEGY][CREATE] DCA strategy creation refused: %s", exception)
        raise HTTPException(
            status_code=409,
            detail=(
                f"Insufficient AVAX for gas: add {exception.native_gas_requirement.missing_balance_avax:.4f} AVAX "
                f"(wallet {exception.native_gas_requirement.wallet_balance_avax:.4f}, "
                f"required {exception.native_gas_requirement.required_balance_avax:.4f})"
            ),
        ) from exception
    logger.info(
        "[HTTP][AAVEDCA][STRATEGY][CREATE] Successfully created DCA strategy with id %s generating %s orders",
        create_response.strategy_id,
        create_response.orders_count,
    )
    cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)
    return create_response


@router.patch("/api/dca/strategies/{strategy_uid}/status", tags=["dca"])
def update_aave_dca_strategy_status_route(
        strategy_uid: int,
        status_payload: AaveDcaStrategyStatusUpdatePayload,
        database_session: Session = Depends(get_fastapi_database_session),
) -> AaveDcaStrategyStatusUpdateResponse:
    logger.debug(
        "[HTTP][AAVEDCA][STRATEGY][STATUS] Initiating status change to %s for DCA strategy id %s",
        status_payload.strategy_status.value,
        strategy_uid,
    )
    try:
        status_update_response = update_aave_dca_strategy_status_from_payload(database_session, strategy_uid, status_payload)
    except AaveDcaStrategyNotFoundError as exception:
        logger.info("[HTTP][AAVEDCA][STRATEGY][STATUS] DCA strategy id %s not found: %s", strategy_uid, exception)
        raise HTTPException(status_code=404, detail="DCA strategy not found") from exception
    except AaveDcaStrategyStatusTransitionError as exception:
        logger.info("[HTTP][AAVEDCA][STRATEGY][STATUS] DCA strategy id %s status change refused: %s", strategy_uid, exception)
        raise HTTPException(status_code=409, detail=str(exception)) from exception
    except AaveDcaActiveStrategyConflictError as exception:
        logger.info("[HTTP][AAVEDCA][STRATEGY][STATUS] DCA strategy id %s activation refused: %s", strategy_uid, exception)
        raise HTTPException(status_code=409, detail="Another DCA strategy is already active on this blockchain") from exception

    logger.info(
        "[HTTP][AAVEDCA][STRATEGY][STATUS] DCA strategy id %s moved from %s to %s",
        strategy_uid,
        status_update_response.previous_strategy_status.value,
        status_update_response.strategy_status.value,
    )
    return status_update_response


@router.get("/api/dca/strategies", tags=["dca"])
async def get_all_aave_dca_strategies(
        database_session: Session = Depends(get_fastapi_database_session),
) -> AaveDcaStrategiesResponse:
    logger.debug("[HTTP][AAVEDCA][STRATEGIES][FETCH] Retrieving all registered DCA strategies")
    strategies_response = await build_aave_dca_strategies_response(database_session)
    logger.debug("[HTTP][AAVEDCA][STRATEGIES][FETCH] Successfully retrieved %s DCA strategies", len(strategies_response.strategies))
    return strategies_response


@router.get("/api/dca/strategies/{strategy_uid}/orders", tags=["dca"])
def get_aave_dca_strategy_orders(
        strategy_uid: int,
        database_session: Session = Depends(get_fastapi_database_session),
) -> AaveDcaOrdersResponse:
    logger.debug("[HTTP][AAVEDCA][ORDERS][FETCH] Retrieving orders mapped to DCA strategy id %s", strategy_uid)
    orders_response = build_aave_dca_orders_response(database_session, strategy_uid)
    logger.info(
        "[HTTP][AAVEDCA][ORDERS][FETCH] Successfully retrieved %s orders mapped to DCA strategy id %s",
        len(orders_response.orders),
        strategy_uid,
    )
    return orders_response
