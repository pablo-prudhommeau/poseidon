from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import List, Deque, Tuple, Dict, Optional

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.core.utils import timezone_now
from src.logging.logger import get_logger
from src.persistence.models import Position, Trade, Phase, Status, Side

log = get_logger(__name__)

# -----------------------------------------------------------------------------
# Re-entry lock (in-memory). Key: address -> eligible_at (timezone-aware datetime)
# -----------------------------------------------------------------------------
_REENTRY_LOCK: Dict[str, datetime] = {}


def _get_cooldown_seconds() -> int:
    """
    Return the re-entry cooldown in seconds.
    Fallback kept for legacy 'COOLDOWN_SECONDS'.
    """
    return int(
        getattr(settings, "REENTRY_COOLDOWN_SECONDS", getattr(settings, "COOLDOWN_SECONDS", 60))
    )


def _ensure_aware_datetime(value: Optional[datetime]) -> Optional[datetime]:
    """
    Ensure a datetime is timezone-aware (UTC). If value is None, return None.
    If value is naive, assume UTC and attach tzinfo=UTC.
    """
    if value is None:
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _cleanup_reentry_lock(now: datetime) -> None:
    """
    Remove stale in-memory locks. Best-effort; O(n) on the number of addresses.
    """
    stale = [addr for addr, eligible_at in _REENTRY_LOCK.items() if eligible_at is not None and now >= eligible_at]
    for addr in stale:
        _REENTRY_LOCK.pop(addr, None)


def _set_reentry_lock(address: str, eligible_at: datetime) -> None:
    """Arm a temporary in-memory re-entry lock for the address."""
    _REENTRY_LOCK[address] = _ensure_aware_datetime(eligible_at)  # always store aware


def _get_reentry_eligible_at(address: str) -> Optional[datetime]:
    """Return the in-memory re-entry eligibility for the address, if any (aware UTC)."""
    return _ensure_aware_datetime(_REENTRY_LOCK.get(address))


# -----------------------------------------------------------------------------
# Position lookup helpers
# -----------------------------------------------------------------------------
def _get_active_position_by_address(db: Session, address: str) -> Optional[Position]:
    """
    Return the most recent ACTIVE position (OPEN or PARTIAL) for this address.
    We never look at CLOSED rows here.
    """
    return (
        db.execute(
            select(Position)
            .where(
                Position.address == address,
                Position.phase.in_([Phase.OPEN, Phase.PARTIAL]),
                )
            .order_by(desc(Position.opened_at), desc(Position.id))
            .limit(1)
        )
        .scalars()
        .first()
    )


def _get_last_closed_position_for_cooldown(db: Session, address: str) -> Optional[Position]:
    """
    Return the most recently CLOSED position for cooldown enforcement purposes.
    """
    return (
        db.execute(
            select(Position)
            .where(
                Position.address == address,
                Position.phase == Phase.CLOSED,
                Position.closed_at.isnot(None),
                )
            .order_by(desc(Position.closed_at), desc(Position.id))
            .limit(1)
        )
        .scalars()
        .first()
    )


def _cooldown_guard(db: Session, address: str) -> None:
    """
    Strictly enforce business rules BEFORE accepting a BUY:

    - Absolutely forbid DCA:
        If any ACTIVE (OPEN or PARTIAL) position exists for this address,
        reject immediately.
    - When there is no active position, enforce the re-entry cooldown based on:
        1) the most recent CLOSED position's closed_at
        2) the in-memory re-entry lock

    Raises:
        RuntimeError: when a BUY would be a DCA or when cooldown has not elapsed yet.
    """
    now: datetime = timezone_now()  # should already be aware (UTC)
    now = _ensure_aware_datetime(now)  # defensive
    _cleanup_reentry_lock(now)
    cooldown_seconds = _get_cooldown_seconds()

    active = _get_active_position_by_address(db, address)
    if active is not None:
        log.info(
            "[SKIP][DCA_DISABLED] address=%s phase=%s — active position exists",
            address,
            active.phase,
        )
        raise RuntimeError("BUY rejected: a position is already OPEN or PARTIAL for this address.")

    last_closed = _get_last_closed_position_for_cooldown(db, address)
    eligible_from_closed: Optional[datetime] = None
    if last_closed and last_closed.closed_at:
        closed_at_aware = _ensure_aware_datetime(last_closed.closed_at)
        eligible_from_closed = closed_at_aware + timedelta(seconds=cooldown_seconds)

    eligible_from_lock = _get_reentry_eligible_at(address)

    candidates: List[datetime] = [
        t for t in (eligible_from_closed, eligible_from_lock) if t is not None
    ]
    eligible_at: Optional[datetime] = max(candidates) if candidates else None

    if eligible_at is not None and now < eligible_at:
        remaining = (eligible_at - now).total_seconds()
        log.info("[SKIP][COOLDOWN] address=%s next=%s (remaining=%.1fs)", address, eligible_at, remaining)
        raise RuntimeError(f"BUY rejected by cooldown; next eligible at {eligible_at.isoformat()}")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _compute_open_quantity_from_trades(db: Session, address: str) -> float:
    """
    Return current open quantity for an address as sum(BUY) - sum(SELL).
    This spans lifecycles; prior CLOSED cycles should net to zero.
    """
    trades = db.execute(select(Trade).where(Trade.address == address)).scalars().all()
    open_qty = 0.0
    for tr in trades:
        if tr.qty is None:
            continue
        if tr.side == Side.BUY:
            open_qty += float(tr.qty)
        elif tr.side == Side.SELL:
            open_qty -= float(tr.qty)
    return max(0.0, open_qty)


