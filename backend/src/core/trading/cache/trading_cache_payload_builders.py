from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Optional

from src.api.http.api_schemas import (
    TradingPortfolioPayload,
    BlockchainCashBalancePayload,
    TradingLiquidityPayload,
    TradingShadowMetaPayload,
    ShadowIntelligenceStatusPayload,
    TradingTradePayload,
    TradingPositionPayload,
)
from src.api.serializers import (
    serialize_trading_portfolio_snapshot,
    serialize_trading_trade,
    serialize_trading_position,
)
from src.configuration.config import MAX_TRADING_ALLOWED_CHAIN_COUNT, settings
from src.core.structures.structures import RealizedProfitAndLoss, HoldingsAndUnrealizedProfitAndLoss
from src.core.trading.shadowing.shadow_trading_structures import ShadowIntelligenceSnapshot
from src.core.trading.trading_service import compute_realized_profit_and_loss, compute_available_cash_usd
from src.core.utils.date_utils import get_current_local_datetime
from src.core.utils.math_utils import quantize_2dp, decimal_from_primitive
from src.integrations.blockchain.blockchain_free_cash_service import BlockchainCashBalance, fetch_stablecoin_balances_for_allowed_chains
from src.logging.logger import get_application_logger
from src.persistence.dao.trading.shadowing_verdict_dao import TradingShadowingVerdictDao
from src.persistence.dao.trading.trading_portfolio_snapshot_dao import TradingPortfolioSnapshotDao
from src.persistence.dao.trading.trading_position_dao import TradingPositionDao
from src.persistence.dao.trading.trading_trade_dao import TradingTradeDao
from src.persistence.db import get_database_session
from src.persistence.models import TradingPortfolioSnapshot, TradingPosition

logger = get_application_logger(__name__)


def _convert_blockchain_cash_balance_to_payload(balance: BlockchainCashBalance) -> BlockchainCashBalancePayload:
    return BlockchainCashBalancePayload(
        blockchain_network=balance.blockchain_network,
        stablecoin_symbol=balance.stablecoin_symbol,
        stablecoin_address=balance.stablecoin_address,
        stablecoin_currency_symbol=balance.stablecoin_currency_symbol,
        balance_raw=balance.balance_raw,
        native_token_symbol=balance.native_token_symbol,
        native_token_balance_raw=balance.native_token_balance_raw,
        native_token_balance_usd=balance.native_token_balance_usd,
    )


def holdings_and_unrealized_from_positions(
        positions: Iterable[TradingPosition],
        prices_by_pair_address: dict[str, float],
) -> HoldingsAndUnrealizedProfitAndLoss:
    from src.core.trading.trading_utils import convert_trading_position_to_token
    position_list = list(positions)
    holdings_value_dec = Decimal("0")
    unrealized_dec = Decimal("0")

    for position in position_list:
        token = convert_trading_position_to_token(position)
        pair_address_value = position.pair_address
        price_usd: Optional[float] = None
        if pair_address_value is not None and pair_address_value != "":
            if pair_address_value in prices_by_pair_address:
                price_usd = prices_by_pair_address[pair_address_value]
        entry_price = position.entry_price or 0.0

        if price_usd is None or price_usd <= 0.0:
            logger.debug("[PNL][UNREAL][SKIP] token=%s reason=missing_onchain_price", token)
            continue

        quantity = position.current_quantity or 0.0
        if quantity <= 0.0:
            logger.debug("[PNL][UNREAL][SKIP] token=%s reason=non_positive_qty", token)
            continue

        holdings_value_dec += decimal_from_primitive(quantity * price_usd)
        unrealized_dec += decimal_from_primitive((price_usd - entry_price) * quantity)

    return HoldingsAndUnrealizedProfitAndLoss(
        total_holdings_value=float(quantize_2dp(holdings_value_dec)),
        total_unrealized_profit_and_loss=float(quantize_2dp(unrealized_dec)),
    )


def build_shadow_intelligence_status_payload() -> ShadowIntelligenceStatusPayload:
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


