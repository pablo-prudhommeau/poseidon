from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.websocket.telemetry import TelemetryService
from src.configuration.config import settings
from src.core.structures.structures import Token, BlockchainNetwork
from src.core.trading.execution.trading_executor import TradingExecutor
from src.core.trading.execution.trading_order_builder import build_route_for_live_sell
from src.core.trading.trading_service import invalidate_trading_positions_and_trades_cache
from src.core.trading.trading_structures import AutosellTriggerReason
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_trade_dao import TradingTradeDao
from src.persistence.models import TradingPosition, TradingTrade, ExecutionStatus, PositionPhase, TradeSide

logger = get_application_logger(__name__)


def check_thresholds_and_autosell_for_token_address(
        database_session: Session,
        token: Token,
        last_price: float,
) -> List[TradingTrade]:
    created_trades: List[TradingTrade] = []
    if not token or last_price <= 0.0:
        return created_trades

    database_query = select(TradingPosition).where(
        TradingPosition.blockchain_network == token.chain.value,
        TradingPosition.token_address == token.token_address,
        TradingPosition.pair_address == token.pair_address,
        TradingPosition.position_phase.in_([PositionPhase.OPEN, PositionPhase.PARTIAL]),
    )
    position = database_session.execute(database_query).scalars().first()

    if not position:
        return created_trades

    created_trades = _evaluate_position_thresholds(database_session, position, last_price)

    if created_trades:
        database_session.commit()
        invalidate_trading_positions_and_trades_cache()

    return created_trades


def _execute_sell_operation(
        database_session: Session,
        position: TradingPosition,
        execution_price: float,
        sell_quantity: float,
        reason: AutosellTriggerReason,
) -> Optional[TradingTrade]:
    if not settings.PAPER_MODE:
        chain_lower = position.blockchain_network.strip().lower()
        try:
            chain_enum = BlockchainNetwork(chain_lower)
        except ValueError:
            logger.error("[TRADING][AUTOSELL] Unknown chain in DB: %s", chain_lower)
            return None

        if chain_enum == BlockchainNetwork.SOLANA:
            from src.integrations.blockchain.solana.solana_rpc_client import get_spl_token_decimals
            from src.integrations.blockchain.blockchain_rpc_registry import resolve_rpc_url_for_chain
            from src.integrations.blockchain.blockchain_free_cash_service import _fetch_solana_stablecoin_balance
            from src.integrations.blockchain.solana.blockchain_solana_signer import build_default_solana_signer

            rpc_url = resolve_rpc_url_for_chain(BlockchainNetwork.SOLANA)
            decimals = get_spl_token_decimals(rpc_url, position.token_address)
            if decimals is None:
                logger.error("[TRADING][AUTOSELL][LIVE] Failed to fetch decimals for %s. Sell aborted.", position.token_symbol)
                return None

            try:
                wallet_address = build_default_solana_signer().address
                actual_balance = _fetch_solana_stablecoin_balance(rpc_url, wallet_address, position.token_address)
                if actual_balance < sell_quantity:
                    logger.warning("[TRADING][AUTOSELL][LIVE] Actual balance (%.6f) is less than theoretical (%.6f). Capping sell quantity.", actual_balance, sell_quantity)
                    sell_quantity = actual_balance
            except Exception as exception:
                logger.warning("[TRADING][AUTOSELL][LIVE] Could not fetch actual balance for capping: %s", exception)

        else:
            decimals = 18
            try:
                from src.integrations.blockchain.blockchain_rpc_registry import resolve_rpc_url_for_chain
                from src.integrations.blockchain.blockchain_free_cash_service import _fetch_evm_stablecoin_balance
                from src.integrations.blockchain.evm.blockchain_evm_signer import build_default_evm_signer

                rpc_url = resolve_rpc_url_for_chain(chain_enum)
                wallet_address = build_default_evm_signer(chain=chain_enum).wallet_address
                actual_balance = _fetch_evm_stablecoin_balance(rpc_url, wallet_address, position.token_address)
                if actual_balance < sell_quantity:
                    logger.warning("[TRADING][AUTOSELL][LIVE] Actual balance (%.6f) is less than theoretical (%.6f). Capping sell quantity.", actual_balance, sell_quantity)
                    sell_quantity = actual_balance
            except Exception as exception:
                logger.warning("[TRADING][AUTOSELL][LIVE] Could not fetch actual EVM balance for capping: %s", exception)

        if sell_quantity <= 0.0:
            logger.error("[TRADING][AUTOSELL][LIVE] Actual balance is zero or less for %s. Sell aborted.", position.token_symbol)
            return None

        execution_route = build_route_for_live_sell(
            token_mint=position.token_address,
            chain=chain_enum,
            token_quantity=sell_quantity,
            token_decimals=decimals
        )

        if execution_route is None:
            logger.error("[TRADING][AUTOSELL][LIVE] Failed to build sell route for %s. Sell aborted.", position.token_symbol)
            return None

        executor = TradingExecutor()
        execution_outcome = executor.run_live_sell_blocking(
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
            logger.warning("[TRADING][AUTOSELL][LIVE] Execution failed or aborted by slippage guard for %s. Ignoring autosell tick.", position.token_symbol)
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
    )
    trade_dao.save(sell_trade)

    if reason in (AutosellTriggerReason.STOP_LOSS, AutosellTriggerReason.TAKE_PROFIT_2):
        position.current_quantity = 0.0
        position.position_phase = PositionPhase.CLOSED
    else:
        position.current_quantity -= sell_quantity
        if position.current_quantity <= 0.0:
            position.position_phase = PositionPhase.CLOSED
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

    TelemetryService.link_trade_outcome(
        token_address=position.token_address,
        trade_id=sell_trade.id,
        closed_at=get_current_local_datetime(),
        realized_profit_and_loss_percentage=pnl_percentage,
        realized_profit_and_loss_usd=trade_pnl_usd,
        holding_duration_minutes=holding_duration,
        was_profitable=(trade_pnl_usd > 0),
        exit_reason=reason.value,
        database_session=database_session,
    )

    return sell_trade


