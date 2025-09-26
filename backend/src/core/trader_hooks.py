# src/core/trader_hooks.py
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import Dict, Optional

from src.api.ws_manager import ws_manager
from src.configuration.config import settings
from src.core.pnl import (
    latest_prices_for_positions,
    fifo_realized_pnl,
    cash_from_trades,
    holdings_and_unrealized,
)
from src.persistence import crud
from src.persistence.db import SessionLocal
from src.persistence.serializers import serialize_trade, serialize_portfolio


@contextmanager
def _session(db: Optional[SessionLocal] = None):
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


def on_trade(
        side: str,
        symbol: str,
        price: float,
        qty: float,
        *,
        address: str = "",
        chain: str,
        fee: float = 0.0,
        status: str = "PAPER",
        db=None,
) -> None:
    """
    Enregistre le trade, déclenche d'éventuelles ventes auto, puis relance un
    recalcul + broadcast unifié (positions + portfolio) en utilisant pnl_center.
    """
    with _session(db) as s:
        tr = crud.record_trade(
            s, side=side, symbol=symbol, chain=chain, address=address, qty=qty, price=price, fee=fee, status=status
        )
        ws_manager.broadcast_json_threadsafe({"type": "trade", "payload": serialize_trade(tr)})

        # Déclencher les ventes sur seuils pour ce symbole avec le prix courant
        auto_trades = crud.check_thresholds_and_autosell(s, symbol=symbol, last_price=price)
        for atr in auto_trades:
            ws_manager.broadcast_json_threadsafe({"type": "trade", "payload": serialize_trade(atr)})

            # Recompute + broadcast (positions + portfolio) en arrière-plan
            _schedule_recompute_and_broadcast()


def on_position_opened(*, address: str, db=None) -> None:
    _schedule_recompute_and_broadcast()


def on_position_closed(*, address: str, db=None) -> None:
    _schedule_recompute_and_broadcast()


def on_portfolio_snapshot(*, latest: bool = True, db=None) -> None:
    _schedule_recompute_and_broadcast()


def _schedule_recompute_and_broadcast() -> None:
    """
    Planifie l'exécution de _recompute_and_broadcast() sans bloquer le thread courant.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_recompute_and_broadcast())
    except RuntimeError:
        # Pas de loop active (appel hors contexte async)
        asyncio.run(_recompute_and_broadcast())


async def _recompute_and_broadcast() -> None:
    """
    Recalcule avec pnl_center puis broadcast:
      - positions (avec last_price live par adresse)
      - portfolio (unrealized_pnl, realized 24h/total, equity, etc.)
    Ecrit un snapshot (équity/cash/holdings) via crud.snapshot_portfolio (écriture pure).
    """
    # 1) Charger données
    with SessionLocal() as db:
        positions = crud.get_open_positions(db)
        get_all = getattr(crud, "get_all_trades", None)
        trades = get_all(db) if callable(get_all) else crud.get_recent_trades(db, limit=10000)

    # 2) Prix live par adresse
    prices: Dict[str, float] = {}
    if positions:
        prices = await latest_prices_for_positions(positions, chain_id=getattr(settings, "TREND_CHAIN_ID", None))

    # 3) Calculs centralisés
    start_cash = float(getattr(settings, "PAPER_STARTING_CASH", 10_000.0))
    realized_total, realized_24h = fifo_realized_pnl(trades, cutoff_hours=24)
    cash, _, _, _ = cash_from_trades(start_cash, trades)
    holdings, unrealized = holdings_and_unrealized(positions, prices)
    equity = round(cash + holdings, 2)

    # 4) Snapshot + payloads et broadcast
    with SessionLocal() as db:
        # Snapshot (écriture pure : valeurs déjà calculées)
        snap = crud.snapshot_portfolio(db, equity=equity, cash=cash, holdings=holdings)

        # Positions avec last_price live
        pos_payload = crud.serialize_positions_with_prices_by_address(db, prices)

        # Portfolio cohérent avec orchestrator/ws_hub
        portfolio_payload = serialize_portfolio(
            snap,
            equity_curve=crud.equity_curve(db),
            realized_total=realized_total,
            realized_24h=realized_24h,
        )
        portfolio_payload["unrealized_pnl"] = unrealized

    # Broadcast (threadsafe)
    ws_manager.broadcast_json_threadsafe({"type": "positions", "payload": pos_payload})
    ws_manager.broadcast_json_threadsafe({"type": "portfolio", "payload": portfolio_payload})


# (facultatif) alias public utilisé par Trader._rebroadcast_portfolio()
async def rebroadcast_portfolio() -> None:
    await _recompute_and_broadcast()
