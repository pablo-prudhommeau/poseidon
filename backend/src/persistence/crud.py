# src/persistence/crud.py
from __future__ import annotations
from datetime import timedelta, datetime
from typing import Optional, Dict, List

from sqlalchemy import func, select, delete
from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.persistence.models import Position, PortfolioSnapshot, Trade
from src.persistence.serializers import serialize_position


# ----------------- Lectures simples -----------------

def get_open_positions(db: Session) -> list[Position]:
    stmt = select(Position).where(Position.is_open == True).order_by(Position.opened_at.desc())
    return list(db.execute(stmt).scalars().all())


def get_latest_portfolio(db: Session, *, create_if_missing: bool = False) -> Optional[PortfolioSnapshot]:
    stmt = select(PortfolioSnapshot).order_by(PortfolioSnapshot.created_at.desc(), PortfolioSnapshot.id.desc()).limit(1)
    snap = db.execute(stmt).scalars().first()
    if snap is None and create_if_missing:
        snap = ensure_initial_cash(db)
    return snap


def get_recent_trades(db: Session, limit: int = 100) -> list[Trade]:
    stmt = select(Trade).order_by(Trade.created_at.desc(), Trade.id.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())


def get_all_trades(db: Session) -> list[Trade]:
    """Tous les trades, triés par date asc (utile pour FIFO orchestrator)."""
    stmt = select(Trade).order_by(Trade.created_at.asc(), Trade.id.asc())
    return list(db.execute(stmt).scalars().all())


def ensure_initial_cash(db: Session) -> PortfolioSnapshot:
    start_cash = float(getattr(settings, "PAPER_STARTING_CASH", 10_000.0))
    snap = PortfolioSnapshot(equity=start_cash, cash=start_cash, holdings=0.0)
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap


def reset_paper(db: Session) -> None:
    db.execute(delete(Trade))
    db.execute(delete(Position))
    db.execute(delete(PortfolioSnapshot))
    db.commit()


def get_open_addresses(db: Session) -> List[str]:
    rows = db.execute(select(Position.address).where(Position.is_open == True)).scalars().all()
    return [r for r in rows if r]


def serialize_positions_with_prices_by_address(db: Session, address_price: Dict[str, float]) -> list[dict]:
    pos = get_open_positions(db)
    payload = []
    for p in pos:
        lp = None
        if p.address:
            lp = address_price.get((p.address or "").lower())
        payload.append(serialize_position(p, lp))
    return payload


# ----------------- Snapshot (écriture pure, PAS de calcul ici) -----------------

def snapshot_portfolio(db: Session, *, equity: float, cash: float, holdings: float) -> PortfolioSnapshot:
    """
    Ecrit un snapshot du portfolio avec les valeurs **déjà calculées** par l'orchestrator.
    """
    snap = PortfolioSnapshot(equity=float(equity or 0.0), cash=float(cash or 0.0), holdings=float(holdings or 0.0))
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap


# ----------------- Trades / Positions (sans calculs PnL globaux) -----------------

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
    side_u = side.upper()
    if side_u not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")

    t = Trade(side=side_u, symbol=symbol, chain=chain, price=float(price), qty=float(qty), fee=float(fee or 0.0), status=status, address=address or "")
    db.add(t)

    pos = db.execute(select(Position).where(Position.address == address)).scalars().first()
    if side_u == "BUY":
        if pos is None:
            pos = Position(
                symbol=symbol,
                chain=chain,
                address=address or "",
                qty=float(qty), entry=float(price),
                tp1=0.0, tp2=0.0, stop=0.0, phase="OPEN", is_open=True
            )
            d_tp1, d_tp2, d_stop = compute_default_thresholds(price)
            pos.tp1 = d_tp1
            pos.tp2 = d_tp2
            pos.stop = d_stop
            db.add(pos)
        else:
            total_qty = float(pos.qty or 0.0) + float(qty)
            avg = 0.0 if total_qty <= 0 else (
                    ((float(pos.entry or 0.0) * float(pos.qty or 0.0)) + (float(price) * float(qty))) / total_qty
            )
            pos.qty = total_qty
            pos.entry = avg
            pos.phase = "OPEN" if total_qty > 0 else "CLOSED"
            pos.is_open = total_qty > 0
            if (float(pos.tp1 or 0.0) <= 0.0) or (float(pos.tp2 or 0.0) <= 0.0) or (float(pos.stop or 0.0) <= 0.0):
                d_tp1, d_tp2, d_stop = compute_default_thresholds(avg)
                if float(pos.tp1 or 0.0) <= 0.0: pos.tp1 = d_tp1
                if float(pos.tp2 or 0.0) <= 0.0: pos.tp2 = d_tp2
                if float(pos.stop or 0.0) <= 0.0: pos.stop = d_stop
    else:  # SELL
        realized = 0.0
        if pos is not None:
            sell_qty = min(float(qty), float(pos.qty or 0.0))
            cost_basis = float(pos.entry or 0.0) * sell_qty
            proceeds = float(price) * sell_qty
            realized = proceeds - cost_basis - float(fee or 0.0)
            pos.qty = float(pos.qty or 0.0) - sell_qty
            if pos.qty <= 1e-12:
                pos.qty = 0.0
                pos.is_open = False
                pos.phase = "CLOSED"
                pos.closed_at = datetime.utcnow()
        else:
            realized = (float(price) - 0.0) * float(qty) - float(fee or 0.0)
        t.pnl = realized

    db.commit()
    db.refresh(t)

    # IMPORTANT: plus d'appel à snapshot_portfolio ici.
    return t


