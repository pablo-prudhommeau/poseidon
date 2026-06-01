from __future__ import annotations

import threading
from typing import Optional

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.configuration.config import settings
from src.core.structures.structures import Token, BlockchainNetwork
from src.core.trading.execution.trading_execution_handler_service import resolve_execution_chain_handler_for_blockchain
from src.core.trading.trading_structures import TradingOrderPayload
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.blockchain.blockchain_live_executor import BlockchainExecutionResult
from src.integrations.blockchain.blockchain_exceptions import BlockchainPriceUnavailableError
from src.integrations.blockchain.blockchain_price_service import fetch_onchain_price_for_token
from src.integrations.blockchain.blockchain_structures import BlockchainExecutionRoute
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_position_dao import TradingPositionDao
from src.persistence.dao.trading_trade_dao import TradingTradeDao
from src.persistence.database_session_manager import get_database_session
from src.persistence.models import ExecutionStatus, TradingTrade, TradingPosition, TradeSide, PositionPhase

logger = get_application_logger(__name__)

SWAP_EXECUTION_LOCK = threading.Lock()


def run_live_sell_blocking(
        token_symbol: str,
        token_address: str,
        pair_address: str,
        chain: BlockchainNetwork,
        dex_id: str,
        quantity: float,
        execution_price: float,
        execution_route: BlockchainExecutionRoute,
        origin_evaluation_id: int,
) -> Optional[BlockchainExecutionResult]:
    chain_handler = resolve_execution_chain_handler_for_blockchain(chain)
    if chain_handler is None:
        logger.warning(
            "[TRADING][EXECUTION][SWAP] Live sell blocked — no handler for blockchain_network=%s token=%s",
            chain.value,
            token_symbol,
        )
        return None

    with SWAP_EXECUTION_LOCK:
        logger.debug("[TRADING][EXECUTION][SWAP][LIVE][SELL] Acquired global execution lock")
        return chain_handler.run_live_sell_blocking(
            token_symbol=token_symbol,
            token_address=token_address,
            pair_address=pair_address,
            dex_id=dex_id,
            quantity=quantity,
            execution_price=execution_price,
            execution_route=execution_route,
            origin_evaluation_id=origin_evaluation_id,
        )


