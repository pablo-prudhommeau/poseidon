from __future__ import annotations

from collections import deque
from datetime import timedelta
from typing import List, Deque, Tuple, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.core.utils import timezone_now
from src.logging.logger import get_logger
from src.persistence.models import Position, Trade, Phase, Status, Side

log = get_logger(__name__)

# -----------------------------------------------------------------------------
# Re-entry lock (in-memory). Clé: address -> eligible_at (datetime)
# -----------------------------------------------------------------------------
_REENTRY_LOCK: Dict[str, object] = {}

def _get_cooldown_seconds() -> int:
    return int(getattr(settings, "REENTRY_COOLDOWN_SECONDS",
                       getattr(settings, "COOLDOWN_SECONDS", 60)))

def _cleanup_reentry_lock(now) -> None:
    """Remove stale locks (best-effort; O(n) on addresses count)."""
    stale = [addr for addr, eligible_at in _REENTRY_LOCK.items() if eligible_at is not None and now >= eligible_at]
    for addr in stale:
        _REENTRY_LOCK.pop(addr, None)

def _set_reentry_lock(address: str, eligible_at) -> None:
    _REENTRY_LOCK[address] = eligible_at

def _get_reentry_eligible_at(address: str):
    return _REENTRY_LOCK.get(address)

def _cooldown_guard(address: str, position: Optional[Position]) -> None:
    """
    Enforce cooldown only when la dernière position a été fermée récemment.
    - Si position inexistante -> pas de cooldown (1er BUY)
    - Si position phase OPEN/PARTIAL -> pas de cooldown (DCA autorisé)
    - Si position CLOSED -> cooldown (via closed_at et/ou lock en mémoire)
    """
    now = timezone_now()
    _cleanup_reentry_lock(now)
    cd = _get_cooldown_seconds()

    if position is None:
        return

    if position.phase in (Phase.OPEN, Phase.PARTIAL):
        # DCA: autorisé
        return

    # Phase CLOSED -> regarder closed_at et lock en mémoire
    eligible_from_closed_at = None
    if position.closed_at:
        eligible_from_closed_at = position.closed_at + timedelta(seconds=cd)

    eligible_from_lock = _get_reentry_eligible_at(address)
    # Choisir l'eligible_at la plus tardive
    eligible_candidates = [t for t in (eligible_from_closed_at, eligible_from_lock) if t is not None]
    eligible_at = max(eligible_candidates).astimezone() if eligible_candidates else None

    if eligible_at is not None and now < eligible_at:
        # Rejet explicite pour empêcher la réouverture trop tôt
        delay = (eligible_at - now).total_seconds()
        log.info("[SKIP][COOLDOWN] address=%s next=%s (remaining=%.1fs)", address, eligible_at, delay)
        raise RuntimeError(f"BUY rejected by cooldown; next eligible at {eligible_at.isoformat()}")

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _compute_open_quantity_from_trades(db: Session, address: str) -> float:
    """
    Return current open quantity for an address as sum(BUY) - sum(SELL).
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
    Register a BUY trade. If a Position exists, **do not mutate** its snapshot fields
    (qty, entry, tp1, tp2, stop). Only its phase can change (e.g., from CLOSED to OPEN).

    Ajouts:
      - Cooldown basé sur la dernière clôture + re-entry lock en mémoire.
      - Logs explicites si rejeté par cooldown.
    """
    if float(price) <= 0.0:
        raise ValueError("BUY rejected: price must be > 0")

    # Vérifier la règle de re-entry (cooldown)
    position = db.execute(select(Position).where(Position.address == address)).scalars().first()
    _cooldown_guard(address, position)

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

    if position is None:
        # First BUY creates an immutable snapshot (photo at open)
        position = Position(
            symbol=symbol,
            chain=chain,
            address=address,
            qty=qty,            # snapshot at open (will never be mutated)
            entry=price,        # snapshot at open (net fees visibles via PnL, pas ici)
            tp1=tp1,
            tp2=tp2,
            stop=stop,
            phase=Phase.OPEN
        )
        db.add(position)
        log.info("BUY created position snapshot — symbol=%s address=%s qty=%s entry=%s", symbol, address, qty, price)
    else:
        # Snapshot is immutable. We only ensure the phase reflects the fact the address is not fully closed.
        position.phase = Phase.OPEN
        log.info("BUY on existing position — snapshot kept immutable; phase set to OPEN (address=%s)", address)

    db.commit()
    db.refresh(trade)
    return trade


def _fifo_realized_for_sell(
        db: Session,
        address: str,
        sell_qty: float,
        sell_price: float,
        fee: float
) -> float:
    """
    Compute realized PnL for a SELL using FIFO lots built from prior trades of the same address.

    Fees handling:
        - Buy fees are allocated per-unit and subtracted when a lot is consumed.
        - The **current** sell fee is distributed per-unit across the sold quantity and subtracted.

    En conditions normales, un oversell est empêché plus haut (sell()).
    On garde toutefois une protection défensive (warning + ignore du résiduel).
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
            address, remaining_to_sell
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
        phase: Phase
) -> Trade:
    """
    Register a SELL trade, compute realized PnL using FIFO lots, and update the Position **phase only**.
    Snapshot fields (qty, entry, tp1, tp2, stop) remain untouched.

    Ajouts:
      - Blocage strict si la quantité vendue dépasse le restant ouvert (no oversell).
      - À la fermeture complète, on arme un re-entry lock (cooldown).
    """
    if float(price) <= 0.0:
        raise ValueError("SELL rejected: price must be > 0")

    position = db.execute(select(Position).where(Position.address == address)).scalars().first()

    # Contrôle d'oversell (strict)
    open_qty_before = _compute_open_quantity_from_trades(db, address)
    sell_qty = float(qty)
    if sell_qty > open_qty_before + 1e-9:
        log.error(
            "SELL exceeds open quantity — address=%s sell_qty=%.12f open_qty=%.12f",
            address, sell_qty, open_qty_before
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
        log.warning("SELL with no position snapshot — address=%s; realized set to -fee only.", address)

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
            position.phase = phase  # CLOSED or whatever was passed
            position.closed_at = timezone_now()

            # Armer le cooldown (re-entry lock)
            cd = _get_cooldown_seconds()
            eligible_at = position.closed_at + timedelta(seconds=cd)
            _set_reentry_lock(address, eligible_at)
            log.info("Position CLOSED — address=%s; re-entry locked until %s", address, eligible_at)
        else:
            position.phase = Phase.PARTIAL
        log.info(
            "SELL updated position phase — address=%s phase=%s (open_qty_after=%s)",
            address, position.phase, open_qty_after
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
