from __future__ import annotations

import asyncio
from typing import List

from src.configuration.config import settings
from src.core.structures.structures import Token
from src.core.trading.execution.trading_autosell import check_thresholds_and_autosell_for_token_address
from src.core.utils.pnl_utils import cash_from_trades, holdings_and_unrealized_from_positions
from src.integrations.blockchain.blockchain_price_service import fetch_onchain_prices_for_tokens
from src.logging.logger import get_application_logger
from src.persistence.dao.trading.trading_portfolio_snapshot_dao import TradingPortfolioSnapshotDao
from src.persistence.dao.trading.trading_position_dao import TradingPositionDao
from src.persistence.dao.trading.trading_trade_dao import TradingTradeDao
from src.persistence.db import get_database_session
from src.persistence.models import TradingTrade

logger = get_application_logger(__name__)


class TradingPositionGuardJob:
    async def run_loop(self) -> None:
        interval = settings.TRADING_POSITION_GUARD_INTERVAL_SECONDS
        logger.info("[TRADING][POSITION_GUARD][JOB] Position guard loop starting (interval=%ss)", interval)
        while True:
            try:
                await self._execute_guard_cycle()
            except Exception as exception:
                logger.exception("[TRADING][POSITION_GUARD][JOB] Position guard cycle error: %s", exception)
            await asyncio.sleep(interval)

    async def _execute_guard_cycle(self) -> None:
        position_tokens = await asyncio.to_thread(self._read_position_tokens)

        if not position_tokens:
            return

        try:
            prices_by_pair_address = await asyncio.to_thread(fetch_onchain_prices_for_tokens, position_tokens)
        except Exception as exception:
            logger.exception("[TRADING][POSITION_GUARD][CYCLE] On-chain price fetch failed: %s", exception)
            return

        await asyncio.to_thread(self._evaluate_thresholds_and_update_equity, position_tokens, prices_by_pair_address)

    @staticmethod
    def _read_position_tokens() -> List[Token]:
        with get_database_session() as database_session:
            position_dao = TradingPositionDao(database_session)
            open_position_records = position_dao.retrieve_open_positions()
            return [
                Token(
                    symbol=position.token_symbol,
                    chain=position.blockchain_network,
                    token_address=position.token_address,
                    pair_address=position.pair_address,
                    dex_id=position.dex_id,
                ) for position in open_position_records
            ]

    @staticmethod
    def _evaluate_thresholds_and_update_equity(
            position_tokens: List[Token],
            prices_by_pair_address: dict[str, float],
    ) -> None:
        with get_database_session() as database_session:
            database_session.expire_on_commit = False

            autosell_trade_records: List[TradingTrade] = []

            for token in position_tokens:
                pair_address = token.pair_address
                if not pair_address:
                    continue

                price_usd = prices_by_pair_address.get(pair_address)
                if price_usd is None or price_usd <= 0.0:
                    continue

                try:
                    newly_created_trades = check_thresholds_and_autosell_for_token_address(
                        database_session, token, price_usd,
                    )
                    if newly_created_trades:
                        autosell_trade_records.extend(newly_created_trades)
                except Exception as exception:
                    logger.warning(
                        "[TRADING][POSITION_GUARD][CYCLE] Autosell threshold evaluation failed for position %s: %s",
                        token.symbol,
                        exception,
                    )

            if autosell_trade_records:
                logger.info("[TRADING][POSITION_GUARD][CYCLE] Executed %s automated sell trades", len(autosell_trade_records))

            position_dao = TradingPositionDao(database_session)
            trade_dao = TradingTradeDao(database_session)
            portfolio_dao = TradingPortfolioSnapshotDao(database_session)

            open_position_records = position_dao.retrieve_open_positions()
            recent_trade_records = trade_dao.retrieve_recent_trades(limit_count=10000)

            starting_cash_balance_usd: float = settings.PAPER_STARTING_CASH
            realized_cash_flow = cash_from_trades(starting_cash_balance_usd, recent_trade_records)

            missing_prices = any(
                prices_by_pair_address.get(position.pair_address) is None
                for position in open_position_records
                if position.pair_address
            )

            if missing_prices:
                logger.warning("[TRADING][POSITION_GUARD][CYCLE] Skipping equity snapshot — some positions missing on-chain price")
                database_session.commit()
                return

            holdings_data = holdings_and_unrealized_from_positions(open_position_records, prices_by_pair_address)

            total_equity_usd: float = round(realized_cash_flow.available_cash + holdings_data.total_holdings_value, 2)

            portfolio_dao.create_snapshot(
                equity=total_equity_usd,
                cash=realized_cash_flow.available_cash,
                holdings=holdings_data.total_holdings_value,
            )
            database_session.commit()

            logger.debug("[TRADING][POSITION_GUARD][CYCLE] Equity snapshot updated — equity=%.2f", total_equity_usd)