def execute_buy(payload: TradingOrderPayload) -> bool:
    logger.debug("[TRADING][EXECUTION][SWAP][BUY] Normalized order — %s", payload.target_token)

    if not payload.target_token.chain or not payload.target_token.pair_address:
        logger.debug("[TRADING][EXECUTION][SWAP][BUY] Skip: missing chain or pair_address — %s", payload.target_token)
        return False

    onchain_price_usd = _fetch_onchain_price_for_token(payload.target_token)

    if onchain_price_usd is None or onchain_price_usd <= 0.0:
        logger.warning(
            "[TRADING][EXECUTION][SWAP][BUY] Skip: CRITICAL FAILURE — On-chain price absolutely required but missing for %s (DEX: %s). Trade aborted for safety.",
            payload.target_token.symbol,
            payload.target_token.dex_id,
        )
        return False

    price_usd = onchain_price_usd

    maximum_slippage = settings.TRADING_MAX_SLIPPAGE
    if payload.execution_price is not None and payload.execution_price > 0.0:
        low_price, high_price = sorted([onchain_price_usd, payload.execution_price])
        if (high_price / low_price - 1.0) > maximum_slippage:
            logger.warning(
                "[TRADING][EXECUTION][SWAP][BUY] Skip: slippage too high for %s — onchain=%.12f pipeline=%.12f (>%.1f%%)",
                payload.target_token.symbol,
                onchain_price_usd,
                payload.execution_price,
                maximum_slippage * 100.0,
            )
            return False

    if payload.order_notional <= 0.0:
        logger.debug(
            "[TRADING][EXECUTION][SWAP][BUY] Skip: non-positive order_notional_usd=%.6f for %s",
            payload.order_notional,
            payload.target_token,
        )
        return False

    quantity = payload.order_notional / price_usd
    logger.debug(
        "[TRADING][EXECUTION][SWAP][BUY] Sized order — notional=%.4f price=%.12f quantity=%.12f",
        payload.order_notional,
        price_usd,
        quantity,
    )

    take_profit_one_fraction = settings.TRADING_TP1_EXIT_FRACTION
    take_profit_two_fraction = settings.TRADING_TP2_EXIT_FRACTION
    stop_loss_fraction = settings.TRADING_STOP_LOSS_FRACTION

    take_profit_tp1 = price_usd * (1.0 + take_profit_one_fraction)
    take_profit_tp2 = price_usd * (1.0 + take_profit_two_fraction)
    stop_loss = price_usd * (1.0 - stop_loss_fraction)

    logger.info(
        "[TRADING][EXECUTION][SWAP][THRESHOLDS] entry=%.10f tp1=%.6f (%.1f%%) tp2=%.6f (%.1f%%) stop=%.6f (%.1f%%)",
        price_usd,
        take_profit_tp1,
        take_profit_one_fraction * 100,
        take_profit_tp2,
        take_profit_two_fraction * 100,
        stop_loss,
        stop_loss_fraction * 100,
    )

    if settings.PAPER_MODE:
        logger.info("[TRADING][EXECUTION][SWAP][BUY] PAPER trade — %s @ %.12f qty=%.12f", payload.target_token, price_usd, quantity)
        with get_database_session() as database_session:
            trade_dao = TradingTradeDao(database_session)
            position_dao = TradingPositionDao(database_session)

            trading_trade = TradingTrade(
                evaluation_id=payload.origin_evaluation_id,
                trade_side=TradeSide.BUY,
                token_symbol=payload.target_token.symbol,
                blockchain_network=payload.target_token.chain,
                execution_price=price_usd,
                execution_quantity=quantity,
                transaction_fee=0.0,
                realized_profit_and_loss=None,
                execution_status=ExecutionStatus.PAPER,
                token_address=payload.target_token.token_address,
                pair_address=payload.target_token.pair_address,
                dex_id=payload.target_token.dex_id,
                created_at=get_current_local_datetime(),
            )
            trade_dao.save(trading_trade)

            trading_position = TradingPosition(
                evaluation_id=payload.origin_evaluation_id,
                token_symbol=payload.target_token.symbol,
                blockchain_network=payload.target_token.chain,
                token_address=payload.target_token.token_address,
                pair_address=payload.target_token.pair_address,
                open_quantity=quantity,
                current_quantity=quantity,
                entry_price=price_usd,
                take_profit_tier_1_price=take_profit_tp1,
                take_profit_tier_2_price=take_profit_tp2,
                stop_loss_price=stop_loss,
                position_phase=PositionPhase.OPEN,
                dex_id=payload.target_token.dex_id,
                opened_at=get_current_local_datetime(),
                updated_at=get_current_local_datetime(),
            )
            position_dao.save(trading_position)
            database_session.commit()

        cache_invalidator.mark_dirty(
            CacheRealm.POSITIONS,
            CacheRealm.TRADES,
            CacheRealm.AVAILABLE_CASH,
            CacheRealm.PORTFOLIO,
        )
        return True

    if payload.execution_route is None:
        logger.info(
            "[TRADING][EXECUTION][SWAP][LIVE][BUY] Skip: missing execution route for %s (LIVE disabled for this order)",
            payload.target_token,
        )
        return False

    chain_handler = resolve_execution_chain_handler_for_blockchain(payload.target_token.chain)
    if chain_handler is None:
        logger.warning(
            "[TRADING][EXECUTION][SWAP][LIVE][BUY] Skip: no handler for blockchain_network=%s token=%s",
            payload.target_token.chain.value,
            payload.target_token.symbol,
        )
        return False

    with SWAP_EXECUTION_LOCK:
        logger.debug("[TRADING][EXECUTION][SWAP][LIVE][BUY] Acquired global execution lock")
        return chain_handler.run_live_buy_blocking(
            token=payload.target_token,
            quantity=quantity,
            price_usd=price_usd,
            stop_loss_usd=stop_loss,
            take_profit_tp1_usd=take_profit_tp1,
            take_profit_tp2_usd=take_profit_tp2,
            execution_route=payload.execution_route,
            origin_evaluation_id=payload.origin_evaluation_id,
        )


def _fetch_onchain_price_for_token(token: Token) -> Optional[float]:
    try:
        price_usd = fetch_onchain_price_for_token(token)
        if price_usd is not None and price_usd > 0.0:
            logger.debug("[TRADING][EXECUTION][SWAP][PRICE] On-chain price fetched for %s = %.12f", token, price_usd)
            return price_usd

        logger.debug("[TRADING][EXECUTION][SWAP][PRICE] No valid on-chain price for %s", token)
        return None
    except BlockchainPriceUnavailableError as price_unavailable_error:
        logger.warning("[TRADING][EXECUTION][SWAP][PRICE] %s", price_unavailable_error)
        return None
    except Exception:
        logger.exception("[TRADING][EXECUTION][SWAP][PRICE] On-chain price fetch failed for %s", token)
        return None
