from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.api.http.api_schemas import (
    WebsocketInitializationPayload,
    WebsocketStatusPayload,
    TradingTradePayload,
    TradingPositionPayload,
    TradingPortfolioPayload,
    DcaStrategyPayload,
)
from src.api.serializers import (
    serialize_trading_trade,
    serialize_trading_portfolio_snapshot,
    serialize_dca_strategy,
    serialize_trading_position,
)
from src.api.websocket.websocket_manager import websocket_manager
from src.configuration.config import settings
from src.core.structures.structures import (
    Token,
    HoldingsAndUnrealizedProfitAndLoss,
    RealizedProfitAndLoss,
    EquityCurve,
    CashFromTrades,
    WebsocketInboundMessage,
    WebsocketMessageType,
)
from src.core.utils.pnl_utils import (
    fifo_realized_pnl,
    holdings_and_unrealized_from_positions,
    cash_from_trades,
)
from src.integrations.aave.aave_executor import AaveExecutor
from src.integrations.blockchain.blockchain_price_service import fetch_onchain_prices_for_positions
from src.logging.logger import get_application_logger
from src.persistence.dao.dca.dca_strategy_dao import DcaStrategyDao
from src.persistence.dao.trading.trading_portfolio_snapshot_dao import TradingPortfolioSnapshotDao
from src.persistence.dao.trading.trading_position_dao import TradingPositionDao
from src.persistence.dao.trading.trading_trade_dao import TradingTradeDao
from src.persistence.db import get_database_session
from src.persistence.models import (
    TradingPortfolioSnapshot,
    TradingPosition,
    TradingTrade,
)

router = APIRouter()
logger = get_application_logger(__name__)

aave_executor_client = AaveExecutor()


def _serialize_positions_sync(
        prices_by_pair_address: Dict[str, float],
        position_records: List[TradingPosition],
) -> List[TradingPositionPayload]:
    serialized_positions = []
    for position_record in position_records:
        last_known_price = prices_by_pair_address.get(position_record.pair_address) if position_record.pair_address else None
        if last_known_price is None or last_known_price <= 0.0:
            last_known_price = position_record.entry_price

        serialized_positions.append(serialize_trading_position(position_record, last_price=last_known_price))
    return serialized_positions


def _serialize_portfolio_sync(
        prices_by_pair_address: Dict[str, float],
        portfolio_snapshot: TradingPortfolioSnapshot,
        position_records: List[TradingPosition],
        trade_records: List[TradingTrade],
        equity_curve_data: EquityCurve,
) -> TradingPortfolioPayload:
    realized_profit_and_loss_data: RealizedProfitAndLoss = fifo_realized_pnl(trade_records, cutoff_hours=24)
    holdings_and_unrealized_profit_and_loss_data: HoldingsAndUnrealizedProfitAndLoss = holdings_and_unrealized_from_positions(
        position_records, prices_by_pair_address
    )
    return serialize_trading_portfolio_snapshot(
        portfolio_snapshot,
        equity_curve=equity_curve_data,
        realized_total=realized_profit_and_loss_data.total_realized_profit_and_loss,
        realized_24h=realized_profit_and_loss_data.recent_realized_profit_and_loss,
        unrealized=holdings_and_unrealized_profit_and_loss_data.total_unrealized_profit_and_loss,
    )


def _serialize_trades_sync(trade_records: List[TradingTrade]) -> List[TradingTradePayload]:
    return [serialize_trading_trade(trade_record) for trade_record in trade_records]


async def compute_dca_strategies_payload(database_session: Session) -> List[DcaStrategyPayload]:
    dca_strategy_dao = DcaStrategyDao(database_session)
    registered_strategies = dca_strategy_dao.retrieve_all()
    dca_strategy_payloads: List[DcaStrategyPayload] = []

    for registered_strategy in registered_strategies:
        live_metrics = await aave_executor_client.get_live_metrics(
            chain=registered_strategy.blockchain_network,
            asset_in_address=registered_strategy.source_asset_address,
            asset_out_address=registered_strategy.target_asset_address,
        )
        dca_strategy_payloads.append(serialize_dca_strategy(registered_strategy, live_metrics))

    return dca_strategy_payloads


