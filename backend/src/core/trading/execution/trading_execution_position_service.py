from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.cache.trading_cache import trading_cache
from src.core.trading.execution.trading_execution_blockchain_route_service import build_route_for_live_sell
from src.core.trading.execution.trading_execution_handler_service import resolve_execution_chain_handler_for_blockchain
from src.core.trading.execution.trading_execution_swap_service import run_live_sell_blocking
from src.core.trading.trading_structures import PositionExitTriggerReason
from src.core.trading.trading_utils import convert_trading_position_to_token
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.blockchain.blockchain_price_service import fetch_onchain_prices_for_tokens
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_evaluation_dao import TradingEvaluationDao
from src.persistence.dao.trading_trade_dao import TradingTradeDao
from src.persistence.database_session_manager import get_database_session
from src.persistence.models import TradingPosition, TradingTrade, ExecutionStatus, PositionPhase, TradeSide

logger = get_application_logger(__name__)


class PositionCloseNotFoundError(Exception):
    pass


class PositionCloseConflictError(Exception):
    pass


def close_position(database_session: Session, position_id: int) -> None:
    position = database_session.get(TradingPosition, position_id)
    if position is None:
        raise PositionCloseNotFoundError(f"Position {position_id} not found")

    if position.position_phase == PositionPhase.CLOSING:
        raise PositionCloseConflictError("Position is already closing")

    if position.position_phase not in (PositionPhase.OPEN, PositionPhase.PARTIAL):
        raise PositionCloseNotFoundError(f"Position {position_id} is not closable")

    remaining_quantity = position.current_quantity or 0.0
    if remaining_quantity <= 0.0:
        raise PositionCloseNotFoundError(f"Position {position_id} has no remaining quantity")

    mark_position_closing(database_session, position, PositionExitTriggerReason.MANUAL)
    cache_invalidator.mark_dirty(CacheRealm.POSITIONS)


def execute_manual_close_sell(position_id: int) -> None:
    with get_database_session() as database_session:
        position = database_session.get(TradingPosition, position_id)
        if position is None:
            logger.warning("[TRADING][EXECUTION][POSITION] Background sell skipped — position %s not found", position_id)
            return

        if position.position_phase != PositionPhase.CLOSING:
            logger.warning(
                "[TRADING][EXECUTION][POSITION] Background sell skipped — position %s is not CLOSING (phase=%s)",
                position_id,
                position.position_phase,
            )
            return

        if position.exit_reason != PositionExitTriggerReason.MANUAL.value:
            logger.warning(
                "[TRADING][EXECUTION][POSITION] Background sell skipped — position %s exit_reason=%s",
                position_id,
                position.exit_reason,
            )
            return

        sell_quantity = position.current_quantity or 0.0
        if sell_quantity <= 0.0:
            logger.warning("[TRADING][EXECUTION][POSITION] Background sell skipped — position %s has zero quantity", position_id)
            return

        previous_phase = infer_reopen_phase_after_failed_close(position)
        execution_price = resolve_execution_price_for_position(position)

        trade = execute_closing_sell(
            database_session,
            position,
            execution_price,
            sell_quantity,
            PositionExitTriggerReason.MANUAL,
            previous_phase,
        )

        if trade is not None:
            database_session.commit()
            cache_invalidator.mark_dirty(
                CacheRealm.POSITIONS,
                CacheRealm.TRADES,
                CacheRealm.AVAILABLE_CASH,
                CacheRealm.PORTFOLIO,
            )
            logger.info(
                "[TRADING][EXECUTION][POSITION] Manual close completed for position %s (%s)",
                position_id,
                position.token_symbol,
            )


def mark_position_closing(
        database_session: Session,
        position: TradingPosition,
        reason: PositionExitTriggerReason,
) -> PositionPhase:
    previous_phase = position.position_phase
    position.position_phase = PositionPhase.CLOSING
    position.exit_reason = reason.value

    database_session.commit()
    cache_invalidator.mark_dirty(CacheRealm.POSITIONS)

    return previous_phase


def execute_position_exit_sell(
        database_session: Session,
        position: TradingPosition,
        execution_price: float,
        sell_quantity: float,
        reason: PositionExitTriggerReason,
) -> Optional[TradingTrade]:
    previous_phase = mark_position_closing(database_session, position, reason)
    return execute_closing_sell(
        database_session,
        position,
        execution_price,
        sell_quantity,
        reason,
        previous_phase,
    )


