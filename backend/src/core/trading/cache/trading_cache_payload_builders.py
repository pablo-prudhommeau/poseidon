from __future__ import annotations

from typing import Iterable, Optional

from src.api.http.api_schemas import (
    TradingPortfolioPayload,
    BlockchainCashBalancePayload,
    SolanaTokenAccountRentPayload,
    TradingLiquidityPayload,
    TradingTradePayload,
    TradingPositionPayload,
    TradingPositionPricePayload,
)
from src.api.serializers import (
    serialize_trading_portfolio,
    serialize_trading_trade,
    serialize_trading_position,
)
from src.cache.cache_protocols import CacheRealmRebuildSkipped
from src.configuration.config import MAX_TRADING_ALLOWED_CHAIN_COUNT, settings
from src.core.structures.structures import BlockchainNetwork, Token
from src.core.trading.cache.trading_cache import trading_cache
from src.core.trading.shadowing.trading_shadowing_snapshot_service import compute_shadowing_snapshot
from src.core.trading.shadowing.trading_shadowing_structures import TradingShadowingSnapshot
from src.core.trading.trading_helpers import build_trading_portfolio
from src.core.trading.portfolio.trading_portfolio_structures import SolanaTokenAccountRentBreakdown
from src.integrations.blockchain.blockchain_exceptions import BlockchainRpcUnavailableError, BlockchainPriceUnavailableError
from src.integrations.blockchain.blockchain_free_cash_service import (
    BlockchainCashBalance,
    fetch_stablecoin_balances_for_allowed_chains,
)
from src.core.trading.portfolio.trading_portfolio_valuation_service import build_trading_portfolio_valuation
from src.core.trading.trading_service import (
    compute_available_cash_usd,
    has_any_closing_positions,
)
from src.core.utils.date_utils import get_current_local_datetime
from src.core.utils.math_utils import quantize_2dp, decimal_from_primitive
from src.integrations.blockchain.solana.solana_onchain_wallet_context_service import (
    is_solana_live_portfolio_chain_enabled,
    resolve_required_solana_onchain_wallet_context_for_live_portfolio,
)
from src.integrations.blockchain.blockchain_price_service import fetch_onchain_prices_for_tokens
from src.integrations.blockchain.blockchain_price_structures import OnchainPricesByPairAddress
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_portfolio_snapshot_dao import TradingPortfolioSnapshotDao
from src.persistence.dao.trading_position_dao import TradingPositionDao
from src.persistence.dao.trading_trade_dao import TradingTradeDao
from src.persistence.database_session_manager import get_database_session
from src.persistence.models import TradingPortfolioSnapshot, TradingPosition

logger = get_application_logger(__name__)


def build_trading_prices_payload() -> OnchainPricesByPairAddress:
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
        return OnchainPricesByPairAddress.empty()

    return fetch_onchain_prices_for_tokens(tokens)