# -----------------------------------------------------------------------------
# Commands
# -----------------------------------------------------------------------------
def buy(
        db: Session,
        symbol: str,
        chain: str,
        address: str,
        qty: float,
        price: float,
        stop: float,
        tp1: float,
        tp2: float,
        fee: float,
        status: Status,
) -> Trade:
    """
    Register a BUY trade for a **new lifecycle**:

    - DCA is forbidden. If an active position exists, the BUY is rejected.
    - Snapshot fields (qty, entry, tp1, tp2, stop) are immutable per lifecycle.
      A re-entry (after CLOSED) **always** creates a NEW Position row.
    - Cooldown is enforced between lifecycles.
    """
    if float(price) <= 0.0:
        raise ValueError("BUY rejected: price must be > 0")

    # Enforce "no DCA" + cooldown rules
    _cooldown_guard(db, address)

    # Create the BUY trade
    trade = Trade(
        side=Side.BUY,
        symbol=symbol,
        chain=chain,
        price=price,
        qty=qty,
        fee=fee,
        status=status,
        address=address,
    )
    db.add(trade)

    # Always create a fresh snapshot row for the lifecycle
    position = Position(
        symbol=symbol,
        chain=chain,
        address=address,
        qty=qty,     # snapshot at open
        entry=price, # snapshot at open
        tp1=tp1,
        tp2=tp2,
        stop=stop,
        phase=Phase.OPEN,
    )
    db.add(position)

    log.info(
        "BUY created new position snapshot — symbol=%s address=%s qty=%s entry=%s tp1=%s tp2=%s stop=%s",
        symbol,
        address,
        qty,
        price,
        tp1,
        tp2,
        stop,
    )
    log.debug("Snapshot immutables locked for lifecycle — address=%s", address)

    db.commit()
    db.refresh(trade)
    return trade


def _fifo_realized_for_sell(
        db: Session,
        address: str,
        sell_qty: float,
        sell_price: float,
        fee: float,
) -> float:
    """
    Compute realized PnL for a SELL using FIFO lots built from prior trades of the same address.

    Fees handling:
        - Buy fees are allocated per-unit and subtracted when a lot is consumed.
        - The current sell fee is distributed per-unit across the sold quantity and subtracted.

    In normal conditions, an oversell is prevented by sell(); we additionally keep a
    defensive safeguard here.
    """
    sell_qty = float(sell_qty)
    sell_price = float(sell_price)
    fee = float(fee or 0.0)

    if sell_qty <= 0.0 or sell_price <= 0.0:
        return 0.0 - fee

    prior_trades = db.execute(
        select(Trade).where(Trade.address == address).order_by(Trade.created_at.asc(), Trade.id.asc())
    ).scalars().all()

    lots: Deque[Tuple[float, float, float]] = deque()  # (qty, price, buy_fee_per_unit)

    for tr in prior_trades:
        if tr.qty is None or tr.price is None:
            continue
        qty = float(tr.qty)
        px = float(tr.price)
        tr_fee = float(tr.fee or 0.0)
        if qty <= 0.0 or px <= 0.0:
            continue
        if tr.side == Side.BUY:
            fee_per_unit = tr_fee / qty if qty > 0.0 else 0.0
            lots.append((qty, px, fee_per_unit))
        elif tr.side == Side.SELL:
            remaining = qty
            while remaining > 1e-12 and lots:
                lot_qty, lot_px, fee_per_unit = lots[0]
                matched = min(remaining, lot_qty)
                lot_qty -= matched
                remaining -= matched
                if lot_qty <= 1e-12:
                    lots.popleft()
                else:
                    lots[0] = (lot_qty, lot_px, fee_per_unit)

    remaining_to_sell = float(sell_qty)
    realized = 0.0
    sell_fee_per_unit = fee / sell_qty if sell_qty > 0.0 else 0.0

    while remaining_to_sell > 1e-12 and lots:
        lot_qty, lot_px, buy_fee_per_unit = lots[0]
        matched = min(remaining_to_sell, lot_qty)

        realized += (sell_price - lot_px) * matched
        realized -= buy_fee_per_unit * matched
        realized -= sell_fee_per_unit * matched

        lot_qty -= matched
        remaining_to_sell -= matched
        if lot_qty <= 1e-12:
            lots.popleft()
        else:
            lots[0] = (lot_qty, lot_px, buy_fee_per_unit)

    if remaining_to_sell > 1e-12:
        log.warning(
            "SELL qty exceeds available lots — address=%s residual=%s; ignoring residual for realized PnL.",
            address,
            remaining_to_sell,
        )

    return round(realized, 8)


