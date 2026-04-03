from __future__ import annotations

import asyncio
from typing import List, Optional

from src.api.serializers import serialize_trade
from src.api.websocket.websocket_hub import recompute_metrics_and_broadcast
from src.api.websocket.websocket_manager import websocket_manager
from src.core.structures.structures import Token, WebsocketMessageType
from src.core.trading.execution.trading_autosell import check_thresholds_and_autosell
from src.core.trading.execution.trading_risk_manager import TradingRiskManager
from src.configuration.config import settings
from src.core.trading.trading_structures import TradingOrderPayload, TradingLifiRoute
from src.integrations.blockchain.blockchain_live_executor import LiveExecutionService
from src.integrations.dexscreener.dexscreener_client import fetch_dexscreener_token_information_list_sync
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.logging.logger import get_application_logger
from src.persistence.dao import trades
from src.persistence.db import _session
from src.persistence.models import ExecutionStatus

logger = get_application_logger(__name__)


class TradingExecutor:
    def __init__(self) -> None:
        self.paper_mode_enabled: bool = settings.PAPER_MODE
        self._risk_manager = TradingRiskManager()

    def _fetch_dex_price_for_token(self, token: Token) -> Optional[float]:
        try:
            try:
                asyncio.get_running_loop()
                logger.debug("[TRADING][EXECUTOR][PRICE] Event loop detected — skip sync price fetch for %s", token)
                return None
            except RuntimeError:
                pass

            token_information_list: List[DexscreenerTokenInformation] = fetch_dexscreener_token_information_list_sync([token])
            if not token_information_list:
                logger.debug("[TRADING][EXECUTOR][PRICE] No price returned for %s", token)
                return None

            for token_information in token_information_list:
                if token_information.pair_address == token.pair_address and token_information.price_usd > 0.0:
                    logger.debug("[TRADING][EXECUTOR][PRICE] Price fetched for %s = %.12f", token, token_information.price_usd)
                    return token_information.price_usd

            logger.debug("[TRADING][EXECUTOR][PRICE] No valid price for exact pair — %s", token)
            return None
        except Exception as exception:
            logger.warning("[TRADING][EXECUTOR][PRICE] Dexscreener price fetch failed for %s — %s", token, exception)
            return None

    def _schedule_portfolio_rebroadcast(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            if not loop.is_running() or loop.is_closed():
                logger.debug("[TRADING][EXECUTOR][PORTFOLIO] Skip schedule (loop closing)")
                return
            loop.call_soon_threadsafe(lambda: loop.create_task(recompute_metrics_and_broadcast()))
            logger.debug("[TRADING][EXECUTOR][PORTFOLIO] Scheduled recomputation on running loop")
        except RuntimeError:
            logger.debug("[TRADING][EXECUTOR][PORTFOLIO] Skip schedule (no running loop)")
            return

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

            with _session() as database_session:
                trade_row = trades.buy(
                    db=database_session,
                    token=token,
                    qty=quantity,
                    price=price_usd,
                    stop=stop_loss_usd,
                    tp1=take_profit_tp1_usd,
                    tp2=take_profit_tp2_usd,
                    fee=0.0,
                    status=ExecutionStatus.LIVE,
                )
                websocket_manager.broadcast_json_payload_threadsafe({"type": WebsocketMessageType.TRADE.value, "payload": serialize_trade(trade_row)})
            return True
        except Exception as exception:
            logger.exception("[TRADING][EXECUTOR][LIVE][BUY] Execution failed for %s (%s) — %s", token.symbol, token.token_address, exception)
            return False
        finally:
            try:
                await execution_service.close()
            except Exception as close_exception:
                logger.debug("[TRADING][EXECUTOR][LIVE] Execution service close suppressed — %s", close_exception)
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
    ) -> bool:
        coroutine = self._execute_live_buy(
            token=token,
            quantity=quantity,
            price_usd=price_usd,
            stop_loss_usd=stop_loss_usd,
            take_profit_tp1_usd=take_profit_tp1_usd,
            take_profit_tp2_usd=take_profit_tp2_usd,
            lifi_route=lifi_route,
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

        dex_price_usd = self._fetch_dex_price_for_token(payload.target_token)
        resolved_price: Optional[float] = dex_price_usd if dex_price_usd is not None else payload.execution_price
        if resolved_price is None or resolved_price <= 0.0:
            logger.debug("[TRADING][EXECUTOR][BUY] Skip: no valid price for %s", payload.target_token)
            return False
        price_usd = resolved_price

        maximum_price_multiplier = settings.TRADING_MAX_PRICE_DEVIATION_MULTIPLIER
        if dex_price_usd is not None and payload.execution_price is not None:
            low_price, high_price = sorted([dex_price_usd, payload.execution_price])
            if high_price > 0.0 and (high_price / low_price) > maximum_price_multiplier:
                logger.warning(
                    "[TRADING][EXECUTOR][BUY] Skip: price mismatch for %s — dex=%.12f ext=%.12f (>×%.1f)",
                    payload.target_token, dex_price_usd, payload.execution_price, maximum_price_multiplier,
                )
                return False

        if payload.order_notional <= 0.0:
            logger.debug("[TRADING][EXECUTOR][BUY] Skip: non-positive order_notional_usd=%.6f for %s", payload.order_notional, payload.target_token)
            return False

        quantity = payload.order_notional / price_usd
        logger.debug("[TRADING][EXECUTOR][BUY] Sized order — notional=%.4f price=%.12f quantity=%.12f", payload.order_notional, price_usd, quantity)

        risk_manager = self._risk_manager
        thresholds = risk_manager.compute_thresholds(price_usd, payload.original_candidate)
        stop_loss = thresholds.stop_loss_price
        take_profit_tp1 = thresholds.take_profit_tier_1_price
        take_profit_tp2 = thresholds.take_profit_tier_2_price

        if self.paper_mode_enabled:
            logger.info("[TRADING][EXECUTOR][BUY] PAPER trade — %s @ %.12f qty=%.12f", payload.target_token, price_usd, quantity)
            with _session() as database_session:
                trade_row = trades.buy(
                    db=database_session,
                    token=payload.target_token,
                    qty=quantity,
                    price=price_usd,
                    stop=stop_loss,
                    tp1=take_profit_tp1,
                    tp2=take_profit_tp2,
                    fee=0.0,
                    status=ExecutionStatus.PAPER,
                )
                websocket_manager.broadcast_json_payload_threadsafe({"type": WebsocketMessageType.TRADE.value, "payload": serialize_trade(trade_row)})

                auto_trades = check_thresholds_and_autosell(
                    database_session,
                    dexscreener_token_information=payload.original_candidate.dexscreener_token_information,
                )
                for auto_trade in auto_trades:
                    websocket_manager.broadcast_json_payload_threadsafe({"type": WebsocketMessageType.TRADE.value, "payload": serialize_trade(auto_trade)})

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
        )
