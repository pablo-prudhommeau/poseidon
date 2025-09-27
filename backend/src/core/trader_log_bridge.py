from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator, Any, Dict, Optional

from src.core.trader_hooks import on_position_opened
from src.persistence.db import SessionLocal


@contextmanager
def _db_session() -> Iterator[Any]:
    """Yield a SQLAlchemy session with commit/rollback semantics."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class TraderLogBridge(logging.Handler):
    """Logging handler wired to trader logs.

    It inspects log records for trade-related extras and calls the proper hooks
    **with** an explicit DB session (fixes the 'on_trade missing db' issue).
    """

    PAPER_BUY_TAG = "[PAPER BUY]"
    LIVE_BUY_TAG = "[LIVE BUY]"

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        message = record.getMessage()

        # Extras are attached by caller code (trader.py / trending_job.py)
        extras: Dict[str, Any] = getattr(record, "__dict__", {})
        symbol: Optional[str] = extras.get("symbol") or extras.get("sym")
        price: Optional[float] = extras.get("price")
        qty: Optional[float] = extras.get("qty")
        address: Optional[str] = extras.get("address") or extras.get("addr")

        if self.PAPER_BUY_TAG in message or self.LIVE_BUY_TAG in message:
            # Exit plan → upsert OPEN position if provided
            tp1 = extras.get("tp1")
            tp2 = extras.get("tp2")
            stop = extras.get("stop")

            if tp1 is not None and tp2 is not None and stop is not None:
                with _db_session() as db:
                    on_position_opened(
                        db=db,
                        symbol=symbol,
                        address=address or "",
                        qty=qty or 0.0,
                        entry=price or 0.0,
                        tp1=tp1,
                        tp2=tp2,
                        stop=stop,
                        phase="OPEN",
                    )


def install_bridge() -> None:
    """Install the TraderLogBridge on the root logger (idempotent)."""
    root = logging.getLogger()
    if any(isinstance(h, TraderLogBridge) for h in root.handlers):
        return
    root.addHandler(TraderLogBridge())
