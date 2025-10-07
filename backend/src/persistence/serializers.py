from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.persistence.db import _session


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
        "created_at": trade.created_at,
    }


def serialize_position(position: Any, last_price: Optional[float] = None) -> Dict[str, Any]:
    """Serialize a Position ORM object, optionally appending a live last_price."""
    data: Dict[str, Any] = {
        "id": position.id,
        "symbol": position.symbol,
        "chain": getattr(position, "chain", "unknown"),
        "address": position.address,
        "qty": position.qty,
        "entry": position.entry,
        "tp1": position.tp1,
        "tp2": position.tp2,
        "stop": position.stop,
        "phase": position.phase,
        "opened_at": position.opened_at,
        "updated_at": position.updated_at,
        "closed_at": getattr(position, "closed_at", None),
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
            "created_at": snapshot.created_at,
        }
        if equity_curve is not None:
            data["equity_curve"] = [[int(t), float(v)] for t, v in equity_curve]
        if realized_total is not None:
            data["realized_pnl_total"] = float(realized_total)
        if realized_24h is not None:
            data["realized_pnl_24h"] = float(realized_24h)
        return data


def serialize_analytics(row: Any) -> Dict[str, Any]:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "chain": row.chain,
        "address": row.address,
        "evaluatedAt": row.evaluated_at.isoformat(),
        "rank": row.rank,
        "scores": {
            "quality": float(row.quality_score),
            "statistics": float(row.statistics_score),
            "entry": float(row.entry_score),
            "final": float(row.final_score),
        },
        "ai": {
            "probabilityTp1BeforeSl": float(row.ai_probability_tp1_before_sl),
            "qualityScoreDelta": float(row.ai_quality_score_delta),
        },
        "rawMetrics": {
            "tokenAgeHours": float(row.token_age_hours),
            "volume24hUsd": float(row.volume24h_usd),
            "liquidityUsd": float(row.liquidity_usd),
            "pct5m": float(row.pct_5m),
            "pct1h": float(row.pct_1h),
            "pct24h": float(row.pct_24h),
        },
        "pricing": {
            "dex": float(row.dex_price),
            "quoted": float(row.quoted_price),
        },
        "decision": {
            "action": row.decision,
            "reason": row.decision_reason,
            "sizingMultiplier": float(row.sizing_multiplier),
            "orderNotionalUsd": float(row.order_notional_usd),
            "freeCashBeforeUsd": float(row.free_cash_before_usd),
            "freeCashAfterUsd": float(row.free_cash_after_usd),
        },
        "outcome": {
            "hasOutcome": bool(row.has_outcome),
            "tradeId": int(row.outcome_trade_id),
            "closedAt": row.outcome_closed_at.isoformat(),
            "holdingMinutes": float(row.outcome_holding_minutes),
            "pnlPct": float(row.outcome_pnl_pct),
            "pnlUsd": float(row.outcome_pnl_usd),
            "wasProfit": bool(row.outcome_was_profit),
            "exitReason": row.outcome_exit_reason,
        },
        # RAW blobs (toujours présents, jamais null)
        "raw": {
            "dexscreener": row.raw_dexscreener or {},
            "ai": row.raw_ai or {},
            "risk": row.raw_risk or {},
            "pricing": row.raw_pricing or {},
            "settings": row.raw_settings or {},
            "order": row.raw_order_result or {},
        },
    }