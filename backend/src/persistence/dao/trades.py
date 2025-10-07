from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from typing import List, Deque, Tuple, Dict, Optional

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.core.utils import timezone_now
from src.core.telemetry import TelemetryService
from src.logging.logger import get_logger
from src.persistence.models import Position, Trade, Phase, Status, Side

log = get_logger(__name__)

# -----------------------------------------------------------------------------
# Re-entry lock (in-memory). Key: address -> eligible_at (UTC aware)
# -----------------------------------------------------------------------------
_REENTRY_LOCK: Dict[str, datetime] = {}


def _get_cooldown_seconds() -> int:
    """Return the re-entry cooldown in seconds (fallback kept for legacy key)."""
    return int(getattr(settings, "REENTRY_COOLDOWN_SECONDS",
                       getattr(settings, "COOLDOWN_SECONDS", 60)))


def _cleanup_reentry_lock(now: datetime) -> None:
    """Remove stale in-memory locks."""
    stale = [addr for addr, eligible_at in _REENTRY_LOCK.items()
             if eligible_at is not None and now >= eligible_at]
    for addr in stale:
        _REENTRY_LOCK.pop(addr, None)


def _set_reentry_lock(address: str, eligible_at: datetime) -> None:
    """Arm a temporary in-memory re-entry lock for the address."""
    _REENTRY_LOCK[address] = eligible_at


