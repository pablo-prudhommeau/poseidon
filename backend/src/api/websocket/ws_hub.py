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
    WebsocketInitializationPayload,
    WebsocketStatusPayload,
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
    HoldingsAndUnrealizedProfitAndLoss,
    RealizedProfitAndLoss,
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
    DexscreenerConsistencyGuard,
    PairIdentity,
    Observation,
    WindowActivity,
    ConsistencyVerdict,
)
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.logging.logger import get_logger
from src.persistence.dao.analytics import retrieve_recent_analytics
from src.persistence.dao.dca_dao import DcaDao
from src.persistence.dao.portfolio_snapshots import (
    get_portfolio_snapshot,
    equity_curve,
    snapshot_portfolio,
)
from src.persistence.dao.positions import retrieve_open_positions
from src.persistence.dao.trades import get_recent_trades
from src.persistence.db import get_database_session, _session
from src.persistence.models import PortfolioSnapshot, Position, Trade, Analytics, PositionPhase

router = APIRouter()
logger = get_logger(__name__)

dex_consistency_guard = DexscreenerConsistencyGuard(
    window_size=settings.DEX_INCONSISTENCY_WINDOW_SIZE,
    alternation_minimum_cycles=settings.DEX_INCONSISTENCY_ALTERNATION_CYCLES,
    jump_factor=settings.DEX_INCONSISTENCY_JUMP_FACTOR,
    fields_mismatch_minimum=settings.DEX_INCONSISTENCY_FIELDS_MISMATCH_MIN,
    staleness_horizon=timedelta(seconds=settings.MARKETDATA_MAX_STALE_SECONDS),
)

aave_executor_client = AaveExecutor()


async def compute_trades_payload(trade_records: List[Trade]) -> List[TradePayload]:
    return [serialize_trade(trade_record) for trade_record in trade_records]


async def compute_analytics_payload(analytics_records: List[Analytics]) -> List[AnalyticsPayload]:
    return [serialize_analytics(analytics_record) for analytics_record in analytics_records]


async def compute_positions_payload(
        token_information_list: List[DexscreenerTokenInformation],
        position_records: List[Position],
) -> List[PositionPayload]:
    serialized_positions = []

    for position_record in position_records:
        last_known_price = next(
            (
                token_information.price_usd for token_information in token_information_list
                if token_information.chain_id == position_record.blockchain_network
                   and token_information.base_token.address == position_record.token_address
                   and token_information.pair_address == position_record.pair_address
            ),
            None,
        )
        serialized_positions.append(serialize_position(position_record, last_price=last_known_price))

    return serialized_positions


async def compute_portfolio_payload(
        token_information_list: List[DexscreenerTokenInformation],
        portfolio_snapshot: PortfolioSnapshot,
        position_records: List[Position],
        trade_records: List[Trade],
        equity_curve_data: EquityCurve,
) -> PortfolioPayload:
    realized_pnl_data: RealizedProfitAndLoss = fifo_realized_pnl(trade_records, cutoff_hours=24)
    holdings_and_unrealized_pnl_data: HoldingsAndUnrealizedProfitAndLoss = holdings_and_unrealized_from_positions(
        position_records, token_information_list
    )

    return serialize_portfolio(
        portfolio_snapshot,
        equity_curve=equity_curve_data,
        realized_total=realized_pnl_data.total_realized_profit_and_loss,
        realized_24h=realized_pnl_data.recent_realized_profit_and_loss,
        unrealized=holdings_and_unrealized_pnl_data.total_unrealized_profit_and_loss,
    )


async def compute_dca_strategies_payload(database_session: Session) -> List[DcaStrategyPayload]:
    dca_data_access_object = DcaDao(database_session)
    registered_strategies = dca_data_access_object.get_all_strategies()
    dca_strategy_payloads: List[DcaStrategyPayload] = []

    for registered_strategy in registered_strategies:
        live_metrics = await aave_executor_client.get_live_metrics(
            chain=registered_strategy.blockchain_network,
            asset_in_address=registered_strategy.source_asset_address,
            asset_out_address=registered_strategy.target_asset_address,
        )
        dca_strategy_payloads.append(serialize_dca_strategy(registered_strategy, live_metrics))

    return dca_strategy_payloads


