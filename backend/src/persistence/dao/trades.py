from __future__ import annotations

from collections import deque
from typing import Deque, List, Optional, Tuple

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from src.api.websocket.telemetry import TelemetryService
from src.core.structures.structures import Token
from src.core.utils.date_utils import timezone_now
from src.logging.logger import get_logger
from src.persistence.models import Phase, Position, Side, Status, Trade

log = get_logger(__name__)

EPSILON_QTY = 1e-12


def _get_active_position_by_address(db: Session, address: str) -> Optional[Position]:
    """
    Return the most recent ACTIVE position (OPEN or PARTIAL) for this token address.
    CLOSED rows are ignored.

    Note:
        Multiple pools for the same token are forbidden by lifecycle policy (no DCA).
        If that policy changes in the future, queries must also filter by pairAddress.
    """
    return (
        db.execute(
            select(Position)
            .where(
                Position.tokenAddress == address,
                Position.phase.in_([Phase.OPEN, Phase.PARTIAL]),
                )
            .order_by(desc(Position.opened_at), desc(Position.id))
            .limit(1)
        )
        .scalars()
        .first()
    )


def _get_last_closed_position_for_cooldown(db: Session, address: str) -> Optional[Position]:
    """Return the most recently CLOSED position for cooldown enforcement."""
    return (
        db.execute(
            select(Position)
            .where(
                Position.tokenAddress == address,
                Position.phase == Phase.CLOSED,
                Position.closed_at.isnot(None),
                )
            .order_by(desc(Position.closed_at), desc(Position.id))
            .limit(1)
        )
        .scalars()
        .first()
    )


def _fifo_realized_and_basis_for_sell(
        db: Session,
        address: str,
        sell_qty: float,
        sell_price: float,
        fee: float,
        pair_address: Optional[str] = None,
) -> Tuple[float, float]:
    """
    Compute (realized_usd, cost_basis_usd) for a SELL using FIFO lots **scoped to a market**.

    Market scope:
        - If 'pair_address' is provided: use (tokenAddress, pairAddress).
        - Otherwise: fallback to token-only (legacy behavior).

    Rules:
        - Buy fees are allocated per-unit into cost basis.
        - Current sell fee is distributed per-unit and subtracted from proceeds.

    Returns:
        realized_usd: proceeds - cost (already net of fees)
        cost_basis_usd: cost of the sold chunk including buy fees
    """
    qty_to_sell = float(sell_qty)
    price_to_sell = float(sell_price)
    sell_fee_total = float(fee or 0.0)

    if qty_to_sell <= 0.0 or price_to_sell <= 0.0:
        return (0.0 - sell_fee_total, 0.0)

    # Build prior trades query in the correct market scope
    stmt = select(Trade).where(Trade.tokenAddress == address).order_by(Trade.created_at.asc(), Trade.id.asc())
    if isinstance(pair_address, str) and pair_address:
        stmt = stmt.where(Trade.pairAddress == pair_address)

    prior_trades: List[Trade] = list(db.execute(stmt).scalars().all())

    lots: Deque[Tuple[float, float, float]] = deque()

    for tr in prior_trades:
        if tr.qty is None or tr.price is None:
            continue
        qty = float(tr.qty)
        px = float(tr.price)
        trade_fee = float(tr.fee or 0.0)
        if qty <= 0.0 or px <= 0.0:
            continue

        if tr.side == Side.BUY:
            fee_per_unit = trade_fee / qty if qty > 0.0 else 0.0
            lots.append((qty, px, fee_per_unit))
        elif tr.side == Side.SELL:
            # Consume from lots for already-recorded sells
            remaining = qty
            while remaining > EPSILON_QTY and len(lots) > 0:
                lot_qty, lot_px, fee_per_unit = lots[0]
                matched = min(remaining, lot_qty)
                lot_qty -= matched
                remaining -= matched
                if lot_qty <= EPSILON_QTY:
                    lots.popleft()
                else:
                    lots[0] = (lot_qty, lot_px, fee_per_unit)

    remaining_to_sell = float(qty_to_sell)
    realized = 0.0
    cost_basis = 0.0
    sell_fee_per_unit = sell_fee_total / qty_to_sell if qty_to_sell > 0.0 else 0.0

    while remaining_to_sell > EPSILON_QTY and len(lots) > 0:
        lot_qty, lot_px, buy_fee_per_unit = lots[0]
        matched = min(remaining_to_sell, lot_qty)

        proceeds = (price_to_sell - sell_fee_per_unit) * matched
        cost = (lot_px + buy_fee_per_unit) * matched

        realized += (proceeds - cost)
        cost_basis += cost

        lot_qty -= matched
        remaining_to_sell -= matched
        if lot_qty <= EPSILON_QTY:
            lots.popleft()
        else:
            lots[0] = (lot_qty, lot_px, buy_fee_per_unit)

    if remaining_to_sell > EPSILON_QTY:
        log.warning(
            "[DAO][TRADES][FIFO] SELL qty exceeds available lots — token=%s pair=%s residual=%.12f",
            address,
            (pair_address or "")[-6:],
            remaining_to_sell,
        )

    return (round(realized, 8), round(cost_basis, 8))