def _get_reentry_eligible_at(address: str) -> Optional[datetime]:
    """Return the in-memory re-entry eligibility for the address, if any."""
    return _REENTRY_LOCK.get(address)


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
    """Return the most recently CLOSED position for cooldown enforcement."""
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

    - Absolutely forbid DCA (any ACTIVE position).
    - When there is no active position, enforce re-entry cooldown based on:
      last CLOSED position and the in-memory lock.
    """
    now: datetime = timezone_now()
    _cleanup_reentry_lock(now)
    cooldown_seconds = _get_cooldown_seconds()

    active = _get_active_position_by_address(db, address)
    if active is not None:
        log.info("[SKIP][DCA_DISABLED] address=%s phase=%s — active position exists",
                 address, active.phase)
        raise RuntimeError("BUY rejected: a position is already OPEN or PARTIAL for this address.")

    last_closed = _get_last_closed_position_for_cooldown(db, address)
    eligible_from_closed: Optional[datetime] = None
    if last_closed and last_closed.closed_at:
        eligible_from_closed = last_closed.closed_at + timedelta(seconds=cooldown_seconds)

    eligible_from_lock = _get_reentry_eligible_at(address)
    candidates: List[datetime] = [t for t in (eligible_from_closed, eligible_from_lock) if t is not None]
    eligible_at: Optional[datetime] = max(candidates) if candidates else None

    if eligible_at is not None and now < eligible_at.astimezone():
        remaining = (eligible_at - now).total_seconds()
        log.info("[SKIP][COOLDOWN] address=%s next=%s (remaining=%.1fs)",
                 address, eligible_at, remaining)
        raise RuntimeError(f"BUY rejected by cooldown; next eligible at {eligible_at.isoformat()}")


# -----------------------------------------------------------------------------
# FIFO helpers
# -----------------------------------------------------------------------------
def _fifo_realized_and_basis_for_sell(
        db: Session,
        address: str,
        sell_qty: float,
        sell_price: float,
        fee: float,
) -> Tuple[float, float]:
    """
    Compute (realized_usd, cost_basis_usd) for a SELL using FIFO lots.

    - Buy fees are allocated per-unit into cost basis.
    - Current sell fee is distributed per-unit and subtracted from proceeds.

    Returns:
        realized_usd: proceeds - cost (already net of fees)
        cost_basis_usd: cost of the sold chunk including buy fees
    """
    sell_qty = float(sell_qty)
    sell_price = float(sell_price)
    fee = float(fee or 0.0)

    if sell_qty <= 0.0 or sell_price <= 0.0:
        return (0.0 - fee, 0.0)

    prior_trades = db.execute(
        select(Trade)
        .where(Trade.address == address)
        .order_by(Trade.created_at.asc(), Trade.id.asc())
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
    cost_basis = 0.0
    sell_fee_per_unit = fee / sell_qty if sell_qty > 0.0 else 0.0

    while remaining_to_sell > 1e-12 and lots:
        lot_qty, lot_px, buy_fee_per_unit = lots[0]
        matched = min(remaining_to_sell, lot_qty)

        proceeds = (sell_price - sell_fee_per_unit) * matched
        cost = (lot_px + buy_fee_per_unit) * matched

        realized += (proceeds - cost)
        cost_basis += cost

        lot_qty -= matched
        remaining_to_sell -= matched
        if lot_qty <= 1e-12:
            lots.popleft()
        else:
            lots[0] = (lot_qty, lot_px, buy_fee_per_unit)

    if remaining_to_sell > 1e-12:
        log.warning("SELL qty exceeds available lots — address=%s residual=%s",
                    address, remaining_to_sell)

    return (round(realized, 8), round(cost_basis, 8))


def _compute_open_quantity_from_trades(db: Session, address: str) -> float:
    """Return current open quantity for an address as sum(BUY) - sum(SELL)."""
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

    - DCA is forbidden.
    - Snapshot fields (qty, entry, tp1, tp2, stop) are immutable per lifecycle.
    - Cooldown is enforced between lifecycles.
    """
    if float(price) <= 0.0:
        raise ValueError("BUY rejected: price must be > 0")

    _cooldown_guard(db, address)

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

    position = Position(
        symbol=symbol,
        chain=chain,
        address=address,
        qty=qty,      # snapshot at open
        entry=price,  # snapshot at open
        tp1=tp1,
        tp2=tp2,
        stop=stop,
        phase=Phase.OPEN,
    )
    db.add(position)

    log.info("BUY snapshot — %s %s qty=%s entry=%s tp1=%s tp2=%s stop=%s",
             symbol, address, qty, price, tp1, tp2, stop)
    db.commit()
    db.refresh(trade)
    return trade


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
    and update the Position **phase only**.

    Semantics:
      - On PARTIAL (TP1): we **link an outcome** snapshot with exit_reason=TP1
        using the realized PnL for the sold chunk and its FIFO cost basis.
      - On full CLOSE: we link a final outcome with reason inferred (TP2/SL/TP1/MANUAL)
        and aggregate PnL over the whole lifecycle.
    """
    if float(price) <= 0.0:
        raise ValueError("SELL rejected: price must be > 0")

    position = _get_active_position_by_address(db, address)

    open_qty_before = _compute_open_quantity_from_trades(db, address)
    sell_qty = float(qty)
    if sell_qty > open_qty_before + 1e-9:
        log.error("SELL exceeds open quantity — address=%s sell_qty=%.12f open_qty=%.12f",
                  address, sell_qty, open_qty_before)
        raise ValueError("SELL rejected: quantity exceeds currently open quantity")

    # Realized and basis for this SELL (used both for trade.pnl and TP1 outcome)
    realized_this_sell, basis_this_sell = _fifo_realized_and_basis_for_sell(
        db=db,
        address=address,
        sell_qty=sell_qty,
        sell_price=float(price),
        fee=float(fee or 0.0),
    )

    trade = Trade(
        side=Side.SELL,
        symbol=symbol,
        chain=chain,
        price=price,
        qty=qty,
        fee=fee,
        status=status,
        address=address,
        pnl=realized_this_sell,
    )
    db.add(trade)

    # Phase update after accounting for the SELL
    closed_now = False
    if position is not None:
        open_qty_after = max(0.0, open_qty_before - sell_qty)
        if open_qty_after <= 1e-12:
            position.phase = phase  # expected CLOSED on full exit
            position.closed_at = timezone_now()
            closed_now = True

            # Arm cooldown (re-entry lock)
            cd = _get_cooldown_seconds()
            eligible_at = position.closed_at + timedelta(seconds=cd)
            _set_reentry_lock(address, eligible_at)
            log.info("Position CLOSED — address=%s; re-entry locked until %s", address, eligible_at)
        else:
            position.phase = Phase.PARTIAL

        log.info("SELL updated position phase — address=%s phase=%s (open_qty_after=%s)",
                 address, position.phase, open_qty_after)
        log.debug("Lifecycle after SELL — %s %s qty=%s px=%s realized=%s",
                  symbol, address, qty, price, realized_this_sell)

    db.commit()
    db.refresh(trade)

    # ---------------- Outcome linkage ----------------
    try:
        if position is not None and closed_now:
            # Final outcome on full close: aggregate over lifecycle
            start = position.opened_at
            life_trades: List[Trade] = list(
                db.execute(
                    select(Trade)
                    .where(Trade.address == address, Trade.created_at >= start)
                    .order_by(Trade.created_at.asc(), Trade.id.asc())
                ).scalars().all()
            )
            invested = sum(float(t.qty or 0) * float(t.price or 0) + float(t.fee or 0)
                           for t in life_trades if t.side == Side.BUY)
            realized_total = sum(float(t.pnl or 0.0)
                                 for t in life_trades if t.side == Side.SELL)

            pnl_usd = round(realized_total, 8)
            pnl_pct = round((pnl_usd / invested) * 100, 6) if invested > 0 else 0.0
            holding_minutes = max(
                0.0,
                (position.closed_at - position.opened_at).total_seconds() / 60.0
                if (position.closed_at and position.opened_at) else 0.0
            )

            # Reason at final close
            eps = 1e-12
            reason = "MANUAL"
            if float(price) <= float(position.stop or 0) + eps:
                reason = "SL"
            elif float(price) >= float(position.tp2 or 0) - eps:
                reason = "TP2"
            elif float(price) >= float(position.tp1 or 0) - eps:
                reason = "TP1"

            TelemetryService.link_trade_outcome(
                address=address,
                trade_id=trade.id,
                closed_at=position.closed_at,
                pnl_pct=pnl_pct,
                pnl_usd=pnl_usd,
                holding_minutes=holding_minutes,
                was_profit=pnl_usd > 0,
                exit_reason=reason,
            )

        elif position is not None and position.phase == Phase.PARTIAL:
            # TP1 partial snapshot: link an intermediate outcome for analytics
            # Use the **chunk**-level realized and basis from this SELL.
            pnl_usd_chunk = float(trade.pnl or 0.0)
            basis_usd_chunk = float(basis_this_sell or 0.0)
            pnl_pct_chunk = (pnl_usd_chunk / basis_usd_chunk * 100.0) if basis_usd_chunk > 0 else 0.0
            holding_minutes_chunk = max(
                0.0,
                (trade.created_at - position.opened_at).total_seconds() / 60.0
                if (trade.created_at and position.opened_at) else 0.0
            )

            TelemetryService.link_trade_outcome(
                address=address,
                trade_id=trade.id,
                closed_at=trade.created_at,  # snapshot time for TP1 partial
                pnl_pct=round(pnl_pct_chunk, 6),
                pnl_usd=round(pnl_usd_chunk, 8),
                holding_minutes=round(holding_minutes_chunk, 4),
                was_profit=pnl_usd_chunk > 0,
                exit_reason="TP1",
            )
    except Exception as exc:
        # Telemetry must never block trading flow
        log.exception("Failed to link trade outcome — address=%s trade=%s: %s", address, trade.id, exc)

    return trade


def get_recent_trades(db: Session, limit: int = 100) -> List[Trade]:
    """Return the most recent trades (descending by time and id)."""
    stmt = select(Trade).order_by(Trade.created_at.desc(), Trade.id.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())


def get_all_trades(db: Session) -> List[Trade]:
    """Return all trades in ascending time order (useful for FIFO computations)."""
    stmt = select(Trade).order_by(Trade.created_at.asc(), Trade.id.asc())
    return list(db.execute(stmt).scalars().all())