async def send_initial_websocket_state(websocket_connection: WebSocket, database_session: Session) -> None:
    current_portfolio_snapshot = get_portfolio_snapshot(database_session)
    open_position_records = retrieve_open_positions(database_session)

    tokens_list: List[Token] = [
        Token(
            symbol=position_record.token_symbol,
            chain=position_record.blockchain_network,
            token_address=position_record.token_address,
            pair_address=position_record.pair_address
        )
        for position_record in open_position_records
    ]

    token_information_list: List[DexscreenerTokenInformation] = await fetch_dexscreener_token_information_list(tokens_list)
    recent_trade_records = get_recent_trades(database_session, limit_count=10000)
    recent_analytics_records = retrieve_recent_analytics(database_session, maximum_results_limit=10000)

    initial_state_payload = WebsocketInitializationPayload(
        status=WebsocketStatusPayload(paper_mode=settings.PAPER_MODE, interval_seconds=settings.TREND_INTERVAL_SEC),
        portfolio=await compute_portfolio_payload(
            token_information_list,
            current_portfolio_snapshot,
            open_position_records,
            recent_trade_records,
            equity_curve(database_session)
        ),
        positions=await compute_positions_payload(token_information_list, open_position_records),
        trades=await compute_trades_payload(recent_trade_records),
        analytics=await compute_analytics_payload(recent_analytics_records),
        dca_strategies=await compute_dca_strategies_payload(database_session),
    )

    await websocket_connection.send_json({"type": "init", "payload": jsonable_encoder(initial_state_payload)})
    logger.info("[WEBSOCKET][HUB][INIT] Initial state payload successfully sent to client")


def schedule_full_recompute_broadcast() -> None:
    try:
        event_loop = asyncio.get_running_loop()
    except RuntimeError as exception:
        logger.debug("[WEBSOCKET][HUB][REBROADCAST] No running event loop detected, recompute scheduled for next orchestrator tick", exc_info=exception)
        return

    if not event_loop.is_running() or event_loop.is_closed():
        logger.debug("[WEBSOCKET][HUB][REBROADCAST] Event loop is either closed or not running, recompute scheduled for next orchestrator tick")
        return

    event_loop.call_soon_threadsafe(
        lambda: event_loop.create_task(recompute_metrics_and_broadcast())
    )


