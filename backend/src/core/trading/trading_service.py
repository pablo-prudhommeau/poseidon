from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable, List, Dict, Deque, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.http.api_schemas import TradingTradePayload
from src.configuration.config import settings
from src.core.structures.structures import Token
from src.core.trading.cache.trading_cache import trading_cache
from src.core.trading.screener.trading_screener_provider import get_trading_screener_provider
from src.core.trading.trading_helpers import build_trading_evaluation
from src.core.trading.trading_structures import TradingCandidate
from src.core.trading.trading_utils import convert_trading_position_to_token, normalize_side_to_upper
from src.core.utils.date_utils import ensure_timezone_aware, get_current_local_datetime, parse_iso_datetime_to_local
from src.core.utils.math_utils import quantize_2dp, decimal_from_primitive
from src.integrations.blockchain.blockchain_exceptions import BlockchainRpcUnavailableError
from src.integrations.blockchain.blockchain_free_cash_service import fetch_stablecoin_balances_for_allowed_chains
from src.integrations.blockchain.blockchain_price_structures import OnchainPricesByPairAddress
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_evaluation_dao import TradingEvaluationDao
from src.persistence.dao.trading_position_dao import TradingPositionDao
from src.persistence.dao.trading_trade_dao import TradingTradeDao
from src.persistence.database_session_manager import get_database_session
from src.persistence.models import PositionPhase, TradingPosition, TradingTrade

POSITION_PHASES_CONSUMING_MAX_OPEN_SLOT = (
    PositionPhase.OPEN,
    PositionPhase.PARTIAL,
    PositionPhase.CLOSING,
    PositionPhase.STALED,
)

logger = get_application_logger(__name__)


@dataclass
class _FifoInventoryLot:
    quantity: float
    unit_price_usd: float
    buy_fee_per_unit_usd: float


def _consume_fifo_inventory_lots(
        lots_by_token: Dict[Token, Deque[_FifoInventoryLot]],
        token: Token,
        quantity_to_match: float,
) -> None:
    remaining_quantity_to_match: float = quantity_to_match
    while remaining_quantity_to_match > 1e-12 and lots_by_token[token]:
        lot = lots_by_token[token][0]
        matched_quantity = min(remaining_quantity_to_match, lot.quantity)
        lot.quantity -= matched_quantity
        remaining_quantity_to_match -= matched_quantity
        if lot.quantity <= 1e-12:
            lots_by_token[token].popleft()


