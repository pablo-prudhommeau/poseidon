from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.core.trading.shadowing.trading_shadowing_structures import TradingShadowingStatusSummary
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_shadowing_probe_dao import TradingShadowingProbeDao
from src.persistence.models import TradingShadowingVerdict, TradingShadowingProbe

logger = get_application_logger(__name__)


class TradingShadowingVerdictDao:
    @staticmethod
    def _pending_verdicts_load_profile():
        from sqlalchemy.orm import joinedload, load_only
        return (
            load_only(
                TradingShadowingVerdict.id,
                TradingShadowingVerdict.probe_id,
                TradingShadowingVerdict.take_profit_tier_1_price,
                TradingShadowingVerdict.take_profit_tier_2_price,
                TradingShadowingVerdict.stop_loss_price,
                TradingShadowingVerdict.take_profit_tier_1_hit_at,
                TradingShadowingVerdict.take_profit_tier_2_hit_at,
                TradingShadowingVerdict.stop_loss_hit_at,
                TradingShadowingVerdict.exit_reason,
                TradingShadowingVerdict.realized_pnl_percentage,
                TradingShadowingVerdict.realized_pnl_usd,
                TradingShadowingVerdict.holding_duration_minutes,
                TradingShadowingVerdict.is_profitable,
                TradingShadowingVerdict.resolved_at,
                TradingShadowingVerdict.created_at,
            ),
            joinedload(TradingShadowingVerdict.probe).load_only(
                TradingShadowingProbe.id,
                TradingShadowingProbe.token_symbol,
                TradingShadowingProbe.blockchain_network,
                TradingShadowingProbe.token_address,
                TradingShadowingProbe.pair_address,
                TradingShadowingProbe.dex_id,
                TradingShadowingProbe.entry_price_usd,
                TradingShadowingProbe.order_notional_value_usd,
                TradingShadowingProbe.probed_at,
            ),
        )

    def __init__(self, database_session: Session) -> None:
        self.database_session = database_session

    def _apply_shadow_probe_training_requirements(self, statement):
        from sqlalchemy import and_, or_
        conditions = []

        if settings.TRADING_GATE_SHADOWING_TOXIC_METRICS_ENABLED:
            conditions.append(
                and_(
                    TradingShadowingProbe.shadowing_summary.is_not(None),
                    TradingShadowingProbe.shadowing_metrics.is_not(None)
                )
            )

        if settings.TRADING_GATE_CORTEX_ENABLED:
            conditions.append(
                TradingShadowingProbe.cortex_inference_summary.is_not(None)
            )

        if not conditions:
            return statement

        return statement.join(TradingShadowingProbe).where(or_(*conditions))

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
                .options(*self._pending_verdicts_load_profile())
                .where(TradingShadowingVerdict.exit_reason.is_(None))
                .order_by(TradingShadowingVerdict.created_at.desc())
                .limit(limit_count)
            ).unique().all())
        except Exception as error:
            logger.exception("[DAO][SHADOWING_VERDICT] Failed to retrieve pending verdicts — %s", error)
            raise

    def retrieve_pending_verdicts_after_id(
            self,
            after_id_exclusive: int,
            limit_count: int,
    ) -> list[TradingShadowingVerdict]:
        try:
            return list(self.database_session.scalars(
                select(TradingShadowingVerdict)
                .options(*self._pending_verdicts_load_profile())
                .where(TradingShadowingVerdict.id > after_id_exclusive)
                .where(TradingShadowingVerdict.exit_reason.is_(None))
                .order_by(TradingShadowingVerdict.id.asc())
                .limit(limit_count)
            ).unique().all())
        except Exception as error:
            logger.exception(
                "[DAO][SHADOWING_VERDICT] Failed to retrieve pending verdicts after id=%s — %s",
                after_id_exclusive,
                error,
            )
            raise

    def retrieve_resolved_for_cortex_training(self) -> list[TradingShadowingVerdict]:
        from sqlalchemy.orm import joinedload, load_only
        try:
            return list(self.database_session.scalars(
                select(TradingShadowingVerdict)
                .join(TradingShadowingProbe)
                .options(
                    load_only(
                        TradingShadowingVerdict.id,
                        TradingShadowingVerdict.probe_id,
                        TradingShadowingVerdict.realized_pnl_percentage,
                        TradingShadowingVerdict.realized_pnl_usd,
                        TradingShadowingVerdict.holding_duration_minutes,
                        TradingShadowingVerdict.is_profitable,
                        TradingShadowingVerdict.exit_reason,
                        TradingShadowingVerdict.resolved_at,
                    ),
                    joinedload(TradingShadowingVerdict.probe).load_only(
                        TradingShadowingProbe.id,
                        TradingShadowingProbe.token_symbol,
                        TradingShadowingProbe.blockchain_network,
                        TradingShadowingProbe.dex_id,
                        TradingShadowingProbe.pair_address,
                        TradingShadowingProbe.candidate_rank,
                        TradingShadowingProbe.quality_score,
                        TradingShadowingProbe.token_age_hours,
                        TradingShadowingProbe.liquidity_usd,
                        TradingShadowingProbe.market_cap_usd,
                        TradingShadowingProbe.fully_diluted_valuation_usd,
                        TradingShadowingProbe.dexscreener_boost,
                        TradingShadowingProbe.volume_m5_usd,
                        TradingShadowingProbe.volume_h1_usd,
                        TradingShadowingProbe.volume_h6_usd,
                        TradingShadowingProbe.volume_h24_usd,
                        TradingShadowingProbe.price_change_percentage_m5,
                        TradingShadowingProbe.price_change_percentage_h1,
                        TradingShadowingProbe.price_change_percentage_h6,
                        TradingShadowingProbe.price_change_percentage_h24,
                        TradingShadowingProbe.transaction_count_m5,
                        TradingShadowingProbe.transaction_count_h1,
                        TradingShadowingProbe.transaction_count_h6,
                        TradingShadowingProbe.transaction_count_h24,
                        TradingShadowingProbe.buy_to_sell_ratio,
                        TradingShadowingProbe.order_notional_value_usd,
                        TradingShadowingProbe.shadowing_summary,
                        TradingShadowingProbe.shadowing_metrics,
                    ),
                )
                .where(TradingShadowingVerdict.realized_pnl_percentage.is_not(None))
                .where(TradingShadowingVerdict.realized_pnl_usd.is_not(None))
                .where(TradingShadowingVerdict.holding_duration_minutes.is_not(None))
                .where(TradingShadowingVerdict.is_profitable.is_not(None))
                .where(TradingShadowingVerdict.exit_reason.is_not(None))
                .where(TradingShadowingVerdict.exit_reason != "STALED")
                .where(TradingShadowingVerdict.resolved_at.is_not(None))
                .where(TradingShadowingProbe.shadowing_summary.is_not(None))
                .where(TradingShadowingProbe.shadowing_metrics.is_not(None))
                .order_by(TradingShadowingVerdict.resolved_at.asc())
            ).unique().all())
        except Exception as error:
            logger.exception("[DAO][SHADOWING_VERDICT] Failed to retrieve cortex training verdicts — %s", error)
            raise

    def count_staled_verdicts(self) -> int:
        from sqlalchemy import func
        try:
            return self.database_session.scalar(
                select(func.count())
                .select_from(TradingShadowingVerdict)
                .where(TradingShadowingVerdict.exit_reason == "STALED")
            ) or 0
        except Exception as error:
            logger.exception("[DAO][SHADOWING_VERDICT] Failed to count STALED verdicts — %s", error)
            raise

    def retrieve_recent_resolved(self, limit_count: int) -> list[TradingShadowingVerdict]:
        from sqlalchemy.orm import joinedload, load_only
        try:
            return list(self.database_session.scalars(
                select(TradingShadowingVerdict)
                .options(
                    load_only(
                        TradingShadowingVerdict.id,
                        TradingShadowingVerdict.probe_id,
                        TradingShadowingVerdict.exit_reason,
                        TradingShadowingVerdict.realized_pnl_percentage,
                        TradingShadowingVerdict.realized_pnl_usd,
                        TradingShadowingVerdict.holding_duration_minutes,
                        TradingShadowingVerdict.is_profitable,
                        TradingShadowingVerdict.resolved_at,
                    ),
                    joinedload(TradingShadowingVerdict.probe).load_only(
                        TradingShadowingProbe.id,
                        TradingShadowingProbe.token_symbol,
                        TradingShadowingProbe.token_address,
                        TradingShadowingProbe.quality_score,
                        TradingShadowingProbe.liquidity_usd,
                        TradingShadowingProbe.market_cap_usd,
                        TradingShadowingProbe.volume_m5_usd,
                        TradingShadowingProbe.volume_h1_usd,
                        TradingShadowingProbe.volume_h6_usd,
                        TradingShadowingProbe.volume_h24_usd,
                        TradingShadowingProbe.price_change_percentage_m5,
                        TradingShadowingProbe.price_change_percentage_h1,
                        TradingShadowingProbe.price_change_percentage_h6,
                        TradingShadowingProbe.price_change_percentage_h24,
                        TradingShadowingProbe.token_age_hours,
                        TradingShadowingProbe.transaction_count_m5,
                        TradingShadowingProbe.transaction_count_h1,
                        TradingShadowingProbe.transaction_count_h6,
                        TradingShadowingProbe.transaction_count_h24,
                        TradingShadowingProbe.buy_to_sell_ratio,
                        TradingShadowingProbe.fully_diluted_valuation_usd,
                        TradingShadowingProbe.dexscreener_boost,
                    ),
                )
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
        from sqlalchemy.orm import joinedload, load_only
        try:
            verdicts = list(self.database_session.scalars(
                select(TradingShadowingVerdict)
                .options(
                    load_only(
                        TradingShadowingVerdict.id,
                        TradingShadowingVerdict.probe_id,
                        TradingShadowingVerdict.exit_reason,
                        TradingShadowingVerdict.realized_pnl_percentage,
                        TradingShadowingVerdict.realized_pnl_usd,
                        TradingShadowingVerdict.is_profitable,
                        TradingShadowingVerdict.resolved_at,
                    ),
                    joinedload(TradingShadowingVerdict.probe).load_only(
                        TradingShadowingProbe.id,
                        TradingShadowingProbe.order_notional_value_usd,
                        TradingShadowingProbe.cortex_inference_summary,
                    ),
                )
                .where(TradingShadowingVerdict.exit_reason.is_not(None))
                .where(TradingShadowingVerdict.exit_reason != "STALED")
                .where(TradingShadowingVerdict.resolved_at.is_not(None))
                .where(TradingShadowingVerdict.resolved_at >= start_datetime)
                .where(TradingShadowingVerdict.resolved_at <= end_datetime)
                .order_by(TradingShadowingVerdict.resolved_at.desc())
                .limit(limit_count)
            ).unique().all())
            verdicts.reverse()
            return verdicts
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
        from sqlalchemy.orm import joinedload, load_only
        try:
            return list(self.database_session.scalars(
                select(TradingShadowingVerdict)
                .options(
                    load_only(
                        TradingShadowingVerdict.id,
                        TradingShadowingVerdict.probe_id,
                        TradingShadowingVerdict.exit_reason,
                        TradingShadowingVerdict.realized_pnl_percentage,
                        TradingShadowingVerdict.realized_pnl_usd,
                        TradingShadowingVerdict.is_profitable,
                        TradingShadowingVerdict.resolved_at,
                    ),
                    joinedload(TradingShadowingVerdict.probe).load_only(
                        TradingShadowingProbe.id,
                        TradingShadowingProbe.order_notional_value_usd,
                        TradingShadowingProbe.cortex_inference_summary,
                    ),
                )
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

    def count_resolved_with_shadowing_and_cortex_inference(self) -> int:
        from sqlalchemy import func
        try:
            statement = (
                select(func.count(TradingShadowingVerdict.id))
                .where(TradingShadowingVerdict.exit_reason.is_not(None))
                .where(TradingShadowingVerdict.exit_reason != "STALED")
            )
            statement = self._apply_shadow_probe_training_requirements(statement)
            return self.database_session.execute(statement).scalar_one_or_none() or 0
        except Exception as error:
            logger.exception("[DAO][SHADOWING_VERDICT] Failed to count resolved verdicts — %s", error)
            raise

    def count_resolved(self) -> int:
        from sqlalchemy import func
        try:
            statement = (
                select(func.count(TradingShadowingVerdict.id))
                .where(TradingShadowingVerdict.exit_reason.is_not(None))
                .where(TradingShadowingVerdict.exit_reason != "STALED")
            )
            return self.database_session.execute(statement).scalar_one_or_none() or 0
        except Exception as error:
            logger.exception("[DAO][SHADOWING_VERDICT] Failed to count resolved verdicts — %s", error)
            raise

    def retrieve_resolved_for_pair(self, pair_address: str, limit_count: int) -> list[TradingShadowingVerdict]:
        from sqlalchemy.orm import joinedload
        try:
            return list(self.database_session.scalars(
                select(TradingShadowingVerdict)
                .join(TradingShadowingProbe)
                .options(joinedload(TradingShadowingVerdict.probe))
                .where(
                    TradingShadowingVerdict.exit_reason.is_not(None),
                    TradingShadowingProbe.pair_address == pair_address
                )
                .order_by(TradingShadowingVerdict.resolved_at.desc())
                .limit(limit_count)
            ).unique().all())
        except Exception as error:
            logger.exception("[DAO][SHADOWING_VERDICT] Failed to retrieve resolved verdicts for pair %s — %s", pair_address, error)
            raise

    def retrieve_shadow_intelligence_status_summary(self) -> TradingShadowingStatusSummary:
        resolved_outcome_count = self.count_resolved()
        resolved_shadowing_and_cortex_inference_aware_outcome_count = self.count_resolved_with_shadowing_and_cortex_inference()
        probe_dao = TradingShadowingProbeDao(self.database_session)
        elapsed_hours = probe_dao.retrieve_oldest_probe_timestamp()

        return TradingShadowingStatusSummary(
            resolved_outcome_count=resolved_outcome_count,
            resolved_shadowing_and_cortex_inference_aware_outcome_count=resolved_shadowing_and_cortex_inference_aware_outcome_count,
            elapsed_hours=elapsed_hours,
        )