def build_trading_portfolio_payload_with_snapshot_creation() -> Optional[TradingPortfolioPayload]:
    base_prices = trading_cache.get_onchain_prices_by_pair_address()
    onchain_prices_lookup: OnchainPricesByPairAddress = (
        base_prices if base_prices is not None else OnchainPricesByPairAddress.empty()
    )

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

    try:
        merged_onchain_prices = _merge_incremental_onchain_prices_for_open_positions(
            position_tokens_seed,
            onchain_prices_lookup,
        )
    except BlockchainPriceUnavailableError:
        return _skip_live_portfolio_rebuild_when_cache_warm(
            "Incomplete on-chain prices for open positions — skipping equity snapshot",
        )
    if merged_onchain_prices is not None:
        onchain_prices_lookup = merged_onchain_prices

    cache_rebuild_skip_reason: Optional[str] = None
    open_positions: Optional[list[TradingPosition]] = None

    with get_database_session() as database_session:
        database_session.expire_on_commit = False
        position_dao = TradingPositionDao(database_session)
        portfolio_dao = TradingPortfolioSnapshotDao(database_session)

        if has_any_closing_positions(database_session):
            cache_rebuild_skip_reason = (
                "Position is currently CLOSING — skipping equity snapshot to avoid transient spikes"
            )
        else:
            database_session.expire_all()
            if has_any_closing_positions(database_session):
                cache_rebuild_skip_reason = (
                    "Position entered CLOSING during snapshot — skipping equity snapshot to avoid transient spikes"
                )
            else:
                open_positions = position_dao.retrieve_open_positions()
                if not _paired_open_positions_have_full_usable_onchain_prices(open_positions, onchain_prices_lookup):
                    cache_rebuild_skip_reason = (
                        "Incomplete on-chain prices for paired open positions — skipping equity snapshot"
                    )
                elif is_solana_live_portfolio_chain_enabled():
                    try:
                        resolve_required_solana_onchain_wallet_context_for_live_portfolio()
                    except BlockchainRpcUnavailableError:
                        cache_rebuild_skip_reason = (
                            "Incomplete Solana on-chain wallet context — skipping equity snapshot"
                        )

        if cache_rebuild_skip_reason is None:
            portfolio_valuation = build_trading_portfolio_valuation(
                database_session=database_session,
                open_positions=open_positions,
                onchain_prices_by_pair_address=onchain_prices_lookup,
            )
            trading_cache.update_trading_available_cash_state(
                available_cash_balance_usd=portfolio_valuation.deployable_cash_usd,
            )
            trading_cache.update_trading_sizing_capital_state(
                sizing_capital_usd=portfolio_valuation.sizing_capital_usd,
            )

            portfolio_dao.create_snapshot(
                total_equity_value=portfolio_valuation.total_equity_value,
                deployable_cash_usd=portfolio_valuation.deployable_cash_usd,
                holdings_mark_to_market_usd=portfolio_valuation.holdings_mark_to_market_usd,
                wallet_auxiliary_assets_usd=portfolio_valuation.wallet_auxiliary_assets_usd,
                sizing_capital_usd=portfolio_valuation.sizing_capital_usd,
            )
            logger.debug(
                "[TRADING][CACHE][PORTFOLIO] Equity snapshot created — equity=%.2f deployable=%.2f holdings=%.2f "
                "wallet_auxiliary=%.2f sizing_capital=%.2f",
                portfolio_valuation.total_equity_value,
                portfolio_valuation.deployable_cash_usd,
                portfolio_valuation.holdings_mark_to_market_usd,
                portfolio_valuation.wallet_auxiliary_assets_usd,
                portfolio_valuation.sizing_capital_usd,
            )

    if cache_rebuild_skip_reason is not None:
        return _skip_live_portfolio_rebuild_when_cache_warm(cache_rebuild_skip_reason)

    return build_trading_portfolio_payload_reusing_cached_chain_balances(onchain_prices_lookup)


def build_trading_trades_payloads() -> list[TradingTradePayload]:
    with get_database_session() as database_session:
        trade_dao = TradingTradeDao(database_session)
        position_dao = TradingPositionDao(database_session)
        recent_trade_records = trade_dao.retrieve_recent_trades(limit_count=10000)
        evaluation_ids = [trade_record.evaluation_id for trade_record in recent_trade_records]
        linked_positions = position_dao.retrieve_by_evaluation_ids(evaluation_ids)
        positions_by_evaluation_id: dict[int, TradingPosition] = {}
        for linked_position in linked_positions:
            existing = positions_by_evaluation_id.get(linked_position.evaluation_id)
            if existing is None or linked_position.id > existing.id:
                positions_by_evaluation_id[linked_position.evaluation_id] = linked_position

        payloads: list[TradingTradePayload] = []
        for trade_record in recent_trade_records:
            linked_position = positions_by_evaluation_id.get(trade_record.evaluation_id)
            if linked_position is None:
                raise ValueError(
                    f"Missing linked trading position for trade_id={trade_record.id} evaluation_id={trade_record.evaluation_id}"
                )
            payloads.append(serialize_trading_trade(trade_record, linked_position.id))
        return payloads


