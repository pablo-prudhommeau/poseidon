from __future__ import annotations

import logging
from contextlib import contextmanager

from src.persistence.db import SessionLocal
from src.integrations.trader_hooks import on_trade, on_position_opened


@contextmanager
def _db_session():
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
    """
    Handler branché sur les logs du trader.
    Il appelle les hooks *avec* un db session (corrige l'erreur 'on_trade missing db').
    """

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        msg = record.getMessage()

        # Ces attributs sont ajoutés par le code qui log (trader.py / trending_job.py)
        extra = getattr(record, "__dict__", {})
        sym = extra.get("symbol") or extra.get("sym")
        price = extra.get("price")
        qty = extra.get("qty")
        addr = extra.get("address") or extra.get("addr")

        if "[PAPER BUY]" in msg or "[LIVE BUY]" in msg:
            with _db_session() as db:
                # plan de sortie → upsert position OPEN si fourni
                tp1, tp2, stop = extra.get("tp1"), extra.get("tp2"), extra.get("stop")
                if tp1 is not None and tp2 is not None and stop is not None:
                    on_position_opened(
                        db=db,
                        symbol=sym,
                        address=addr or "",
                        qty=qty or 0.0,
                        entry=price or 0.0,
                        tp1=tp1, tp2=tp2, stop=stop,
                        phase="OPEN",
                    )


def install_bridge() -> None:
    """À appeler au startup de l'app UI."""
    root = logging.getLogger()
    # évite double ajout
    if any(isinstance(h, TraderLogBridge) for h in root.handlers):
        return
    root.addHandler(TraderLogBridge())
    root.setLevel(logging.INFO)