def build_trading_trades_payloads() -> list[TradingTradePayload]:
    with get_database_session() as database_session:
        trade_dao = TradingTradeDao(database_session)
        recent_trade_records = trade_dao.retrieve_recent_trades(limit_count=10000)
        return [serialize_trading_trade(trade_record) for trade_record in recent_trade_records]


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
    blockchain_balance_payloads = [
        _convert_blockchain_cash_balance_to_payload(balance)
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


def build_trading_positions_payloads(prices_by_pair_address: dict[str, float]) -> list[TradingPositionPayload]:
    with get_database_session() as database_session:
        position_dao = TradingPositionDao(database_session)
        open_position_records = position_dao.retrieve_open_positions()
        payloads: list[TradingPositionPayload] = []
        for position_record in open_position_records:
            pair_address_value = position_record.pair_address
            last_price_candidate: Optional[float] = None
            if pair_address_value is not None and pair_address_value != "":
                if pair_address_value in prices_by_pair_address:
                    last_price_candidate = prices_by_pair_address[pair_address_value]
            payloads.append(serialize_trading_position(position_record, last_price=last_price_candidate))
        return payloads


def build_trading_portfolio_payload(
        trades: list[TradingTradePayload],
        holdings_data: HoldingsAndUnrealizedProfitAndLoss,
        trading_portfolio_snapshot: TradingPortfolioSnapshot,
        *,
        blockchain_balances_override_payload: Optional[list[BlockchainCashBalancePayload]] = None,
) -> TradingPortfolioPayload:
    with get_database_session() as database_session:
        portfolio_dao = TradingPortfolioSnapshotDao(database_session)
        portfolio_snapshot_bound_to_session = database_session.merge(trading_portfolio_snapshot)

        shadow_status = build_shadow_intelligence_status_payload()
        realized_profit_and_loss_data: RealizedProfitAndLoss = compute_realized_profit_and_loss(trades, cutoff_hours=24)
        if blockchain_balances_override_payload is None:
            blockchain_balances_raw = fetch_stablecoin_balances_for_allowed_chains()
            blockchain_balance_payloads = [
                BlockchainCashBalancePayload(
                    blockchain_network=balance.blockchain_network,
                    stablecoin_symbol=balance.stablecoin_symbol,
                    stablecoin_address=balance.stablecoin_address,
                    stablecoin_currency_symbol=balance.stablecoin_currency_symbol,
                    balance_raw=balance.balance_raw,
                    native_token_symbol=balance.native_token_symbol,
                    native_token_balance_raw=balance.native_token_balance_raw,
                    native_token_balance_usd=balance.native_token_balance_usd,
                )
                for balance in blockchain_balances_raw
            ]
        else:
            blockchain_balance_payloads = list(blockchain_balances_override_payload)

        return serialize_trading_portfolio_snapshot(
            portfolio_snapshot_bound_to_session,
            equity_curve=portfolio_dao.retrieve_equity_curve(),
            realized_total=realized_profit_and_loss_data.total_realized_profit_and_loss,
            realized_24h=realized_profit_and_loss_data.recent_realized_profit_and_loss,
            unrealized=holdings_data.total_unrealized_profit_and_loss,
            shadow_status=shadow_status,
            blockchain_balances=blockchain_balance_payloads,
        )


def build_trading_portfolio_payload_reusing_cached_chain_balances(
        prices_lookup: dict[str, float],
) -> Optional[TradingPortfolioPayload]:
    from src.core.trading.cache.trading_cache import trading_state_cache

    trading_cached_state = trading_state_cache.get_trading_state()
    trades_payload_list = trading_cached_state.trades if trading_cached_state.trades is not None else []
    prior_portfolio = trading_cached_state.portfolio
    if prior_portfolio is None:
        override_balances: list[BlockchainCashBalancePayload] = []
    else:
        override_balances = list(prior_portfolio.blockchain_balances)

    previous_portfolio_candidate = prior_portfolio
    with get_database_session() as database_session:
        position_dao = TradingPositionDao(database_session)
        portfolio_dao = TradingPortfolioSnapshotDao(database_session)
        open_positions_list = position_dao.retrieve_open_positions()
        snapshot_candidate = portfolio_dao.retrieve_latest_snapshot()
        if snapshot_candidate is None:
            return None
        holdings_result = holdings_and_unrealized_from_positions(open_positions_list, prices_lookup)
        paired_open_positions_list = [
            position_row for position_row in open_positions_list
            if position_row.pair_address not in (None, "")
        ]
        for position_row in paired_open_positions_list:
            pair_key = position_row.pair_address
            if pair_key is None or pair_key == "":
                continue
            if pair_key not in prices_lookup or prices_lookup[pair_key] <= 0.0:
                if previous_portfolio_candidate is not None:
                    logger.warning(
                        "[TRADING][CACHE][PORTFOLIO][LIVE_GUARD] "
                        "Incomplete on-chain prices for paired open positions; retaining cached portfolio"
                    )
                    return previous_portfolio_candidate
                return None
    try:
        return build_trading_portfolio_payload(
            trades_payload_list,
            holdings_result,
            snapshot_candidate,
            blockchain_balances_override_payload=override_balances,
        )
    except ConnectionError:
        if previous_portfolio_candidate is not None:
            logger.warning(
                "[TRADING][CACHE][PORTFOLIO][LIVE_GUARD] "
                "On-chain balances unavailable; retaining cached portfolio snapshot"
            )
            return previous_portfolio_candidate
        raise


def build_shadow_intelligence_snapshot() -> ShadowIntelligenceSnapshot:
    from src.core.trading.shadowing.shadow_analytics_intelligence import compute_shadow_intelligence_snapshot
    return compute_shadow_intelligence_snapshot()


def build_trading_shadow_meta_payload(snapshot: ShadowIntelligenceSnapshot) -> TradingShadowMetaPayload:
    phase = "ACTIVE" if snapshot.is_activated else "LEARNING"
    if not settings.TRADING_SHADOWING_ENABLED:
        phase = "DISABLED"

    return TradingShadowMetaPayload(
        is_enabled=settings.TRADING_SHADOWING_ENABLED,
        is_activated=snapshot.is_activated,
        phase=phase,
        total_outcomes_analyzed=snapshot.total_outcomes_analyzed,
        resolved_outcome_count=snapshot.resolved_outcome_count,
        elapsed_hours=snapshot.elapsed_hours,
        win_rate_percentage=snapshot.meta_win_rate * 100.0,
        profit_factor=snapshot.meta_profit_factor,
        expected_value_usd=snapshot.meta_expected_value_usd,
        capital_velocity=snapshot.meta_capital_velocity,
        minimum_profit_factor=settings.TRADING_SHADOWING_MIN_PROFIT_FACTOR,
    )
