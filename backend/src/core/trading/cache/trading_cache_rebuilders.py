from __future__ import annotations

from typing import Iterable, Optional, cast

from fastapi.encoders import jsonable_encoder

from src.api.http.api_schemas import (
    TradingLiquidityPayload,
    TradingPortfolioPayload,
    TradingPositionPayload,
    TradingShadowMetaPayload,
    TradingTradePayload,
)
from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork, Token
from src.core.trading.cache.trading_cache import trading_state_cache
from src.core.trading.cache.trading_cache_payload_builders import (
    build_trading_positions_payloads,
    build_trading_trades_payloads,
    build_trading_liquidity_payload,
    build_shadow_intelligence_snapshot,
    build_trading_shadow_meta_payload,
    build_trading_portfolio_payload_reusing_cached_chain_balances,
    holdings_and_unrealized_from_positions,
)
from src.core.trading.shadowing.shadow_trading_structures import ShadowIntelligenceSnapshot
from src.core.trading.trading_service import compute_available_cash_usd
from src.integrations.blockchain.blockchain_price_service import fetch_onchain_prices_for_tokens
from src.logging.logger import get_application_logger
from src.persistence.dao.trading.trading_portfolio_snapshot_dao import TradingPortfolioSnapshotDao
from src.persistence.dao.trading.trading_position_dao import TradingPositionDao
from src.persistence.db import get_database_session
from src.persistence.models import TradingPosition

logger = get_application_logger(__name__)


def _paired_open_positions_have_full_usable_prices(
        open_positions: Iterable[TradingPosition],
        prices_lookup: dict[str, float],
) -> bool:
    for position_record in open_positions:
        pair_address_label = position_record.pair_address
        if pair_address_label in (None, ""):
            continue
        if pair_address_label not in prices_lookup or prices_lookup[pair_address_label] <= 0.0:
            return False
    return True


def _tokens_missing_onchain_price(position_tokens: Iterable[Token], prices_lookup: dict[str, float]) -> list[Token]:
    dedupe_pairs_seen: set[str] = set()
    tokens_need_fetch: list[Token] = []
    for token_candidate in position_tokens:
        pair_address_label = token_candidate.pair_address
        if pair_address_label in (None, ""):
            continue
        if pair_address_label in prices_lookup and prices_lookup[pair_address_label] > 0.0:
            continue
        if pair_address_label in dedupe_pairs_seen:
            continue
        dedupe_pairs_seen.add(pair_address_label)
        tokens_need_fetch.append(token_candidate)
    return tokens_need_fetch


def _merge_incremental_onchain_prices_for_open_positions(
        position_tokens_seed: Iterable[Token],
        prices_lookup: dict[str, float],
) -> Optional[dict[str, float]]:
    tokens_missing = _tokens_missing_onchain_price(position_tokens_seed, prices_lookup)
    if not tokens_missing:
        return None
    fetched_incremental_partial = fetch_onchain_prices_for_tokens(tokens_missing)
    if not fetched_incremental_partial:
        return dict(prices_lookup)
    merged_lookup = dict(prices_lookup)
    merged_lookup.update(fetched_incremental_partial)
    trading_state_cache.update_prices_by_pair_address(merged_lookup)
    return merged_lookup


class _PricesRebuilder:
    realm = CacheRealm.PRICES
    ttl_seconds = 30.0

    def rebuild(self) -> dict[str, float]:
        with get_database_session() as database_session:
            position_dao = TradingPositionDao(database_session)
            open_positions = position_dao.retrieve_open_positions()
            tokens = [
                Token(
                    symbol=position.token_symbol,
                    chain=BlockchainNetwork(position.blockchain_network.lower()),
                    token_address=position.token_address,
                    pair_address=position.pair_address,
                    dex_id=position.dex_id,
                )
                for position in open_positions
            ]

        if not tokens:
            return {}

        fetched_prices = fetch_onchain_prices_for_tokens(tokens)
        if not fetched_prices:
            stale_prices = trading_state_cache.get_prices_by_pair_address()
            if stale_prices:
                logger.warning(
                    "[TRADING][CACHE][PRICES] On-chain fetch returned empty; retaining %d cached entries",
                    len(stale_prices),
                )
                return stale_prices

        return fetched_prices

    def apply_to_cache(self, payload: object) -> None:
        trading_state_cache.update_prices_by_pair_address(cast(dict[str, float], payload))

    async def notify_websocket(self, _payload: object) -> None:
        pass


