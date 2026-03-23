from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.http.api_schemas import (
    WsInitPayload,
    WsStatusPayload,
    TradePayload,
    PositionPayload,
    PortfolioPayload,
    AnalyticsPayload,
    DcaStrategyPayload,
)
from src.api.serializers import (
    serialize_trade,
    serialize_portfolio,
    serialize_analytics,
    serialize_dca_strategy,
    serialize_position,
)
from src.api.websocket.ws_manager import ws_manager
from src.configuration.config import settings
from src.core.structures.structures import (
    Token,
    HoldingsAndUnrealizedPnl,
    RealizedPnl,
    EquityCurve,
    CashFromTrades,
    WebsocketInboundMessage,
)
from src.core.utils.pnl_utils import (
    fifo_realized_pnl,
    holdings_and_unrealized_from_positions,
    cash_from_trades,
)
from src.integrations.aave.aave_executor import AaveExecutor
from src.integrations.dexscreener.dexscreener_client import fetch_dexscreener_token_information_list
from src.integrations.dexscreener.dexscreener_consistency_guard import (
    DexConsistencyGuard,
    PairIdentity,
    Observation,
    WindowActivity,
    ConsistencyVerdict,
)
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.logging.logger import get_logger
from src.persistence.dao.analytics import get_recent_analytics
from src.persistence.dao.dca_dao import DcaDao
from src.persistence.dao.portfolio_snapshots import (
    get_portfolio_snapshot,
    equity_curve,
    snapshot_portfolio,
)
from src.persistence.dao.positions import get_open_positions
from src.persistence.dao.trades import get_recent_trades
from src.persistence.db import get_db, _session
from src.persistence.models import PortfolioSnapshot, Position, Trade, Analytics, Phase

router = APIRouter()
log = get_logger(__name__)

_guard = DexConsistencyGuard(
    window_size=settings.DEX_INCONSISTENCY_WINDOW_SIZE,
    alternation_min_cycles=settings.DEX_INCONSISTENCY_ALTERNATION_CYCLES,
    jump_factor=settings.DEX_INCONSISTENCY_JUMP_FACTOR,
    fields_mismatch_min=settings.DEX_INCONSISTENCY_FIELDS_MISMATCH_MIN,
    staleness_horizon=timedelta(seconds=settings.MARKETDATA_MAX_STALE_SECONDS),
)

aave_executor = AaveExecutor()


async def _compute_trades_payload(trades: List[Trade]) -> List[TradePayload]:
    return [serialize_trade(t) for t in trades]


async def _compute_analytics_payload(analytics: List[Analytics]) -> List[AnalyticsPayload]:
    return [serialize_analytics(a) for a in analytics]


async def _compute_positions_payload(
        token_information_list: List[DexscreenerTokenInformation],
        positions: List[Position],
) -> List[PositionPayload]:
    result = []
    for position in positions:
        price = next(
            (t.price_usd for t in token_information_list
             if t.chain_id == position.chain
             and t.base_token.address == position.tokenAddress
             and t.pair_address == position.pairAddress),
            None,
        )
        result.append(serialize_position(position, last_price=price))
    return result


async def _compute_portfolio_payload(
        token_information_list: List[DexscreenerTokenInformation],
        portfolio_snapshot: PortfolioSnapshot,
        positions: List[Position],
        trades: List[Trade],
        equity_curve_data: EquityCurve,
) -> PortfolioPayload:
    realized: RealizedPnl = fifo_realized_pnl(trades, cutoff_hours=24)
    holdings_and_unrealized: HoldingsAndUnrealizedPnl = holdings_and_unrealized_from_positions(
        positions, token_information_list
    )
    return serialize_portfolio(
        portfolio_snapshot,
        equity_curve=equity_curve_data,
        realized_total=realized.total,
        realized_24h=realized.recent,
        unrealized=holdings_and_unrealized.unrealized_pnl,
    )


async def _compute_dca_strategies_payload(db: Session) -> List[DcaStrategyPayload]:
    strategies = DcaDao(db).get_all_strategies()
    dca_payloads: List[DcaStrategyPayload] = []
    for strategy in strategies:
        live_metrics = await aave_executor.get_live_metrics(
            chain=strategy.chain,
            asset_in_address=strategy.asset_in_address,
            asset_out_address=strategy.asset_out_address,
        )
        dca_payloads.append(serialize_dca_strategy(strategy, live_metrics))

    return dca_payloads