def build_trading_liquidity_payload() -> TradingLiquidityPayload:
    updated_at = get_current_local_datetime().isoformat()
    if settings.PAPER_MODE:
        available_cash_usd = compute_available_cash_usd()
        return TradingLiquidityPayload(
            mode="PAPER",
            available_cash_balance=available_cash_usd,
            stablecoin_currency_symbol="$",
            maximum_chain_count=MAX_TRADING_ALLOWED_CHAIN_COUNT,
            blockchain_balances=[],
            updated_at=updated_at,
        )

    blockchain_balances_raw = fetch_stablecoin_balances_for_allowed_chains()
    live_deployable_cash_usd = sum(balance.balance_raw for balance in blockchain_balances_raw)

    position_is_closing = False
    with get_database_session() as database_session:
        position_is_closing = has_any_closing_positions(database_session)

    if position_is_closing:
        _defer_live_liquidity_rebuild_during_closing()

    solana_rent_breakdown = _resolve_solana_rent_breakdown_for_live_liquidity_payload()
    blockchain_balance_payloads = [
        _convert_blockchain_cash_balance_to_payload(balance, solana_rent_breakdown)
        for balance in blockchain_balances_raw
    ]
    available_cash_usd = sum(balance.balance_raw for balance in blockchain_balance_payloads)
    stablecoin_currency_symbol = "$"
    if blockchain_balance_payloads:
        stablecoin_currency_symbol = blockchain_balance_payloads[0].stablecoin_currency_symbol

    return TradingLiquidityPayload(
        mode="LIVE",
        available_cash_balance=available_cash_usd,
        stablecoin_currency_symbol=stablecoin_currency_symbol,
        maximum_chain_count=MAX_TRADING_ALLOWED_CHAIN_COUNT,
        blockchain_balances=blockchain_balance_payloads,
        updated_at=updated_at,
    )


def build_trading_positions_payloads(
        onchain_prices_by_pair_address: OnchainPricesByPairAddress,
) -> list[TradingPositionPayload]:
    with get_database_session() as database_session:
        position_dao = TradingPositionDao(database_session)
        open_position_records = position_dao.retrieve_open_positions()
        payloads: list[TradingPositionPayload] = []
        for position_record in open_position_records:
            last_price_candidate = _resolve_optional_last_price_for_position(
                position_record,
                onchain_prices_by_pair_address,
            )
            payloads.append(serialize_trading_position(position_record, last_price=last_price_candidate))
        return payloads


def build_trading_position_prices_payloads(
        onchain_prices_by_pair_address: OnchainPricesByPairAddress,
) -> list[TradingPositionPricePayload]:
    with get_database_session() as database_session:
        position_dao = TradingPositionDao(database_session)
        open_position_records = position_dao.retrieve_open_positions()
        payloads: list[TradingPositionPricePayload] = []
        for position_record in open_position_records:
            pair_address_value = position_record.pair_address
            last_price_candidate = _resolve_optional_last_price_for_position(
                position_record,
                onchain_prices_by_pair_address,
            )

            delta_percent_candidate: Optional[float] = None
            entry_price_value = position_record.entry_price if position_record.entry_price is not None else 0.0
            if (
                    last_price_candidate is not None
                    and entry_price_value is not None
                    and entry_price_value != 0.0
            ):
                delta_percent_candidate = ((last_price_candidate - entry_price_value) / abs(entry_price_value)) * 100.0

            payloads.append(TradingPositionPricePayload(
                position_id=position_record.id,
                pair_address=pair_address_value or "",
                last_price=last_price_candidate,
                delta_percent=delta_percent_candidate,
            ))
        return payloads


def build_trading_portfolio_payload(
        trades: list[TradingTradePayload],
        trading_portfolio_snapshot: TradingPortfolioSnapshot,
        onchain_prices_by_pair_address: OnchainPricesByPairAddress,
        *,
        blockchain_balances_override_payload: Optional[list[BlockchainCashBalancePayload]] = None,
) -> TradingPortfolioPayload:
    with get_database_session() as database_session:
        portfolio_dao = TradingPortfolioSnapshotDao(database_session)
        position_dao = TradingPositionDao(database_session)
        portfolio_snapshot_bound_to_session = database_session.merge(trading_portfolio_snapshot)
        open_positions = position_dao.retrieve_open_positions()
        equity_curve = portfolio_dao.retrieve_equity_curve_points()

        portfolio = build_trading_portfolio(
            portfolio_snapshot=portfolio_snapshot_bound_to_session,
            trades=trades,
            open_positions=open_positions,
            onchain_prices_by_pair_address=onchain_prices_by_pair_address,
            equity_curve=equity_curve,
        )

        if blockchain_balances_override_payload is None:
            if settings.PAPER_MODE:
                blockchain_balance_payloads: list[BlockchainCashBalancePayload] = []
            else:
                blockchain_balances_raw = fetch_stablecoin_balances_for_allowed_chains()
                solana_rent_breakdown = _resolve_solana_rent_breakdown_for_live_liquidity_payload()
                blockchain_balance_payloads = [
                    _convert_blockchain_cash_balance_to_payload(balance, solana_rent_breakdown)
                    for balance in blockchain_balances_raw
                ]
        else:
            blockchain_balance_payloads = list(blockchain_balances_override_payload)

        return serialize_trading_portfolio(portfolio, blockchain_balance_payloads)


