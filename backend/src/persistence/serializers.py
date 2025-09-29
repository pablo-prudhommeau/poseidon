from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from src.persistence.db import _session


def _isoformat_or_none(value: Any) -> Optional[str]:
    """Return ISO 8601 string if value has .isoformat(), else None."""
    iso = getattr(value, "isoformat", None)
    return iso() if callable(iso) else None


def serialize_trade(trade: Any) -> Dict[str, Any]:
    """Serialize a Trade ORM object to a frontend-friendly dict."""
    return {
        "id": trade.id,
        "side": trade.side,
        "symbol": trade.symbol,
        "chain": getattr(trade, "chain", "unknown"),
        "price": trade.price,
        "qty": trade.qty,
        "fee": trade.fee,
        "pnl": trade.pnl,
        "status": trade.status,
        "address": trade.address,
        "tx_hash": trade.tx_hash,
        "created_at": _isoformat_or_none(trade.created_at),
    }


def serialize_position(position: Any, last_price: Optional[float] = None) -> Dict[str, Any]:
    """Serialize a Position ORM object, optionally appending a live last_price."""
    data: Dict[str, Any] = {
        "id": position.id,
        "address": position.address,
        "symbol": position.symbol,
        "chain": getattr(position, "chain", "unknown"),
        "qty": position.qty,
        "entry": position.entry,
        "tp1": position.tp1,
        "tp2": position.tp2,
        "stop": position.stop,
        "phase": position.phase,
        "is_open": position.is_open,
        "opened_at": _isoformat_or_none(position.opened_at),
        "updated_at": _isoformat_or_none(position.updated_at),
    }
    if last_price is not None:
        data["last_price"] = float(last_price)
    return data


def serialize_portfolio(
        snapshot: Any,
        equity_curve: Optional[List[Tuple[int, float]]] = None,
        realized_total: Optional[float] = None,
        realized_24h: Optional[float] = None,
) -> Dict[str, Any]:
    """Serialize a PortfolioSnapshot with optional equity curve and realized PnL."""
    with _session():
        data: Dict[str, Any] = {
            "equity": snapshot.equity,
            "cash": snapshot.cash,
            "holdings": snapshot.holdings,
            "created_at": _isoformat_or_none(snapshot.created_at),
        }
        if equity_curve is not None:
            data["equity_curve"] = [{"t": int(t), "v": float(v)} for t, v in equity_curve]
        if realized_total is not None:
            data["realized_pnl_total"] = float(realized_total)
        if realized_24h is not None:
            data["realized_pnl_24h"] = float(realized_24h)
        return data
