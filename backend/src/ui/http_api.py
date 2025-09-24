from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.persistence import crud
from src.persistence.db import get_db
from src.persistence.serializers import serialize_trade, serialize_position, serialize_portfolio

router = APIRouter()


@router.get("/api/portfolio")
def get_portfolio(db: Session = Depends(get_db)):
    snap = crud.get_latest_portfolio(db, create_if_missing=True)
    return (serialize_portfolio(
        snap,
        equity_curve=crud.equity_curve(db),
        realized_total=crud.realized_pnl_total(db),
        realized_24h=crud.realized_pnl_24h(db),
    ) if snap else None)


@router.get("/api/positions")
def get_positions(db: Session = Depends(get_db)):
    positions = crud.get_open_positions(db)
    prices = crud.last_price_by_symbol(db)
    return [serialize_position(p, prices.get(p.symbol)) for p in positions]


@router.get("/api/trades")
def get_trades(limit: int = 100, db: Session = Depends(get_db)):
    trades = crud.get_recent_trades(db, limit=limit)
    return [serialize_trade(t) for t in trades]


@router.post("/api/paper/reset")
def reset_paper(db: Session = Depends(get_db)):
    crud.reset_paper(db)
    crud.ensure_initial_cash(db)  # seed 10k$
    return {"ok": True}
