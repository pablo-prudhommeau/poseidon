from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.logging.logger import get_logger
from src.persistence.models import Position, PortfolioSnapshot, Trade
from src.persistence.serializers import serialize_position

log = get_logger(__name__)


def _infer_active_phase(position: Position) -> str:
    """
    Infer the correct active phase for an open position (non-STALED):
    - if TP1 déjà exécuté (tp1 = 0.0) et qty > 0 => PARTIAL
    - sinon => OPEN
    - (si plus ouvert / qty 0 => CLOSED, mais on ne devrait pas passer ici)
    """
    if not position.is_open or float(position.qty or 0.0) <= 0.0:
        return "CLOSED"
    return "PARTIAL" if float(position.tp1 or 0.0) == 0.0 else "OPEN"


def _set_phase_if_changed(db: Session, position: Position, new_phase: str) -> None:
    """Idempotent phase setter with concise logging."""
    old = (position.phase or "").upper()
    new = new_phase.upper()
    if old != new:
        position.phase = new
        db.commit()
        log.info("[PHASE] %s (%s) — %s -> %s",
                 position.symbol, (position.address or "")[-6:], old or "-", new)


def get_open_positions(db: Session) -> List[Position]:
    """Return all open positions, newest first."""
    stmt = (
        select(Position)
        .where(Position.is_open == True)  # noqa: E712 (keep explicit truthy check)
        .order_by(Position.opened_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


def get_latest_portfolio(db: Session, *, create_if_missing: bool = False) -> Optional[PortfolioSnapshot]:
    """Return the latest portfolio snapshot; optionally create an initial one."""
    stmt = (
        select(PortfolioSnapshot)
        .order_by(PortfolioSnapshot.created_at.desc(), PortfolioSnapshot.id.desc())
        .limit(1)
    )
    snapshot = db.execute(stmt).scalars().first()
    if snapshot is None and create_if_missing:
        snapshot = ensure_initial_cash(db)
    return snapshot


def get_recent_trades(db: Session, limit: int = 100) -> List[Trade]:
    """Return the most recent trades (descending by time and id)."""
    stmt = (
        select(Trade)
        .order_by(Trade.created_at.desc(), Trade.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def get_all_trades(db: Session) -> List[Trade]:
    """Return all trades in ascending time order (useful for FIFO computations)."""
    stmt = select(Trade).order_by(Trade.created_at.asc(), Trade.id.asc())
    return list(db.execute(stmt).scalars().all())


def ensure_initial_cash(db: Session) -> PortfolioSnapshot:
    """Create an initial portfolio snapshot using PAPER_STARTING_CASH."""
    starting_cash = float(settings.PAPER_STARTING_CASH)
    snapshot = PortfolioSnapshot(equity=starting_cash, cash=starting_cash, holdings=0.0)
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def reset_paper(db: Session) -> None:
    """Delete all trades, positions, and snapshots (paper reset)."""
    db.execute(delete(Trade))
    db.execute(delete(Position))
    db.execute(delete(PortfolioSnapshot))
    db.commit()


def get_open_addresses(db: Session) -> List[str]:
    """Return lowercased addresses for all open positions (empty strings excluded)."""
    rows = db.execute(
        select(Position.address).where(Position.is_open == True)  # noqa: E712
    ).scalars().all()
    return [addr for addr in rows if addr]


def serialize_positions_with_prices_by_address(db: Session, address_price: Dict[str, float]) -> List[dict]:
    """Serialize open positions and attach a live last_price by address when available."""
    positions = get_open_positions(db)
    payload: List[dict] = []
    for position in positions:
        last_price = None
        if position.address:
            last_price = address_price.get((position.address or "").lower())
        payload.append(serialize_position(position, last_price))
    return payload


def snapshot_portfolio(db: Session, *, equity: float, cash: float, holdings: float) -> PortfolioSnapshot:
    """Persist a portfolio snapshot with values already computed by the orchestrator."""
    snapshot = PortfolioSnapshot(
        equity=float(equity or 0.0),
        cash=float(cash or 0.0),
        holdings=float(holdings or 0.0),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def record_trade(
        db: Session,
        *,
        side: str,
        symbol: str,
        chain: str,
        address: str,
        qty: float,
        price: float,
        fee: float = 0.0,
        status: str = "PAPER",
) -> Trade:
    """Insert a trade and update the related position state (entry/qty/phase)."""
    side_upper = side.upper()
    if side_upper not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")

    trade = Trade(
        side=side_upper,
        symbol=symbol,
        chain=chain,
        price=float(price),
        qty=float(qty),
        fee=float(fee or 0.0),
        status=status,
        address=address or "",
    )
    db.add(trade)

    position = db.execute(select(Position).where(Position.address == address)).scalars().first()

    if side_upper == "BUY":
        if position is None:
            # New position
            position = Position(
                symbol=symbol,
                chain=chain,
                address=address or "",
                qty=float(qty),
                entry=float(price),
                tp1=0.0,
                tp2=0.0,
                stop=0.0,
                phase="OPEN",
                is_open=True,
            )
            tp1_default, tp2_default, stop_default = compute_default_thresholds(price)
            position.tp1 = tp1_default
            position.tp2 = tp2_default
            position.stop = stop_default
            db.add(position)
        else:
            # Average up/down on existing position
            total_qty = float(position.qty or 0.0) + float(qty)
            avg_entry = 0.0 if total_qty <= 0 else (
                    ((float(position.entry or 0.0) * float(position.qty or 0.0)) + (
                            float(price) * float(qty))) / total_qty
            )
            position.qty = total_qty
            position.entry = avg_entry
            position.phase = "OPEN" if total_qty > 0 else "CLOSED"
            position.is_open = total_qty > 0

            # Set missing thresholds if needed
            if (float(position.tp1 or 0.0) <= 0.0) or (float(position.tp2 or 0.0) <= 0.0) or (
                    float(position.stop or 0.0) <= 0.0):
                tp1_default, tp2_default, stop_default = compute_default_thresholds(avg_entry)
                if float(position.tp1 or 0.0) <= 0.0:
                    position.tp1 = tp1_default
                if float(position.tp2 or 0.0) <= 0.0:
                    position.tp2 = tp2_default
                if float(position.stop or 0.0) <= 0.0:
                    position.stop = stop_default
    else:
        # SELL
        realized = 0.0
        if position is not None:
            sell_qty = min(float(qty), float(position.qty or 0.0))
            cost_basis = float(position.entry or 0.0) * sell_qty
            proceeds = float(price) * sell_qty
            realized = proceeds - cost_basis - float(fee or 0.0)

            position.qty = float(position.qty or 0.0) - sell_qty
            if position.qty <= 1e-12:
                position.qty = 0.0
                position.is_open = False
                position.phase = "CLOSED"
                position.closed_at = datetime.utcnow()
        else:
            # No position found; consider full amount against zero entry
            realized = (float(price) - 0.0) * float(qty) - float(fee or 0.0)

        trade.pnl = realized

    db.commit()
    db.refresh(trade)

    # IMPORTANT: no snapshot write here; snapshots are handled by orchestrator/loops.
    return trade


def compute_default_thresholds(entry: float) -> Tuple[float, float, float]:
    """Compute default tp1/tp2/stop prices from an entry price and settings."""
    entry_f = float(entry or 0.0)
    tp1 = entry_f * (1.0 + float(settings.TRENDING_TP1_FRACTION))
    tp2 = entry_f * (1.0 + float(settings.TRENDING_TP2_FRACTION))
    stop = entry_f * (1.0 - float(settings.TRENDING_STOP_FRACTION))
    return tp1, tp2, stop


def check_thresholds_and_autosell(db: Session, *, symbol: str, last_price: float) -> List[Trade]:
    """Autosell positions for a symbol based on tp1/tp2/stop thresholds and last price."""
    created: List[Trade] = []
    last_price_f = float(last_price or 0.0)
    if last_price_f <= 0.0:
        return created

    positions = db.execute(
        select(Position).where(Position.is_open == True, Position.symbol == symbol)  # noqa: E712
    ).scalars().all()

    for position in positions:
        qty = float(position.qty or 0.0)
        if qty <= 0.0:
            continue

        tp1 = float(position.tp1 or 0.0)
        tp2 = float(position.tp2 or 0.0)
        stop = float(position.stop or 0.0)

        # Stop-loss → full exit
        if stop > 0.0 and last_price_f <= stop:
            trade = record_trade(
                db,
                side="SELL",
                symbol=symbol,
                chain=position.chain,
                address=position.address,
                qty=qty,
                price=last_price_f,
                status="PAPER",
            )
            position.tp1 = 0.0
            position.tp2 = 0.0
            position.stop = 0.0
            created.append(trade)
            continue

        # TP2 → full exit
        if tp2 > 0.0 and last_price_f >= tp2 and qty > 0.0:
            trade = record_trade(
                db,
                side="SELL",
                symbol=symbol,
                chain=position.chain,
                address=position.address,
                qty=qty,
                price=last_price_f,
                status="PAPER",
            )
            position.tp1 = 0.0
            position.tp2 = 0.0
            position.stop = 0.0
            created.append(trade)
            continue

        # TP1 → partial exit (fraction defined by TRENDING_TAKE_PROFIT_TP1_FRACTION)
        if tp1 > 0.0 and last_price_f >= tp1 and qty > 0.0:
            tp1_sell_fraction = max(0.0, min(1.0, float(settings.TRENDING_TAKE_PROFIT_TP1_FRACTION)))
            part = max(0.0, min(qty, qty * tp1_sell_fraction))
            if part > 0.0:
                trade = record_trade(
                    db,
                    side="SELL",
                    symbol=symbol,
                    chain=position.chain,
                    address=position.address,
                    qty=part,
                    price=last_price_f,
                    status="PAPER",
                )
                created.append(trade)
                position.tp1 = 0.0

    if created:
        db.commit()
    return created


def check_thresholds_and_autosell_for_address(db: Session, *, address: str, last_price: float) -> List[Trade]:
    """Autosell for a specific address based on thresholds and last price."""
    created: List[Trade] = []
    if not address or float(last_price or 0.0) <= 0.0:
        return created

    position = db.execute(
        select(Position).where(Position.address == address, Position.is_open == True)  # noqa: E712
    ).scalars().first()
    if not position:
        return created

    qty = float(position.qty or 0.0)
    if qty <= 0.0:
        return created

    tp1 = float(position.tp1 or 0.0)
    tp2 = float(position.tp2 or 0.0)
    stop = float(position.stop or 0.0)
    last_price_f = float(last_price)

    # Stop-loss → full exit
    if stop > 0.0 and last_price_f <= stop:
        trade = record_trade(
            db,
            side="SELL",
            symbol=position.symbol,
            chain=position.chain,
            address=position.address,
            qty=qty,
            price=last_price_f,
            status="PAPER",
        )
        position.tp1 = 0.0
        position.tp2 = 0.0
        position.stop = 0.0
        created.append(trade)
        db.commit()
        return created

    # TP2 → full exit
    if tp2 > 0.0 and last_price_f >= tp2 and qty > 0.0:
        trade = record_trade(
            db,
            side="SELL",
            symbol=position.symbol,
            chain=position.chain,
            address=position.address,
            qty=qty,
            price=last_price_f,
            status="PAPER",
        )
        position.tp1 = 0.0
        position.tp2 = 0.0
        position.stop = 0.0
        created.append(trade)
        db.commit()
        return created

    # TP1 → partial exit (fraction defined by TRENDING_TAKE_PROFIT_TP1_FRACTION)
    if tp1 > 0.0 and last_price_f >= tp1 and qty > 0.0:
        tp1_sell_fraction = max(0.0, min(1.0, float(settings.TRENDING_TAKE_PROFIT_TP1_FRACTION)))
        part = max(0.0, min(qty, qty * tp1_sell_fraction))
        if part > 0.0:
            trade = record_trade(
                db,
                side="SELL",
                symbol=position.symbol,
                chain=position.chain,
                address=position.address,
                qty=part,
                price=last_price_f,
                status="PAPER",
            )
            created.append(trade)
            position.tp1 = 0.0
            db.commit()

    return created


def equity_curve(db: Session, points: int = 60) -> List[Tuple[int, float]]:
    """Return a simplified equity curve as (timestamp, equity) points."""
    snapshots = list(
        db.execute(
            select(PortfolioSnapshot).order_by(PortfolioSnapshot.created_at.asc())
        ).scalars().all()
    )
    if not snapshots:
        return []

    if len(snapshots) > points:
        step = max(1, len(snapshots) // points)
        snapshots = snapshots[::step]

    out: List[Tuple[int, float]] = []
    for s in snapshots:
        out.append((int(s.created_at.timestamp()), float(s.equity or 0.0)))
    return out