def compute_default_thresholds(entry: float) -> tuple[float, float, float]:
    entry = float(entry or 0.0)
    tp1 = entry * (1.0 + float(settings.TP1_PCT))
    tp2 = entry * (1.0 + float(settings.TP2_PCT))
    stop = entry * (1.0 - float(settings.STOP_PCT))
    return tp1, tp2, stop


def check_thresholds_and_autosell(db: Session, *, symbol: str, last_price: float) -> list[Trade]:
    created: list[Trade] = []
    last_price = float(last_price or 0.0)
    if last_price <= 0.0:
        return created

    positions = db.execute(
        select(Position).where(Position.is_open == True, Position.symbol == symbol)
    ).scalars().all()

    for p in positions:
        qty = float(p.qty or 0.0)
        if qty <= 0.0:
            continue

        tp1 = float(p.tp1 or 0.0)
        tp2 = float(p.tp2 or 0.0)
        stop = float(p.stop or 0.0)

        if stop > 0.0 and last_price <= stop:
            tr = record_trade(
                db, side="SELL", symbol=symbol, chain=p.chain, address=p.address, qty=qty, price=last_price, status="PAPER"
            )
            p.tp1 = 0.0; p.tp2 = 0.0; p.stop = 0.0
            created.append(tr)
            continue

        if tp2 > 0.0 and last_price >= tp2 and qty > 0.0:
            tr = record_trade(
                db, side="SELL", symbol=symbol, chain=p.chain, address=p.address, qty=qty, price=last_price, status="PAPER"
            )
            p.tp1 = 0.0; p.tp2 = 0.0; p.stop = 0.0
            created.append(tr)
            continue

        if tp1 > 0.0 and last_price >= tp1 and qty > 0.0:
            part = max(0.0, min(qty, qty * float(settings.TP1_PCT)))
            if part > 0.0:
                tr = record_trade(
                    db, side="SELL", symbol=symbol, chain=p.chain, address=p.address, qty=part, price=last_price, status="PAPER"
                )
                created.append(tr)
                p.tp1 = 0.0

    if created:
        db.commit()
    return created


def check_thresholds_and_autosell_for_address(db: Session, *, address: str, last_price: float) -> list[Trade]:
    created: list[Trade] = []
    if not address or float(last_price or 0.0) <= 0.0:
        return created

    p = db.execute(select(Position).where(Position.address == address, Position.is_open == True)).scalars().first()
    if not p:
        return created

    qty = float(p.qty or 0.0)
    if qty <= 0.0:
        return created

    tp1 = float(p.tp1 or 0.0)
    tp2 = float(p.tp2 or 0.0)
    stop = float(p.stop or 0.0)

    if stop > 0.0 and last_price <= stop:
        tr = record_trade(db, side="SELL", symbol=p.symbol, chain=p.chain, address=p.address, qty=qty, price=last_price, status="PAPER")
        p.tp1 = 0.0; p.tp2 = 0.0; p.stop = 0.0
        created.append(tr)
        db.commit()
        return created

    if tp2 > 0.0 and last_price >= tp2 and qty > 0.0:
        tr = record_trade(db, side="SELL", symbol=p.symbol, chain=p.chain, address=p.address, qty=qty, price=last_price, status="PAPER")
        p.tp1 = 0.0; p.tp2 = 0.0; p.stop = 0.0
        created.append(tr)
        db.commit()
        return created

    if tp1 > 0.0 and last_price >= tp1 and qty > 0.0:
        part = max(0.0, min(qty, qty * float(settings.TP1_PCT)))
        if part > 0.0:
            tr = record_trade(db, side="SELL", symbol=p.symbol, chain=p.chain, address=p.address, qty=part, price=last_price, status="PAPER")
            created.append(tr)
            p.tp1 = 0.0
            db.commit()

    return created


# Courbe d'équité = lecture simple des snapshots (on peut garder ici)
def equity_curve(db: Session, points: int = 60) -> list[tuple[int, float]]:
    snaps = list(db.execute(select(PortfolioSnapshot).order_by(PortfolioSnapshot.created_at.asc())).scalars().all())
    if not snaps:
        return []
    if len(snaps) > points:
        step = max(1, len(snaps) // points)
        snaps = snaps[::step]
    out: list[tuple[int, float]] = []
    for s in snaps:
        out.append((int(s.created_at.timestamp()), float(s.equity or 0.0)))
    return out