def compute_realized_profit_and_loss_totals(
        trades: Iterable[TradingTradePayload],
) -> tuple[float, float, float, float]:
    now = get_current_local_datetime()
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)

    def trade_timestamp(trade: TradingTradePayload) -> datetime:
        return parse_iso_datetime_to_local(trade.created_at)

    sorted_trades: List[TradingTradePayload] = sorted(trades, key=trade_timestamp)

    lots_by_token: Dict[Token, Deque[_FifoInventoryLot]] = defaultdict(deque)
    realized_total: Decimal = Decimal("0")
    realized_24h: Decimal = Decimal("0")
    realized_7d: Decimal = Decimal("0")
    realized_30d: Decimal = Decimal("0")

    def accumulate_realized(trade_time: datetime, contribution: Decimal) -> None:
        nonlocal realized_total, realized_24h, realized_7d, realized_30d
        realized_total += contribution
        if trade_time >= cutoff_24h:
            realized_24h += contribution
        if trade_time >= cutoff_7d:
            realized_7d += contribution
        if trade_time >= cutoff_30d:
            realized_30d += contribution

    for trade in sorted_trades:
        side = normalize_side_to_upper(trade.trade_side)
        token = Token(
            symbol=trade.token_symbol,
            chain=trade.blockchain_network,
            token_address=trade.token_address,
            pair_address=trade.pair_address,
            dex_id=trade.dex_id,
        )

        try:
            quantity = float(trade.execution_quantity) if trade.execution_quantity is not None else 0.0
            unit_price_usd = float(trade.execution_price) if trade.execution_price is not None else 0.0
            fee_usd = float(trade.transaction_fee) if trade.transaction_fee is not None else 0.0
        except (TypeError, ValueError):
            logger.debug("[PNL][REALIZED][SKIP] token=%s reason=invalid_numeric_fields", token)
            continue

        if side == "SELL" and trade.realized_profit_and_loss is not None:
            trade_time = trade_timestamp(trade)
            usd_contribution = decimal_from_primitive(trade.realized_profit_and_loss)
            accumulate_realized(trade_time, usd_contribution)
            if quantity <= 0.0:
                logger.debug(
                    "[PNL][REALIZED][SYNTHETIC] token=%s ledger write-off cleared fifo inventory lots",
                    token,
                )
                lots_by_token[token].clear()
            else:
                _consume_fifo_inventory_lots(
                    lots_by_token=lots_by_token,
                    token=token,
                    quantity_to_match=quantity,
                )
            continue

        if quantity <= 0.0 or unit_price_usd <= 0.0:
            logger.debug("[PNL][REALIZED][SKIP] token=%s reason=non_positive_qty_or_price", token)
            continue

        if side == "BUY":
            buy_fee_per_unit_usd = fee_usd / quantity if quantity > 0.0 else 0.0
            lots_by_token[token].append(
                _FifoInventoryLot(
                    quantity=quantity,
                    unit_price_usd=unit_price_usd,
                    buy_fee_per_unit_usd=buy_fee_per_unit_usd,
                )
            )
            continue

        if side == "SELL":
            sell_fee_per_unit_usd = fee_usd / quantity if quantity > 0.0 else 0.0
            trade_time = trade_timestamp(trade)

            remaining_quantity_to_match: float = quantity
            while remaining_quantity_to_match > 1e-12 and lots_by_token[token]:
                lot = lots_by_token[token][0]
                matched_quantity = min(remaining_quantity_to_match, lot.quantity)

                profit_and_loss_per_unit = (
                    unit_price_usd - lot.unit_price_usd - lot.buy_fee_per_unit_usd - sell_fee_per_unit_usd
                )
                profit_and_loss_contribution = (
                    decimal_from_primitive(matched_quantity) * decimal_from_primitive(profit_and_loss_per_unit)
                )

                accumulate_realized(trade_time, profit_and_loss_contribution)

                lot.quantity -= matched_quantity
                remaining_quantity_to_match -= matched_quantity
                if lot.quantity <= 1e-12:
                    lots_by_token[token].popleft()

    return (
        float(quantize_2dp(realized_total)),
        float(quantize_2dp(realized_24h)),
        float(quantize_2dp(realized_7d)),
        float(quantize_2dp(realized_30d)),
    )


def compute_holdings_and_unrealized_totals(
        positions: Iterable[TradingPosition],
        onchain_prices_by_pair_address: OnchainPricesByPairAddress,
) -> tuple[float, float]:
    holdings_value_dec = Decimal("0")
    unrealized_dec = Decimal("0")

    for position in positions:
        token = convert_trading_position_to_token(position)
        pair_address = position.pair_address
        price_usd = (
            onchain_prices_by_pair_address.try_resolve_price_usd_for_pair_address(pair_address)
            if pair_address
            else None
        )

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

    return (
        float(quantize_2dp(holdings_value_dec)),
        float(quantize_2dp(unrealized_dec)),
    )


def compute_available_cash_usd(*, database_session: Optional[Session] = None) -> float:
    if settings.PAPER_MODE:
        if database_session is not None:
            return compute_paper_deployable_cash_usd(database_session)
        with get_database_session() as opened_database_session:
            return compute_paper_deployable_cash_usd(opened_database_session)
    return _compute_live_deployable_cash_usd()


def compute_paper_deployable_cash_usd(database_session: Session) -> float:
    trade_records = TradingTradeDao(database_session).retrieve_recent_trades(limit_count=100000)
    deployable_cash_usd = compute_available_cash_from_trades(settings.PAPER_STARTING_CASH, trade_records)
    logger.debug(
        "[TRADING][CASH][PAPER] Deployable cash resolved — balance=%.2f",
        deployable_cash_usd,
    )
    return deployable_cash_usd


def compute_cumulative_swap_fees_usd(trades: Iterable[TradingTrade]) -> float:
    cumulative_fees: Decimal = Decimal("0")
    for trade_record in trades:
        try:
            fee_usd = float(trade_record.transaction_fee) if trade_record.transaction_fee is not None else 0.0
        except (TypeError, ValueError):
            continue
        if fee_usd <= 0.0:
            continue
        cumulative_fees += decimal_from_primitive(fee_usd)
    return float(quantize_2dp(cumulative_fees))


