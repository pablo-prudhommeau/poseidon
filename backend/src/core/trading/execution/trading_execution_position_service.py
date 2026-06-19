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
from src.core.trading.execution.trading_blockchain_circuit_breaker_service import (
    record_retryable_exit_failure,
    reset_retryable_exit_failure_count,
    should_block_live_sell_before_broadcast,
    should_mark_position_staled_after_retryable_exit_failure,
    should_mark_position_staled_immediately_after_failure,
)
from src.core.trading.execution.solana.trading_execution_solana_service import (
    build_solana_sell_route_with_smallest_unit_amount,
    resolve_solana_wallet_token_transfer_blocked_for_mint,
    resolve_sell_amount_in_lamports_for_close,
    resolve_wallet_token_balance_raw_for_mint,
)
from src.core.trading.execution.trading_execution_notification_service import (
    dispatch_position_dust_remaining_alert,
)
from src.core.trading.execution.trading_execution_swap_service import run_live_sell_blocking
from src.integrations.blockchain.blockchain_execution_structures import BlockchainTransactionFailureReason
from src.core.trading.trading_structures import PositionExitTriggerReason
from src.core.trading.trading_utils import convert_trading_position_to_token
from src.core.trading.execution.trading_execution_structures import TradingPositionClosingSellResult
from src.core.trading.portfolio.trading_portfolio_stablecoin_settlement_service import (
    poll_deployable_stablecoin_until_swap_settled,
    resolve_total_deployable_stablecoin_cash_usd,
)
from src.core.trading.portfolio.trading_portfolio_structures import StablecoinSwapSettlementDirection
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.blockchain.blockchain_exceptions import (
    BlockchainExecutionRouteBuildError,
    BlockchainRpcUnavailableError,
    BlockchainTradingNotSupportedError,
    BlockchainPriceUnavailableError,
)
from src.integrations.blockchain.blockchain_price_service import fetch_onchain_prices_for_tokens
from src.integrations.blockchain.solana.blockchain_solana_transaction_trade_amounts_service import (
    resolve_solana_executed_trade_amounts_from_transaction,
)
from src.integrations.blockchain.solana.solana_structures import SolanaExecutedTradeAmounts
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


class PositionRecoveryConflictError(Exception):
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

        trade_outcome = execute_closing_sell(
            database_session,
            position,
            execution_price,
            sell_quantity,
            PositionExitTriggerReason.MANUAL,
            previous_phase,
        )

        if trade_outcome.trading_trade is not None:
            database_session.commit()
            _invalidate_trading_realms_after_closing_sell(
                stablecoin_swap_settled_on_chain=trade_outcome.stablecoin_swap_settled_on_chain,
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
) -> TradingPositionClosingSellResult:
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
) -> TradingPositionClosingSellResult:
    try:
        return _execute_closing_sell(
            database_session=database_session,
            position=position,
            execution_price=execution_price,
            sell_quantity=sell_quantity,
            reason=reason,
            previous_phase=previous_phase,
        )
    except Exception:
        logger.exception(
            "[TRADING][EXECUTION][POSITION] Closing sell failed — position_id=%s token=%s reason=%s previous_phase=%s",
            position.id,
            position.token_symbol,
            reason.value,
            previous_phase.value,
        )
        if position.position_phase == PositionPhase.CLOSING:
            revert_position_closing(database_session, position, previous_phase)
        return TradingPositionClosingSellResult(
            trading_trade=None,
            stablecoin_swap_settled_on_chain=False,
        )


def _invalidate_trading_realms_after_closing_sell(stablecoin_swap_settled_on_chain: bool) -> None:
    if stablecoin_swap_settled_on_chain:
        cache_invalidator.mark_dirty(
            CacheRealm.POSITIONS,
            CacheRealm.TRADES,
            CacheRealm.AVAILABLE_CASH,
            CacheRealm.PORTFOLIO,
        )
        return

    cache_invalidator.mark_dirty(
        CacheRealm.POSITIONS,
        CacheRealm.TRADES,
    )


