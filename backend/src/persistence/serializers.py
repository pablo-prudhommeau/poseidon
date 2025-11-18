from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional, Tuple, TypedDict

from src.core.structures.structures import EquityCurve
from src.logging.logger import get_logger
from src.persistence.models import Trade, Position, PortfolioSnapshot, Analytics, Phase

log = get_logger(__name__)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    """
    Convert a timezone-aware datetime to an ISO 8601 string using the system local timezone.
    Returns None when the input is None.
    """
    if dt is None:
        return None
    return dt.astimezone().isoformat()


class TradePayload(TypedDict, total=False):
    id: int
    side: str
    symbol: str
    chain: str
    price: float
    qty: float
    fee: float
    status: str
    tokenAddress: str
    pairAddress: str
    created_at: str
    pnl: Optional[float]
    tx_hash: Optional[str]


class PositionPayload(TypedDict, total=False):
    id: int
    symbol: str
    tokenAddress: str
    pairAddress: str
    qty: float
    entry: float
    tp1: float
    tp2: float
    stop: float
    phase: str
    chain: Optional[str]
    opened_at: str
    updated_at: str
    closed_at: Optional[str]
    last_price: Optional[float]
    _lastDir: Optional[str]
    _changePct: Optional[float]


EquityCurvePointTuple = Tuple[int, float]


class PortfolioPayload(TypedDict, total=False):
    equity: float
    cash: float
    holdings: float
    updated_at: str
    equity_curve: List[EquityCurvePointTuple]
    unrealized_pnl: float
    realized_pnl_24h: float
    realized_pnl_total: float
    win_rate: float


class AnalyticsScoresPayload(TypedDict):
    quality: float
    statistics: float
    entry: float
    final: float


class AnalyticsAiPayload(TypedDict):
    probabilityTp1BeforeSl: float
    qualityScoreDelta: float


class AnalyticsDecisionPayload(TypedDict):
    action: str
    reason: str
    sizingMultiplier: float
    orderNotionalUsd: float
    freeCashBeforeUsd: float
    freeCashAfterUsd: float


class AnalyticsOutcomePayload(TypedDict):
    hasOutcome: bool
    tradeId: int
    closedAt: str
    holdingMinutes: float
    pnlPct: float
    pnlUsd: float
    wasProfit: bool
    exitReason: str


class AnalyticsFundamentalsPayload(TypedDict):
    tokenAgeHours: float
    volume5mUsd: float
    volume1hUsd: float
    volume6hUsd: float
    volume24hUsd: float
    liquidityUsd: float
    pct5m: float
    pct1h: float
    pct6h: float
    pct24h: float
    tx5m: float
    tx1h: float
    tx6h: float
    tx24h: float


class AnalyticsPayload(TypedDict, total=False):
    id: int
    symbol: str
    chain: str
    tokenAddress: str
    pairAddress: str
    evaluatedAt: str
    rank: int
    scores: AnalyticsScoresPayload
    ai: AnalyticsAiPayload
    fundamentals: AnalyticsFundamentalsPayload
    decision: AnalyticsDecisionPayload
    outcome: AnalyticsOutcomePayload
    rawScreener: object
    rawSettings: object


def _map_position_phase_to_frontend(phase: Phase, position: Position, last_price: Optional[float]) -> str:
    """
    Map backend Phase to the frontend Phase union ('OPEN' | 'TP1' | 'TP2' | 'CLOSED').

    Rules:
        - CLOSED -> 'CLOSED'
        - OPEN   -> 'OPEN' (or TP1/TP2 if last_price crosses thresholds)
        - PARTIAL -> 'TP1' by default (or 'TP2' if last_price >= tp2)
        - STALED -> treated as 'OPEN'

    If last_price is provided, it is used to refine between OPEN/TP1/TP2 based on tp thresholds.
    """
    if phase == Phase.CLOSED or position.closed_at is not None:
        return "CLOSED"

    if last_price is not None:
        if last_price >= position.tp2:
            return "TP2"
        if last_price >= position.tp1:
            return "TP1"

    if phase == Phase.PARTIAL:
        return "TP1"

    return "OPEN"


def serialize_trade(trade: Trade) -> TradePayload:
    """
    Convert a Trade ORM instance to a strongly-typed payload for the frontend.

    Logging:
        [SERIALIZER][TRADE][SERIALIZE] Info when a trade is serialized.
        [SERIALIZER][TRADE][FIELDS] Verbose details of key fields.
    """
    payload: TradePayload = {
        "id": trade.id,
        "side": trade.side.value if isinstance(trade.side, Enum) else str(trade.side),
        "symbol": trade.symbol,
        "chain": trade.chain,
        "price": trade.price,
        "qty": trade.qty,
        "fee": trade.fee,
        "pnl": trade.pnl,
        "status": trade.status.value if isinstance(trade.status, Enum) else str(trade.status),
        "tokenAddress": trade.tokenAddress,
        "pairAddress": trade.pairAddress,
        "tx_hash": trade.tx_hash,
        "created_at": _iso(trade.created_at) or "",
    }

    return payload