def sell(
        db: Session,
        symbol: str,
        chain: str,
        address: str,
        qty: float,
        price: float,
        fee: float,
        status: Status,
        phase: Phase,
) -> Trade:
    """
    Register a SELL trade, compute realized PnL with FIFO lots,
    and update the Position **phase only** (snapshot immutables are never touched).

    Business rules:
        - Price must be > 0 (guards wrong data that could lead to 0$ autosells).
        - No oversell: the sold quantity cannot exceed the currently open quantity.
        - When the open quantity becomes zero, the position is CLOSED and a cooldown lock is armed.
    """
    if float(price) <= 0.0:
        raise ValueError("SELL rejected: price must be > 0")

    # Use the ACTIVE position only (never pick a CLOSED row by accident)
    position = _get_active_position_by_address(db, address)

    # Oversell guard (strict)
    open_qty_before = _compute_open_quantity_from_trades(db, address)
    sell_qty = float(qty)
    if sell_qty > open_qty_before + 1e-9:
        log.error(
            "SELL exceeds open quantity — address=%s sell_qty=%.12f open_qty=%.12f",
            address,
            sell_qty,
            open_qty_before,
        )
        raise ValueError("SELL rejected: quantity exceeds currently open quantity")

    if position is not None:
        realized = _fifo_realized_for_sell(
            db=db,
            address=address,
            sell_qty=sell_qty,
            sell_price=float(price),
            fee=float(fee or 0.0),
        )
    else:
        realized = 0.0 - float(fee or 0.0)
        log.warning("SELL with no active position snapshot — address=%s; realized set to -fee only.", address)

    trade = Trade(
        side=Side.SELL,
        symbol=symbol,
        chain=chain,
        price=price,
        qty=qty,
        fee=fee,
        status=status,
        address=address,
        pnl=realized,
    )
    db.add(trade)

    # Phase update based on open quantity AFTER this sell is accounted for
    if position is not None:
        open_qty_after = max(0.0, open_qty_before - sell_qty)
        if open_qty_after <= 1e-12:
            position.phase = phase  # expected CLOSED on full exit
            position.closed_at = _ensure_aware_datetime(timezone_now())

            # Arm cooldown (re-entry lock)
            cd = _get_cooldown_seconds()
            eligible_at = position.closed_at + timedelta(seconds=cd)
            _set_reentry_lock(address, eligible_at)
            log.info("Position CLOSED — address=%s; re-entry locked until %s", address, eligible_at)
        else:
            position.phase = Phase.PARTIAL

        log.info(
            "SELL updated position phase — address=%s phase=%s (open_qty_after=%s)",
            address,
            position.phase,
            open_qty_after,
        )
        log.debug(
            "Lifecycle status after SELL — symbol=%s address=%s qty_sold=%s price=%s realized=%s",
            symbol,
            address,
            qty,
            price,
            realized,
        )

    db.commit()
    db.refresh(trade)
    return trade


def get_recent_trades(db: Session, limit: int = 100) -> List[Trade]:
    """Return the most recent trades (descending by time and id)."""
    stmt = select(Trade).order_by(Trade.created_at.desc(), Trade.id.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())


def get_all_trades(db: Session) -> List[Trade]:
    """Return all trades in ascending time order (useful for FIFO computations)."""
    stmt = select(Trade).order_by(Trade.created_at.asc(), Trade.id.asc())
    return list(db.execute(stmt).scalars().all())