def _execute_closing_sell(
        database_session: Session,
        position: TradingPosition,
        execution_price: float,
        sell_quantity: float,
        reason: PositionExitTriggerReason,
        previous_phase: PositionPhase,
) -> TradingPositionClosingSellResult:
    stablecoin_swap_settled_on_chain = True
    execution_outcome = None
    deployable_cash_before_swap_usd = 0.0
    executed_trade_amounts: Optional[SolanaExecutedTradeAmounts] = None
    chain_enum: Optional[BlockchainNetwork] = None
    token_decimals = 0
    full_close_reasons = (
        PositionExitTriggerReason.STOP_LOSS,
        PositionExitTriggerReason.TAKE_PROFIT_2,
        PositionExitTriggerReason.MANUAL,
    )
    is_full_close = reason in full_close_reasons

    if not settings.PAPER_MODE:
        chain_lower = position.blockchain_network.strip().lower()
        try:
            chain_enum = BlockchainNetwork(chain_lower)
        except ValueError:
            logger.error("[TRADING][EXECUTION][POSITION] Unknown chain in DB: %s", chain_lower)
            revert_position_closing(database_session, position, previous_phase)
            return TradingPositionClosingSellResult()

        chain_handler = resolve_execution_chain_handler_for_blockchain(chain_enum)

        try:
            token_decimals = chain_handler.resolve_sell_token_decimals(position.token_address)
        except BlockchainRpcUnavailableError:
            logger.debug(
                "[TRADING][EXECUTION][POSITION][LIVE] Token decimals unavailable for %s — reverting closing, will retry later",
                position.token_symbol,
            )
            revert_position_closing(database_session, position, previous_phase)
            return TradingPositionClosingSellResult()
        except BlockchainTradingNotSupportedError:
            logger.error(
                "[TRADING][EXECUTION][POSITION][LIVE] Live trading not supported for %s on %s — sell aborted",
                position.token_symbol,
                chain_enum.value,
            )
            revert_position_closing(database_session, position, previous_phase)
            return TradingPositionClosingSellResult()

        try:
            deployable_cash_before_swap_usd = resolve_total_deployable_stablecoin_cash_usd()
        except BlockchainRpcUnavailableError:
            logger.debug(
                "[TRADING][EXECUTION][POSITION][LIVE] Deployable baseline unavailable for %s — reverting closing, will retry later",
                position.token_symbol,
            )
            revert_position_closing(database_session, position, previous_phase)
            return TradingPositionClosingSellResult()

        try:
            sell_quantity = chain_handler.cap_sell_quantity_to_wallet_balance(
                position.token_address,
                sell_quantity,
                token_decimals,
            )
        except BlockchainRpcUnavailableError:
            logger.debug(
                "[TRADING][EXECUTION][POSITION][LIVE] Wallet balance unavailable for %s — reverting closing, will retry later",
                position.token_symbol,
            )
            revert_position_closing(database_session, position, previous_phase)
            return TradingPositionClosingSellResult()

        if sell_quantity <= 0.0:
            logger.error(
                "[TRADING][EXECUTION][POSITION][LIVE] Wallet SPL balance is zero for %s while position still holds quantity — marking STALED (external sell or ledger desync)",
                position.token_symbol,
            )
            mark_position_staled(database_session, position, PositionExitTriggerReason.WALLET_BALANCE_EMPTY)
            return TradingPositionClosingSellResult()

        if chain_enum == BlockchainNetwork.SOLANA:
            wallet_token_transfer_blocked = resolve_solana_wallet_token_transfer_blocked_for_mint(position.token_address)
            if should_block_live_sell_before_broadcast(wallet_token_transfer_blocked):
                logger.error(
                    "[TRADING][EXECUTION][POSITION][LIVE][SELL] Wallet token account frozen for %s — closing position as HONEYPOT",
                    position.token_symbol,
                )
                close_position_as_honeypot(database_session=database_session, position=position)
                return TradingPositionClosingSellResult()

        if chain_enum == BlockchainNetwork.SOLANA:
            token_amount_in_smallest_unit = resolve_sell_amount_in_lamports_for_close(
                token_mint_address=position.token_address,
                sell_quantity_human=sell_quantity,
                token_decimals=token_decimals,
                is_full_close=is_full_close,
            )
            if token_amount_in_smallest_unit <= 0:
                logger.error(
                    "[TRADING][EXECUTION][POSITION][LIVE] Wallet SPL balance is zero for %s while position still holds quantity — marking STALED (external sell or ledger desync)",
                    position.token_symbol,
                )
                mark_position_staled(database_session, position, PositionExitTriggerReason.WALLET_BALANCE_EMPTY)
                return TradingPositionClosingSellResult()
            sell_quantity = float(token_amount_in_smallest_unit) / float(10 ** token_decimals)

        try:
            if chain_enum == BlockchainNetwork.SOLANA:
                execution_route = build_solana_sell_route_with_smallest_unit_amount(
                    token_mint=position.token_address,
                    token_amount_in_smallest_unit=token_amount_in_smallest_unit,
                )
            else:
                execution_route = build_route_for_live_sell(
                    token_mint=position.token_address,
                    chain=chain_enum,
                    token_quantity=sell_quantity,
                    token_decimals=token_decimals,
                )
        except BlockchainExecutionRouteBuildError as route_build_error:
            if route_build_error.is_transient:
                logger.debug(
                    "[TRADING][EXECUTION][POSITION][LIVE] Sell route unavailable for %s — reverting closing, will retry later",
                    position.token_symbol,
                )
            else:
                logger.warning(
                    "[TRADING][EXECUTION][POSITION][LIVE] Sell route build failed for %s — reverting closing, will retry later",
                    position.token_symbol,
                )
            revert_position_closing(database_session, position, previous_phase)
            return TradingPositionClosingSellResult()
        except BlockchainTradingNotSupportedError:
            logger.error(
                "[TRADING][EXECUTION][POSITION][LIVE] Live sell route not supported for %s on %s — sell aborted",
                position.token_symbol,
                chain_enum.value,
            )
            revert_position_closing(database_session, position, previous_phase)
            return TradingPositionClosingSellResult()

        sell_execution_outcome = run_live_sell_blocking(
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

        if sell_execution_outcome.execution_result is None:
            logger.warning(
                "[TRADING][EXECUTION][POSITION][LIVE] Execution failed or aborted for %s.",
                position.token_symbol,
            )
            _handle_failed_closing_sell(
                database_session=database_session,
                position=position,
                previous_phase=previous_phase,
                failure_reason=sell_execution_outcome.failure_reason,
            )
            return TradingPositionClosingSellResult()

        execution_outcome = sell_execution_outcome.execution_result
        if position.id is not None:
            reset_retryable_exit_failure_count(position.id)

        settlement_poll_result = poll_deployable_stablecoin_until_swap_settled(
            deployable_cash_before_swap_usd=deployable_cash_before_swap_usd,
            settlement_direction=StablecoinSwapSettlementDirection.SELL_CREDIT,
            transaction_signature=execution_outcome.transaction_hash_or_signature,
        )
        stablecoin_swap_settled_on_chain = settlement_poll_result.swap_settled_on_chain

        if chain_enum == BlockchainNetwork.SOLANA:
            executed_trade_amounts = resolve_solana_executed_trade_amounts_from_transaction(
                transaction_signature=execution_outcome.transaction_hash_or_signature,
                target_token_mint_address=position.token_address,
                token_decimals=token_decimals,
            )
            if executed_trade_amounts is not None:
                execution_price = executed_trade_amounts.executed_token_price_usd
                sell_quantity = executed_trade_amounts.executed_token_quantity
                logger.info(
                    "[TRADING][EXECUTION][POSITION][LIVE][SELL] Recorded on-chain executed trade amounts — "
                    "token=%s executed_token_price_usd=%.12f executed_token_quantity=%.12f stablecoin_balance_delta_usd=%.6f",
                    position.token_symbol,
                    execution_price,
                    sell_quantity,
                    executed_trade_amounts.stablecoin_balance_delta_usd,
                )
            else:
                logger.warning(
                    "[TRADING][EXECUTION][POSITION][LIVE][SELL] On-chain trade amount parsing unavailable — "
                    "token=%s transaction_signature=%s falling back to quote-based PnL",
                    position.token_symbol,
                    execution_outcome.transaction_hash_or_signature,
                )

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

    if is_full_close:
        position.current_quantity = 0.0
        position.position_phase = PositionPhase.CLOSED
        position.closed_at = get_current_local_datetime()
    else:
        if (
                not settings.PAPER_MODE
                and chain_enum == BlockchainNetwork.SOLANA
                and token_decimals > 0
        ):
            remaining_balance_raw = resolve_wallet_token_balance_raw_for_mint(position.token_address)
            position.current_quantity = float(remaining_balance_raw) / float(10 ** token_decimals)
        else:
            position.current_quantity -= sell_quantity
        if position.current_quantity <= 0.0:
            position.position_phase = PositionPhase.CLOSED
            position.closed_at = get_current_local_datetime()
        else:
            position.position_phase = PositionPhase.PARTIAL

    if executed_trade_amounts is not None and executed_trade_amounts.stablecoin_balance_delta_usd > 0.0:
        exit_notional = executed_trade_amounts.stablecoin_balance_delta_usd
    else:
        exit_notional = sell_quantity * execution_price
    entry_notional = sell_quantity * position.entry_price
    allocated_buy_swap_fee_usd = _resolve_allocated_buy_swap_fee_usd_for_sell(
        database_session=database_session,
        evaluation_id=position.evaluation_id,
        sell_quantity=sell_quantity,
    )
    sell_swap_fee_usd = live_transaction_fee_usd
    trade_pnl_usd = exit_notional - entry_notional - allocated_buy_swap_fee_usd - sell_swap_fee_usd
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

    if (
            is_full_close
            and not settings.PAPER_MODE
            and chain_enum == BlockchainNetwork.SOLANA
            and token_decimals > 0
    ):
        remaining_balance_raw = resolve_wallet_token_balance_raw_for_mint(position.token_address)
        if remaining_balance_raw > 0:
            dispatch_position_dust_remaining_alert(
                token_symbol=position.token_symbol,
                token_mint_address=position.token_address,
                remaining_balance_raw=remaining_balance_raw,
                token_decimals=token_decimals,
                position_id=position.id,
            )

    return TradingPositionClosingSellResult(
        trading_trade=sell_trade,
        stablecoin_swap_settled_on_chain=stablecoin_swap_settled_on_chain,
    )


def revert_position_closing(
        database_session: Session,
        position: TradingPosition,
        previous_phase: PositionPhase,
) -> None:
    position.position_phase = previous_phase
    position.exit_reason = None
    database_session.commit()
    cache_invalidator.mark_dirty(CacheRealm.POSITIONS, CacheRealm.PORTFOLIO)


def mark_position_staled(
        database_session: Session,
        position: TradingPosition,
        staled_exit_reason: PositionExitTriggerReason,
) -> None:
    position.position_phase = PositionPhase.STALED
    position.exit_reason = staled_exit_reason.value
    database_session.commit()
    cache_invalidator.mark_dirty(CacheRealm.POSITIONS, CacheRealm.PORTFOLIO)
    logger.warning(
        "[TRADING][EXECUTION][POSITION][STALED] Position marked STALED — position_id=%s token=%s exit_reason=%s",
        position.id,
        position.token_symbol,
        staled_exit_reason.value,
    )


def close_position_as_honeypot(database_session: Session, position: TradingPosition) -> None:
    close_position_with_synthetic_total_loss(
        database_session=database_session,
        position=position,
        exit_reason=PositionExitTriggerReason.HONEYPOT,
    )


def close_position_with_synthetic_total_loss(
        database_session: Session,
        position: TradingPosition,
        exit_reason: PositionExitTriggerReason,
) -> None:
    open_quantity = position.open_quantity or 0.0
    entry_price = position.entry_price or 0.0
    entry_notional_usd = open_quantity * entry_price

    trade_dao = TradingTradeDao(database_session)
    execution_status = ExecutionStatus.PAPER if settings.PAPER_MODE else ExecutionStatus.LIVE
    synthetic_sell_trade = TradingTrade(
        evaluation_id=position.evaluation_id,
        trade_side=TradeSide.SELL,
        token_symbol=position.token_symbol,
        blockchain_network=position.blockchain_network,
        execution_price=0.0,
        execution_quantity=0.0,
        transaction_fee=0.0,
        realized_profit_and_loss=-entry_notional_usd,
        execution_status=execution_status,
        token_address=position.token_address,
        pair_address=position.pair_address,
        dex_id=position.dex_id,
        transaction_hash=None,
        created_at=get_current_local_datetime(),
    )
    trade_dao.save(synthetic_sell_trade)

    position.current_quantity = 0.0
    position.position_phase = PositionPhase.CLOSED
    position.closed_at = get_current_local_datetime()
    position.exit_reason = exit_reason.value

    current_time = get_current_local_datetime().replace(tzinfo=None)
    opened_time = position.opened_at.replace(tzinfo=None) if position.opened_at else current_time
    holding_duration_minutes = (current_time - opened_time).total_seconds() / 60.0

    TradingEvaluationDao(database_session).link_trade_outcome(
        token_address=position.token_address,
        trade_id=synthetic_sell_trade.id,
        closed_at=get_current_local_datetime(),
        realized_profit_and_loss_percentage=-100.0,
        realized_profit_and_loss_usd=-entry_notional_usd,
        holding_duration_minutes=holding_duration_minutes,
        was_profitable=False,
    )

    if position.id is not None:
        reset_retryable_exit_failure_count(position.id)

    database_session.commit()
    cache_invalidator.mark_dirty(
        CacheRealm.POSITIONS,
        CacheRealm.TRADES,
        CacheRealm.AVAILABLE_CASH,
        CacheRealm.PORTFOLIO,
    )
    logger.warning(
        "[TRADING][EXECUTION][POSITION][%s] Position closed with synthetic total loss — position_id=%s token=%s",
        exit_reason.value,
        position.id,
        position.token_symbol,
    )


def kill_staled_position(database_session: Session, position_id: int) -> None:
    position = database_session.get(TradingPosition, position_id)
    if position is None:
        raise PositionCloseNotFoundError(f"Position {position_id} not found")

    if position.position_phase != PositionPhase.STALED:
        raise PositionRecoveryConflictError(f"Position {position_id} is not STALED")

    close_position_with_synthetic_total_loss(
        database_session=database_session,
        position=position,
        exit_reason=PositionExitTriggerReason.KILLED,
    )
    logger.info(
        "[TRADING][EXECUTION][POSITION][KILL] Staled position killed — position_id=%s token=%s",
        position_id,
        position.token_symbol,
    )


def reopen_staled_position(database_session: Session, position_id: int) -> None:
    position = database_session.get(TradingPosition, position_id)
    if position is None:
        raise PositionCloseNotFoundError(f"Position {position_id} not found")

    if position.position_phase != PositionPhase.STALED:
        raise PositionRecoveryConflictError(f"Position {position_id} is not STALED")

    position.position_phase = infer_reopen_phase_after_failed_close(position)
    position.exit_reason = None
    reset_retryable_exit_failure_count(position_id)
    database_session.commit()
    cache_invalidator.mark_dirty(CacheRealm.POSITIONS, CacheRealm.PORTFOLIO)
    logger.info(
        "[TRADING][EXECUTION][POSITION][REOPEN] Staled position reopened — position_id=%s token=%s phase=%s",
        position_id,
        position.token_symbol,
        position.position_phase.value,
    )


def _handle_failed_closing_sell(
        database_session: Session,
        position: TradingPosition,
        previous_phase: PositionPhase,
        failure_reason: BlockchainTransactionFailureReason | None,
) -> None:
    position_id = position.id
    if position_id is None:
        revert_position_closing(database_session, position, previous_phase)
        return

    if should_mark_position_staled_immediately_after_failure(failure_reason):
        if failure_reason == BlockchainTransactionFailureReason.ACCOUNT_FROZEN:
            close_position_as_honeypot(database_session=database_session, position=position)
            return

        mark_position_staled(database_session, position, PositionExitTriggerReason.CIRCUIT_BREAKER)
        return

    record_retryable_exit_failure(position_id)
    if should_mark_position_staled_after_retryable_exit_failure(position_id):
        mark_position_staled(database_session, position, PositionExitTriggerReason.CIRCUIT_BREAKER)
        return

    revert_position_closing(database_session, position, previous_phase)


def infer_reopen_phase_after_failed_close(position: TradingPosition) -> PositionPhase:
    open_quantity = position.open_quantity or 0.0
    current_quantity = position.current_quantity or 0.0
    if current_quantity >= open_quantity:
        return PositionPhase.OPEN
    return PositionPhase.PARTIAL


def resolve_execution_price_for_position(position: TradingPosition) -> float:
    pair_address = position.pair_address
    blockchain_network = BlockchainNetwork(position.blockchain_network.lower())
    cached_onchain_prices = trading_cache.get_onchain_prices_by_pair_address()
    if cached_onchain_prices is not None and pair_address:
        try:
            return cached_onchain_prices.resolve_price_usd_for_pair_address(
                pair_address,
                blockchain_network=blockchain_network,
            )
        except BlockchainPriceUnavailableError:
            pass

    token = convert_trading_position_to_token(position)
    try:
        fetched_onchain_prices = fetch_onchain_prices_for_tokens([token])
        return fetched_onchain_prices.resolve_price_usd_for_pair_address(
            pair_address,
            blockchain_network=blockchain_network,
        )
    except BlockchainPriceUnavailableError:
        logger.exception(
            "[TRADING][EXECUTION][POSITION] On-chain price fetch failed for %s, falling back to entry price",
            position.token_symbol,
        )

    return position.entry_price


def _resolve_allocated_buy_swap_fee_usd_for_sell(
        database_session: Session,
        evaluation_id: int,
        sell_quantity: float,
) -> float:
    if sell_quantity <= 0.0:
        return 0.0
    trade_dao = TradingTradeDao(database_session)
    evaluation_trades = trade_dao.retrieve_by_evaluation_id(evaluation_id)
    for trade_record in evaluation_trades:
        if trade_record.trade_side != TradeSide.BUY:
            continue
        buy_quantity = trade_record.execution_quantity if trade_record.execution_quantity is not None else 0.0
        if buy_quantity <= 0.0:
            return 0.0
        buy_swap_fee_usd = trade_record.transaction_fee if trade_record.transaction_fee is not None else 0.0
        return buy_swap_fee_usd * (sell_quantity / buy_quantity)
    return 0.0