def _evaluate_position_thresholds(
        database_session: Session,
        position: TradingPosition,
        last_price_value: float,
) -> List[TradingTrade]:
    created_trades: List[TradingTrade] = []
    position_quantity = position.current_quantity or 0.0

    if position_quantity <= 0.0:
        return created_trades

    tp1 = position.take_profit_tier_1_price or 0.0
    tp2 = position.take_profit_tier_2_price or 0.0
    stop = position.stop_loss_price or 0.0

    if stop > 0.0 and last_price_value <= stop:
        logger.info("[TRADING][AUTOSELL][SL] Triggered for %s @ %.12f (stop=%.12f)", position.token_symbol, last_price_value, stop)
        trade = _execute_sell_operation(database_session, position, last_price_value, position_quantity, AutosellTriggerReason.STOP_LOSS)
        if trade:
            created_trades.append(trade)
        return created_trades

    if tp2 > 0.0 and last_price_value >= tp2:
        logger.info("[TRADING][AUTOSELL][TP2] Triggered for %s @ %.12f (tp2=%.12f)", position.token_symbol, last_price_value, tp2)
        trade = _execute_sell_operation(database_session, position, last_price_value, position_quantity, AutosellTriggerReason.TAKE_PROFIT_2)
        if trade:
            created_trades.append(trade)
        return created_trades

    if tp1 > 0.0 and last_price_value >= tp1 and position.position_phase == PositionPhase.OPEN:
        take_profit_fraction = max(0.0, min(1.0, settings.TRADING_TP1_TAKE_PROFIT_FRACTION))
        partial_quantity = position_quantity * take_profit_fraction
        if partial_quantity > 0.0:
            logger.info("[TRADING][AUTOSELL][TP1] Triggered for %s @ %.12f (tp1=%.12f)", position.token_symbol, last_price_value, tp1)
            trade = _execute_sell_operation(database_session, position, last_price_value, partial_quantity, AutosellTriggerReason.TAKE_PROFIT_1)
            if trade:
                created_trades.append(trade)

    return created_trades
