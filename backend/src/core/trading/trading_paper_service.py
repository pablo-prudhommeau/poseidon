from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from src.logging.logger import get_application_logger
from src.persistence.models import (
    TradingEvaluation,
    TradingOutcome,
    TradingPortfolioSnapshot,
    TradingPosition,
    TradingTrade,
)

logger = get_application_logger(__name__)


def reset_trading_paper_state(database_session: Session) -> None:
    database_session.execute(delete(TradingPosition))
    database_session.execute(delete(TradingPortfolioSnapshot))
    database_session.execute(delete(TradingOutcome))
    database_session.execute(delete(TradingTrade))
    database_session.execute(delete(TradingEvaluation))
    database_session.commit()
    logger.info(
        "[TRADING][PAPER][RESET] Trading paper state reset (positions, snapshots, trades, evaluations, outcomes removed)",
    )
