from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.trading.shadowing.trading_shadowing_structures import ShadowIntelligenceStatusSummary
from src.logging.logger import get_application_logger
from src.persistence.models import TradingShadowingVerdict, TradingShadowingProbe

logger = get_application_logger(__name__)


class TradingShadowingVerdictDao:
    def __init__(self, database_session: Session) -> None:
        self.database_session = database_session

    def save(self, verdict: TradingShadowingVerdict) -> TradingShadowingVerdict:
        try:
            self.database_session.add(verdict)
            self.database_session.flush()
            return verdict
        except Exception as error:
            logger.exception("[DAO][SHADOWING_VERDICT] Failed to save verdict — %s", error)
            raise

    def retrieve_pending_verdicts(self, limit_count: int) -> list[TradingShadowingVerdict]:
        try:
            return list(self.database_session.scalars(
                select(TradingShadowingVerdict)
                .where(TradingShadowingVerdict.exit_reason.is_(None))
                .order_by(TradingShadowingVerdict.created_at.desc())
                .limit(limit_count)
            ).all())
        except Exception as error:
            logger.exception("[DAO][SHADOWING_VERDICT] Failed to retrieve pending verdicts — %s", error)
            raise

    def retrieve_recent_resolved(self, limit_count: int) -> list[TradingShadowingVerdict]:
        from sqlalchemy.orm import joinedload
        try:
            return list(self.database_session.scalars(
                select(TradingShadowingVerdict)
                .options(joinedload(TradingShadowingVerdict.probe))
                .where(TradingShadowingVerdict.exit_reason.is_not(None))
                .where(TradingShadowingVerdict.exit_reason != "STALED")
                .order_by(TradingShadowingVerdict.resolved_at.desc())
                .limit(limit_count)
            ).unique().all())
        except Exception as error:
            logger.exception("[DAO][SHADOWING_VERDICT] Failed to retrieve recent resolved verdicts — %s", error)
            raise

    def retrieve_resolved_in_window(
            self,
            start_datetime: datetime,
            end_datetime: datetime,
            limit_count: int,
    ) -> list[TradingShadowingVerdict]:
        from sqlalchemy.orm import joinedload
        try:
            return list(self.database_session.scalars(
                select(TradingShadowingVerdict)
                .options(joinedload(TradingShadowingVerdict.probe))
                .where(TradingShadowingVerdict.exit_reason.is_not(None))
                .where(TradingShadowingVerdict.exit_reason != "STALED")
                .where(TradingShadowingVerdict.resolved_at.is_not(None))
                .where(TradingShadowingVerdict.resolved_at >= start_datetime)
                .where(TradingShadowingVerdict.resolved_at <= end_datetime)
                .order_by(TradingShadowingVerdict.resolved_at.asc())
                .limit(limit_count)
            ).unique().all())
        except Exception as error:
            logger.exception(
                "[DAO][SHADOWING_VERDICT] Failed to retrieve resolved verdicts in range [%s, %s] — %s",
                start_datetime,
                end_datetime,
                error,
            )
            raise

    def retrieve_resolved_in_window_after_id(
            self,
            after_id_exclusive: int,
            start_datetime: datetime,
            end_datetime: datetime,
            limit_count: int,
    ) -> list[TradingShadowingVerdict]:
        from sqlalchemy.orm import joinedload
        try:
            return list(self.database_session.scalars(
                select(TradingShadowingVerdict)
                .options(joinedload(TradingShadowingVerdict.probe))
                .where(TradingShadowingVerdict.id > after_id_exclusive)
                .where(TradingShadowingVerdict.exit_reason.is_not(None))
                .where(TradingShadowingVerdict.exit_reason != "STALED")
                .where(TradingShadowingVerdict.resolved_at.is_not(None))
                .where(TradingShadowingVerdict.resolved_at >= start_datetime)
                .where(TradingShadowingVerdict.resolved_at <= end_datetime)
                .order_by(TradingShadowingVerdict.id.asc())
                .limit(limit_count)
            ).unique().all())
        except Exception as error:
            logger.exception(
                "[DAO][SHADOWING_VERDICT] Failed to retrieve resolved verdicts after id=%s in range [%s, %s] — %s",
                after_id_exclusive,
                start_datetime,
                end_datetime,
                error,
            )
            raise

    def count_resolved(self) -> int:
        from sqlalchemy import func
        try:
            return self.database_session.execute(
                select(func.count(TradingShadowingVerdict.id))
                .where(TradingShadowingVerdict.exit_reason.is_not(None))
                .where(TradingShadowingVerdict.exit_reason != "STALED")
            ).scalar_one_or_none() or 0
        except Exception as error:
            logger.exception("[DAO][SHADOWING_VERDICT] Failed to count resolved verdicts — %s", error)
            raise

    def retrieve_resolved_for_pair(self, pair_address: str, limit_count: int) -> list[TradingShadowingVerdict]:
        try:
            return list(self.database_session.scalars(
                select(TradingShadowingVerdict)
                .join(TradingShadowingProbe)
                .where(
                    TradingShadowingVerdict.exit_reason.is_not(None),
                    TradingShadowingProbe.pair_address == pair_address
                )
                .order_by(TradingShadowingVerdict.resolved_at.desc())
                .limit(limit_count)
            ).all())
        except Exception as error:
            logger.exception("[DAO][SHADOWING_VERDICT] Failed to retrieve resolved verdicts for pair %s — %s", pair_address, error)
            raise

    def retrieve_shadow_intelligence_status_summary(self) -> ShadowIntelligenceStatusSummary:
        from src.core.trading.shadowing.trading_shadowing_structures import ShadowIntelligenceStatusSummary
        from src.persistence.dao.trading_shadowing_probe_dao import TradingShadowingProbeDao

        resolved_outcome_count = self.count_resolved()
        probe_dao = TradingShadowingProbeDao(self.database_session)
        elapsed_hours = probe_dao.retrieve_oldest_probe_timestamp()

        return ShadowIntelligenceStatusSummary(
            resolved_outcome_count=resolved_outcome_count,
            elapsed_hours=elapsed_hours,
        )
