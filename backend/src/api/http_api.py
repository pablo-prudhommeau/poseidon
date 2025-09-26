# src/api/http_api.py
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.persistence import crud
from src.persistence.db import get_db
from src.persistence.serializers import serialize_trade, serialize_position, serialize_portfolio
from src.configuration.config import settings
from src.core.pnl import (
    latest_prices_for_positions,
    fifo_realized_pnl,
    cash_from_trades,
    holdings_and_unrealized,
)

router = APIRouter()


@router.get("/api/portfolio")
async def get_portfolio(db: Session = Depends(get_db)):
    """
    Renvoie le portfolio courant en recalculant:
      - realized_total / realized_24h (FIFO)
      - cash (depuis le journal de trades)
      - holdings + unrealized_pnl (via prix live DexScreener)
      - equity
    Écrit aussi un snapshot DB pour l'historique d'équité.
    """
    # données nécessaires
    snap = crud.get_latest_portfolio(db, create_if_missing=True)
    positions = crud.get_open_positions(db)
    # prix live par adresse
    prices = await latest_prices_for_positions(positions, chain_id=getattr(settings, "TREND_CHAIN_ID", None))
    # tous les trades (ou fallback recent large)
    get_all = getattr(crud, "get_all_trades", None)
    trades = get_all(db) if callable(get_all) else crud.get_recent_trades(db, limit=10000)

    # calculs centralisés
    start_cash = float(getattr(settings, "PAPER_STARTING_CASH", 10_000.0))
    realized_total, realized_24h = fifo_realized_pnl(trades, cutoff_hours=24)
    cash, _, _, _ = cash_from_trades(start_cash, trades)
    holdings, unrealized = holdings_and_unrealized(positions, prices)
    equity = round(cash + holdings, 2)

    # snapshot (écriture pure; pas de calcul côté CRUD)
    snap = crud.snapshot_portfolio(db, equity=equity, cash=cash, holdings=holdings)

    payload = serialize_portfolio(
        snap,
        equity_curve=crud.equity_curve(db),
        realized_total=realized_total,
        realized_24h=realized_24h,
    )
    # champ explicite attendu par le front
    payload["unrealized_pnl"] = unrealized
    return payload


@router.get("/api/positions")
async def get_positions(db: Session = Depends(get_db)):
    """
    Positions ouvertes avec last_price live (DexScreener), pour l'UI.
    """
    positions = crud.get_open_positions(db)
    prices = await latest_prices_for_positions(positions, chain_id=getattr(settings, "TREND_CHAIN_ID", None))
    out: List[dict] = []
    for p in positions:
        last = prices.get((p.address or "").lower())
        out.append(serialize_position(p, last))
    return out


@router.get("/api/trades")
def get_trades(limit: int = 100, db: Session = Depends(get_db)):
    trades = crud.get_recent_trades(db, limit=limit)
    return [serialize_trade(t) for t in trades]


@router.post("/api/paper/reset")
def reset_paper(db: Session = Depends(get_db)):
    crud.reset_paper(db)
    crud.ensure_initial_cash(db)  # seed 10k$
    return {"ok": True}


@router.get("/pnl/summary")
async def pnl_summary(db: Session = Depends(get_db)):
    """
    Résumé PnL cohérent avec orchestrator/ws_hub:
      - realizedUsd (total FIFO)
      - unrealizedUsd (prix live)
      - totalUsd
      - byChain: breakdown par chaîne (realized/unrealized/total)
    """
    positions = crud.get_open_positions(db)
    prices = await latest_prices_for_positions(positions, chain_id=getattr(settings, "TREND_CHAIN_ID", None))

    get_all = getattr(crud, "get_all_trades", None)
    trades = get_all(db) if callable(get_all) else crud.get_recent_trades(db, limit=10000)

    # Totaux
    realized_total, _ = fifo_realized_pnl(trades, cutoff_hours=10_000)  # >> effectively "all-time"
    _, unrealized = holdings_and_unrealized(positions, prices)
    total = round(realized_total + unrealized, 2)

    # Breakdown par chaîne (FIFO par chaîne pour le réalisé, latent par positions)
    trades_by_chain: Dict[str, list] = defaultdict(list)
    for t in trades:
        c = (getattr(t, "chain", "") or "unknown").lower()
        trades_by_chain[c].append(t)

    realized_by_chain: Dict[str, float] = {}
    for c, ts in trades_by_chain.items():
        rt, _ = fifo_realized_pnl(ts, cutoff_hours=10_000)
        realized_by_chain[c] = rt

    unrealized_by_chain: Dict[str, float] = defaultdict(float)
    for p in positions:
        c = (getattr(p, "chain", "") or "unknown").lower()
        addr = (getattr(p, "address", "") or "").lower()
        last = float(prices.get(addr, 0.0) or 0.0)
        if last <= 0.0:
            last = float(getattr(p, "entry", 0.0) or 0.0)
        entry = float(getattr(p, "entry", 0.0) or 0.0)
        qty = float(getattr(p, "qty", 0.0) or 0.0)
        unrealized_by_chain[c] += (last - entry) * qty

    by_chain = {}
    for c in set(list(realized_by_chain.keys()) + list(unrealized_by_chain.keys())):
        r = round(realized_by_chain.get(c, 0.0), 2)
        u = round(unrealized_by_chain.get(c, 0.0), 2)
        by_chain[c] = {
            "realizedUsd": r,
            "unrealizedUsd": u,
            "totalUsd": round(r + u, 2),
        }

    return {
        "realizedUsd": round(realized_total, 2),
        "unrealizedUsd": round(unrealized, 2),
        "totalUsd": total,
        "byChain": by_chain,
    }