async def recompute_metrics_and_broadcast() -> None:
    from src.persistence.service import check_thresholds_and_autosell

    with _session() as database_session:
        open_position_records = retrieve_open_positions(database_session)

        tokens_list: List[Token] = [
            Token(
                symbol=position_record.token_symbol,
                chain=position_record.blockchain_network,
                token_address=position_record.token_address,
                pair_address=position_record.pair_address
            )
            for position_record in open_position_records
        ]

        token_information_list: List[DexscreenerTokenInformation] = await fetch_dexscreener_token_information_list(tokens_list)

        autosell_trade_records: List[Trade] = []
        staled_pair_keys: set[str] = set()

        for token_information in token_information_list:
            try:
                pair_identity = PairIdentity(
                    chain=token_information.chain_id,
                    token_address=token_information.base_token.address,
                    pair_address=token_information.pair_address,
                )

                m5_buys = token_information.txns.m5.buys if token_information.txns and token_information.txns.m5 else None
                m5_sells = token_information.txns.m5.sells if token_information.txns and token_information.txns.m5 else None
                h1_buys = token_information.txns.h1.buys if token_information.txns and token_information.txns.h1 else None
                h1_sells = token_information.txns.h1.sells if token_information.txns and token_information.txns.h1 else None
                h6_buys = token_information.txns.h6.buys if token_information.txns and token_information.txns.h6 else None
                h6_sells = token_information.txns.h6.sells if token_information.txns and token_information.txns.h6 else None
                h24_buys = token_information.txns.h24.buys if token_information.txns and token_information.txns.h24 else None
                h24_sells = token_information.txns.h24.sells if token_information.txns and token_information.txns.h24 else None

                market_observation = Observation(
                    observation_date=token_information.retrieval_date,
                    liquidity_usd=token_information.liquidity.usd,
                    fully_diluted_valuation_usd=token_information.fully_diluted_valuation,
                    market_cap_usd=token_information.market_cap,
                    window_5m=WindowActivity(buys=m5_buys, sells=m5_sells),
                    window_1h=WindowActivity(buys=h1_buys, sells=h1_sells),
                    window_6h=WindowActivity(buys=h6_buys, sells=h6_sells),
                    window_24h=WindowActivity(buys=h24_buys, sells=h24_sells),
                )

                consistency_verdict = dex_consistency_guard.evaluate_consistency(pair_identity, market_observation)

                if consistency_verdict == ConsistencyVerdict.REQUIRES_MANUAL_INTERVENTION:
                    staled_pair_keys.add(pair_identity.key())

                    staled_position = (
                        database_session.execute(
                            select(Position).where(
                                Position.blockchain_network == token_information.chain_id,
                                Position.token_symbol == token_information.base_token.symbol,
                                Position.token_address == token_information.base_token.address,
                                Position.pair_address == token_information.pair_address,
                                Position.position_phase.in_([PositionPhase.OPEN, PositionPhase.PARTIAL]),
                            )
                        ).scalars().first()
                    )

                    if staled_position:
                        staled_position.position_phase = PositionPhase.STALED
                        database_session.commit()
                        logger.warning(
                            "[WEBSOCKET][HUB][CONSISTENCY][TRIGGER] Consistency guard triggered manual intervention. Staling position with symbol %s and token address %s on pair %s",
                            staled_position.token_symbol,
                            staled_position.token_address,
                            staled_position.pair_address,
                        )

            except Exception as exception:
                logger.warning(
                    "[WEBSOCKET][HUB][CONSISTENCY][CHECK] Market data consistency check failed for token %s",
                    token_information.base_token,
                    exc_info=exception
                )

        for token_information in token_information_list:
            staled_pair_key = f"{token_information.chain_id}:{token_information.pair_address or token_information.base_token.address}".lower()

            if staled_pair_key in staled_pair_keys:
                logger.info(
                    "[WEBSOCKET][HUB][AUTOSELL][SKIP] Skipping autosell evaluation for staled token %s and pair %s",
                    token_information.base_token.address,
                    token_information.pair_address
                )
                continue

            try:
                if token_information.price_usd is None or token_information.price_usd <= 0.0:
                    continue

                newly_created_trades = check_thresholds_and_autosell(database_session, token_information)
                if newly_created_trades:
                    autosell_trade_records.extend(newly_created_trades)
            except Exception as exception:
                logger.warning(
                    "[WEBSOCKET][HUB][AUTOSELL][EVALUATION] Autosell threshold evaluation failed for token %s",
                    token_information.base_token,
                    exc_info=exception
                )

        for autosell_trade in autosell_trade_records:
            ws_manager.broadcast_json_payload_threadsafe({
                "type": "trade",
                "payload": jsonable_encoder(serialize_trade(autosell_trade))
            })

        if autosell_trade_records:
            logger.info("[WEBSOCKET][HUB][AUTOSELL][BROADCAST] Broadcasted %s automated sell trades", len(autosell_trade_records))

        recent_trade_records = get_recent_trades(database_session, limit_count=10000)
        recent_analytics_records = retrieve_recent_analytics(database_session, maximum_results_limit=10000)

        starting_cash_balance_usd: float = settings.PAPER_STARTING_CASH
        realized_cash_flow: CashFromTrades = cash_from_trades(starting_cash_balance_usd, recent_trade_records)
        holdings_and_unrealized_pnl_data: HoldingsAndUnrealizedProfitAndLoss = holdings_and_unrealized_from_positions(open_position_records, token_information_list)
        total_equity_usd: float = round(realized_cash_flow.available_cash + holdings_and_unrealized_pnl_data.total_holdings_value, 2)

        new_portfolio_snapshot = snapshot_portfolio(
            database_session,
            equity=total_equity_usd,
            cash=realized_cash_flow.available_cash,
            holdings=holdings_and_unrealized_pnl_data.total_holdings_value
        )

        positions_payload = await compute_positions_payload(token_information_list, open_position_records)
        trades_payload = await compute_trades_payload(recent_trade_records)
        portfolio_payload = await compute_portfolio_payload(
            token_information_list,
            new_portfolio_snapshot,
            open_position_records,
            recent_trade_records,
            equity_curve(database_session)
        )
        analytics_payload = await compute_analytics_payload(recent_analytics_records)
        dca_strategies_payload = await compute_dca_strategies_payload(database_session)

        ws_manager.broadcast_json_payload_threadsafe({"type": "positions", "payload": jsonable_encoder(positions_payload)})
        ws_manager.broadcast_json_payload_threadsafe({"type": "portfolio", "payload": jsonable_encoder(portfolio_payload)})
        ws_manager.broadcast_json_payload_threadsafe({"type": "trades", "payload": jsonable_encoder(trades_payload)})
        ws_manager.broadcast_json_payload_threadsafe({"type": "analytics", "payload": jsonable_encoder(analytics_payload)})
        ws_manager.broadcast_json_payload_threadsafe({"type": "dca_strategies", "payload": jsonable_encoder(dca_strategies_payload)})

        logger.info("[WEBSOCKET][HUB][RECOMPUTE][BROADCAST] All portfolio metrics and DCA strategy states successfully refreshed and broadcasted")


