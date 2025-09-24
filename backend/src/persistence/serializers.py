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

def serialize_position(p, last_price: float | None = None) -> dict:
    data = {
        "id": p.id,
        "address": p.address,
        "symbol": p.symbol,
        "qty": float(p.qty or 0.0),
        "entry": float(p.entry or 0.0),
        "tp1": float(p.tp1 or 0.0),
        "tp2": float(p.tp2 or 0.0),
        "stop": float(p.stop or 0.0),
        "phase": p.phase,
        "is_open": bool(p.is_open),
        "updated_at": _dt(p.updated_at),
    }
    if last_price is not None:
        data["last_price"] = float(last_price)
    return data

def serialize_portfolio(
        s,
        *,
        equity_curve: list[tuple[int, float]] | None = None,
        realized_total: float | None = None,
        realized_24h: float | None = None,
) -> dict:
    data = {
        "equity": _f(s.equity) or 0.0,
        "cash": _f(s.cash) or 0.0,
        "holdings": _f(s.holdings) or 0.0,
        "created_at": _dt(s.created_at),
    }
    if equity_curve is not None:
        data["equity_curve"] = [{"t": int(t), "v": float(v)} for t, v in equity_curve]
    if realized_total is not None:
        data["realized_pnl_total"] = float(realized_total)
    if realized_24h is not None:
        data["realized_pnl_24h"] = float(realized_24h)
    return data
