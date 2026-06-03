from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from src.api.http.api_schemas import (
    AnalyticsResponse,
    TradingEvaluationPayload,
    TradingPaperResetPayload,
    TradingPositionPayload,
    TradingPositionsResponse,
)
from src.api.http.http_helpers import (
    build_live_trading_analytics_response,
    build_open_positions_response,
    build_shadow_evaluation_payloads_for_pair,
    build_shadow_trading_analytics_response,
    build_trading_evaluation_payload_for_evaluation_id,
    resolve_linked_position_payload_for_evaluation,
)
from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.core.paper import paper_service
from src.core.trading.execution.trading_execution_position_service import (
    PositionCloseConflictError,
    PositionCloseNotFoundError,
    PositionRecoveryConflictError,
    close_position,
    execute_manual_close_sell,
    kill_staled_position,
    reopen_staled_position,
)
from src.logging.logger import get_application_logger
from src.persistence.database_session_manager import get_fastapi_database_session

router = APIRouter(prefix="/api/trading", tags=["trading"])
logger = get_application_logger(__name__)


@router.post("/paper/reset")
def reset_trading_paper_mode(
        database_session: Session = Depends(get_fastapi_database_session),
) -> TradingPaperResetPayload:
    logger.debug("[HTTP][TRADING][PAPER][RESET] Initiating paper mode reset process")
    paper_service.reset_paper(database_session)

    cache_invalidator.mark_dirty(
        CacheRealm.POSITIONS,
        CacheRealm.TRADES,
        CacheRealm.PORTFOLIO,
        CacheRealm.AVAILABLE_CASH,
    )
    logger.info("[HTTP][TRADING][PAPER][RESET] Cache invalidated after paper mode reset")
    return TradingPaperResetPayload(ok=True)


@router.get("/analytics")
def get_trading_analytics(
        limit_results: int = Query(50000, ge=1, le=50000),
        database_session: Session = Depends(get_fastapi_database_session),
) -> AnalyticsResponse:
    logger.debug("[HTTP][TRADING][ANALYTICS][FETCH] Retrieving live analytics with limit %s", limit_results)
    analytics_response = build_live_trading_analytics_response(database_session, limit_results)
    logger.info("[HTTP][TRADING][ANALYTICS][FETCH] Successfully processed live analytics")
    return analytics_response


@router.get("/analytics/shadow")
def get_trading_shadowing_analytics(
        limit_results: int = Query(50000, ge=1, le=50000),
        database_session: Session = Depends(get_fastapi_database_session),
) -> AnalyticsResponse:
    logger.debug("[HTTP][TRADING][ANALYTICS][SHADOWING][FETCH] Retrieving shadow analytics with limit %s", limit_results)
    analytics_response = build_shadow_trading_analytics_response(database_session, limit_results)
    logger.info("[HTTP][TRADING][ANALYTICS][SHADOWING][FETCH] Successfully processed shadow analytics")
    return analytics_response


@router.get("/evaluations/{evaluation_id}")
def get_trading_evaluation_by_id(
        evaluation_id: int,
        database_session: Session = Depends(get_fastapi_database_session),
) -> Optional[TradingEvaluationPayload]:
    logger.debug("[HTTP][TRADING][EVALUATIONS][FETCH] Retrieving evaluation by id %s", evaluation_id)
    return build_trading_evaluation_payload_for_evaluation_id(evaluation_id, database_session)


@router.get("/shadowing/evaluations/{pair_address}")
def get_trading_shadowing_evaluations_for_pair(
        pair_address: str,
        database_session: Session = Depends(get_fastapi_database_session),
) -> List[TradingEvaluationPayload]:
    logger.debug("[HTTP][TRADING][SHADOWING][EVALUATIONS] Retrieving shadowing verdicts for pair %s", pair_address)
    return build_shadow_evaluation_payloads_for_pair(pair_address, database_session)


@router.get("/positions")
async def get_trading_open_positions(
        database_session: Session = Depends(get_fastapi_database_session),
) -> TradingPositionsResponse:
    logger.debug("[HTTP][TRADING][POSITIONS][FETCH] Retrieving currently open positions")
    positions_response = build_open_positions_response(database_session)
    logger.info("[HTTP][TRADING][POSITIONS][FETCH] Retrieved %s open positions", len(positions_response.positions))
    return positions_response


