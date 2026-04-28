from __future__ import annotations

import asyncio
from typing import Optional

from src.api.websocket.websocket_hub import notify_trading_state_changed
from src.configuration.config import settings
from src.core.structures.structures import Token
from src.core.trading.execution.trading_risk_manager import TradingRiskManager
from src.core.trading.trading_structures import TradingOrderPayload, TradingLifiRoute
from src.integrations.blockchain.blockchain_live_executor import LiveExecutionService
from src.integrations.blockchain.blockchain_price_service import fetch_onchain_price_for_position
from src.logging.logger import get_application_logger
from src.persistence.dao.trading.trading_position_dao import TradingPositionDao
from src.persistence.dao.trading.trading_trade_dao import TradingTradeDao
from src.persistence.db import get_database_session
from src.persistence.models import ExecutionStatus, TradingTrade, TradingPosition, TradeSide, PositionPhase

logger = get_application_logger(__name__)


class TradingExecutor:
    def __init__(self) -> None:
        self.paper_mode_enabled: bool = settings.PAPER_MODE
        self._risk_manager = TradingRiskManager()

    def _fetch_onchain_price_for_token(self, token: Token) -> Optional[float]:
        try:
            try:
                asyncio.get_running_loop()
                logger.debug("[TRADING][EXECUTOR][PRICE] Event loop detected — skip sync price fetch for %s", token)
                return None
            except RuntimeError:
                pass

            from src.persistence.models import TradingPosition
            synthetic_position = TradingPosition(
                token_symbol=token.symbol,
                blockchain_network=token.chain,
                token_address=token.token_address,
                pair_address=token.pair_address,
                dex_id=token.dex_id,
            )
            price_usd = fetch_onchain_price_for_position(synthetic_position)
            if price_usd is not None and price_usd > 0.0:
                logger.debug("[TRADING][EXECUTOR][PRICE] On-chain price fetched for %s = %.12f", token, price_usd)
                return price_usd

            logger.debug("[TRADING][EXECUTOR][PRICE] No valid on-chain price for %s", token)
            return None
        except Exception as exception:
            logger.exception("[TRADING][EXECUTOR][PRICE] On-chain price fetch failed for %s — %s", token, exception)
            return None

    def _schedule_portfolio_rebroadcast(self) -> None:
        try:
            notify_trading_state_changed()
            logger.debug("[TRADING][EXECUTOR][PORTFOLIO] Notified state change to trigger broadcast")
        except Exception as e:
            logger.exception("[TRADING][EXECUTOR][PORTFOLIO] Skip notification — %s", e)


    @staticmethod
    def _infer_route_network(route: TradingLifiRoute, hint_chain: Optional[str] = None) -> str:
        from src.core.utils.dict_utils import _read_path

        if isinstance(hint_chain, str) and hint_chain.strip().lower() == "solana":
            return "SOLANA"

        from_chain_code = _read_path(route, ("fromChain",))
        to_chain_code = _read_path(route, ("toChain",))
        if isinstance(from_chain_code, str) and from_chain_code.strip().upper() == "SOL":
            return "SOLANA"
        if isinstance(to_chain_code, str) and to_chain_code.strip().upper() == "SOL":
            return "SOLANA"

        serialized_transaction_1 = _read_path(route, ("transaction", "serializedTransaction"))
        serialized_transaction_2 = _read_path(route, ("transactions", 0, "serializedTransaction"))
        if (isinstance(serialized_transaction_1, str) and serialized_transaction_1) or (isinstance(serialized_transaction_2, str) and serialized_transaction_2):
            return "SOLANA"

        return "EVM"

    async def _execute_live_buy(
            self,
            token: Token,
            quantity: float,
            price_usd: float,
            stop_loss_usd: float,
            take_profit_tp1_usd: float,
            take_profit_tp2_usd: float,
            lifi_route: TradingLifiRoute,
            origin_evaluation_id: int,
    ) -> bool:
        execution_service = LiveExecutionService()
        try:
            network = self._infer_route_network(lifi_route, hint_chain=token.chain)
            logger.info("[TRADING][EXECUTOR][LIVE][BUY] Executing route for %s on %s (chain=%s)", token.symbol, network, token.chain)

            if network == "EVM":
                transaction_hash = await execution_service.evm_execute_route(lifi_route)
                logger.info("[TRADING][EXECUTOR][LIVE][BUY][EVM] Broadcast successful for %s — tx=%s", token.symbol, transaction_hash)
            else:
                signature = await execution_service.solana_execute_route(lifi_route)
                logger.info("[TRADING][EXECUTOR][LIVE][BUY][SOL] Broadcast successful for %s — sig=%s", token.symbol, signature)

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
            self._schedule_portfolio_rebroadcast()

    def _run_live_buy_blocking(
            self,
            token: Token,
            quantity: float,
            price_usd: float,
            stop_loss_usd: float,
            take_profit_tp1_usd: float,
            take_profit_tp2_usd: float,
            lifi_route: TradingLifiRoute,
            origin_evaluation_id: int,
    ) -> bool:
        coroutine = self._execute_live_buy(
            token=token,
            quantity=quantity,
            price_usd=price_usd,
            stop_loss_usd=stop_loss_usd,
            take_profit_tp1_usd=take_profit_tp1_usd,
            take_profit_tp2_usd=take_profit_tp2_usd,
            lifi_route=lifi_route,
            origin_evaluation_id=origin_evaluation_id,
        )

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop and running_loop.is_running():
            from concurrent.futures import ThreadPoolExecutor
            logger.debug("[TRADING][EXECUTOR][LIVE][BUY] Blocking execution via worker thread (event loop detected)")
            with ThreadPoolExecutor(max_workers=1) as thread_executor:
                future = thread_executor.submit(asyncio.run, coroutine)
                return future.result()

        logger.debug("[TRADING][EXECUTOR][LIVE][BUY] Blocking execution via asyncio.run (no event loop)")
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

        maximum_price_multiplier = settings.TRADING_MAX_PRICE_DEVIATION_MULTIPLIER
        if payload.execution_price is not None and payload.execution_price > 0.0:
            low_price, high_price = sorted([onchain_price_usd, payload.execution_price])
            if (high_price / low_price) > maximum_price_multiplier:
                logger.warning(
                    "[TRADING][EXECUTOR][BUY] Skip: price mismatch for %s — onchain=%.12f pipeline=%.12f (>×%.1f)",
                    payload.target_token.symbol, onchain_price_usd, payload.execution_price, maximum_price_multiplier,
                )
                return False

        if payload.order_notional <= 0.0:
            logger.debug("[TRADING][EXECUTOR][BUY] Skip: non-positive order_notional_usd=%.6f for %s", payload.order_notional, payload.target_token)
            return False

        quantity = payload.order_notional / price_usd
        logger.debug("[TRADING][EXECUTOR][BUY] Sized order — notional=%.4f price=%.12f quantity=%.12f", payload.order_notional, price_usd, quantity)

        risk_manager = self._risk_manager
        thresholds = risk_manager.compute_thresholds(price_usd, payload.original_candidate, shadow_tp_multiplier=payload.original_candidate.shadow_tp_multiplier)
        stop_loss = thresholds.stop_loss_price
        take_profit_tp1 = thresholds.take_profit_tier_1_price
        take_profit_tp2 = thresholds.take_profit_tier_2_price

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

            self._schedule_portfolio_rebroadcast()
            return True

        if payload.lifi_routing_path is None:
            logger.info("[TRADING][EXECUTOR][LIVE][BUY] Skip: missing LI.FI route for %s (LIVE disabled for this order)", payload.target_token)
            return False

        return self._run_live_buy_blocking(
            token=payload.target_token,
            quantity=quantity,
            price_usd=price_usd,
            stop_loss_usd=stop_loss,
            take_profit_tp1_usd=take_profit_tp1,
            take_profit_tp2_usd=take_profit_tp2,
            lifi_route=payload.lifi_routing_path,
            origin_evaluation_id=payload.origin_evaluation_id,
        )