async def _send_init(ws: WebSocket, db: Session) -> None:
    snapshot = get_portfolio_snapshot(db)
    positions = get_open_positions(db)

    tokens: List[Token] = [
        Token(symbol=p.symbol, chain=p.chain, tokenAddress=p.tokenAddress, pairAddress=p.pairAddress)
        for p in positions
    ]
    token_information_list: List[DexscreenerTokenInformation] = await fetch_dexscreener_token_information_list(tokens)
    trades = get_recent_trades(db, limit=10000)
    analytics_rows = get_recent_analytics(db, limit=10000)

    payload = WsInitPayload(
        status=WsStatusPayload(paperMode=settings.PAPER_MODE, interval=settings.TREND_INTERVAL_SEC),
        portfolio=await _compute_portfolio_payload(token_information_list, snapshot, positions, trades, equity_curve(db)),
        positions=await _compute_positions_payload(token_information_list, positions),
        trades=await _compute_trades_payload(trades),
        analytics=await _compute_analytics_payload(analytics_rows),
        dca_strategies=await _compute_dca_strategies_payload(db),
    )

    await ws.send_json({"type": "init", "payload": jsonable_encoder(payload)})
    log.info("[WS][INIT] Initial snapshot sent.")


def schedule_full_recompute_broadcast() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log.debug("[WS][REBROADCAST] No running loop; recompute will happen on next orchestrator tick.")
        return

    if not loop.is_running() or loop.is_closed():
        log.debug("[WS][REBROADCAST] Event loop not running; recompute will happen on next orchestrator tick.")
        return

    loop.call_soon_threadsafe(lambda: loop.create_task(_recompute_positions_portfolio_analytics_and_broadcast()))


