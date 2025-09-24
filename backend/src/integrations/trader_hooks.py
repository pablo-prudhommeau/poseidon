from __future__ import annotations
from contextlib import contextmanager
from typing import Optional

from src.persistence.db import SessionLocal
from src.persistence import crud
from src.persistence.serializers import (
    serialize_trade, serialize_position, serialize_portfolio
)
from src.realtime.ws_manager import ws_manager

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

def on_trade(*, side: str, symbol: str, price: float, qty: float,
             status: str, address: str = "", tx_hash: str = "",
             fee: float = 0.0, pnl: Optional[float] = None, notes: str = "",
             db=None) -> None:
    with _session(db) as s:
        tr = crud.add_trade(
            s, side=side, symbol=symbol, price=price, qty=qty,
            fee=fee, pnl=pnl, status=status, address=address,
            tx_hash=tx_hash, notes=notes
        )
        ws_manager.broadcast_json_threadsafe({
            "type": "trade",
            "payload": serialize_trade(tr)
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