def execute_closing_sell(
        database_session: Session,
        position: TradingPosition,
        execution_price: float,
        sell_quantity: float,
        reason: PositionExitTriggerReason,
        previous_phase: PositionPhase,
) -> Optional[TradingTrade]:
    execution_outcome = None

    if not settings.PAPER_MODE:
        chain_lower = position.blockchain_network.strip().lower()
        try:
            chain_enum = BlockchainNetwork(chain_lower)
        except ValueError:
            logger.error("[TRADING][EXECUTION][POSITION] Unknown chain in DB: %s", chain_lower)
            revert_position_closing(database_session, position, previous_phase)
            return None

        chain_handler = resolve_execution_chain_handler_for_blockchain(chain_enum)
        if chain_handler is None:
            logger.error(
                "[TRADING][EXECUTION][POSITION] No execution handler for %s. Sell aborted.",
                position.token_symbol,
            )
            revert_position_closing(database_session, position, previous_phase)
            return None

        token_decimals = chain_handler.resolve_sell_token_decimals(position.token_address)
        if token_decimals is None:
            logger.error(
                "[TRADING][EXECUTION][POSITION][LIVE] Failed to fetch decimals for %s. Sell aborted.",
                position.token_symbol,
            )
            revert_position_closing(database_session, position, previous_phase)
            return None

        sell_quantity = chain_handler.cap_sell_quantity_to_wallet_balance(
            position.token_address,
            sell_quantity,
            token_decimals,
        )

        if sell_quantity <= 0.0:
            logger.error(
                "[TRADING][EXECUTION][POSITION][LIVE] Actual balance is zero or less for %s. Sell aborted.",
                position.token_symbol,
            )
            revert_position_closing(database_session, position, previous_phase)
            return None

        execution_route = build_route_for_live_sell(
            token_mint=position.token_address,
            chain=chain_enum,
            token_quantity=sell_quantity,
            token_decimals=token_decimals,
        )

        if execution_route is None:
            logger.error(
                "[TRADING][EXECUTION][POSITION][LIVE] Failed to build sell route for %s. Sell aborted.",
                position.token_symbol,
            )
            revert_position_closing(database_session, position, previous_phase)
            return None

        execution_outcome = run_live_sell_blocking(
            token_symbol=position.token_symbol,
            token_address=position.token_address,
            pair_address=position.pair_address,
            chain=chain_enum,
            dex_id=position.dex_id,
            quantity=sell_quantity,
            execution_price=execution_price,
            execution_route=execution_route,
            origin_evaluation_id=position.evaluation_id,
        )

        if execution_outcome is None:
            logger.warning(
                "[TRADING][EXECUTION][POSITION][LIVE] Execution failed or aborted by slippage guard for %s.",
                position.token_symbol,
            )
            revert_position_closing(database_session, position, previous_phase)
            return None

    trade_dao = TradingTradeDao(database_session)
    execution_status = ExecutionStatus.PAPER if settings.PAPER_MODE else ExecutionStatus.LIVE
    live_transaction_fee_usd = 0.0
    live_transaction_hash: Optional[str] = None
    if not settings.PAPER_MODE:
        live_transaction_fee_usd = execution_outcome.transaction_fee_usd
        live_transaction_hash = execution_outcome.transaction_hash_or_signature
    sell_trade = TradingTrade(
        evaluation_id=position.evaluation_id,
        trade_side=TradeSide.SELL,
        token_symbol=position.token_symbol,
        blockchain_network=position.blockchain_network,
        execution_price=execution_price,
        execution_quantity=sell_quantity,
        transaction_fee=live_transaction_fee_usd,
        realized_profit_and_loss=0.0,
        execution_status=execution_status,
        token_address=position.token_address,
        pair_address=position.pair_address,
        dex_id=position.dex_id,
        transaction_hash=live_transaction_hash,
        created_at=get_current_local_datetime(),
    )
    trade_dao.save(sell_trade)

    full_close_reasons = (
        PositionExitTriggerReason.STOP_LOSS,
        PositionExitTriggerReason.TAKE_PROFIT_2,
        PositionExitTriggerReason.MANUAL,
    )
    if reason in full_close_reasons:
        position.current_quantity = 0.0
        position.position_phase = PositionPhase.CLOSED
        position.closed_at = get_current_local_datetime()
    else:
        position.current_quantity -= sell_quantity
        if position.current_quantity <= 0.0:
            position.position_phase = PositionPhase.CLOSED
            position.closed_at = get_current_local_datetime()
        else:
            position.position_phase = PositionPhase.PARTIAL

    exit_notional = sell_quantity * execution_price
    entry_notional = sell_quantity * position.entry_price
    trade_pnl_usd = exit_notional - entry_notional
    sell_trade.realized_profit_and_loss = trade_pnl_usd

    database_session.flush()

    pnl_percentage = ((execution_price / position.entry_price) - 1) * 100

    current_time = get_current_local_datetime().replace(tzinfo=None)
    opened_time = position.opened_at.replace(tzinfo=None) if position.opened_at else current_time
    holding_duration = (current_time - opened_time).total_seconds() / 60.0

    TradingEvaluationDao(database_session).link_trade_outcome(
        token_address=position.token_address,
        trade_id=sell_trade.id,
        closed_at=get_current_local_datetime(),
        realized_profit_and_loss_percentage=pnl_percentage,
        realized_profit_and_loss_usd=trade_pnl_usd,
        holding_duration_minutes=holding_duration,
        was_profitable=(trade_pnl_usd > 0),
    )

    return sell_trade


def revert_position_closing(
        database_session: Session,
        position: TradingPosition,
        previous_phase: PositionPhase,
) -> None:
    position.position_phase = previous_phase
    position.exit_reason = None
    database_session.commit()
    cache_invalidator.mark_dirty(CacheRealm.POSITIONS, CacheRealm.PORTFOLIO)


def infer_reopen_phase_after_failed_close(position: TradingPosition) -> PositionPhase:
    open_quantity = position.open_quantity or 0.0
    current_quantity = position.current_quantity or 0.0
    if current_quantity >= open_quantity:
        return PositionPhase.OPEN
    return PositionPhase.PARTIAL


def resolve_execution_price_for_position(position: TradingPosition) -> float:
    pair_address = position.pair_address
    cached_prices = trading_cache.get_prices_by_pair_address()
    if cached_prices and pair_address in cached_prices:
        cached_price = cached_prices[pair_address]
        if cached_price > 0.0:
            return cached_price

    token = convert_trading_position_to_token(position)
    try:
        fetched_prices = fetch_onchain_prices_for_tokens([token])
        fetched_price = fetched_prices.get(pair_address)
        if fetched_price is not None and fetched_price > 0.0:
            return fetched_price
    except Exception:
        logger.exception(
            "[TRADING][EXECUTION][POSITION] On-chain price fetch failed for %s, falling back to entry price",
            position.token_symbol,
        )

    return position.entry_price
