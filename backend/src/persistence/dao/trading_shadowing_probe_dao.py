from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from src.logging.logger import get_application_logger
from src.persistence.models import TradingShadowingProbe

logger = get_application_logger(__name__)


class TradingShadowingProbeDao:
    def __init__(self, database_session: Session) -> None:
        self.database_session = database_session

    def save(self, probe: TradingShadowingProbe) -> TradingShadowingProbe:
        try:
            self.database_session.add(probe)
            self.database_session.flush()
            return probe
        except Exception as error:
            logger.exception("[DAO][SHADOWING_PROBE] Failed to save probe — %s", error)
            raise

    def retrieve_oldest_probe_timestamp(self) -> float:
        from src.core.utils.date_utils import get_current_local_datetime
        try:
            oldest_probed_at = self.database_session.execute(
                select(func.min(TradingShadowingProbe.probed_at))
            ).scalar_one_or_none()
            if oldest_probed_at is None:
                return 0.0
            from src.core.utils.date_utils import ensure_timezone_aware
            aware_oldest = ensure_timezone_aware(oldest_probed_at) or get_current_local_datetime()
            current_time = get_current_local_datetime()
            return (current_time - aware_oldest).total_seconds() / 3600.0
        except Exception as error:
            logger.exception("[DAO][SHADOWING_PROBE] Failed to retrieve oldest probe timestamp — %s", error)
            raise

    def count_total_probes(self) -> int:
        try:
            return self.database_session.execute(
                select(func.count(TradingShadowingProbe.id))
            ).scalar_one_or_none() or 0
        except Exception as error:
            logger.exception("[DAO][SHADOWING_PROBE] Failed to count probes — %s", error)
            raise

    def retrieve_recent_probes_by_tokens(self, token_addresses: list[str], since: datetime) -> list[TradingShadowingProbe]:
        try:
            return self.database_session.execute(
                select(TradingShadowingProbe).where(
                    TradingShadowingProbe.token_address.in_(token_addresses),
                    TradingShadowingProbe.probed_at >= since
                )
            ).scalars().all()
        except Exception as error:
            logger.exception("[DAO][SHADOWING_PROBE] Failed to retrieve recent probes by tokens — %s", error)
            raise

    def retrieve_recent_probes(self, limit_count: int) -> list[TradingShadowingProbe]:
        try:
            return self.database_session.execute(
                select(TradingShadowingProbe)
                .order_by(TradingShadowingProbe.probed_at.desc())
                .limit(limit_count)
            ).scalars().all()
        except Exception as error:
            logger.exception("[DAO][SHADOWING_PROBE] Failed to retrieve recent probes — %s", error)
            raise
