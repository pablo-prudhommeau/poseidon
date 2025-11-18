from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from enum import Enum
from typing import Deque, Dict, Iterable, List, Optional

from src.core.structures.structures import (
    RealizedPnl,
    Token,
    CashFromTrades,
    HoldingsAndUnrealizedPnl,
)
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.logging.logger import get_logger
from src.persistence.models import Trade, Position

log = get_logger(__name__)


@dataclass
class InventoryLot:
    """
    FIFO inventory lot with explicit cost basis.
    """
    quantity: float
    unit_price_usd: float
    buy_fee_per_unit_usd: float


def _now_with_timezone() -> datetime:
    """Return the current time with timezone information attached."""
    return datetime.now().astimezone()


def _get_created_at_or_now(obj: Trade | object) -> datetime:
    """
    Accessor for 'created_at' with timezone normalization and safe fallback.
    """
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
    """Normalize a side string/enum to uppercase (e.g. 'BUY', 'SELL')."""
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
    """
    Safe Decimal constructor from common primitives.
    Returns Decimal('0') when parsing fails.
    """
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _to_token_from_position(position: Position) -> Token:
    """Build a TokenIdentity from a position-like object."""
    pair_address: Optional[str] = position.pairAddress if isinstance(position.pairAddress,
                                                                     str) and position.pairAddress else None
    return Token(
        chain=position.chain,
        tokenAddress=position.tokenAddress,
        symbol=position.symbol,
        pairAddress=pair_address,
    )


def _quantize_2dp(amount: Decimal) -> Decimal:
    """Round to 2 decimal places with HALF_UP."""
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fifo_realized_pnl(trades: Iterable[Trade], *, cutoff_hours: int = 24) -> RealizedPnl:
    """
    Compute realized PnL using FIFO **per pair address when available, otherwise per token address**.

    Policy:
    - Buy fees are amortized per-unit into cost basis.
    - Sell fee is applied per matched unit on the sell side.
    - Grouping key: pairAddress if present; otherwise tokenAddress (chain-qualified).

    Logging:
    - [PNL][REALIZED][START]/[END] at function boundaries.
    - [PNL][REALIZED][BUY]/[SELL]/[SKIP] at key steps (debug level).
    """
    sorted_trades: List[Trade] = sorted(trades, key=_get_created_at_or_now)

    lots_by_token: Dict[Token, Deque[InventoryLot]] = defaultdict(deque)
    realized_total: Decimal = Decimal("0")
    realized_recent: Decimal = Decimal("0")
    cutoff_timestamp = _now_with_timezone() - timedelta(hours=cutoff_hours)

    for trade in sorted_trades:
        side = _normalize_side_to_upper(trade.side)
        token = Token(
            symbol=trade.symbol,
            chain=trade.chain,
            tokenAddress=trade.tokenAddress,
            pairAddress=trade.pairAddress,
        )

        try:
            quantity = float(trade.qty) if trade.qty is not None else 0.0
            unit_price_usd = float(trade.price) if trade.price is not None else 0.0
            fee_usd = float(trade.fee) if trade.fee is not None else 0.0
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

    realized = RealizedPnl(
        total=float(_quantize_2dp(realized_total)),
        recent=float(_quantize_2dp(realized_recent)),
    )

    return realized


def cash_from_trades(start_cash_usd: float, trades: Iterable[Trade]) -> CashFromTrades:
    """
    Compute ending cash from trades based on trade USD prices.

    Returns:
        CashFromTrades(cash, total_buys, total_sells, total_fees)
    """
    sorted_trades: List[Trade] = list(trades)

    total_buys: Decimal = Decimal("0")
    total_sells: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")

    for trade in sorted_trades:
        side = _normalize_side_to_upper(trade.side)

        try:
            quantity = float(trade.qty) if trade.qty is not None else 0.0
            unit_price_usd = float(trade.price) if trade.price is not None else 0.0
            fee_usd_dec = _decimal_from_primitive(trade.fee)
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
        cash=float(_quantize_2dp(ending_cash)),
        total_buys=float(_quantize_2dp(total_buys)),
        total_sells=float(_quantize_2dp(total_sells)),
        total_fees=float(_quantize_2dp(total_fees)),
    )
    return result


def holdings_and_unrealized_from_positions(
        positions: Iterable[Position],
        token_information_list: List[DexscreenerTokenInformation]
) -> HoldingsAndUnrealizedPnl:
    position_list: List[Position] = list(positions)
    holdings_value_dec = Decimal("0")
    unrealized_dec = Decimal("0")

    for position in position_list:
        token = _to_token_from_position(position)
        price_usd = next((token_information for token_information in token_information_list if
                          token_information.pair_address == position.pairAddress)).price_usd
        if price_usd is None or price_usd <= 0.0:
            log.debug("[PNL][UNREAL][NOPRICE] token=%s — skipping unrealized valuation", token)
            continue

        try:
            quantity = float(position.current_quantity)
            entry_price = float(position.entry)
        except (TypeError, ValueError):
            log.debug("[PNL][UNREAL][SKIP] token=%s reason=invalid_numeric_fields", token)
            continue

        if quantity <= 0.0:
            log.debug("[PNL][UNREAL][SKIP] token=%s reason=non_positive_qty", token)
            continue

        position_value = _decimal_from_primitive(quantity * price_usd)
        holdings_value_dec += position_value

        unrealized_for_position = _decimal_from_primitive((price_usd - entry_price) * quantity)
        unrealized_dec += unrealized_for_position

    result = HoldingsAndUnrealizedPnl(
        holdings=float(_quantize_2dp(holdings_value_dec)),
        unrealized_pnl=float(_quantize_2dp(unrealized_dec)),
    )
    return result


async def latest_prices_for_positions(positions: Iterable[object]) -> Dict[str, float]:
    """
    Pair-aware live pricing for a set of positions, **preserving keys**:

    Rules:
    - When a position has a non-empty 'pairAddress' and a valid 'chain', query Dexscreener
      and return a mapping {pairAddress -> priceUsd}.
    - Positions without a pair are ignored here (pair-only policy).
    """
    from src.core.structures.structures import Token as CoreToken
    from src.integrations.dexscreener.dexscreener_client import fetch_dexscreener_token_information_list
    from src.integrations.dexscreener.dexscreener_structures import \
        DexscreenerTokenPrice as CoreTokenPrice  # noqa: F401

    tokens: List[CoreToken] = []
    for position in positions:
        pair_address = getattr(position, "pairAddress", None)
        chain = getattr(position, "chain", None)
        token_address = getattr(position, "tokenAddress", None) or getattr(position, "address", None)
        symbol = getattr(position, "symbol", "")

        if (
                isinstance(pair_address, str) and pair_address
                and isinstance(chain, str) and chain
                and isinstance(token_address, str) and token_address
        ):
            tokens.append(CoreToken(symbol=symbol, chain=chain, tokenAddress=token_address, pairAddress=pair_address))

    result: Dict[str, float] = {}
    if not tokens:
        log.info("[PRICES][LATEST][END] positions=0 returned=0 reason=no_queryable_pairs")
        return result

    token_information_list: List[DexscreenerTokenInformation] = await fetch_dexscreener_token_information_list(tokens)
    for token_information in token_information_list:
        has_pair = isinstance(token_information.pair_address, str) and token_information.pair_address
        if has_pair and token_information.price_usd and token_information.price_usd > 0.0:
            result[token_information.pair_address] = float(token_information.price_usd)

    return result