def _fetch_portfolio_sync_data(websocket_connection_id: int) -> Optional[dict]:
    with get_database_session() as database_session:
        portfolio_dao = TradingPortfolioSnapshotDao(database_session)
        position_dao = TradingPositionDao(database_session)
        trade_dao = TradingTradeDao(database_session)

        current_portfolio_snapshot = portfolio_dao.retrieve_latest_snapshot()
        if not current_portfolio_snapshot:
            logger.warning("[WEBSOCKET][HUB][SYNC][PORTFOLIO] No portfolio snapshot available")
            return None

        open_position_records = position_dao.retrieve_open_positions()
        recent_trade_records = trade_dao.retrieve_recent_trades(limit_count=10000)

        try:
            prices_by_pair_address = fetch_onchain_prices_for_positions(open_position_records)
        except Exception as exception:
            logger.exception("[WEBSOCKET][HUB][SYNC][PORTFOLIO] On-chain price fetch failed: %s", exception)
            prices_by_pair_address = {}

        portfolio_payload = _serialize_portfolio_sync(
            prices_by_pair_address,
            current_portfolio_snapshot,
            open_position_records,
            recent_trade_records,
            portfolio_dao.retrieve_equity_curve()
        )

    return jsonable_encoder(portfolio_payload)


async def sync_portfolio_state_async(websocket_connection: WebSocket) -> None:
    try:
        encoded_payload = await asyncio.to_thread(_fetch_portfolio_sync_data, id(websocket_connection))
        if encoded_payload is None:
            return
        await websocket_connection.send_json({"type": WebsocketMessageType.PORTFOLIO.value, "payload": encoded_payload})
        logger.info("[WEBSOCKET][HUB][SYNC][PORTFOLIO] Portfolio state successfully streamed to client")
    except RuntimeError as exception:
        if "Unexpected ASGI message" in str(exception) or "already completed" in str(exception):
            logger.debug("[WEBSOCKET][HUB][SYNC][PORTFOLIO] Client disconnected during background execution")
        else:
            logger.exception("[WEBSOCKET][HUB][SYNC][PORTFOLIO] Background portfolio sync failed: %s", exception)
    except Exception as exception:
        logger.exception("[WEBSOCKET][HUB][SYNC][PORTFOLIO] Background portfolio sync failed: %s", exception)


def _fetch_positions_sync_data() -> dict:
    with get_database_session() as database_session:
        position_dao = TradingPositionDao(database_session)
        open_position_records = position_dao.retrieve_open_positions()

        try:
            prices_by_pair_address = fetch_onchain_prices_for_positions(open_position_records)
        except Exception as exception:
            logger.exception("[WEBSOCKET][HUB][SYNC][POSITIONS] On-chain price fetch failed: %s", exception)
            prices_by_pair_address = {}

        positions_payload = _serialize_positions_sync(prices_by_pair_address, open_position_records)

    return jsonable_encoder(positions_payload)


async def sync_positions_state_async(websocket_connection: WebSocket) -> None:
    try:
        encoded_payload = await asyncio.to_thread(_fetch_positions_sync_data)
        await websocket_connection.send_json({"type": WebsocketMessageType.POSITIONS.value, "payload": encoded_payload})
        logger.info("[WEBSOCKET][HUB][SYNC][POSITIONS] Positions state successfully streamed to client")
    except RuntimeError as exception:
        if "Unexpected ASGI message" in str(exception) or "already completed" in str(exception):
            logger.debug("[WEBSOCKET][HUB][SYNC][POSITIONS] Client disconnected during background execution")
        else:
            logger.exception("[WEBSOCKET][HUB][SYNC][POSITIONS] Background positions sync failed: %s", exception)
    except Exception as exception:
        logger.exception("[WEBSOCKET][HUB][SYNC][POSITIONS] Background positions sync failed: %s", exception)