def _compute_open_quantity_from_trades(db: Session, address: str) -> float:
    """
    Legacy helper: return current open quantity for a token address as sum(BUY) - sum(SELL).
    Kept for backward compatibility with historical call-sites.
    """
    trade_rows: List[Trade] = list(db.execute(select(Trade).where(Trade.tokenAddress == address)).scalars().all())
    open_quantity = 0.0
    for tr in trade_rows:
        if tr.qty is None:
            continue
        if tr.side == Side.BUY:
            open_quantity += float(tr.qty)
        elif tr.side == Side.SELL:
            open_quantity -= float(tr.qty)
    return max(0.0, open_quantity)


def compute_open_quantity_for_position(db: Session, position: Position) -> float:
    """
    Return current open quantity **scoped to the position's market**:
    (tokenAddress, pairAddress) when pair is present; otherwise token-only.
    """
    stmt = select(Trade).where(Trade.tokenAddress == position.tokenAddress)
    if isinstance(position.pairAddress, str) and position.pairAddress:
        stmt = stmt.where(Trade.pairAddress == position.pairAddress)

    trade_rows: List[Trade] = list(db.execute(stmt).scalars().all())
    open_quantity = 0.0
    for tr in trade_rows:
        if tr.qty is None:
            continue
        if tr.side == Side.BUY:
            open_quantity += float(tr.qty)
        elif tr.side == Side.SELL:
            open_quantity -= float(tr.qty)
    open_quantity = max(0.0, open_quantity)
    log.debug(
        "[DAO][TRADES][OPENQ] token=%s pair=%s open_qty=%.12f",
        position.tokenAddress,
        position.pairAddress,
        open_quantity,
    )
    return open_quantity


def buy(
        db: Session,
        token: Token,
        qty: float,
        price: float,
        stop: float,
        tp1: float,
        tp2: float,
        fee: float,
        status: Status,
) -> Trade:
    """
    Register a BUY trade for a new lifecycle.

    Policy:
    - DCA is forbidden.
    - Snapshot fields (qty, entry, tp1, tp2, stop) are immutable per lifecycle.
    - Cooldown is enforced between lifecycles.

    Note:
        'pairAddress' is optional for backward compatibility. When provided, it is
        stored on both Trade and Position so subsequent valuations are pool-aware.
    """
    if float(price) <= 0.0:
        raise ValueError("BUY rejected: price must be > 0")

    trade_row = Trade(
        side=Side.BUY,
        symbol=token.symbol,
        chain=token.chain,
        tokenAddress=token.tokenAddress,
        pairAddress=token.pairAddress,
        price=price,
        qty=qty,
        fee=fee,
        status=status
    )
    db.add(trade_row)

    position = Position(
        symbol=token.symbol,
        chain=token.chain,
        tokenAddress=token.tokenAddress,
        pairAddress=token.pairAddress,
        qty=qty,
        entry=price,
        tp1=tp1,
        tp2=tp2,
        stop=stop,
        phase=Phase.OPEN,
    )
    db.add(position)

    log.info(
        "[TRADE][BUY] snapshot %s %s/%s qty=%.8f entry=%.8f tp1=%.8f tp2=%.8f stop=%.8f",
        token.symbol, token.tokenAddress, token.pairAddress, qty, price, tp1, tp2, stop,
    )
    db.commit()
    db.refresh(trade_row)
    return trade_row