def compute_cumulative_swap_fees_from_trade_payloads(trades: Iterable[TradingTradePayload]) -> float:
    cumulative_fees: Decimal = Decimal("0")
    for trade_payload in trades:
        try:
            fee_usd = float(trade_payload.transaction_fee) if trade_payload.transaction_fee is not None else 0.0
        except (TypeError, ValueError):
            continue
        if fee_usd <= 0.0:
            continue
        cumulative_fees += decimal_from_primitive(fee_usd)
    return float(quantize_2dp(cumulative_fees))


def has_any_closing_positions(database_session: Session) -> bool:
    closing_positions = TradingPositionDao(database_session).retrieve_by_phase(PositionPhase.CLOSING)
    return len(closing_positions) > 0


def count_positions_consuming_max_open_slots(database_session: Session) -> int:
    return database_session.execute(
        select(func.count(TradingPosition.id)).where(
            TradingPosition.position_phase.in_(POSITION_PHASES_CONSUMING_MAX_OPEN_SLOT)
        )
    ).scalar_one_or_none() or 0


def compute_available_cash_from_trades(start_cash_usd: float, trades: Iterable[TradingTrade]) -> float:
    total_buys: Decimal = Decimal("0")
    total_sells: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")

    for trade in trades:
        side = normalize_side_to_upper(trade.trade_side)

        try:
            quantity = float(trade.execution_quantity) if trade.execution_quantity is not None else 0.0
            unit_price_usd = float(trade.execution_price) if trade.execution_price is not None else 0.0
            fee_usd_dec = decimal_from_primitive(trade.transaction_fee)
        except (TypeError, ValueError):
            logger.debug("[PNL][CASH][SKIP] reason=invalid_numeric_fields")
            continue

        if quantity <= 0.0 or unit_price_usd <= 0.0:
            logger.debug("[PNL][CASH][SKIP] reason=non_positive_qty_or_price")
            continue

        notional_dec = decimal_from_primitive(unit_price_usd * quantity)
        if side == "BUY":
            total_buys += notional_dec
        elif side == "SELL":
            total_sells += notional_dec
        total_fees += fee_usd_dec

    ending_cash = decimal_from_primitive(start_cash_usd) - total_buys + total_sells - total_fees
    return float(quantize_2dp(ending_cash))


def fetch_trading_candidates_sync() -> list[TradingCandidate]:
    candidates_list: list[TradingCandidate] = get_trading_screener_provider().fetch_trending_candidates()
    logger.info("[TRADING][FETCH] Hydrated %d trading candidates from screener", len(candidates_list))
    return candidates_list


def record_trading_evaluation(
        candidate: TradingCandidate,
        rank: int,
        decision: str,
        reason: str,
        sizing_multiplier: float = 0.0,
        order_notional_usd: float = 0.0,
        free_cash_before_usd: float = 0.0,
        free_cash_after_usd: float = 0.0,
) -> Optional[int]:
    token_symbol = candidate.token.symbol.upper()
    normalized_decision = decision.upper()

    if normalized_decision != "BUY":
        logger.info(
            "[TRADING][EVALUATION] Token %s evaluated -> Decision: %s | Reason: %s",
            token_symbol,
            normalized_decision,
            reason,
        )
        return None

    trading_evaluation = build_trading_evaluation(
        candidate=candidate,
        rank=rank,
        decision=normalized_decision,
        sizing_multiplier=sizing_multiplier,
        order_notional_usd=order_notional_usd,
        free_cash_before_usd=free_cash_before_usd,
        free_cash_after_usd=free_cash_after_usd,
    )

    logger.info(
        "[TRADING][EVALUATION] Token %s evaluated -> Decision: %s | Reason: %s",
        trading_evaluation.token_symbol,
        normalized_decision,
        reason,
    )

    with get_database_session() as database_session:
        serialized_evaluation = TradingEvaluationDao(database_session).record_evaluation(trading_evaluation)
        database_session.commit()
        return serialized_evaluation.id


def record_skipped_trading_evaluation(evaluation_candidate: TradingCandidate, sequence_rank: int, exclusion_reason: str) -> None:
    record_trading_evaluation(evaluation_candidate, rank=sequence_rank, decision="SKIP", reason=exclusion_reason)


def _compute_live_deployable_cash_usd() -> float:
    try:
        balances = fetch_stablecoin_balances_for_allowed_chains()
    except (ConnectionError, BlockchainRpcUnavailableError):
        cached_cash = trading_cache.get_available_cash_usd()
        if cached_cash is not None:
            logger.warning(
                "[TRADING][CASH] Live balances unavailable; using cached available cash %.2f USD",
                cached_cash,
            )
            return cached_cash
        raise
    return sum(balance.balance_raw for balance in balances)