async def _recompute_positions_portfolio_analytics_and_broadcast() -> None:
    from src.persistence.service import check_thresholds_and_autosell

    with _session() as db:
        positions = get_open_positions(db)
        tokens: List[Token] = [
            Token(symbol=p.symbol, chain=p.chain, tokenAddress=p.tokenAddress, pairAddress=p.pairAddress)
            for p in positions
        ]
        token_information_list: List[DexscreenerTokenInformation] = await fetch_dexscreener_token_information_list(tokens)

        autosell_trades: List[Trade] = []
        staled_keys: set[str] = set()

        for token_information in token_information_list:
            try:
                pair = PairIdentity(
                    chain=token_information.chain_id,
                    token_address=token_information.base_token.address,
                    pair_address=token_information.pair_address,
                )
                observation = Observation(
                    observation_date=token_information.retrieval_date,
                    liquidity_usd=token_information.liquidity.usd,
                    fully_diluted_valuation_usd=token_information.fully_diluted_valuation,
                    market_cap_usd=token_information.market_cap,
                    window_5m=WindowActivity(
                        buys=(token_information.txns.m5.buys if (token_information.txns and token_information.txns.m5) else None),
                        sells=(token_information.txns.m5.sells if (token_information.txns and token_information.txns.m5) else None),
                    ),
                    window_1h=WindowActivity(
                        buys=(token_information.txns.h1.buys if (token_information.txns and token_information.txns.h1) else None),
                        sells=(token_information.txns.h1.sells if (token_information.txns and token_information.txns.h1) else None),
                    ),
                    window_6h=WindowActivity(
                        buys=(token_information.txns.h6.buys if (token_information.txns and token_information.txns.h6) else None),
                        sells=(token_information.txns.h6.sells if (token_information.txns and token_information.txns.h6) else None),
                    ),
                    window_24h=WindowActivity(
                        buys=(token_information.txns.h24.buys if (token_information.txns and token_information.txns.h24) else None),
                        sells=(token_information.txns.h24.sells if (token_information.txns and token_information.txns.h24) else None),
                    ),
                )
                verdict = _guard.observe(pair, observation)
                if verdict == ConsistencyVerdict.REQUIRES_MANUAL_INTERVENTION:
                    staled_keys.add(pair.key())
                    position = (
                        db.execute(
                            select(Position).where(
                                Position.chain == token_information.chain_id,
                                Position.symbol == token_information.base_token.symbol,
                                Position.tokenAddress == token_information.base_token.address,
                                Position.pairAddress == token_information.pair_address,
                                Position.phase.in_([Phase.OPEN, Phase.PARTIAL]),
                            )
                        ).scalars().first()
                    )
                    if position:
                        position.phase = Phase.STALED
                        db.commit()
                        log.warning(
                            "[WS][STALED][TRIGGER] symbol=%s token=%s pair=%s reason=DEX_INCONSISTENT_DATA",
                            position.symbol, position.tokenAddress, position.pairAddress,
                        )
            except Exception as exc:
                log.warning("[WS][DEX][CONSISTENCY] Check failed for %s - %s", token_information.base_token, exc)

        for token_information in token_information_list:
            staled_key = f"{token_information.chain_id}:{token_information.pair_address or token_information.base_token.address}".lower()
            if staled_key in staled_keys:
                log.info("[WS][AUTOSELL][SKIP][STALED] token=%s pair=%s", token_information.base_token.address, token_information.pair_address)
                continue
            try:
                if token_information.price_usd is None or token_information.price_usd <= 0.0:
                    continue
                created = check_thresholds_and_autosell(db, token_information)
                if created:
                    autosell_trades.extend(created)
            except Exception as exc:
                log.warning("[WS][AUTOSELL] Threshold evaluation failed for %s - %s", token_information.base_token, exc)

        for trade in autosell_trades:
            ws_manager.broadcast_json_threadsafe({"type": "trade", "payload": jsonable_encoder(serialize_trade(trade))})
        if autosell_trades:
            log.info("[WS][AUTOSELL] Broadcasted %d autosell trade(s).", len(autosell_trades))

        trades = get_recent_trades(db, limit=10000)
        analytics_rows = get_recent_analytics(db, limit=10000)

        starting_cash_usd: float = settings.PAPER_STARTING_CASH
        cash_flow: CashFromTrades = cash_from_trades(starting_cash_usd, trades)
        holdings_and_unrealized: HoldingsAndUnrealizedPnl = holdings_and_unrealized_from_positions(positions, token_information_list)
        equity_usd: float = round(cash_flow.cash + holdings_and_unrealized.holdings, 2)

        snapshot = snapshot_portfolio(db, equity=equity_usd, cash=cash_flow.cash, holdings=holdings_and_unrealized.holdings)

        positions_payload = await _compute_positions_payload(token_information_list, positions)
        trades_payload = await _compute_trades_payload(trades)
        portfolio_payload = await _compute_portfolio_payload(token_information_list, snapshot, positions, trades, equity_curve(db))
        analytics_payload = await _compute_analytics_payload(analytics_rows)
        dca_strategies_payload = await _compute_dca_strategies_payload(db)

        ws_manager.broadcast_json_threadsafe({"type": "positions", "payload": jsonable_encoder(positions_payload)})
        ws_manager.broadcast_json_threadsafe({"type": "portfolio", "payload": jsonable_encoder(portfolio_payload)})
        ws_manager.broadcast_json_threadsafe({"type": "trades", "payload": jsonable_encoder(trades_payload)})
        ws_manager.broadcast_json_threadsafe({"type": "analytics", "payload": jsonable_encoder(analytics_payload)})
        ws_manager.broadcast_json_threadsafe({"type": "dca_strategies", "payload": jsonable_encoder(dca_strategies_payload)})

        log.info("[WS][BROADCAST] All metrics & DCA state refreshed.")


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, db: Session = Depends(get_db)) -> None:
    await ws.accept()
    ws_manager.connect(ws)
    log.info("[WS][CONNECT] Client connected.")

    try:
        await _send_init(ws, db)
        while True:
            raw_message = await ws.receive_json()
            try:
                inbound = WebsocketInboundMessage.model_validate(raw_message)
            except ValidationError as exc:
                log.debug("[WS][RECV] Invalid message schema: %s", exc)
                await ws.send_json({"type": "error", "payload": "Invalid message schema"})
                continue

            if inbound.type == "ping":
                await ws.send_json({"type": "pong"})
                log.debug("[WS][RECV] Ping → Pong.")
            elif inbound.type == "refresh":
                await _send_init(ws, db)
                log.info("[WS][REFRESH] Full init payload sent on client request.")
            else:
                log.debug("[WS][RECV] Unknown message type: %s", inbound.type)

    except WebSocketDisconnect:
        log.info("[WS][DISCONNECT] Client disconnected.")
    except Exception as exc:
        log.exception("[WS][ERROR] WebSocket error: %s", exc)
        try:
            await ws.send_json({"type": "error", "payload": str(exc)})
        except Exception:
            pass
    finally:
        ws_manager.disconnect(ws)
        log.debug("[WS][CLEANUP] Socket removed from manager.")
