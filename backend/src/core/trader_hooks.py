from __future__ import annotations
from contextlib import contextmanager

from src.persistence.db import SessionLocal
from src.persistence import crud
from src.persistence.serializers import (
    serialize_trade, serialize_position, serialize_portfolio
)
from src.api.ws_manager import ws_manager

@contextmanager
def _session(db=None):
    if db is not None:
        yield db
        return
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()

def on_trade(side: str, symbol: str, price: float, qty: float, *, address: str = "", fee: float = 0.0, status: str = "PAPER", db=None) -> None:
    with _session(db) as s:
        tr = crud.record_trade(s, side=side, symbol=symbol, address=address, qty=qty, price=price, fee=fee, status=status)
        ws_manager.broadcast_json_threadsafe({"type": "trade", "payload": serialize_trade(tr)})

        # Déclenche les ventes sur seuils pour ce symbole avec le prix du trade courant
        auto_trades = crud.check_thresholds_and_autosell(s, symbol=symbol, last_price=price)
        for atr in auto_trades:
            ws_manager.broadcast_json_threadsafe({"type": "trade", "payload": serialize_trade(atr)})

        # Re-broadcast positions & portfolio après éventuelles ventes auto
        positions = crud.get_open_positions(s)
        prices = crud.last_price_by_symbol(s)
        ws_manager.broadcast_json_threadsafe({
            "type": "positions",
            "payload": [serialize_position(p, prices.get(p.symbol)) for p in positions]
        })

        snap = crud.get_latest_portfolio(s, create_if_missing=True)
        ws_manager.broadcast_json_threadsafe({
            "type": "portfolio",
            "payload": serialize_portfolio(
                snap,
                equity_curve=crud.equity_curve(s),
                realized_total=crud.realized_pnl_total(s),
                realized_24h=crud.realized_pnl_24h(s),
            ) if snap else None
        })

def on_position_opened(*, address: str, db=None) -> None:
    with _session(db) as s:
        positions = crud.get_open_positions(s)
        ws_manager.broadcast_json_threadsafe({
            "type": "positions",
            "payload": [serialize_position(p) for p in positions]
        })

def on_position_closed(*, address: str, db=None) -> None:
    with _session(db) as s:
        positions = crud.get_open_positions(s)
        ws_manager.broadcast_json_threadsafe({
            "type": "positions",
            "payload": [serialize_position(p) for p in positions]
        })

def on_portfolio_snapshot(*, latest: bool = True, db=None) -> None:
    with _session(db) as s:
        snap = crud.get_latest_portfolio(s)
        ws_manager.broadcast_json_threadsafe({
            "type": "portfolio",
            "payload": serialize_portfolio(snap) if snap else None
        })
