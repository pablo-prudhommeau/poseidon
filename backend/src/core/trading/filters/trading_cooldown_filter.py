from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_application_logger
from src.persistence.db import _session
from src.persistence.models import Trade

logger = get_application_logger(__name__)


def _recently_traded(address: str, time_window_minutes: int) -> bool:
    if not address:
        return False

    with _session() as database_session:
        database_query = (
            select(Trade)
            .where(Trade.token_address == address)
            .order_by(Trade.created_at.desc())
        )
        trade_record = database_session.execute(database_query).scalars().first()
        if not trade_record:
            return False

        current_time = get_current_local_datetime()
        trade_creation_time = trade_record.created_at.astimezone()
        return (current_time - trade_creation_time) < timedelta(minutes=time_window_minutes)


def apply_cooldown_filter(candidates: list[TradingCandidate]) -> list[TradingCandidate]:
    from src.core.trading.analytics.trading_evaluation_recorder import TradingEvaluationRecorder

    cooldown_minutes = settings.TRADING_REBUY_COOLDOWN_MINUTES
    retained: list[TradingCandidate] = []

    for candidate in candidates:
        token_address = candidate.dexscreener_token_information.base_token.address
        if token_address and _recently_traded(token_address, time_window_minutes=cooldown_minutes):
            logger.debug("[TRADING][FILTER][COOLDOWN] %s — recently traded within %d minutes", candidate.dexscreener_token_information.base_token.symbol, cooldown_minutes)
            TradingEvaluationRecorder.persist_and_broadcast_skip(candidate, len(retained) + 1, "COOLDOWN")
            continue

        retained.append(candidate)

    if not retained:
        logger.info("[TRADING][FILTER][COOLDOWN] Zero candidates after cooldown check")
    else:
        logger.info("[TRADING][FILTER][COOLDOWN] Retained %d / %d candidates", len(retained), len(candidates))

    return retained