def build_trading_portfolio_payload_reusing_cached_chain_balances(
        onchain_prices_lookup: OnchainPricesByPairAddress,
) -> Optional[TradingPortfolioPayload]:
    trading_cached_state = trading_cache.get_trading_state()
    trades_payload_list = trading_cached_state.trades if trading_cached_state.trades is not None else []
    prior_portfolio = trading_cached_state.portfolio
    if prior_portfolio is None:
        override_balances: list[BlockchainCashBalancePayload] = []
    else:
        override_balances = list(prior_portfolio.blockchain_balances)

    cache_rebuild_skip_reason: Optional[str] = None
    snapshot_candidate: Optional[TradingPortfolioSnapshot] = None

    with get_database_session() as database_session:
        position_dao = TradingPositionDao(database_session)
        portfolio_dao = TradingPortfolioSnapshotDao(database_session)
        open_positions_list = position_dao.retrieve_open_positions()
        snapshot_candidate = portfolio_dao.retrieve_latest_snapshot()
        if snapshot_candidate is None:
            return None
        if not _paired_open_positions_have_full_usable_onchain_prices(
                open_positions_list,
                onchain_prices_lookup,
        ):
            cache_rebuild_skip_reason = (
                "Incomplete on-chain prices for paired open positions — retaining cached portfolio"
            )

    if cache_rebuild_skip_reason is not None:
        return _skip_live_portfolio_rebuild_when_cache_warm(cache_rebuild_skip_reason)

    try:
        return build_trading_portfolio_payload(
            trades_payload_list,
            snapshot_candidate,
            onchain_prices_lookup,
            blockchain_balances_override_payload=override_balances,
        )
    except BlockchainRpcUnavailableError:
        return _skip_live_portfolio_rebuild_when_cache_warm(
            "On-chain balances unavailable — retaining cached portfolio snapshot",
        )


def build_shadowing_snapshot() -> TradingShadowingSnapshot:
    return compute_shadowing_snapshot()


def _resolve_live_deployable_cash_usd_from_on_chain_balances() -> float:
    blockchain_balances_raw = fetch_stablecoin_balances_for_allowed_chains()
    return sum(balance.balance_raw for balance in blockchain_balances_raw)


def _skip_live_portfolio_rebuild_when_cache_warm(reason: str) -> Optional[TradingPortfolioPayload]:
    cached_portfolio = trading_cache.get_trading_state().portfolio
    if cached_portfolio is not None:
        logger.debug("[TRADING][CACHE][PORTFOLIO][LIVE_GUARD] %s", reason)
        raise CacheRealmRebuildSkipped(reason)
    logger.warning("[TRADING][CACHE][PORTFOLIO][LIVE_GUARD] %s — no cached portfolio to retain", reason)
    return None


def _defer_live_liquidity_rebuild_during_closing() -> None:
    cached_liquidity = trading_cache.get_trading_liquidity_state()
    if cached_liquidity is not None:
        logger.debug(
            "[TRADING][CACHE][LIQUIDITY][LIVE_GUARD] Position is currently CLOSING — "
            "retaining cached liquidity payload to avoid transient spikes",
        )
        raise CacheRealmRebuildSkipped(
            "Position is currently CLOSING — retaining cached liquidity payload to avoid transient spikes",
        )
    logger.debug(
        "[TRADING][CACHE][LIQUIDITY][LIVE_GUARD] Position is currently CLOSING — "
        "deferring liquidity rebuild until closing settles",
    )
    raise CacheRealmRebuildSkipped(
        "Position is currently CLOSING — deferring liquidity rebuild until closing settles",
    )


def _resolve_solana_rent_breakdown_for_live_liquidity_payload() -> Optional[SolanaTokenAccountRentBreakdown]:
    if not is_solana_live_portfolio_chain_enabled():
        return None
    wallet_context = resolve_required_solana_onchain_wallet_context_for_live_portfolio()
    return wallet_context.rent_breakdown