def sell(
        db: Session,
        token: Token,
        qty: float,
        price: float,
        fee: float,
        status: Status,
        phase: Phase,
) -> Trade:
    """
    Register a SELL trade, compute realized PnL with FIFO lots (pair-aware),
    and update the Position phase.

    Semantics:
      - PARTIAL (TP1): link an intermediate outcome (chunk-level realized/basis).
      - Full CLOSE: link a final outcome with inferred reason (TP2/SL/TP1/MANUAL)
        and aggregate PnL over the lifecycle.
    """
    if float(price) <= 0.0:
        raise ValueError("SELL rejected: price must be > 0")

    position = _get_active_position_by_address(db, token.tokenAddress)

    open_qty_before = compute_open_quantity_for_position(db, position) if position is not None else _compute_open_quantity_from_trades(db, token.tokenAddress)
    sell_qty = float(qty)
    if sell_qty > open_qty_before + EPSILON_QTY:
        log.error(
            "[TRADE][SELL] exceeds open quantity — token=%s pair=%s sell_qty=%.12f open_qty=%.12f",
            token.tokenAddress, token.pairAddress, sell_qty, open_qty_before,
        )
        raise ValueError("SELL rejected: quantity exceeds currently open quantity")

    # Compute realized pnl and cost basis for this SELL
    realized_this_sell, basis_this_sell = _fifo_realized_and_basis_for_sell(
        db=db,
        address=token.tokenAddress,
        sell_qty=sell_qty,
        sell_price=float(price),
        fee=float(fee or 0.0),
        pair_address=token.pairAddress,
    )

    trade_row = Trade(
        side=Side.SELL,
        symbol=token.symbol,
        chain=token.chain,
        price=float(price),
        qty=sell_qty,
        fee=float(fee or 0.0),
        status=status,
        tokenAddress=token.tokenAddress,
        pairAddress=token.pairAddress,
        pnl=realized_this_sell,
    )
    db.add(trade_row)

    # Phase update after accounting for the SELL
    closed_now = False
    if position is not None:
        open_qty_after = max(0.0, open_qty_before - sell_qty)
        if open_qty_after <= EPSILON_QTY:
            position.phase = phase  # usually CLOSED on full exit
            position.closed_at = timezone_now()
            closed_now = True
        else:
            position.phase = Phase.PARTIAL

        log.info(
            "[POSITION][PHASE] update — token=%s pair=%s phase=%s open_qty_after=%.8f",
            token.tokenAddress, token.pairAddress, position.phase, open_qty_after,
        )
        log.debug(
            "[LIFECYCLE] after SELL — %s %s/%s qty=%.8f price=%.8f realized=%.8f",
            token.symbol, token.tokenAddress, token.pairAddress, sell_qty, price, realized_this_sell,
        )

    db.commit()
    db.refresh(trade_row)

    try:
        if position is not None and closed_now:
            start_time = position.opened_at
            lifecycle_stmt = (
                select(Trade)
                .where(Trade.tokenAddress == token.tokenAddress, Trade.created_at >= start_time)
                .order_by(Trade.created_at.asc(), Trade.id.asc())
            )
            lifecycle_stmt = lifecycle_stmt.where(Trade.pairAddress == token.pairAddress)
            lifecycle_trades: List[Trade] = list(db.execute(lifecycle_stmt).scalars().all())

            invested = sum(
                float(t.qty or 0.0) * float(t.price or 0.0) + float(t.fee or 0.0)
                for t in lifecycle_trades
                if t.side == Side.BUY
            )
            realized_total = sum(
                float(t.pnl or 0.0)
                for t in lifecycle_trades
                if t.side == Side.SELL
            )

            pnl_usd = round(realized_total, 8)
            pnl_pct = round((pnl_usd / invested) * 100.0, 6) if invested > 0 else 0.0
            holding_minutes = 0.0
            if position.closed_at is not None and position.opened_at is not None:
                holding_minutes = max(
                    0.0,
                    (position.closed_at - position.opened_at).total_seconds() / 60.0,
                    )

            # Determine final exit reason w.r.t. configured thresholds
            reason = "MANUAL"
            eps = 1e-12
            if float(price) <= float(position.stop or 0.0) + eps:
                reason = "SL"
            elif float(price) >= float(position.tp2 or 0.0) - eps:
                reason = "TP2"
            elif float(price) >= float(position.tp1 or 0.0) - eps:
                reason = "TP1"

            TelemetryService.link_trade_outcome(
                token_address=token.tokenAddress,
                trade_id=trade_row.id,
                closed_at=position.closed_at,
                pnl_pct=pnl_pct,
                pnl_usd=pnl_usd,
                holding_minutes=holding_minutes,
                was_profit=pnl_usd > 0.0,
                exit_reason=reason,
            )

        elif position is not None and position.phase == Phase.PARTIAL:
            # Partial snapshot (TP1) for analytics
            pnl_usd_chunk = float(trade_row.pnl or 0.0)
            basis_usd_chunk = float(basis_this_sell or 0.0)
            pnl_pct_chunk = (pnl_usd_chunk / basis_usd_chunk * 100.0) if basis_usd_chunk > 0.0 else 0.0

            holding_minutes_chunk = 0.0
            if trade_row.created_at is not None and position.opened_at is not None:
                holding_minutes_chunk = max(
                    0.0,
                    (trade_row.created_at - position.opened_at).total_seconds() / 60.0,
                    )

            TelemetryService.link_trade_outcome(
                token_address=token.tokenAddress,
                trade_id=trade_row.id,
                closed_at=trade_row.created_at,
                pnl_pct=round(pnl_pct_chunk, 6),
                pnl_usd=round(pnl_usd_chunk, 8),
                holding_minutes=round(holding_minutes_chunk, 4),
                was_profit=pnl_usd_chunk > 0.0,
                exit_reason="TP1",
            )
    except Exception as exc:
        log.exception(
            "[TELEMETRY] Failed to link trade outcome — token=%s trade=%s: %s",
            token,
            trade_row.id,
            exc,
        )

    return trade_row


def get_recent_trades(db: Session, limit: int = 100) -> List[Trade]:
    """Return the most recent trades (descending by time and id)."""
    stmt = select(Trade).order_by(Trade.created_at.desc(), Trade.id.desc()).limit(int(limit))
    return list(db.execute(stmt).scalars().all())


def get_all_trades(db: Session) -> List[Trade]:
    """Return all trades in ascending time order (useful for FIFO computations)."""
    stmt = select(Trade).order_by(Trade.created_at.asc(), Trade.id.asc())
    return list(db.execute(stmt).scalars().all())