class _PositionsRebuilder:
    realm = CacheRealm.POSITIONS
    ttl_seconds = 30.0

    def rebuild(self) -> list[TradingPositionPayload]:
        prices_candidate = trading_state_cache.get_prices_by_pair_address()
        prices_lookup: dict[str, float] = prices_candidate if prices_candidate is not None else {}
        return build_trading_positions_payloads(prices_lookup)

    def apply_to_cache(self, payload: object) -> None:
        trading_state_cache.update_trading_positions_state(cast(list[TradingPositionPayload], payload))

    async def notify_websocket(self, payload: object) -> None:
        from src.api.websocket.websocket_manager import websocket_manager
        from src.core.structures.structures import WebsocketMessageType

        positions_payload = cast(list[TradingPositionPayload], payload)
        await websocket_manager.broadcast_json_payload({
            "type": WebsocketMessageType.POSITIONS.value,
            "payload": jsonable_encoder(positions_payload),
        })


class _TradesRebuilder:
    realm = CacheRealm.TRADES
    ttl_seconds = 30.0

    def rebuild(self) -> list[TradingTradePayload]:
        return build_trading_trades_payloads()

    def apply_to_cache(self, payload: object) -> None:
        trading_state_cache.update_trading_trades_state(cast(list[TradingTradePayload], payload))

    async def notify_websocket(self, payload: object) -> None:
        from src.api.websocket.websocket_manager import websocket_manager
        from src.core.structures.structures import WebsocketMessageType

        trades_payload = cast(list[TradingTradePayload], payload)
        await websocket_manager.broadcast_json_payload({
            "type": WebsocketMessageType.TRADES.value,
            "payload": jsonable_encoder(trades_payload),
        })


class _AvailableCashRebuilder:
    realm = CacheRealm.AVAILABLE_CASH
    ttl_seconds = 30.0

    def rebuild(self) -> TradingLiquidityPayload:
        try:
            return build_trading_liquidity_payload()
        except ConnectionError:
            previous_liquidity = trading_state_cache.get_trading_liquidity_state()
            if previous_liquidity is not None:
                logger.warning(
                    "[TRADING][CACHE][LIQUIDITY] Live balances unavailable; retaining cached liquidity payload"
                )
                return previous_liquidity
            raise

    def apply_to_cache(self, payload: object) -> None:
        trading_state_cache.update_trading_liquidity_state(cast(TradingLiquidityPayload, payload))

    async def notify_websocket(self, payload: object) -> None:
        from src.api.websocket.websocket_manager import websocket_manager
        from src.core.structures.structures import WebsocketMessageType

        liquidity_payload = cast(TradingLiquidityPayload, payload)
        await websocket_manager.broadcast_json_payload({
            "type": WebsocketMessageType.LIQUIDITY.value,
            "payload": jsonable_encoder(liquidity_payload),
        })


