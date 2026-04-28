from __future__ import annotations

import asyncio
from typing import Dict, List

from fastapi.encoders import jsonable_encoder

from src.api.http.api_schemas import (
    TradingTradePayload,
    TradingPositionPayload,
    TradingPortfolioPayload,
    DcaStrategyPayload,
    ShadowIntelligenceStatusPayload,
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
    HoldingsAndUnrealizedProfitAndLoss,
    RealizedProfitAndLoss,
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
from src.persistence.dao.trading.shadowing_verdict_dao import TradingShadowingVerdictDao
from src.persistence.dao.trading.trading_portfolio_snapshot_dao import TradingPortfolioSnapshotDao
from src.persistence.dao.trading.trading_position_dao import TradingPositionDao
from src.persistence.dao.trading.trading_trade_dao import TradingTradeDao
from src.persistence.db import get_database_session
from src.persistence.models import TradingPortfolioSnapshot, TradingPosition, TradingTrade

logger = get_application_logger(__name__)

aave_executor_client = AaveExecutor()


class TradingDisplayBroadcastJob:
    async def run_loop(self) -> None:
        interval = settings.TRADING_DISPLAY_BROADCAST_INTERVAL_SECONDS
        logger.info("[TRADING][DISPLAY_BROADCAST][JOB] Display broadcast loop starting (interval=%ss)", interval)
        while True:
            try:
                await broadcast_trading_display_state()
            except Exception as exception:
                logger.exception("[TRADING][DISPLAY_BROADCAST][JOB] Display broadcast cycle error: %s", exception)
            await asyncio.sleep(interval)


def _build_shadow_intelligence_status() -> ShadowIntelligenceStatusPayload:
    with get_database_session() as database_session:
        verdict_dao = TradingShadowingVerdictDao(database_session)
        status_summary = verdict_dao.retrieve_shadow_intelligence_status_summary()

    required_outcomes = settings.TRADING_SHADOWING_MIN_OUTCOMES_FOR_ACTIVATION
    required_hours = settings.TRADING_SHADOWING_MIN_HOURS_FOR_ACTIVATION

    outcome_progress = (status_summary.resolved_outcome_count / required_outcomes * 100.0) if required_outcomes > 0 else 100.0
    hours_progress = (status_summary.elapsed_hours / required_hours * 100.0) if required_hours > 0 else 100.0

    is_activated = status_summary.resolved_outcome_count >= required_outcomes and status_summary.elapsed_hours >= required_hours
    phase = "ACTIVE" if is_activated else "LEARNING"
    if not settings.TRADING_SHADOWING_ENABLED:
        phase = "DISABLED"

    return ShadowIntelligenceStatusPayload(
        is_enabled=settings.TRADING_SHADOWING_ENABLED,
        phase=phase,
        resolved_outcome_count=status_summary.resolved_outcome_count,
        required_outcome_count=required_outcomes,
        elapsed_hours=status_summary.elapsed_hours,
        required_hours=required_hours,
        outcome_progress_percentage=min(100.0, outcome_progress),
        hours_progress_percentage=min(100.0, hours_progress),
    )


def _fetch_display_payloads() -> dict:
    with get_database_session() as database_session:
        portfolio_dao = TradingPortfolioSnapshotDao(database_session)
        position_dao = TradingPositionDao(database_session)
        trade_dao = TradingTradeDao(database_session)

        open_position_records = position_dao.retrieve_open_positions()
        recent_trade_records = trade_dao.retrieve_recent_trades(limit_count=10000)

        try:
            prices_by_pair_address = fetch_onchain_prices_for_positions(open_position_records)
        except Exception as exception:
            logger.exception("[TRADING][DISPLAY_BROADCAST][FETCH] On-chain price fetch failed: %s", exception)
            prices_by_pair_address = {}

        shadow_status = _build_shadow_intelligence_status()

        realized_profit_and_loss_data: RealizedProfitAndLoss = fifo_realized_pnl(recent_trade_records, cutoff_hours=24)
        holdings_data: HoldingsAndUnrealizedProfitAndLoss = holdings_and_unrealized_from_positions(
            open_position_records, prices_by_pair_address
        )

        starting_cash_balance_usd: float = settings.PAPER_STARTING_CASH
        realized_cash_flow = cash_from_trades(starting_cash_balance_usd, recent_trade_records)
        total_equity_usd: float = round(realized_cash_flow.available_cash + holdings_data.total_holdings_value, 2)

        current_portfolio_snapshot = portfolio_dao.create_snapshot(
            equity=total_equity_usd,
            cash=realized_cash_flow.available_cash,
            holdings=holdings_data.total_holdings_value,
        )
        database_session.commit()

        portfolio_payload = serialize_trading_portfolio_snapshot(
            current_portfolio_snapshot,
            equity_curve=portfolio_dao.retrieve_equity_curve(),
            realized_total=realized_profit_and_loss_data.total_realized_profit_and_loss,
            realized_24h=realized_profit_and_loss_data.recent_realized_profit_and_loss,
            unrealized=holdings_data.total_unrealized_profit_and_loss,
            shadow_status=shadow_status,
        )

        positions_payload: List[TradingPositionPayload] = []
        for position_record in open_position_records:
            last_known_price = prices_by_pair_address.get(position_record.pair_address) if position_record.pair_address else None
            if last_known_price is None or last_known_price <= 0.0:
                last_known_price = position_record.entry_price
            positions_payload.append(serialize_trading_position(position_record, last_price=last_known_price))

        trades_payload: List[TradingTradePayload] = [serialize_trading_trade(trade_record) for trade_record in recent_trade_records]

    return {
        "positions": jsonable_encoder(positions_payload),
        "trades": jsonable_encoder(trades_payload),
        "portfolio": jsonable_encoder(portfolio_payload),
    }


async def _compute_dca_strategies_payload() -> List[DcaStrategyPayload]:
    with get_database_session() as database_session:
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


async def broadcast_dca_strategies_state() -> None:
    try:
        dca_strategies_payload = await _compute_dca_strategies_payload()
        websocket_manager.broadcast_json_payload_threadsafe({"type": WebsocketMessageType.DCA_STRATEGIES.value, "payload": jsonable_encoder(dca_strategies_payload)})
        logger.info("[TRADING][DISPLAY_BROADCAST][DCA] DCA strategies state successfully broadcasted")
    except Exception as exception:
        logger.exception("[TRADING][DISPLAY_BROADCAST][DCA] DCA strategies payload computation/broadcast failed: %s", exception)


async def broadcast_trading_display_state() -> None:
    display_payloads = await asyncio.to_thread(_fetch_display_payloads)
    if not display_payloads:
        return

    websocket_manager.broadcast_json_payload_threadsafe({"type": WebsocketMessageType.POSITIONS.value, "payload": display_payloads["positions"]})
    websocket_manager.broadcast_json_payload_threadsafe({"type": WebsocketMessageType.PORTFOLIO.value, "payload": display_payloads["portfolio"]})
    websocket_manager.broadcast_json_payload_threadsafe({"type": WebsocketMessageType.TRADES.value, "payload": display_payloads["trades"]})
