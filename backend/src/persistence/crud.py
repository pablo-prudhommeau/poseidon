from datetime import timedelta, datetime
from typing import Optional, Dict, List

from sqlalchemy import func
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.persistence.models import Position, PortfolioSnapshot, Trade
from src.persistence.serializers import serialize_position


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


def _last_price_by_symbol(db: Session) -> dict[str, float]:
    sub = select(Trade.symbol, func.max(Trade.created_at).label("mx")).group_by(Trade.symbol).subquery()
    q = select(Trade.symbol, Trade.price).join(sub, (Trade.symbol == sub.c.symbol) & (Trade.created_at == sub.c.mx))
    out: dict[str, float] = {}
    for sym, price in db.execute(q).all():
        out[sym] = float(price or 0.0)
    return out


def snapshot_portfolio(db: Session) -> PortfolioSnapshot:
    prices = _last_price_by_symbol(db)
    positions = get_open_positions(db)
    holdings_value = 0.0
    for p in positions:
        price = prices.get(p.symbol, p.entry or 0.0)
        holdings_value += (p.qty or 0.0) * float(price or 0.0)

    start_cash = float(getattr(settings, "PAPER_STARTING_CASH", 10_000.0))
    total_buys = 0.0
    total_sells = 0.0
    total_fees = 0.0
    for t in db.execute(select(Trade)).scalars().all():
        if (t.side or "").upper() == "BUY":
            total_buys += float(t.price or 0.0) * float(t.qty or 0.0)
        else:
            total_sells += float(t.price or 0.0) * float(t.qty or 0.0)
        total_fees += float(t.fee or 0.0)
    cash = start_cash - total_buys + total_sells - total_fees
    equity = cash + holdings_value

    snap = PortfolioSnapshot(equity=equity, cash=cash, holdings=holdings_value)
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap


def record_trade(
        db: Session,
        *,
        side: str,
        symbol: str,
        address: str,
        qty: float,
        price: float,
        fee: float = 0.0,
        status: str = "PAPER",
) -> Trade:
    side_u = side.upper()
    if side_u not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")

    t = Trade(side=side_u, symbol=symbol, price=float(price), qty=float(qty), fee=float(fee or 0.0), status=status,
              address=address or "")
    db.add(t)

    pos = db.execute(select(Position).where(Position.address == address)).scalars().first()
    if side_u == "BUY":
        if pos is None:
            pos = Position(
                symbol=symbol, address=address or "", qty=float(qty), entry=float(price),
                tp1=0.0, tp2=0.0, stop=0.0, phase="OPEN", is_open=True
            )
            # s'il n'y a pas de seuils fournis, applique les défauts
            d_tp1, d_tp2, d_stop = compute_default_thresholds(price)
            pos.tp1 = d_tp1
            pos.tp2 = d_tp2
            pos.stop = d_stop
            db.add(pos)
        else:
            # moyenne du prix d'entrée
            total_qty = float(pos.qty or 0.0) + float(qty)
            avg = 0.0 if total_qty <= 0 else (
                    ((float(pos.entry or 0.0) * float(pos.qty or 0.0)) + (float(price) * float(qty))) / total_qty
            )
            pos.qty = total_qty
            pos.entry = avg
            pos.phase = "OPEN" if total_qty > 0 else "CLOSED"
            pos.is_open = total_qty > 0
            # si les seuils n'étaient pas configurés, applique maintenant les défauts basés sur le nouvel avg
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

    # snapshot after every trade
    snapshot_portfolio(db)
    return t


def realized_pnl_total(db: Session) -> float:
    q = select(func.coalesce(func.sum(Trade.pnl), 0.0))
    return float(db.execute(q).scalar_one() or 0.0)


def realized_pnl_24h(db: Session) -> float:
    since = datetime.utcnow() - timedelta(hours=24)
    q = select(func.coalesce(func.sum(Trade.pnl), 0.0)).where(Trade.created_at >= since)
    return float(db.execute(q).scalar_one() or 0.0)


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