def _fetch_trades_sync_data() -> dict:
    with get_database_session() as database_session:
        trade_dao = TradingTradeDao(database_session)
        recent_trade_records = trade_dao.retrieve_recent_trades(limit_count=10000)
        trades_payload = _serialize_trades_sync(recent_trade_records)
    return jsonable_encoder(trades_payload)


async def sync_trades_state_async(websocket_connection: WebSocket) -> None:
    try:
        encoded_payload = await asyncio.to_thread(_fetch_trades_sync_data)
        await websocket_connection.send_json({"type": WebsocketMessageType.TRADES.value, "payload": encoded_payload})
        logger.info("[WEBSOCKET][HUB][SYNC][TRADES] Trades state successfully streamed to client")
    except RuntimeError as exception:
        if "Unexpected ASGI message" in str(exception) or "already completed" in str(exception):
            logger.debug("[WEBSOCKET][HUB][SYNC][TRADES] Client disconnected during background execution")
        else:
            logger.exception("[WEBSOCKET][HUB][SYNC][TRADES] Background trades sync failed: %s", exception)
    except Exception as exception:
        logger.exception("[WEBSOCKET][HUB][SYNC][TRADES] Background trades sync failed: %s", exception)


async def sync_dca_strategies_state_async(websocket_connection: WebSocket) -> None:
    try:
        with get_database_session() as database_session:
            dca_strategies_payload = await compute_dca_strategies_payload(database_session)

        await websocket_connection.send_json({"type": WebsocketMessageType.DCA_STRATEGIES.value, "payload": jsonable_encoder(dca_strategies_payload)})
        logger.info("[WEBSOCKET][HUB][SYNC][DCA] DCA strategies state successfully streamed to client")
    except RuntimeError as exception:
        if "Unexpected ASGI message" in str(exception) or "already completed" in str(exception):
            logger.debug("[WEBSOCKET][HUB][SYNC][DCA] Client disconnected during background execution")
        else:
            logger.exception("[WEBSOCKET][HUB][SYNC][DCA] Background DCA strategies sync failed: %s", exception)
    except Exception as exception:
        logger.exception("[WEBSOCKET][HUB][SYNC][DCA] Background DCA strategies sync failed: %s", exception)


async def send_websocket_handshake(websocket_connection: WebSocket) -> None:
    handshake_payload = WebsocketInitializationPayload(
        status=WebsocketStatusPayload(paper_mode=settings.PAPER_MODE, interval_seconds=settings.TRADING_LOOP_INTERVAL_SECONDS)
    )

    await websocket_connection.send_json({"type": WebsocketMessageType.INITIALIZATION.value, "payload": jsonable_encoder(handshake_payload)})
    logger.info("[WEBSOCKET][HUB][HANDSHAKE] Handshake payload successfully transmitted to client")


def trigger_background_state_sync(websocket_connection: WebSocket) -> None:
    asyncio.create_task(sync_portfolio_state_async(websocket_connection))
    asyncio.create_task(sync_positions_state_async(websocket_connection))
    asyncio.create_task(sync_trades_state_async(websocket_connection))
    asyncio.create_task(sync_dca_strategies_state_async(websocket_connection))


def schedule_full_recompute_broadcast() -> None:
    try:
        event_loop = asyncio.get_running_loop()
    except RuntimeError as exception:
        logger.exception("[WEBSOCKET][HUB][REBROADCAST] No running event loop detected, recompute scheduled for next orchestrator tick: %s", exception)
        return

    if not event_loop.is_running() or event_loop.is_closed():
        logger.debug("[WEBSOCKET][HUB][REBROADCAST] Event loop is either closed or not running, recompute scheduled for next orchestrator tick")
        return

    event_loop.call_soon_threadsafe(
        lambda: event_loop.create_task(recompute_metrics_and_broadcast())
    )


