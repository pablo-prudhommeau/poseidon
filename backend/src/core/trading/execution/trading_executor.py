from __future__ import annotations

import asyncio
import threading
from typing import Optional

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.configuration.config import settings
from src.core.structures.structures import Token, BlockchainNetwork
from src.core.trading.trading_structures import TradingOrderPayload, TradingExecutionRoute
from src.integrations.blockchain.blockchain_live_executor import LiveExecutionService
from src.integrations.blockchain.blockchain_price_service import fetch_onchain_price_for_token
from src.logging.logger import get_application_logger
from src.persistence.dao.trading.trading_position_dao import TradingPositionDao
from src.persistence.dao.trading.trading_trade_dao import TradingTradeDao
from src.persistence.db import get_database_session
from src.persistence.models import ExecutionStatus, TradingTrade, TradingPosition, TradeSide, PositionPhase

logger = get_application_logger(__name__)

SWAP_EXECUTION_LOCK = threading.Lock()


class TradingExecutor:
    def __init__(self) -> None:
        self.paper_mode_enabled: bool = settings.PAPER_MODE

    def run_live_sell_blocking(
            self,
            token_symbol: str,
            token_address: str,
            pair_address: str,
            chain: BlockchainNetwork,
            dex_id: str,
            quantity: float,
            execution_price: float,
            execution_route: TradingExecutionRoute,
            origin_evaluation_id: int,
    ) -> Optional[str]:
        coroutine = self._execute_live_sell(
            token_symbol=token_symbol,
            token_address=token_address,
            pair_address=pair_address,
            chain=chain,
            dex_id=dex_id,
            quantity=quantity,
            execution_price=execution_price,
            execution_route=execution_route,
            origin_evaluation_id=origin_evaluation_id,
        )

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        with SWAP_EXECUTION_LOCK:
            logger.debug("[TRADING][EXECUTOR][LIVE][SELL] Acquired global execution lock")
            if running_loop and running_loop.is_running():
                from concurrent.futures import ThreadPoolExecutor
                logger.debug("[TRADING][EXECUTOR][LIVE][SELL] Blocking execution via worker thread (event loop detected)")
                with ThreadPoolExecutor(max_workers=1) as thread_executor:
                    future = thread_executor.submit(asyncio.run, coroutine)
                    return future.result()

            logger.debug("[TRADING][EXECUTOR][LIVE][SELL] Blocking execution via asyncio.run (no event loop)")
            return asyncio.run(coroutine)

    def buy(self, payload: TradingOrderPayload) -> bool:
        logger.debug("[TRADING][EXECUTOR][BUY] Normalized order — %s", payload.target_token)

        if not payload.target_token.chain or not payload.target_token.pair_address:
            logger.debug("[TRADING][EXECUTOR][BUY] Skip: missing chain or pair_address — %s", payload.target_token)
            return False

        onchain_price_usd = self._fetch_onchain_price_for_token(payload.target_token)

        if onchain_price_usd is None or onchain_price_usd <= 0.0:
            logger.warning(
                "[TRADING][EXECUTOR][BUY] Skip: CRITICAL FAILURE — On-chain price absolutely required but missing for %s (DEX: %s). Trade aborted for safety.",
                payload.target_token.symbol, payload.target_token.dex_id,
            )
            return False

        price_usd = onchain_price_usd

        maximum_slippage = settings.TRADING_MAX_SLIPPAGE
        if payload.execution_price is not None and payload.execution_price > 0.0:
            low_price, high_price = sorted([onchain_price_usd, payload.execution_price])
            if (high_price / low_price - 1.0) > maximum_slippage:
                logger.warning(
                    "[TRADING][EXECUTOR][BUY] Skip: slippage too high for %s — onchain=%.12f pipeline=%.12f (>%.1f%%)",
                    payload.target_token.symbol, onchain_price_usd, payload.execution_price, maximum_slippage * 100.0,
                )
                return False

        if payload.order_notional <= 0.0:
            logger.debug("[TRADING][EXECUTOR][BUY] Skip: non-positive order_notional_usd=%.6f for %s", payload.order_notional, payload.target_token)
            return False

        quantity = payload.order_notional / price_usd
        logger.debug("[TRADING][EXECUTOR][BUY] Sized order — notional=%.4f price=%.12f quantity=%.12f", payload.order_notional, price_usd, quantity)

        take_profit_one_fraction = settings.TRADING_TP1_EXIT_FRACTION
        take_profit_two_fraction = settings.TRADING_TP2_EXIT_FRACTION
        stop_loss_fraction = settings.TRADING_STOP_LOSS_FRACTION

        take_profit_tp1 = price_usd * (1.0 + take_profit_one_fraction)
        take_profit_tp2 = price_usd * (1.0 + take_profit_two_fraction)
        stop_loss = price_usd * (1.0 - stop_loss_fraction)

        logger.info(
            "[TRADING][EXECUTOR][THRESHOLDS] entry=%.10f tp1=%.6f (%.1f%%) tp2=%.6f (%.1f%%) stop=%.6f (%.1f%%)",
            price_usd, take_profit_tp1, take_profit_one_fraction * 100, take_profit_tp2, take_profit_two_fraction * 100, stop_loss, stop_loss_fraction * 100,
        )

        if self.paper_mode_enabled:
            logger.info("[TRADING][EXECUTOR][BUY] PAPER trade — %s @ %.12f qty=%.12f", payload.target_token, price_usd, quantity)
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
                )
                position_dao.save(trading_position)
                database_session.commit()

            self._invalidate_trading_cache()
            return True

        if payload.execution_route is None:
            logger.info("[TRADING][EXECUTOR][LIVE][BUY] Skip: missing execution route for %s (LIVE disabled for this order)", payload.target_token)
            return False

        return self._run_live_buy_blocking(
            token=payload.target_token,
            quantity=quantity,
            price_usd=price_usd,
            stop_loss_usd=stop_loss,
            take_profit_tp1_usd=take_profit_tp1,
            take_profit_tp2_usd=take_profit_tp2,
            execution_route=payload.execution_route,
            origin_evaluation_id=payload.origin_evaluation_id,
        )

    def _invalidate_trading_cache(self) -> None:
        cache_invalidator.mark_dirty(
            CacheRealm.POSITIONS,
            CacheRealm.TRADES,
            CacheRealm.PORTFOLIO,
            CacheRealm.AVAILABLE_CASH,
        )
        logger.debug("[TRADING][EXECUTOR] Cache realms marked dirty after trade execution")

    def _fetch_onchain_price_for_token(self, token: Token) -> Optional[float]:
        try:
            price_usd = fetch_onchain_price_for_token(token)
            if price_usd is not None and price_usd > 0.0:
                logger.debug("[TRADING][EXECUTOR][PRICE] On-chain price fetched for %s = %.12f", token, price_usd)
                return price_usd

            logger.debug("[TRADING][EXECUTOR][PRICE] No valid on-chain price for %s", token)
            return None
        except Exception as exception:
            logger.exception("[TRADING][EXECUTOR][PRICE] On-chain price fetch failed for %s — %s", token, exception)
            return None

    @staticmethod
    def _is_solana_chain(chain: BlockchainNetwork) -> bool:
        return chain == BlockchainNetwork.SOLANA

    @staticmethod
    def _infer_route_network(route: TradingExecutionRoute, hint_chain: Optional[BlockchainNetwork] = None) -> BlockchainNetwork:
        if hint_chain is not None:
            return hint_chain

        if route.solana_route is not None:
            return BlockchainNetwork.SOLANA

        raise ValueError("Cannot infer network from route without hint_chain")

    async def _execute_live_buy(
            self,
            token: Token,
            quantity: float,
            price_usd: float,
            stop_loss_usd: float,
            take_profit_tp1_usd: float,
            take_profit_tp2_usd: float,
            execution_route: TradingExecutionRoute,
            origin_evaluation_id: int,
    ) -> bool:
        execution_service = LiveExecutionService()
        try:
            network = self._infer_route_network(execution_route, hint_chain=token.chain)
            logger.info("[TRADING][EXECUTOR][LIVE][BUY] Executing route for %s on %s (chain=%s)", token.symbol, network, token.chain)
            if network != BlockchainNetwork.SOLANA:
                logger.error(
                    "[TRADING][EXECUTOR][LIVE][BUY] Live execution is temporarily restricted to Solana. "
                    "Rejected network=%s for token=%s",
                    network,
                    token.symbol,
                )
                return False

            jit_price_usd = await asyncio.to_thread(self._fetch_onchain_price_for_token, token)
            if jit_price_usd is None or jit_price_usd <= 0.0:
                logger.warning("[TRADING][EXECUTOR][LIVE][BUY] Skip JIT: Unable to fetch price right before execution. Aborting.")
                return False

            maximum_slippage = settings.TRADING_MAX_SLIPPAGE
            low_price, high_price = sorted([jit_price_usd, price_usd])
            if (high_price / low_price - 1.0) > maximum_slippage:
                logger.warning(
                    "[TRADING][EXECUTOR][LIVE][BUY] JIT Slippage guard triggered for %s — intended=%.12f current=%.12f (>%.1f%%). Aborting cleanly.",
                    token.symbol, price_usd, jit_price_usd, maximum_slippage * 100.0,
                )
                return False

            if network == BlockchainNetwork.SOLANA and execution_route.solana_route:
                signature = await execution_service.solana_execute_route(execution_route.solana_route)
                logger.info("[TRADING][EXECUTOR][LIVE][BUY][SOL] Broadcast successful for %s — sig=%s", token.symbol, signature)
            elif execution_route.evm_route:
                transaction_hash = await execution_service.evm_execute_route(execution_route.evm_route, chain=token.chain)
                logger.info("[TRADING][EXECUTOR][LIVE][BUY][EVM] Broadcast successful for %s — tx=%s", token.symbol, transaction_hash)
            else:
                logger.error("[TRADING][EXECUTOR][LIVE][BUY] Missing proper route payload for network %s", network)
                return False

            with get_database_session() as database_session:
                trade_dao = TradingTradeDao(database_session)
                position_dao = TradingPositionDao(database_session)

                trading_trade = TradingTrade(
                    evaluation_id=origin_evaluation_id,
                    trade_side=TradeSide.BUY,
                    token_symbol=token.symbol,
                    blockchain_network=network,
                    execution_price=price_usd,
                    execution_quantity=quantity,
                    transaction_fee=0.0,
                    realized_profit_and_loss=None,
                    execution_status=ExecutionStatus.LIVE,
                    token_address=token.token_address,
                    pair_address=token.pair_address,
                    dex_id=token.dex_id,
                )
                trade_dao.save(trading_trade)

                trading_position = TradingPosition(
                    evaluation_id=origin_evaluation_id,
                    token_symbol=token.symbol,
                    blockchain_network=network,
                    token_address=token.token_address,
                    pair_address=token.pair_address,
                    open_quantity=quantity,
                    current_quantity=quantity,
                    entry_price=price_usd,
                    take_profit_tier_1_price=take_profit_tp1_usd,
                    take_profit_tier_2_price=take_profit_tp2_usd,
                    stop_loss_price=stop_loss_usd,
                    position_phase=PositionPhase.OPEN,
                    dex_id=token.dex_id,
                )
                position_dao.save(trading_position)

                database_session.commit()
            return True
        except Exception as exception:
            logger.exception("[TRADING][EXECUTOR][LIVE][BUY] Execution failed for %s (%s) — %s", token.symbol, token.token_address, exception)
            return False
        finally:
            try:
                await execution_service.close()
            except Exception as close_exception:
                logger.exception("[TRADING][EXECUTOR][LIVE] Execution service close suppressed — %s", close_exception)
            self._invalidate_trading_cache()

    def _run_live_buy_blocking(
            self,
            token: Token,
            quantity: float,
            price_usd: float,
            stop_loss_usd: float,
            take_profit_tp1_usd: float,
            take_profit_tp2_usd: float,
            execution_route: TradingExecutionRoute,
            origin_evaluation_id: int,
    ) -> bool:
        coroutine = self._execute_live_buy(
            token=token,
            quantity=quantity,
            price_usd=price_usd,
            stop_loss_usd=stop_loss_usd,
            take_profit_tp1_usd=take_profit_tp1_usd,
            take_profit_tp2_usd=take_profit_tp2_usd,
            execution_route=execution_route,
            origin_evaluation_id=origin_evaluation_id,
        )

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        with SWAP_EXECUTION_LOCK:
            logger.debug("[TRADING][EXECUTOR][LIVE][BUY] Acquired global execution lock")
            if running_loop and running_loop.is_running():
                from concurrent.futures import ThreadPoolExecutor
                logger.debug("[TRADING][EXECUTOR][LIVE][BUY] Blocking execution via worker thread (event loop detected)")
                with ThreadPoolExecutor(max_workers=1) as thread_executor:
                    future = thread_executor.submit(asyncio.run, coroutine)
                    return future.result()

            logger.debug("[TRADING][EXECUTOR][LIVE][BUY] Blocking execution via asyncio.run (no event loop)")
            return asyncio.run(coroutine)

    async def _execute_live_sell(
            self,
            token_symbol: str,
            token_address: str,
            pair_address: str,
            chain: BlockchainNetwork,
            dex_id: str,
            quantity: float,
            execution_price: float,
            execution_route: TradingExecutionRoute,
            origin_evaluation_id: int,
    ) -> Optional[str]:
        execution_service = LiveExecutionService()
        try:
            network = self._infer_route_network(execution_route, hint_chain=chain)
            logger.info("[TRADING][EXECUTOR][LIVE][SELL] Executing route for %s on %s (chain=%s)", token_symbol, network, chain)
            if network != BlockchainNetwork.SOLANA:
                logger.error(
                    "[TRADING][EXECUTOR][LIVE][SELL] Live execution is temporarily restricted to Solana. "
                    "Rejected network=%s for token=%s",
                    network,
                    token_symbol,
                )
                return None

            from src.core.structures.structures import Token
            temp_token = Token(
                symbol=token_symbol,
                token_address=token_address,
                pair_address=pair_address,
                chain=chain,
                dex_id=dex_id
            )
            jit_price_usd = await asyncio.to_thread(self._fetch_onchain_price_for_token, temp_token)
            if jit_price_usd is None or jit_price_usd <= 0.0:
                logger.warning("[TRADING][EXECUTOR][LIVE][SELL] Skip JIT: Unable to fetch price right before execution. Aborting.")
                return None

            maximum_slippage = settings.TRADING_MAX_SLIPPAGE
            low_price, high_price = sorted([jit_price_usd, execution_price])
            if (high_price / low_price - 1.0) > maximum_slippage:
                logger.warning(
                    "[TRADING][EXECUTOR][LIVE][SELL] JIT Slippage guard triggered for %s — intended=%.12f current=%.12f (>%.1f%%). Aborting cleanly.",
                    token_symbol, execution_price, jit_price_usd, maximum_slippage * 100.0,
                )
                return None

            if network == BlockchainNetwork.SOLANA and execution_route.solana_route:
                signature = await execution_service.solana_execute_route(execution_route.solana_route)
                logger.info("[TRADING][EXECUTOR][LIVE][SELL][SOL] Broadcast successful for %s — sig=%s", token_symbol, signature)
                return signature
            elif execution_route.evm_route:
                transaction_hash = await execution_service.evm_execute_route(execution_route.evm_route, chain=chain)
                logger.info("[TRADING][EXECUTOR][LIVE][SELL][EVM] Broadcast successful for %s — tx=%s", token_symbol, transaction_hash)
                return transaction_hash
            else:
                logger.error("[TRADING][EXECUTOR][LIVE][SELL] Missing proper route payload for network %s", network)
                return None

        except Exception as exception:
            logger.exception("[TRADING][EXECUTOR][LIVE][SELL] Execution failed for %s (%s) — %s", token_symbol, token_address, exception)
            return None
        finally:
            try:
                await execution_service.close()
            except Exception as close_exception:
                logger.exception("[TRADING][EXECUTOR][LIVE] Execution service close suppressed — %s", close_exception)
            self._invalidate_trading_cache()
