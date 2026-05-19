from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable, List, Dict, Deque, Optional

from sqlalchemy.orm import Session

from src.api.http.api_schemas import TradingTradePayload
from src.configuration.config import settings
from src.core.structures.structures import Token
from src.core.trading.cache.trading_cache import trading_cache
from src.core.trading.screener.trading_screener_provider import get_trading_screener_provider
from src.core.trading.trading_evaluation_helpers import build_trading_evaluation
from src.core.trading.trading_structures import TradingCandidate
from src.core.trading.trading_utils import convert_trading_position_to_token, normalize_side_to_upper
from src.core.utils.date_utils import ensure_timezone_aware, get_current_local_datetime, parse_iso_datetime_to_local
from src.core.utils.math_utils import quantize_2dp, decimal_from_primitive
from src.integrations.blockchain.blockchain_free_cash_service import fetch_stablecoin_balances_for_allowed_chains
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_evaluation_dao import TradingEvaluationDao
from src.persistence.dao.trading_portfolio_snapshot_dao import TradingPortfolioSnapshotDao
from src.persistence.dao.trading_position_dao import TradingPositionDao
from src.persistence.dao.trading_trade_dao import TradingTradeDao
from src.persistence.database_session_manager import get_database_session
from src.persistence.models import PositionPhase, TradingPosition, TradingTrade

logger = get_application_logger(__name__)


@dataclass
class _FifoInventoryLot:
    quantity: float
    unit_price_usd: float
    buy_fee_per_unit_usd: float


def compute_realized_profit_and_loss_totals(
        trades: Iterable[TradingTradePayload],
        *,
        cutoff_hours: int = 24,
) -> tuple[float, float]:
    cutoff_timestamp = get_current_local_datetime() - timedelta(hours=cutoff_hours)

    def trade_timestamp(trade: TradingTradePayload) -> datetime:
        return parse_iso_datetime_to_local(trade.created_at)

    sorted_trades: List[TradingTradePayload] = sorted(trades, key=trade_timestamp)

    lots_by_token: Dict[Token, Deque[_FifoInventoryLot]] = defaultdict(deque)
    realized_total: Decimal = Decimal("0")
    realized_recent: Decimal = Decimal("0")

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

        if side == "SELL" and trade.realized_profit_and_loss is not None:
            is_recent = trade_timestamp(trade) >= cutoff_timestamp
            usd_contribution = decimal_from_primitive(trade.realized_profit_and_loss)
            realized_total += usd_contribution
            if is_recent:
                realized_recent += usd_contribution
            remaining_to_match = quantity
            while remaining_to_match > 1e-12 and lots_by_token[token]:
                lot = lots_by_token[token][0]
                matched_quantity = min(remaining_to_match, lot.quantity)
                lot.quantity -= matched_quantity
                remaining_to_match -= matched_quantity
                if lot.quantity <= 1e-12:
                    lots_by_token[token].popleft()
            continue

        if side == "SELL":
            sell_fee_per_unit_usd = fee_usd / quantity if quantity > 0.0 else 0.0
            remaining_to_match = quantity
            is_recent = trade_timestamp(trade) >= cutoff_timestamp

            while remaining_to_match > 1e-12 and lots_by_token[token]:
                lot = lots_by_token[token][0]
                matched_quantity = min(remaining_to_match, lot.quantity)

                pnl_per_unit = unit_price_usd - lot.unit_price_usd - lot.buy_fee_per_unit_usd - sell_fee_per_unit_usd
                pnl_contribution = decimal_from_primitive(matched_quantity) * decimal_from_primitive(pnl_per_unit)

                realized_total += pnl_contribution
                if is_recent:
                    realized_recent += pnl_contribution

                lot.quantity -= matched_quantity
                remaining_to_match -= matched_quantity
                if lot.quantity <= 1e-12:
                    lots_by_token[token].popleft()

    return (
        float(quantize_2dp(realized_total)),
        float(quantize_2dp(realized_recent)),
    )


