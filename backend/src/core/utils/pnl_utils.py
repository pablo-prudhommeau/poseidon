from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from enum import Enum
from typing import Deque, Dict, Iterable, List, Optional

from src.core.structures.structures import (
    RealizedProfitAndLoss,
    Token,
    CashFromTrades,
    HoldingsAndUnrealizedProfitAndLoss,
)
from src.logging.logger import get_application_logger
from src.persistence.models import TradingTrade, TradingPosition

log = get_application_logger(__name__)


@dataclass
class InventoryLot:
    quantity: float
    unit_price_usd: float
    buy_fee_per_unit_usd: float


def _now_with_timezone() -> datetime:
    return datetime.now().astimezone()


def _get_created_at_or_now(obj: TradingTrade | object) -> datetime:
    try:
        created_at = obj.created_at
    except AttributeError:
        return _now_with_timezone()

    if created_at is None:
        return _now_with_timezone()

    try:
        return created_at.astimezone()
    except Exception:
        return _now_with_timezone()


def _normalize_side_to_upper(value: str | Enum | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.upper()
    if isinstance(value, Enum):
        try:
            enum_value = value.value
        except Exception:
            enum_value = str(value)
        return str(enum_value).upper()
    return str(value).upper()


def _decimal_from_primitive(value: float | int | str | None) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _to_token_from_position(position: TradingPosition) -> Token:
    pair_address: Optional[str] = position.pair_address if isinstance(position.pair_address,
                                                                      str) and position.pair_address else None
    return Token(
        chain=position.blockchain_network,
        token_address=position.token_address,
        symbol=position.token_symbol,
        pair_address=pair_address,
        dex_id=position.dex_id,
    )


def _quantize_2dp(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fifo_realized_pnl(trades: Iterable[TradingTrade], *, cutoff_hours: int = 24) -> RealizedProfitAndLoss:
    sorted_trades: List[TradingTrade] = sorted(trades, key=_get_created_at_or_now)

    lots_by_token: Dict[Token, Deque[InventoryLot]] = defaultdict(deque)
    realized_total: Decimal = Decimal("0")
    realized_recent: Decimal = Decimal("0")
    cutoff_timestamp = _now_with_timezone() - timedelta(hours=cutoff_hours)

    for trade in sorted_trades:
        side = _normalize_side_to_upper(trade.trade_side)
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
            log.debug("[PNL][REALIZED][SKIP] token=%s reason=invalid_numeric_fields", token)
            continue

        if quantity <= 0.0 or unit_price_usd <= 0.0:
            log.debug("[PNL][REALIZED][SKIP] token=%s reason=non_positive_qty_or_price", token)
            continue

        if side == "BUY":
            buy_fee_per_unit_usd = fee_usd / quantity if quantity > 0.0 else 0.0
            lots_by_token[token].append(
                InventoryLot(quantity=quantity, unit_price_usd=unit_price_usd,
                             buy_fee_per_unit_usd=buy_fee_per_unit_usd)
            )
            continue

        if side == "SELL":
            sell_fee_per_unit_usd = fee_usd / quantity if quantity > 0.0 else 0.0
            remaining_to_match = quantity
            is_recent = _get_created_at_or_now(trade) >= cutoff_timestamp

            while remaining_to_match > 1e-12 and lots_by_token[token]:
                lot = lots_by_token[token][0]
                matched_quantity = min(remaining_to_match, lot.quantity)

                pnl_per_unit = unit_price_usd - lot.unit_price_usd - lot.buy_fee_per_unit_usd - sell_fee_per_unit_usd
                pnl_contribution = _decimal_from_primitive(matched_quantity) * _decimal_from_primitive(pnl_per_unit)

                realized_total += pnl_contribution
                if is_recent:
                    realized_recent += pnl_contribution

                lot.quantity -= matched_quantity
                remaining_to_match -= matched_quantity
                if lot.quantity <= 1e-12:
                    lots_by_token[token].popleft()

    realized = RealizedProfitAndLoss(
        total_realized_profit_and_loss=float(_quantize_2dp(realized_total)),
        recent_realized_profit_and_loss=float(_quantize_2dp(realized_recent)),
    )

    return realized


def cash_from_trades(start_cash_usd: float, trades: Iterable[TradingTrade]) -> CashFromTrades:
    sorted_trades: List[TradingTrade] = list(trades)

    total_buys: Decimal = Decimal("0")
    total_sells: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")

    for trade in sorted_trades:
        side = _normalize_side_to_upper(trade.trade_side)

        try:
            quantity = float(trade.execution_quantity) if trade.execution_quantity is not None else 0.0
            unit_price_usd = float(trade.execution_price) if trade.execution_price is not None else 0.0
            fee_usd_dec = _decimal_from_primitive(trade.transaction_fee)
        except (TypeError, ValueError):
            log.debug("[PNL][CASH][SKIP] reason=invalid_numeric_fields")
            continue

        if quantity <= 0.0 or unit_price_usd <= 0.0:
            log.debug("[PNL][CASH][SKIP] reason=non_positive_qty_or_price")
            continue

        notional_dec = _decimal_from_primitive(unit_price_usd * quantity)
        if side == "BUY":
            total_buys += notional_dec
        elif side == "SELL":
            total_sells += notional_dec
        total_fees += fee_usd_dec

    ending_cash = _decimal_from_primitive(start_cash_usd) - total_buys + total_sells - total_fees
    result = CashFromTrades(
        available_cash=float(_quantize_2dp(ending_cash)),
        total_buy_volume=float(_quantize_2dp(total_buys)),
        total_sell_volume=float(_quantize_2dp(total_sells)),
        total_fees_paid=float(_quantize_2dp(total_fees)),
    )
    return result


def holdings_and_unrealized_from_positions(
        positions: Iterable[TradingPosition],
        prices_by_pair_address: Dict[str, float],
) -> HoldingsAndUnrealizedProfitAndLoss:
    position_list: List[TradingPosition] = list(positions)
    holdings_value_dec = Decimal("0")
    unrealized_dec = Decimal("0")

    for position in position_list:
        token = _to_token_from_position(position)
        price_usd = prices_by_pair_address.get(position.pair_address) if position.pair_address else None
        entry_price = position.entry_price or 0.0

        if price_usd is None or price_usd <= 0.0:
            log.debug("[PNL][UNREAL][NOPRICE] token=%s — falling back to entry_price for valuation", token)
            price_usd = entry_price

        quantity = position.current_quantity or 0.0

        if quantity <= 0.0:
            log.debug("[PNL][UNREAL][SKIP] token=%s reason=non_positive_qty", token)
            continue

        position_value = _decimal_from_primitive(quantity * price_usd)
        holdings_value_dec += position_value

        unrealized_for_position = _decimal_from_primitive((price_usd - entry_price) * quantity)
        unrealized_dec += unrealized_for_position

    result = HoldingsAndUnrealizedProfitAndLoss(
        total_holdings_value=float(_quantize_2dp(holdings_value_dec)),
        total_unrealized_profit_and_loss=float(_quantize_2dp(unrealized_dec)),
    )
    return result


def compute_portfolio_free_cash() -> float:
    from src.configuration.config import settings
    from src.persistence.dao.trading.trading_trade_dao import TradingTradeDao
    from src.persistence.db import _session

    with _session() as database_session:
        trade_dao = TradingTradeDao(database_session)
        all_trades = trade_dao.retrieve_recent_trades(limit_count=100000)
        cash_state = cash_from_trades(settings.PAPER_STARTING_CASH, all_trades)
        return cash_state.available_cash
