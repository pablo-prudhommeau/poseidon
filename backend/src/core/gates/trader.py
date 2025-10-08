from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

from src.api.websocket.ws_manager import ws_manager
from src.configuration.config import settings
from src.core.gates.risk_manager import AdaptiveRiskManager
from src.core.onchain.live_executor import LiveExecutionService
from src.core.structures.structures import OrderPayload, LifiRoute
from src.core.utils.pnl_utils import (
    fifo_realized_pnl,
    cash_from_trades,
    holdings_and_unrealized_from_trades,
)
from src.core.utils.price_utils import merge_prices_with_entry
from src.core.utils.dict_utils import _read_path
from src.integrations.dexscreener.dexscreener_client import (
    fetch_prices_by_token_addresses,
    fetch_prices_by_token_addresses_sync,
)
from src.logging.logger import get_logger
from src.persistence.dao import trades
from src.persistence.dao.portfolio_snapshots import snapshot_portfolio, equity_curve
from src.persistence.dao.positions import (
    get_open_positions,
    serialize_positions_with_prices_by_token_address,
)
from src.persistence.dao.trades import get_recent_trades
from src.persistence.db import _session
from src.persistence.models import Status
from src.persistence.serializers import serialize_trade, serialize_portfolio
from src.persistence.service import check_thresholds_and_autosell

log = get_logger(__name__)