@router.websocket("/ws")
async def handle_websocket_connection(websocket_connection: WebSocket, database_session: Session = Depends(get_database_session)) -> None:
    await websocket_connection.accept()
    ws_manager.register_client_connection(websocket_connection)
    logger.info("[WEBSOCKET][HUB][CONNECTION] New client successfully connected")

    try:
        await send_initial_websocket_state(websocket_connection, database_session)

        while True:
            raw_inbound_message = await websocket_connection.receive_json()

            try:
                validated_inbound_message = WebsocketInboundMessage.model_validate(raw_inbound_message)
            except ValidationError as exception:
                logger.debug("[WEBSOCKET][HUB][RECEIVE] Invalid message schema received from client", exc_info=exception)
                await websocket_connection.send_json({"type": "error", "payload": "Invalid message schema"})
                continue

            if validated_inbound_message.type == "ping":
                await websocket_connection.send_json({"type": "pong"})
                logger.debug("[WEBSOCKET][HUB][RECEIVE] Ping request received, Pong response transmitted")
            elif validated_inbound_message.type == "refresh":
                await send_initial_websocket_state(websocket_connection, database_session)
                logger.info("[WEBSOCKET][HUB][REFRESH] Full initialization payload transmitted upon explicit client request")
            else:
                logger.debug("[WEBSOCKET][HUB][RECEIVE] Unknown message type received: %s", validated_inbound_message.type)

    except WebSocketDisconnect:
        logger.info("[WEBSOCKET][HUB][DISCONNECT] Client gracefully disconnected")
    except Exception as exception:
        logger.exception("[WEBSOCKET][HUB][ERROR] Unexpected WebSocket error encountered", exc_info=exception)
        try:
            await websocket_connection.send_json({"type": "error", "payload": str(exception)})
        except Exception:
            pass
    finally:
        ws_manager.unregister_client_connection(websocket_connection)
        logger.debug("[WEBSOCKET][HUB][CLEANUP] Socket safely removed from active connections manager")