@router.get("/positions/by-evaluation/{evaluation_id}")
async def get_trading_position_by_evaluation_id(
        evaluation_id: int,
        database_session: Session = Depends(get_fastapi_database_session),
) -> TradingPositionPayload:
    logger.debug("[HTTP][TRADING][POSITIONS][FETCH] Retrieving position for evaluation_id=%s", evaluation_id)
    linked_position = resolve_linked_position_payload_for_evaluation(evaluation_id, database_session)
    if linked_position is None:
        logger.info("[HTTP][TRADING][POSITIONS][FETCH] No position found for evaluation_id=%s", evaluation_id)
        raise HTTPException(status_code=404, detail="Position not found for evaluation")

    logger.info(
        "[HTTP][TRADING][POSITIONS][FETCH] Successfully retrieved position id=%s for evaluation_id=%s",
        linked_position.id,
        evaluation_id,
    )
    return linked_position


@router.post("/positions/{position_id}/close", status_code=204)
def close_trading_position(
        position_id: int,
        background_tasks: BackgroundTasks,
        database_session: Session = Depends(get_fastapi_database_session),
) -> Response:
    logger.debug("[HTTP][TRADING][POSITIONS][CLOSE] Initiating manual close for position id=%s", position_id)
    try:
        close_position(database_session, position_id)
    except PositionCloseNotFoundError as exception:
        logger.info("[HTTP][TRADING][POSITIONS][CLOSE] Position id=%s not closable: %s", position_id, exception)
        raise HTTPException(status_code=404, detail="Position not found or not closable") from exception
    except PositionCloseConflictError as exception:
        logger.info("[HTTP][TRADING][POSITIONS][CLOSE] Position id=%s close conflict: %s", position_id, exception)
        raise HTTPException(status_code=409, detail="Position is already closing") from exception

    background_tasks.add_task(execute_manual_close_sell, position_id)
    logger.info("[HTTP][TRADING][POSITIONS][CLOSE] Position id=%s marked CLOSING, sell scheduled", position_id)
    return Response(status_code=204)


@router.post("/positions/{position_id}/kill", status_code=204)
def kill_staled_trading_position(
        position_id: int,
        database_session: Session = Depends(get_fastapi_database_session),
) -> Response:
    logger.debug("[HTTP][TRADING][POSITIONS][KILL] Initiating kill for staled position id=%s", position_id)
    try:
        kill_staled_position(database_session, position_id)
    except PositionCloseNotFoundError as exception:
        logger.info("[HTTP][TRADING][POSITIONS][KILL] Position id=%s not found: %s", position_id, exception)
        raise HTTPException(status_code=404, detail="Position not found") from exception
    except PositionRecoveryConflictError as exception:
        logger.info("[HTTP][TRADING][POSITIONS][KILL] Position id=%s kill conflict: %s", position_id, exception)
        raise HTTPException(status_code=409, detail="Position is not STALED") from exception

    logger.info("[HTTP][TRADING][POSITIONS][KILL] Position id=%s killed from STALED", position_id)
    return Response(status_code=204)


@router.post("/positions/{position_id}/reopen", status_code=204)
def reopen_staled_trading_position(
        position_id: int,
        database_session: Session = Depends(get_fastapi_database_session),
) -> Response:
    logger.debug("[HTTP][TRADING][POSITIONS][REOPEN] Initiating reopen for staled position id=%s", position_id)
    try:
        reopen_staled_position(database_session, position_id)
    except PositionCloseNotFoundError as exception:
        logger.info("[HTTP][TRADING][POSITIONS][REOPEN] Position id=%s not found: %s", position_id, exception)
        raise HTTPException(status_code=404, detail="Position not found") from exception
    except PositionRecoveryConflictError as exception:
        logger.info("[HTTP][TRADING][POSITIONS][REOPEN] Position id=%s reopen conflict: %s", position_id, exception)
        raise HTTPException(status_code=409, detail="Position is not STALED") from exception

    logger.info("[HTTP][TRADING][POSITIONS][REOPEN] Position id=%s reopened from STALED", position_id)
    return Response(status_code=204)