class Trader:
    """
    Main trading coordinator.

    Runs in PAPER mode by default and supports opt-in LIVE execution.

    Responsibilities:
        - Price discovery and validation
        - Risk thresholds computation
        - Paper trade persistence and auto-sell handling
        - Live execution via LI.FI route (EVM or Solana)
        - Portfolio recomputation and WebSocket broadcasts
    """

    def __init__(self) -> None:
        self.paper_mode_enabled: bool = settings.PAPER_MODE

    def _fetch_dex_price_for_token_address(self, token_address: str) -> Optional[float]:
        """
        Return a live Dexscreener price for a single `token_address` using the synchronous client.

        Safe from both sync and async contexts:
        - If a running event loop is detected, the sync call is skipped to avoid blocking.
        - Otherwise, it performs a direct synchronous HTTP call.
        """
        if not token_address:
            log.debug("[TRADER][PRICE][DEX] Skip fetch — empty token address")
            return None

        try:
            try:
                asyncio.get_running_loop()
                log.debug(
                    "[TRADER][PRICE][DEX] Event loop detected — skip sync price fetch for %s",
                    token_address,
                )
                return None
            except RuntimeError:
                pass

            result_map = fetch_prices_by_token_addresses_sync([token_address])
            price = result_map[token_address] if token_address in result_map else None
            if price is None or price <= 0.0:
                log.debug("[TRADER][PRICE][DEX] No valid price for %s", token_address)
                return None

            log.debug("[TRADER][PRICE][DEX] Price fetched for %s = %.12f", token_address, price)
            return price
        except Exception as exc:
            log.warning(
                "[TRADER][PRICE][DEX] Dexscreener price fetch failed for %s — %s",
                token_address,
                exc,
            )
            return None

    async def _recompute_portfolio_and_broadcast(self) -> None:
        """
        Recompute portfolio metrics and broadcast updated positions and portfolio.
        """
        log.debug("[TRADER][PORTFOLIO] Recompute and broadcast started")

        with _session() as database_session:
            positions = get_open_positions(database_session)
            recent_trades = get_recent_trades(database_session, limit=10000)

            token_addresses: List[str] = [p.tokenAddress for p in positions if p.tokenAddress]
            live_prices_by_address: Dict[str, float] = await fetch_prices_by_token_addresses(token_addresses)

            display_prices_by_address = merge_prices_with_entry(positions, live_prices_by_address)

            starting_cash_usd = settings.PAPER_STARTING_CASH
            realized_total, realized_24h = fifo_realized_pnl(recent_trades, cutoff_hours=24)
            cash_usd, _, _, _ = cash_from_trades(starting_cash_usd, recent_trades)
            holdings_value_usd, unrealized_pnl_usd = holdings_and_unrealized_from_trades(
                recent_trades, display_prices_by_address
            )
            equity_usd = round(cash_usd + holdings_value_usd, 2)

            snapshot = snapshot_portfolio(
                database_session,
                equity=equity_usd,
                cash=cash_usd,
                holdings=holdings_value_usd,
            )
            positions_payload = serialize_positions_with_prices_by_token_address(
                database_session, display_prices_by_address
            )
            portfolio_payload = serialize_portfolio(
                snapshot,
                equity_curve=equity_curve(database_session),
                realized_total=realized_total,
                realized_24h=realized_24h,
            )
            portfolio_payload["unrealized_pnl"] = unrealized_pnl_usd

        ws_manager.broadcast_json_threadsafe({"type": "positions", "payload": positions_payload})
        ws_manager.broadcast_json_threadsafe({"type": "portfolio", "payload": portfolio_payload})

        log.info(
            "[TRADER][PORTFOLIO] Broadcast complete — equity=%.2f cash=%.2f holdings=%.2f unrealized=%.2f",
            equity_usd,
            cash_usd,
            holdings_value_usd,
            unrealized_pnl_usd,
        )

    def _schedule_portfolio_rebroadcast(self) -> None:
        """
        Schedule a portfolio recomputation si une boucle asyncio vivante est dispo.
        """
        try:
            loop = asyncio.get_running_loop()
            if not loop.is_running() or loop.is_closed():
                log.debug("[TRADER][PORTFOLIO] Skip schedule (loop closing)")
                return
            loop.create_task(self._recompute_portfolio_and_broadcast())
            log.debug("[TRADER][PORTFOLIO] Scheduled recomputation on running loop")
        except RuntimeError:
            log.debug("[TRADER][PORTFOLIO] Skip schedule (no running loop)")
            return

    @staticmethod
    def _infer_route_network(route: LifiRoute, *, hint_chain: Optional[str] = None) -> str:
        """
        Infer whether a LI.FI route targets EVM or Solana.

        Rules (priority order):
          1) If a chain hint is provided and equals 'solana' → SOLANA.
          2) If route exposes chain codes and one equals 'SOL' → SOLANA.
          3) If route contains a serialized Solana transaction → SOLANA.
          4) Otherwise → EVM.

        We DO NOT rely on the mere presence of `transactionRequest` because
        LI.FI may include it alongside Solana payloads.
        """
        # 1) Strong hint from upstream
        if isinstance(hint_chain, str) and hint_chain.strip().lower() == "solana":
            return "SOLANA"

        # 2) Inspect chain codes in the route (do not use dict.get / indexing)
        from_chain_code = _read_path(route, ("fromChain",))
        to_chain_code = _read_path(route, ("toChain",))
        if isinstance(from_chain_code, str) and from_chain_code.strip().upper() == "SOL":
            return "SOLANA"
        if isinstance(to_chain_code, str) and to_chain_code.strip().upper() == "SOL":
            return "SOLANA"

        # 3) Presence of serialized Solana transaction variants
        ser1 = _read_path(route, ("transaction", "serializedTransaction"))
        ser2 = _read_path(route, ("transactions", 0, "serializedTransaction"))
        if (isinstance(ser1, str) and len(ser1) > 0) or (isinstance(ser2, str) and len(ser2) > 0):
            return "SOLANA"

        # 4) Default to EVM
        return "EVM"

    async def _execute_live_buy(
            self,
            symbol: str,
            chain: str,
            address: str,
            quantity: float,
            price_usd: float,
            stop_loss_usd: float,
            take_profit_tp1_usd: float,
            take_profit_tp2_usd: float,
            lifi_route: LifiRoute,
    ) -> None:
        """
        Execute a LIVE buy via a precomputed LI.FI route and persist the trade.

        Notes:
            - The LI.FI route is built upstream; this method only executes it.
            - Always attempts to close the execution service even on failure.
        """
        execution_service = LiveExecutionService()
        try:
            network = self._infer_route_network(lifi_route, hint_chain=chain)
            log.info(
                "[TRADER][LIVE][BUY] Executing route for %s on %s (chain=%s)",
                symbol,
                network,
                chain,
            )

            if network == "EVM":
                transaction_hash = await execution_service.evm_execute_route(lifi_route)
                log.info("[TRADER][LIVE][BUY][EVM] Broadcast successful for %s — tx=%s", symbol, transaction_hash)
            else:
                signature = await execution_service.solana_execute_route(lifi_route)
                log.info("[TRADER][LIVE][BUY][SOL] Broadcast successful for %s — sig=%s", symbol, signature)

            with _session() as database_session:
                trade_row = trades.buy(
                    db=database_session,
                    symbol=symbol,
                    chain=chain,
                    address=address,
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
            log.exception("[TRADER][LIVE][BUY] Execution failed for %s (%s) — %s", symbol, address, exc)
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
            1) Price discovery (DEX price with optional fallback)
            2) Sanity checks (address, price deviation)
            3) Order sizing and risk thresholds
            4) PAPER persistence or LIVE execution via LI.FI route
            5) Portfolio broadcast
        """
        log.debug(
            "[TRADER][BUY] Normalized order — symbol=%s chain=%s address=%s",
            payload.symbol,
            payload.chain,
            payload.address,
        )

        dex_price_usd = self._fetch_dex_price_for_token_address(payload.address)
        price_usd_optional: Optional[float] = dex_price_usd if dex_price_usd is not None else payload.price

        if not payload.address or price_usd_optional is None:
            log.debug(
                "[TRADER][BUY] Skip: invalid address/price — address=%s price=%s symbol=%s",
                payload.address,
                price_usd_optional,
                payload.symbol,
            )
            return

        price_usd = price_usd_optional

        maximum_price_multiplier = float(settings.TRENDING_MAX_PRICE_DEVIATION_MULTIPLIER)
        if dex_price_usd is not None and payload.price is not None:
            low_price, high_price = sorted([dex_price_usd, payload.price])
            if high_price > 0.0 and (high_price / low_price) > maximum_price_multiplier:
                log.warning(
                    "[TRADER][BUY] Skip: price mismatch for %s — dex=%.12f ext=%.12f (>×%.1f)",
                    payload.symbol,
                    dex_price_usd,
                    payload.price,
                    maximum_price_multiplier,
                )
                return

        if payload.order_notional <= 0.0:
            log.debug(
                "[TRADER][BUY] Skip: non-positive order_notional_usd=%.6f for %s",
                payload.order_notional,
                payload.symbol,
            )
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

        # PAPER mode branch
        if self.paper_mode_enabled:
            log.info(
                "[TRADER][BUY] PAPER trade — %s on %s @ %.12f qty=%.12f",
                payload.symbol,
                payload.chain,
                price_usd,
                quantity,
            )
            with _session() as database_session:
                trade_row = trades.buy(
                    db=database_session,
                    symbol=payload.symbol,
                    chain=payload.chain,
                    address=payload.address,
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
                    symbol=payload.symbol,
                    last_price=price_usd,
                )
                for auto_trade in auto_trades:
                    ws_manager.broadcast_json_threadsafe({"type": "trade", "payload": serialize_trade(auto_trade)})

            self._schedule_portfolio_rebroadcast()
            return

        # LIVE mode branch
        if payload.lifi_route is None:
            log.info(
                "[TRADER][LIVE][BUY] Skip: missing LI.FI route for %s on %s (LIVE disabled for this order).",
                payload.symbol,
                payload.chain,
            )
            return

        try:
            event_loop = asyncio.get_running_loop()
            event_loop.create_task(
                self._execute_live_buy(
                    symbol=payload.symbol,
                    chain=payload.chain,
                    address=payload.address,
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
                    symbol=payload.symbol,
                    chain=payload.chain,
                    address=payload.address,
                    quantity=quantity,
                    price_usd=price_usd,
                    stop_loss_usd=stop_loss,
                    take_profit_tp1_usd=take_profit_tp1,
                    take_profit_tp2_usd=take_profit_tp2,
                    lifi_route=payload.lifi_route,
                )
            )