class _PortfolioRebuilder:
    realm = CacheRealm.PORTFOLIO
    ttl_seconds = 30.0

    def rebuild(self) -> Optional[TradingPortfolioPayload]:
        previous_portfolio = trading_state_cache.get_trading_state().portfolio

        base_prices = trading_state_cache.get_prices_by_pair_address()
        prices_lookup: dict[str, float] = dict(base_prices) if base_prices else {}

        with get_database_session() as database_session:
            position_dao = TradingPositionDao(database_session)
            open_positions_for_seed = position_dao.retrieve_open_positions()
            position_tokens_seed = [
                Token(
                    symbol=position.token_symbol,
                    chain=BlockchainNetwork(position.blockchain_network.lower()),
                    token_address=position.token_address,
                    pair_address=position.pair_address,
                    dex_id=position.dex_id,
                )
                for position in open_positions_for_seed
            ]

        merged_prices = _merge_incremental_onchain_prices_for_open_positions(position_tokens_seed, prices_lookup)
        if merged_prices is not None:
            prices_lookup = merged_prices

        with get_database_session() as database_session:
            database_session.expire_on_commit = False
            position_dao = TradingPositionDao(database_session)
            portfolio_dao = TradingPortfolioSnapshotDao(database_session)
            open_positions = position_dao.retrieve_open_positions()

            if not _paired_open_positions_have_full_usable_prices(open_positions, prices_lookup):
                if previous_portfolio is not None:
                    logger.warning(
                        "[TRADING][CACHE][PORTFOLIO] Incomplete on-chain prices for paired open positions; "
                        "skipping equity snapshot and retaining cached portfolio"
                    )
                return previous_portfolio

            cached_available_cash_usd = trading_state_cache.get_available_cash_usd()
            if cached_available_cash_usd is None:
                available_cash_usd = compute_available_cash_usd(
                    database_session=database_session if settings.PAPER_MODE else None,
                )
            else:
                available_cash_usd = cached_available_cash_usd

            holdings_data = holdings_and_unrealized_from_positions(open_positions, prices_lookup)
            total_equity_usd = round(available_cash_usd + holdings_data.total_holdings_value, 2)

            trading_portfolio_snapshot = portfolio_dao.retrieve_initial_snapshot()
            if not trading_portfolio_snapshot:
                portfolio_dao.create_snapshot(
                    equity=available_cash_usd,
                    cash=available_cash_usd,
                    holdings=0.0,
                )
                logger.debug(
                    "[TRADING][CACHE][PORTFOLIO] Equity snapshot initialized — equity=%.2f", available_cash_usd)
            else:
                portfolio_dao.create_snapshot(
                    equity=total_equity_usd,
                    cash=available_cash_usd,
                    holdings=holdings_data.total_holdings_value,
                )
                logger.debug(
                    "[TRADING][CACHE][PORTFOLIO] Equity snapshot created — equity=%.2f cash=%.2f holdings=%.2f",
                    total_equity_usd, available_cash_usd, holdings_data.total_holdings_value,
                )

        return build_trading_portfolio_payload_reusing_cached_chain_balances(prices_lookup)

    def apply_to_cache(self, payload: object) -> None:
        trading_state_cache.update_trading_portfolio_state(cast(Optional[TradingPortfolioPayload], payload))

    async def notify_websocket(self, payload: object) -> None:
        portfolio_payload = cast(Optional[TradingPortfolioPayload], payload)
        if portfolio_payload is None:
            return
        from src.api.websocket.websocket_manager import websocket_manager
        from src.core.structures.structures import WebsocketMessageType

        await websocket_manager.broadcast_json_payload({
            "type": WebsocketMessageType.PORTFOLIO.value,
            "payload": jsonable_encoder(portfolio_payload),
        })


class _ShadowSnapshotRebuilder:
    realm = CacheRealm.SHADOW_INTELLIGENCE_SNAPSHOT
    ttl_seconds = 120.0

    def rebuild(self) -> ShadowIntelligenceSnapshot:
        return build_shadow_intelligence_snapshot()

    def apply_to_cache(self, payload: object) -> None:
        shadow_snapshot = cast(ShadowIntelligenceSnapshot, payload)
        shadow_meta_payload = build_trading_shadow_meta_payload(shadow_snapshot)
        trading_state_cache.update_shadow_intelligence_snapshot(shadow_snapshot)
        trading_state_cache.update_trading_shadow_meta_state(shadow_meta_payload)

    async def notify_websocket(self, payload: object) -> None:
        from src.api.websocket.websocket_manager import websocket_manager
        from src.core.structures.structures import WebsocketMessageType

        shadow_meta_payload = build_trading_shadow_meta_payload(cast(ShadowIntelligenceSnapshot, payload))
        await websocket_manager.broadcast_json_payload({
            "type": WebsocketMessageType.SHADOW_META.value,
            "payload": jsonable_encoder(cast(TradingShadowMetaPayload, shadow_meta_payload)),
        })


def register_trading_rebuilders() -> None:
    cache_invalidator.register(_PricesRebuilder())
    cache_invalidator.register(_PositionsRebuilder())
    cache_invalidator.register(_TradesRebuilder())
    cache_invalidator.register(_AvailableCashRebuilder())
    cache_invalidator.register(_PortfolioRebuilder())
    cache_invalidator.register(_ShadowSnapshotRebuilder())
    logger.info("[TRADING][CACHE][REBUILDERS] 6 trading rebuilders registered")
