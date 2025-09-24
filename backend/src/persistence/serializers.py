from __future__ import annotations

def _dt(v):
    return v.isoformat() if getattr(v, "isoformat", None) else None

def _f(v):
    return float(v) if v is not None else None

def serialize_trade(t) -> dict:
    return {
        "id": t.id,
        "side": t.side,
        "symbol": t.symbol,
        "price": _f(t.price),
        "qty": _f(t.qty),
        "fee": _f(t.fee) or 0.0,
        "pnl": _f(t.pnl),
        "status": t.status,
        "address": t.address or "",
        "tx_hash": t.tx_hash or "",
        "notes": t.notes or "",
        "created_at": _dt(t.created_at),
    }

def serialize_position(p) -> dict:
    return {
        "id": p.id,
        "symbol": p.symbol,
        "address": p.address,
        "qty": _f(p.qty),
        "entry": _f(p.entry),
        "tp1": _f(p.tp1),
        "tp2": _f(p.tp2),
        "stop": _f(p.stop),
        "phase": p.phase,
        "is_open": bool(p.is_open),
        "opened_at": _dt(p.opened_at),
        "updated_at": _dt(p.updated_at),
        "closed_at": _dt(p.closed_at),
    }

def serialize_portfolio(s) -> dict:
    return {
        "equity": _f(s.equity) or 0.0,
        "cash": _f(s.cash) or 0.0,
        "holdings": _f(s.holdings) or 0.0,
        "created_at": _dt(s.created_at),
    }