def compute_default_thresholds(entry: float) -> tuple[float, float, float]:
    entry = float(entry or 0.0)
    tp1 = entry * (1.0 + float(settings.TP1_PCT))
    tp2 = entry * (1.0 + float(settings.TP2_PCT))
    stop = entry * (1.0 - float(settings.STOP_PCT))
    return tp1, tp2, stop


def check_thresholds_and_autosell(db: Session, *, symbol: str, last_price: float) -> list[Trade]:
    """Déclenche les ventes sur TP1/TP2/STOP pour les positions OPEN du symbole donné.
       Règles:
         - STOP: close 100% si last_price <= stop
         - TP2: close 100% si last_price >= tp2
         - TP1: sell fraction paramétrable si last_price >= tp1 (et position > 0)
       Note: un seuil à 0 est considéré 'non configuré' et ignoré.
    """
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

        # STOP (priorité max)
        if stop > 0.0 and last_price <= stop:
            tr = record_trade(
                db, side="SELL", symbol=symbol, address=p.address, qty=qty, price=last_price, status="PAPER"
            )
            # on "désarme" les seuils
            p.tp1 = 0.0;
            p.tp2 = 0.0;
            p.stop = 0.0
            created.append(tr)
            continue  # position close -> passe à la suivante

        # TP2 (close reste)
        if tp2 > 0.0 and last_price >= tp2 and qty > 0.0:
            tr = record_trade(
                db, side="SELL", symbol=symbol, address=p.address, qty=qty, price=last_price, status="PAPER"
            )
            p.tp1 = 0.0;
            p.tp2 = 0.0;
            p.stop = 0.0
            created.append(tr)
            continue

        # TP1 (vente partielle)
        if tp1 > 0.0 and last_price >= tp1 and qty > 0.0:
            part = max(0.0, min(qty, qty * float(settings.TP1_PCT)))
            if part > 0.0:
                tr = record_trade(
                    db, side="SELL", symbol=symbol, address=p.address, qty=part, price=last_price, status="PAPER"
                )
                created.append(tr)
                # on "désarme" TP1 pour éviter les multiples déclenchements,
                # en gardant TP2/STOP pour la suite
                p.tp1 = 0.0

    if created:
        db.commit()
    return created

def last_price_by_symbol(db: Session) -> dict[str, float]:
    # simple proxy du helper interne déjà utilisé
    return _last_price_by_symbol(db)

def get_open_addresses(db) -> List[str]:
    rows = db.execute(select(Position.address).where(Position.is_open == True)).scalars().all()
    return [r for r in rows if r]

def serialize_positions_with_prices_by_address(db, address_price: Dict[str, float]) -> list[dict]:
    pos = get_open_positions(db)
    payload = []
    for p in pos:
        lp = None
        if p.address:
            lp = address_price.get((p.address or "").lower())
        payload.append(serialize_position(p, lp))
    return payload

def check_thresholds_and_autosell_for_address(db, *, address: str, last_price: float) -> list[Trade]:
    """Même logique que check_thresholds_and_autosell mais ciblée sur UNE position (par adresse)."""
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

    # STOP d'abord
    if stop > 0.0 and last_price <= stop:
        tr = record_trade(db, side="SELL", symbol=p.symbol, address=p.address, qty=qty, price=last_price, status="PAPER")
        p.tp1 = 0.0; p.tp2 = 0.0; p.stop = 0.0
        created.append(tr)
        db.commit()
        return created

    # TP2 (close tout)
    if tp2 > 0.0 and last_price >= tp2 and qty > 0.0:
        tr = record_trade(db, side="SELL", symbol=p.symbol, address=p.address, qty=qty, price=last_price, status="PAPER")
        p.tp1 = 0.0; p.tp2 = 0.0; p.stop = 0.0
        created.append(tr)
        db.commit()
        return created

    # TP1 (partiel)
    if tp1 > 0.0 and last_price >= tp1 and qty > 0.0:
        part = max(0.0, min(qty, qty * float(settings.TP1_PCT)))
        if part > 0.0:
            tr = record_trade(db, side="SELL", symbol=p.symbol, address=p.address, qty=part, price=last_price, status="PAPER")
            created.append(tr)
            p.tp1 = 0.0
            db.commit()

    return created