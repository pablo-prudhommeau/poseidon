# src/persistence/serializers.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _isoformat_or_none(value: Any) -> Optional[str]:
    """Return ISO 8601 string if value has .isoformat(), else None."""
    iso = getattr(value, "isoformat", None)
    return iso() if callable(iso) else None


def _to_float_or_none(value: Any) -> Optional[float]:
    """Coerce to float when possible, otherwise return None."""
    return float(value) if value is not None else None


def serialize_trade(trade: Any) -> Dict[str, Any]:
    """Serialize a Trade ORM object to a frontend-friendly dict."""
    return {
        "id": trade.id,
        "side": trade.side,
        "symbol": trade.symbol,
        "chain": getattr(trade, "chain", "unknown"),
        "price": _to_float_or_none(trade.price),
        "qty": _to_float_or_none(trade.qty),
        "fee": _to_float_or_none(trade.fee) or 0.0,
        "pnl": _to_float_or_none(trade.pnl),
        "status": trade.status,
        "address": trade.address or "",
        "tx_hash": trade.tx_hash or "",
        "notes": trade.notes or "",
        "created_at": _isoformat_or_none(trade.created_at),
    }


def serialize_position(position: Any, last_price: Optional[float] = None) -> Dict[str, Any]:
    """Serialize a Position ORM object, optionally appending a live last_price."""
    data: Dict[str, Any] = {
        "id": position.id,
        "address": position.address,
        "symbol": position.symbol,
        "chain": getattr(position, "chain", "unknown"),
        "qty": float(position.qty or 0.0),
        "entry": float(position.entry or 0.0),
        "tp1": float(position.tp1 or 0.0),
        "tp2": float(position.tp2 or 0.0),
        "stop": float(position.stop or 0.0),
        "phase": position.phase,
        "is_open": bool(position.is_open),
        "opened_at": _isoformat_or_none(position.opened_at),
        "updated_at": _isoformat_or_none(position.updated_at),
    }
    if last_price is not None:
        data["last_price"] = float(last_price)
    return data


def serialize_portfolio(
        snapshot: Any,
        *,
        equity_curve: Optional[List[Tuple[int, float]]] = None,
        realized_total: Optional[float] = None,
        realized_24h: Optional[float] = None,
) -> Dict[str, Any]:
    """Serialize a PortfolioSnapshot with optional equity curve and realized PnL."""
    data: Dict[str, Any] = {
        "equity": _to_float_or_none(snapshot.equity) or 0.0,
        "cash": _to_float_or_none(snapshot.cash) or 0.0,
        "holdings": _to_float_or_none(snapshot.holdings) or 0.0,
        "created_at": _isoformat_or_none(snapshot.created_at),
    }
    if equity_curve is not None:
        # Keep the compact {t, v} shape expected by the frontend
        data["equity_curve"] = [{"t": int(t), "v": float(v)} for t, v in equity_curve]
    if realized_total is not None:
        data["realized_pnl_total"] = float(realized_total)
    if realized_24h is not None:
        data["realized_pnl_24h"] = float(realized_24h)
    return data