class _TransientPosition:
    def __init__(self, token_symbol: str, blockchain_network: str, token_address: str, pair_address: str, dex_id: str):
        self.token_symbol = token_symbol
        self.blockchain_network = blockchain_network
        self.token_address = token_address
        self.pair_address = pair_address
        self.dex_id = dex_id


def _read_transient_positions() -> List[_TransientPosition]:
    with get_database_session() as database_session:
        position_dao = TradingPositionDao(database_session)
        open_position_records = position_dao.retrieve_open_positions()
        return [
            _TransientPosition(
                token_symbol=p.token_symbol,
                blockchain_network=p.blockchain_network,
                token_address=p.token_address,
                pair_address=p.pair_address,
                dex_id=p.dex_id,
            ) for p in open_position_records
        ]


def _execute_autosell_and_build_broadcast_payloads(
        transient_positions: List[_TransientPosition],
        prices_by_pair_address: Dict[str, float],
) -> dict:
    from src.core.trading.execution.trading_autosell import check_thresholds_and_autosell_for_token_address

    with get_database_session() as database_session:
        database_session.expire_on_commit = False

        position_dao = TradingPositionDao(database_session)
        trade_dao = TradingTradeDao(database_session)
        portfolio_dao = TradingPortfolioSnapshotDao(database_session)

        autosell_trade_records: List[TradingTrade] = []

        for position in transient_positions:
            pair_address = position.pair_address
            if not pair_address:
                continue

            price_usd = prices_by_pair_address.get(pair_address)
            if price_usd is None or price_usd <= 0.0:
                continue

            try:
                position_token = Token(
                    symbol=position.token_symbol,
                    chain=position.blockchain_network,
                    token_address=position.token_address,
                    pair_address=position.pair_address,
                    dex_id=position.dex_id,
                )
                newly_created_trades = check_thresholds_and_autosell_for_token_address(
                    database_session, position_token, price_usd,
                )
                if newly_created_trades:
                    autosell_trade_records.extend(newly_created_trades)
            except Exception as exception:
                logger.warning(
                    "[WEBSOCKET][HUB][AUTOSELL][EVALUATION] Autosell threshold evaluation failed for position %s: %s",
                    position.token_symbol,
                    exception,
                )

        if autosell_trade_records:
            logger.info("[WEBSOCKET][HUB][AUTOSELL][BROADCAST] Broadcasted %s automated sell trades", len(autosell_trade_records))

        open_position_records = position_dao.retrieve_open_positions()
        recent_trade_records = trade_dao.retrieve_recent_trades(limit_count=10000)

        starting_cash_balance_usd: float = settings.PAPER_STARTING_CASH
        realized_cash_flow: CashFromTrades = cash_from_trades(starting_cash_balance_usd, recent_trade_records)
        holdings_and_unrealized_profit_and_loss_data: HoldingsAndUnrealizedProfitAndLoss = holdings_and_unrealized_from_positions(open_position_records, prices_by_pair_address)
        total_equity_usd: float = round(realized_cash_flow.available_cash + holdings_and_unrealized_profit_and_loss_data.total_holdings_value, 2)

        new_portfolio_snapshot = portfolio_dao.create_snapshot(
            equity=total_equity_usd,
            cash=realized_cash_flow.available_cash,
            holdings=holdings_and_unrealized_profit_and_loss_data.total_holdings_value
        )
        database_session.commit()

        positions_payload = _serialize_positions_sync(prices_by_pair_address, open_position_records)
        trades_payload = _serialize_trades_sync(recent_trade_records)
        portfolio_payload = _serialize_portfolio_sync(
            prices_by_pair_address,
            new_portfolio_snapshot,
            open_position_records,
            recent_trade_records,
            portfolio_dao.retrieve_equity_curve()
        )

    return {
        "positions": jsonable_encoder(positions_payload),
        "trades": jsonable_encoder(trades_payload),
        "portfolio": jsonable_encoder(portfolio_payload),
    }


