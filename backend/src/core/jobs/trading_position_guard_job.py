from __future__ import annotations

import asyncio

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.configuration.config import settings
from src.core.structures.structures import Token, BlockchainNetwork
from src.core.trading.cache.trading_cache import trading_state_cache
from src.core.trading.execution.trading_autosell import check_thresholds_and_autosell_for_token_address
from src.integrations.blockchain.blockchain_price_service import fetch_onchain_prices_for_tokens
from src.logging.logger import get_application_logger
from src.persistence.dao.trading.trading_position_dao import TradingPositionDao
from src.persistence.db import get_database_session

logger = get_application_logger(__name__)


class TradingPositionGuardJob:
    async def run_loop(self) -> None:
        interval = settings.TRADING_POSITION_GUARD_INTERVAL_SECONDS
        logger.info("[TRADING][POSITION_GUARD][JOB] Position guard loop starting (interval=%ss)", interval)
        while True:
            try:
                await self._execute_guard_cycle()
            except Exception:
                logger.exception("[TRADING][POSITION_GUARD][JOB] Position guard cycle error")
            await asyncio.sleep(interval)

    async def _execute_guard_cycle(self) -> None:
        position_tokens = await asyncio.to_thread(self._read_position_tokens)

        try:
            prices_by_pair_address = await asyncio.to_thread(fetch_onchain_prices_for_tokens, position_tokens)
        except Exception:
            logger.exception("[TRADING][POSITION_GUARD][CYCLE] On-chain price fetch failed")
            return

        trading_state_cache.update_prices_by_pair_address(prices_by_pair_address)

        await asyncio.to_thread(self._run_autosell_evaluations_for_tokens, position_tokens, prices_by_pair_address)

        cache_invalidator.mark_dirty(CacheRealm.AVAILABLE_CASH, CacheRealm.POSITIONS, CacheRealm.PORTFOLIO)

    @staticmethod
    def _read_position_tokens() -> list[Token]:
        with get_database_session() as database_session:
            position_dao = TradingPositionDao(database_session)
            open_position_records = position_dao.retrieve_open_positions()
            return [
                Token(
                    symbol=position.token_symbol,
                    chain=BlockchainNetwork(position.blockchain_network.lower()),
                    token_address=position.token_address,
                    pair_address=position.pair_address,
                    dex_id=position.dex_id,
                )
                for position in open_position_records
            ]

    @staticmethod
    def _run_autosell_evaluations_for_tokens(
            position_tokens: list[Token],
            prices_by_pair_address: dict[str, float],
    ) -> None:
        with get_database_session() as database_session:
            database_session.expire_on_commit = False

            autosell_trade_records = []

            for token in position_tokens:
                pair_address_label = token.pair_address
                if pair_address_label is None or pair_address_label == "":
                    continue
                if pair_address_label not in prices_by_pair_address:
                    continue
                price_usd = prices_by_pair_address[pair_address_label]
                if price_usd <= 0.0:
                    continue
                try:
                    newly_created_trades = check_thresholds_and_autosell_for_token_address(
                        database_session, token, price_usd,
                    )
                    if newly_created_trades:
                        autosell_trade_records.extend(newly_created_trades)
                except Exception:
                    logger.exception(
                        "[TRADING][POSITION_GUARD][CYCLE] Autosell evaluation failed for %s",
                        token.symbol,
                    )

            if autosell_trade_records:
                logger.info("[TRADING][POSITION_GUARD][CYCLE] Executed %s automated sell trades", len(autosell_trade_records))
