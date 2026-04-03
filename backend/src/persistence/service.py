from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from src.logging.logger import get_application_logger
from src.persistence.db import _session
from src.persistence.models import Position, PortfolioSnapshot, Trade, Analytics

logger = get_application_logger(__name__)


def reset_paper(database_session: Session) -> None:
    with _session() as session:
        session.execute(delete(Trade))
        session.execute(delete(Position))
        session.execute(delete(PortfolioSnapshot))
        session.execute(delete(Analytics))
        session.commit()
        logger.info("[DATABASE][SERVICE][RESET] Paper state has been reset (trades, positions, snapshots, analytics removed)")