def _build_solana_rent_payload(
        solana_rent_breakdown: SolanaTokenAccountRentBreakdown,
) -> SolanaTokenAccountRentPayload:
    return SolanaTokenAccountRentPayload(
        active_usd=solana_rent_breakdown.active_usd,
        closable_usd=solana_rent_breakdown.closable_usd,
        pending_reclaim_usd=solana_rent_breakdown.pending_reclaim_usd,
        locked_sol=solana_rent_breakdown.locked_sol,
        active_account_count=solana_rent_breakdown.active_account_count,
        closable_account_count=solana_rent_breakdown.closable_account_count,
        pending_reclaim_account_count=solana_rent_breakdown.pending_reclaim_account_count,
    )


def _convert_blockchain_cash_balance_to_payload(
        balance: BlockchainCashBalance,
        solana_rent_breakdown: Optional[SolanaTokenAccountRentBreakdown],
) -> BlockchainCashBalancePayload:
    solana_rent_payload: Optional[SolanaTokenAccountRentPayload] = None
    if balance.blockchain_network == BlockchainNetwork.SOLANA:
        if solana_rent_breakdown is None:
            raise ValueError(
                f"Solana rent breakdown required for Solana balance payload — network={balance.blockchain_network.value}",
            )
        solana_rent_payload = _build_solana_rent_payload(solana_rent_breakdown)
    return BlockchainCashBalancePayload(
        blockchain_network=balance.blockchain_network,
        stablecoin_symbol=balance.stablecoin_symbol,
        stablecoin_address=balance.stablecoin_address,
        stablecoin_currency_symbol=balance.stablecoin_currency_symbol,
        balance_raw=balance.balance_raw,
        native_token_symbol=balance.native_token_symbol,
        native_token_balance_raw=balance.native_token_balance_raw,
        native_token_balance_usd=balance.native_token_balance_usd,
        solana_token_account_rent=solana_rent_payload,
    )


def _resolve_optional_last_price_for_position(
        position_record: TradingPosition,
        onchain_prices_by_pair_address: OnchainPricesByPairAddress,
) -> Optional[float]:
    pair_address_value = position_record.pair_address
    if pair_address_value in (None, ""):
        return None
    return onchain_prices_by_pair_address.try_resolve_price_usd_for_pair_address(pair_address_value)


def _paired_open_positions_have_full_usable_onchain_prices(
        open_positions: Iterable[TradingPosition],
        onchain_prices_by_pair_address: OnchainPricesByPairAddress,
) -> bool:
    for position_record in open_positions:
        pair_address_label = position_record.pair_address
        if pair_address_label in (None, ""):
            continue
        blockchain_network = BlockchainNetwork(position_record.blockchain_network.lower())
        try:
            onchain_prices_by_pair_address.resolve_price_usd_for_pair_address(
                pair_address_label,
                blockchain_network=blockchain_network,
            )
        except BlockchainPriceUnavailableError:
            return False
    return True


def _tokens_missing_onchain_price(
        position_tokens: Iterable[Token],
        onchain_prices_by_pair_address: OnchainPricesByPairAddress,
) -> list[Token]:
    dedupe_pairs_seen: set[str] = set()
    tokens_need_fetch: list[Token] = []
    for token_candidate in position_tokens:
        pair_address_label = token_candidate.pair_address
        if pair_address_label in (None, ""):
            continue
        resolved_price = onchain_prices_by_pair_address.try_resolve_price_usd_for_pair_address(pair_address_label)
        if resolved_price is not None and resolved_price > 0.0:
            continue
        if pair_address_label in dedupe_pairs_seen:
            continue
        dedupe_pairs_seen.add(pair_address_label)
        tokens_need_fetch.append(token_candidate)
    return tokens_need_fetch


def _merge_incremental_onchain_prices_for_open_positions(
        position_tokens_seed: Iterable[Token],
        onchain_prices_lookup: OnchainPricesByPairAddress,
) -> Optional[OnchainPricesByPairAddress]:
    tokens_missing = _tokens_missing_onchain_price(position_tokens_seed, onchain_prices_lookup)
    if not tokens_missing:
        return None
    fetched_incremental = fetch_onchain_prices_for_tokens(tokens_missing)
    merged_lookup = onchain_prices_lookup.merge_with(fetched_incremental)
    trading_cache.update_onchain_prices_by_pair_address(merged_lookup)
    return merged_lookup