async def recompute_metrics_and_broadcast() -> None:
    transient_positions = await asyncio.to_thread(_read_transient_positions)

    try:
        prices_by_pair_address = await asyncio.to_thread(fetch_onchain_prices_for_positions, transient_positions)
    except Exception as exception:
        logger.exception("[WEBSOCKET][HUB][RECOMPUTE] On-chain price fetch failed: %s", exception)
        return

    broadcast_data = await asyncio.to_thread(
        _execute_autosell_and_build_broadcast_payloads, transient_positions, prices_by_pair_address
    )

    dca_strategies_payload: List[DcaStrategyPayload] = []
    try:
        with get_database_session() as database_session:
            dca_strategies_payload = await compute_dca_strategies_payload(database_session)
    except Exception as exception:
        logger.exception("[WEBSOCKET][HUB][RECOMPUTE][DCA] DCA strategies payload computation failed: %s", exception)

    websocket_manager.broadcast_json_payload_threadsafe({"type": WebsocketMessageType.POSITIONS.value, "payload": broadcast_data["positions"]})
    websocket_manager.broadcast_json_payload_threadsafe({"type": WebsocketMessageType.PORTFOLIO.value, "payload": broadcast_data["portfolio"]})
    websocket_manager.broadcast_json_payload_threadsafe({"type": WebsocketMessageType.TRADES.value, "payload": broadcast_data["trades"]})
    websocket_manager.broadcast_json_payload_threadsafe({"type": WebsocketMessageType.DCA_STRATEGIES.value, "payload": jsonable_encoder(dca_strategies_payload)})

    logger.info("[WEBSOCKET][HUB][RECOMPUTE][BROADCAST] All portfolio metrics and DCA strategy states successfully refreshed and broadcasted")


@router.websocket("/ws")
async def handle_websocket_connection(websocket_connection: WebSocket) -> None:
    await websocket_connection.accept()
    websocket_manager.register_client_connection(websocket_connection)
    logger.info("[WEBSOCKET][HUB][CONNECTION] New client successfully connected")

    try:
        await send_websocket_handshake(websocket_connection)
        trigger_background_state_sync(websocket_connection)

        while True:
            raw_inbound_message = await websocket_connection.receive_json()

            try:
                validated_inbound_message = WebsocketInboundMessage.model_validate(raw_inbound_message)
            except ValidationError as exception:
                logger.exception("[WEBSOCKET][HUB][RECEIVE] Invalid message schema received from client: %s", exception)
                await websocket_connection.send_json({"type": WebsocketMessageType.ERROR.value, "payload": "Invalid message schema"})
                continue

            if validated_inbound_message.type == WebsocketMessageType.PING.value:
                await websocket_connection.send_json({"type": WebsocketMessageType.PONG.value})
                logger.debug("[WEBSOCKET][HUB][RECEIVE] Ping request received, Pong response transmitted")
            elif validated_inbound_message.type == WebsocketMessageType.REFRESH.value:
                trigger_background_state_sync(websocket_connection)
                logger.info("[WEBSOCKET][HUB][REFRESH] Asynchronous state synchronization triggered upon client request")
            else:
                logger.debug("[WEBSOCKET][HUB][RECEIVE] Unknown message type received: %s", validated_inbound_message.type)

    except WebSocketDisconnect:
        logger.info("[WEBSOCKET][HUB][DISCONNECT] Client gracefully disconnected")
    except Exception as exception:
        logger.exception("[WEBSOCKET][HUB][ERROR] Unexpected WebSocket error encountered: %s", exception)
        try:
            await websocket_connection.send_json({"type": WebsocketMessageType.ERROR.value, "payload": str(exception)})
        except Exception:
            pass
    finally:
        websocket_manager.unregister_client_connection(websocket_connection)
        logger.debug("[WEBSOCKET][HUB][CLEANUP] Socket safely removed from active connections manager")
