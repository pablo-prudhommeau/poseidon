from __future__ import annotations

import asyncio
from typing import List, Optional

from src.api.websocket.ws_hub import _recompute_positions_portfolio_analytics_and_broadcast
from src.api.websocket.ws_manager import ws_manager
from src.configuration.config import settings
from src.core.gates.risk_manager import AdaptiveRiskManager
from src.core.onchain.live_executor import LiveExecutionService
from src.core.structures.structures import OrderPayload, LifiRoute, Token
from src.integrations.dexscreener.dexscreener_client import (
    fetch_dexscreener_token_information_list_sync,
)
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.logging.logger import get_logger
from src.persistence.dao import trades
from src.persistence.db import _session
from src.persistence.models import Status
from src.persistence.serializers import serialize_trade
from src.persistence.service import check_thresholds_and_autosell

log = get_logger(__name__)


class Trader:
    """
    Main trading coordinator.

    PAPER mode by default; optionally supports LIVE execution.

    Responsibilities:
        - Pair-aware price discovery (exact pairAddress only)
        - Risk thresholds computation
        - Paper trade persistence and auto-sell handling
        - Live execution via LI.FI route (EVM or Solana)
        - Portfolio recomputation and WebSocket broadcasts
    """

    def __init__(self) -> None:
        self.paper_mode_enabled: bool = settings.PAPER_MODE

    def _fetch_dex_price_for_token(self, token: Token) -> Optional[float]:
        """
        Return a live Dexscreener USD price for a single Token using the synchronous client.

        Safety:
            - If a running event loop is detected, skip the sync call to avoid blocking.
            - Only returns a price when Dexscreener has data for the exact pairAddress.
        """
        try:
            try:
                asyncio.get_running_loop()
                log.debug("[TRADER][PRICE][DEX] Event loop detected — skip sync price fetch for %s", token)
                return None
            except RuntimeError:
                pass  # no loop in this thread → safe to run sync client

            token_information_list: List[DexscreenerTokenInformation] = fetch_dexscreener_token_information_list_sync(
                [token])
            if not token_information_list:
                log.debug("[TRADER][PRICE][DEX] No price returned for %s", token)
                return None

            for toke_information in token_information_list:
                if (
                        toke_information.pair_address == token.pairAddress
                        and toke_information.price_usd > 0.0
                ):
                    log.debug("[TRADER][PRICE][DEX] Price fetched for %s = %.12f", token, toke_information.price_usd)
                    return float(toke_information.price_usd)

            log.debug("[TRADER][PRICE][DEX] No valid price for exact pair — %s", token)
            return None
        except Exception as exc:
            log.warning("[TRADER][PRICE][DEX] Dexscreener price fetch failed for %s — %s", token, exc)
            return None

    def _schedule_portfolio_rebroadcast(self) -> None:
        """
        Schedule a portfolio recomputation if a running asyncio loop is available.
        Uses call_soon_threadsafe to avoid 'Task was destroyed' warnings.
        """
        try:
            loop = asyncio.get_running_loop()
            if not loop.is_running() or loop.is_closed():
                log.debug("[TRADER][PORTFOLIO] Skip schedule (loop closing)")
                return
            loop.call_soon_threadsafe(
                lambda: loop.create_task(_recompute_positions_portfolio_analytics_and_broadcast()))
            log.debug("[TRADER][PORTFOLIO] Scheduled recomputation on running loop")
        except RuntimeError:
            log.debug("[TRADER][PORTFOLIO] Skip schedule (no running loop)")
            return

    @staticmethod
    def _infer_route_network(route: LifiRoute, *, hint_chain: Optional[str] = None) -> str:
        """
        Infer whether a LI.FI route targets EVM or Solana.

        Rules (priority order):
          1) chain hint 'solana' → SOLANA
          2) fromChain/toChain == 'SOL' → SOLANA
          3) serializedTransaction present → SOLANA
          4) else → EVM
        """
        from src.core.utils.dict_utils import _read_path

        if isinstance(hint_chain, str) and hint_chain.strip().lower() == "solana":
            return "SOLANA"

        from_chain_code = _read_path(route, ("fromChain",))
        to_chain_code = _read_path(route, ("toChain",))
        if isinstance(from_chain_code, str) and from_chain_code.strip().upper() == "SOL":
            return "SOLANA"
        if isinstance(to_chain_code, str) and to_chain_code.strip().upper() == "SOL":
            return "SOLANA"

        ser1 = _read_path(route, ("transaction", "serializedTransaction"))
        ser2 = _read_path(route, ("transactions", 0, "serializedTransaction"))
        if (isinstance(ser1, str) and ser1) or (isinstance(ser2, str) and ser2):
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
            lifi_route: LifiRoute,
    ) -> None:
        """
        Execute a LIVE buy via a precomputed LI.FI route and persist the trade.
        """
        execution_service = LiveExecutionService()
        try:
            network = self._infer_route_network(lifi_route, hint_chain=token.chain)
            log.info("[TRADER][LIVE][BUY] Executing route for %s on %s (chain=%s)", token.symbol, network, token.chain)

            if network == "EVM":
                transaction_hash = await execution_service.evm_execute_route(lifi_route)
                log.info("[TRADER][LIVE][BUY][EVM] Broadcast successful for %s — tx=%s", token.symbol, transaction_hash)
            else:
                signature = await execution_service.solana_execute_route(lifi_route)
                log.info("[TRADER][LIVE][BUY][SOL] Broadcast successful for %s — sig=%s", token.symbol, signature)

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
                    status=Status.LIVE,
                )
                ws_manager.broadcast_json_threadsafe({"type": "trade", "payload": serialize_trade(trade_row)})
        except Exception as exc:
            log.exception("[TRADER][LIVE][BUY] Execution failed for %s (%s) — %s", token.symbol, token.tokenAddress,
                          exc)
        finally:
            try:
                await execution_service.close()
            except Exception as close_exc:
                log.debug("[TRADER][LIVE] Execution service close suppressed — %s", close_exc)
            self._schedule_portfolio_rebroadcast()

    def buy(self, payload: OrderPayload) -> None:
        """
        Process a BUY order in PAPER or LIVE mode.

        Pipeline:
            1) Pair-aware price discovery from Dexscreener (exact pair only)
            2) Sanity checks (pair present, price deviation)
            3) Order sizing and risk thresholds
            4) PAPER persistence or LIVE execution via LI.FI route
            5) Portfolio broadcast
        """
        log.debug("[TRADER][BUY] Normalized order — %s", payload.token)

        # Require chain and pair for strict pair pricing
        if not payload.token.chain or not payload.token.pairAddress:
            log.debug("[TRADER][BUY] Skip: missing chain or pairAddress — %s", payload.token)
            return

        # Primary price source = Dexscreener; fallback to payload.price if provided
        dex_price_usd = self._fetch_dex_price_for_token(payload.token)
        price_candidate: Optional[float] = dex_price_usd if dex_price_usd is not None else payload.price
        if price_candidate is None or price_candidate <= 0.0:
            log.debug("[TRADER][BUY] Skip: no valid price for %s", payload.token)
            return
        price_usd = float(price_candidate)

        # Deviation guard if both sources available
        maximum_price_multiplier = float(settings.TRENDING_MAX_PRICE_DEVIATION_MULTIPLIER)
        if dex_price_usd is not None and payload.price is not None:
            low_price, high_price = sorted([dex_price_usd, float(payload.price)])
            if high_price > 0.0 and (high_price / low_price) > maximum_price_multiplier:
                log.warning(
                    "[TRADER][BUY] Skip: price mismatch for %s — dex=%.12f ext=%.12f (>×%.1f)",
                    payload.token,
                    dex_price_usd,
                    float(payload.price),
                    maximum_price_multiplier,
                )
                return

        if payload.order_notional <= 0.0:
            log.debug("[TRADER][BUY] Skip: non-positive order_notional_usd=%.6f for %s", payload.order_notional,
                      payload.token)
            return

        quantity = payload.order_notional / price_usd
        log.debug(
            "[TRADER][BUY] Sized order — notional=%.4f price=%.12f quantity=%.12f",
            payload.order_notional,
            price_usd,
            quantity,
        )

        thresholds = AdaptiveRiskManager().compute_thresholds(price_usd, payload.original_candidate)
        stop_loss = thresholds.stop_loss
        take_profit_tp1 = thresholds.take_profit_tp1
        take_profit_tp2 = thresholds.take_profit_tp2

        # PAPER mode
        if self.paper_mode_enabled:
            log.info("[TRADER][BUY] PAPER trade — %s @ %.12f qty=%.12f", payload.token, price_usd, quantity)
            with _session() as database_session:
                trade_row = trades.buy(
                    db=database_session,
                    token=payload.token,
                    qty=quantity,
                    price=price_usd,
                    stop=stop_loss,
                    tp1=take_profit_tp1,
                    tp2=take_profit_tp2,
                    fee=0.0,
                    status=Status.PAPER,
                )
                ws_manager.broadcast_json_threadsafe({"type": "trade", "payload": serialize_trade(trade_row)})

                auto_trades = check_thresholds_and_autosell(
                    database_session,
                    dexscreener_token_information=payload.original_candidate.dexscreener_token_information,
                )
                for auto_trade in auto_trades:
                    ws_manager.broadcast_json_threadsafe({"type": "trade", "payload": serialize_trade(auto_trade)})

            self._schedule_portfolio_rebroadcast()
            return

        # LIVE mode
        if payload.lifi_route is None:
            log.info("[TRADER][LIVE][BUY] Skip: missing LI.FI route for %s (LIVE disabled for this order).",
                     payload.token)
            return

        try:
            event_loop = asyncio.get_running_loop()
            event_loop.create_task(
                self._execute_live_buy(
                    token=payload.token,
                    quantity=quantity,
                    price_usd=price_usd,
                    stop_loss_usd=stop_loss,
                    take_profit_tp1_usd=take_profit_tp1,
                    take_profit_tp2_usd=take_profit_tp2,
                    lifi_route=payload.lifi_route,
                )
            )
            log.debug("[TRADER][LIVE][BUY] Scheduled LIVE execution on running loop")
        except RuntimeError:
            log.debug("[TRADER][LIVE][BUY] No loop detected — running LIVE execution synchronously")
            asyncio.run(
                self._execute_live_buy(
                    token=payload.token,
                    quantity=quantity,
                    price_usd=price_usd,
                    stop_loss_usd=stop_loss,
                    take_profit_tp1_usd=take_profit_tp1,
                    take_profit_tp2_usd=take_profit_tp2,
                    lifi_route=payload.lifi_route,
                )
            )