def serialize_position(position: Position, last_price: Optional[float] = None) -> PositionPayload:
    """
    Convert a Position ORM instance into a payload aligned with the frontend models.

    Phase mapping:
        Backend {OPEN, PARTIAL, CLOSED, STALED} -> Frontend {'OPEN', 'TP1', 'TP2', 'CLOSED'}
        Uses last_price when provided to refine TP1/TP2.
    """
    payload: PositionPayload = {
        "id": position.id,
        "symbol": position.symbol,
        "tokenAddress": position.tokenAddress,
        "pairAddress": position.pairAddress,
        "qty": position.open_quantity,
        "entry": position.entry,
        "tp1": position.tp1,
        "tp2": position.tp2,
        "stop": position.stop,
        "phase": position.phase,
        "chain": position.chain,
        "opened_at": _iso(position.opened_at) or "",
        "updated_at": _iso(position.updated_at) or "",
        "closed_at": _iso(position.closed_at),
    }

    if last_price is not None:
        payload["last_price"] = last_price

    return payload


def serialize_portfolio(
        snapshot: PortfolioSnapshot,
        equity_curve: EquityCurve,
        realized_total: float,
        realized_24h: float,
        unrealized: float
) -> PortfolioPayload:
    """
    Serialize a PortfolioSnapshot and PnL aggregates to the frontend payload.

    Notes:
        - 'updated_at' mirrors the snapshot timestamp (ISO string in local timezone).
        - 'equity_curve' must be a list of [timestamp, value] pairs.
    """
    # EquityCurve is a dataclass wrapper; use its .points list
    curve_points_payload: List[EquityCurvePointTuple] = [
        (point.timestamp, point.equity) for point in equity_curve.points
    ]

    payload: PortfolioPayload = {
        "equity": snapshot.equity,
        "cash": snapshot.cash,
        "holdings": snapshot.holdings,
        "updated_at": _iso(snapshot.created_at) or "",
        "equity_curve": curve_points_payload,
        "unrealized_pnl": unrealized,
        "realized_pnl_total": realized_total,
        "realized_pnl_24h": realized_24h,
    }

    return payload


def serialize_analytics(row: Analytics) -> AnalyticsPayload:
    """
    Serialize an Analytics ORM row into the frontend analytics payload.
    All nested structures are explicitly shaped to match the TypeScript interface.
    """
    payload: AnalyticsPayload = {
        "id": row.id,
        "symbol": row.symbol,
        "chain": row.chain,
        "tokenAddress": row.tokenAddress,
        "pairAddress": row.pairAddress,
        "evaluatedAt": _iso(row.evaluated_at) or "",
        "rank": row.rank,
        "scores": {
            "quality": row.quality_score,
            "statistics": row.statistics_score,
            "entry": row.entry_score,
            "final": row.final_score,
        },
        "ai": {
            "probabilityTp1BeforeSl": row.ai_probability_tp1_before_sl,
            "qualityScoreDelta": row.ai_quality_score_delta,
        },
        "fundamentals": {
            "tokenAgeHours": row.token_age_hours,
            "volume5mUsd": row.volume5m_usd,
            "volume1hUsd": row.volume1h_usd,
            "volume6hUsd": row.volume6h_usd,
            "volume24hUsd": row.volume24h_usd,
            "liquidityUsd": row.liquidity_usd,
            "pct5m": row.pct_5m,
            "pct1h": row.pct_1h,
            "pct6h": row.pct_6h,
            "pct24h": row.pct_24h,
            "tx5m": row.tx_5m,
            "tx1h": row.tx_1h,
            "tx6h": row.tx_6h,
            "tx24h": row.tx_24h
        },
        "decision": {
            "action": row.decision,
            "reason": row.decision_reason,
            "sizingMultiplier": row.sizing_multiplier,
            "orderNotionalUsd": row.order_notional_usd,
            "freeCashBeforeUsd": row.free_cash_before_usd,
            "freeCashAfterUsd": row.free_cash_after_usd,
        },
        "outcome": {
            "hasOutcome": row.has_outcome,
            "tradeId": row.outcome_trade_id,
            "closedAt": _iso(row.outcome_closed_at) or "",
            "holdingMinutes": row.outcome_holding_minutes,
            "pnlPct": row.outcome_pnl_pct,
            "pnlUsd": row.outcome_pnl_usd,
            "wasProfit": row.outcome_was_profit,
            "exitReason": row.outcome_exit_reason,
        },
        "rawScreener": row.raw_dexscreener or {},
        "rawSettings": row.raw_settings or {},
    }

    return payload


__all__ = [
    "serialize_trade",
    "serialize_position",
    "serialize_portfolio",
    "serialize_analytics",
    "TradePayload",
    "PositionPayload",
    "PortfolioPayload",
    "AnalyticsPayload",
]