def compute_holdings_and_unrealized_totals(
        positions: Iterable[TradingPosition],
        prices_by_pair_address: dict[str, float],
) -> tuple[float, float]:
    holdings_value_dec = Decimal("0")
    unrealized_dec = Decimal("0")

    for position in positions:
        token = convert_trading_position_to_token(position)
        pair_address = position.pair_address
        price_usd: Optional[float] = None
        if pair_address:
            price_usd = prices_by_pair_address.get(pair_address)

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
            return compute_trade_ledger_available_cash_usd(database_session)
        with get_database_session() as opened_database_session:
            return compute_trade_ledger_available_cash_usd(opened_database_session)
    return _compute_live_available_cash_usd()


def compute_trade_ledger_available_cash_usd(database_session: Session) -> float:
    baseline_cash_usd = _resolve_trade_ledger_baseline_cash_usd(database_session)
    trade_records = _retrieve_trades_for_trade_ledger(database_session)
    available_cash = compute_available_cash_from_trades(baseline_cash_usd, trade_records)
    operating_mode_label = "paper" if settings.PAPER_MODE else "live"
    logger.debug(
        "[TRADING][CASH][LEDGER] Trade-ledger available cash resolved — mode=%s balance=%.2f",
        operating_mode_label,
        available_cash,
    )
    return available_cash


def has_any_closing_positions(database_session: Session) -> bool:
    closing_positions = TradingPositionDao(database_session).retrieve_by_phase(PositionPhase.CLOSING)
    return len(closing_positions) > 0


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


def _resolve_trade_ledger_baseline_cash_usd(database_session: Session) -> float:
    if settings.PAPER_MODE:
        return settings.PAPER_STARTING_CASH
    return _resolve_live_trade_ledger_baseline_cash_usd(database_session)


def _resolve_live_trade_ledger_baseline_cash_usd(database_session: Session) -> float:
    portfolio_dao = TradingPortfolioSnapshotDao(database_session)
    latest_portfolio_snapshot = portfolio_dao.retrieve_latest_snapshot()
    if latest_portfolio_snapshot is not None:
        return latest_portfolio_snapshot.available_cash_balance

    logger.info(
        "[TRADING][CASH][LEDGER] No portfolio snapshot in live mode; "
        "bootstrapping trade-ledger baseline from on-chain balances"
    )
    on_chain_cash_balance_usd = _compute_live_available_cash_usd()
    trade_dao = TradingTradeDao(database_session)
    all_trade_records = trade_dao.retrieve_recent_trades(limit_count=100000)
    cash_from_zero_baseline = compute_available_cash_from_trades(0.0, all_trade_records)
    return on_chain_cash_balance_usd - cash_from_zero_baseline


def _retrieve_trades_for_trade_ledger(database_session: Session) -> List[TradingTrade]:
    trade_dao = TradingTradeDao(database_session)
    all_trade_records = trade_dao.retrieve_recent_trades(limit_count=100000)

    if settings.PAPER_MODE:
        return all_trade_records

    portfolio_dao = TradingPortfolioSnapshotDao(database_session)
    latest_portfolio_snapshot = portfolio_dao.retrieve_latest_snapshot()
    if latest_portfolio_snapshot is None:
        return all_trade_records

    ledger_anchor_timestamp = ensure_timezone_aware(latest_portfolio_snapshot.created_at)
    if ledger_anchor_timestamp is None:
        return all_trade_records

    trade_records_after_ledger_anchor: List[TradingTrade] = []
    for trade_record in all_trade_records:
        trade_timestamp = ensure_timezone_aware(trade_record.created_at)
        if trade_timestamp is None:
            continue
        if trade_timestamp > ledger_anchor_timestamp:
            trade_records_after_ledger_anchor.append(trade_record)
    return trade_records_after_ledger_anchor


def _compute_live_available_cash_usd() -> float:
    try:
        balances = fetch_stablecoin_balances_for_allowed_chains()
    except ConnectionError:
        cached_cash = trading_cache.get_available_cash_usd()
        if cached_cash is not None:
            logger.warning(
                "[TRADING][CASH] Live balances unavailable; using cached available cash %.2f USD",
                cached_cash,
            )
            return cached_cash
        raise
    return sum(balance.balance_raw for balance in balances)
