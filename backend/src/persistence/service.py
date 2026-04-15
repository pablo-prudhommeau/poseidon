from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from src.logging.logger import get_application_logger
from src.persistence.models import (
    TradingPosition,
    TradingPortfolioSnapshot,
    TradingTrade,
    TradingEvaluation,
    TradingOutcome,
    DcaStrategy,
    DcaOrder,
)

logger = get_application_logger(__name__)


def reset_paper(database_session: Session) -> None:
    database_session.execute(delete(TradingTrade))
    database_session.execute(delete(TradingPosition))
    database_session.execute(delete(TradingPortfolioSnapshot))
    database_session.execute(delete(TradingEvaluation))
    database_session.execute(delete(TradingOutcome))
    database_session.execute(delete(DcaOrder))
    database_session.execute(delete(DcaStrategy))
    database_session.commit()
    logger.info("[DATABASE][SERVICE][RESET] Paper state has been reset (trades, positions, snapshots, evaluations, outcomes, and DCA records removed)")
