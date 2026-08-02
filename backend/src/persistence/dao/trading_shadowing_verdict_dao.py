from datetime import datetime
from typing import Iterator, Optional

from sqlalchemy import select, Select
from sqlalchemy.orm import Session, contains_eager, joinedload, load_only

from src.logging.logger import get_application_logger
from src.persistence.models import TradingShadowingVerdict, TradingShadowingProbe

logger = get_application_logger(__name__)


class TradingShadowingVerdictDao:
    @staticmethod
    def _pending_verdicts_load_profile():
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

    def _apply_shadow_gate_eligibility_requirements(self, statement):
        return (
            statement
            .join(TradingShadowingProbe)
            .where(TradingShadowingProbe.shadowing_regime.is_not(None))
            .where(TradingShadowingProbe.shadowing_metrics.is_not(None))
        )

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

    def _resolved_for_cortex_training_statement(
            self,
            include_staled_verdicts: bool,
            resolved_since: Optional[datetime] = None,
    ) -> Select:
        statement = (
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
                contains_eager(TradingShadowingVerdict.probe).load_only(
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
                    TradingShadowingProbe.promotion_score,
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
                    TradingShadowingProbe.shadowing_regime,
                    TradingShadowingProbe.shadowing_metrics,
                ),
            )
            .where(TradingShadowingVerdict.realized_pnl_percentage.is_not(None))
            .where(TradingShadowingVerdict.realized_pnl_usd.is_not(None))
            .where(TradingShadowingVerdict.holding_duration_minutes.is_not(None))
            .where(TradingShadowingVerdict.is_profitable.is_not(None))
            .where(TradingShadowingVerdict.exit_reason.is_not(None))
            .where(TradingShadowingVerdict.resolved_at.is_not(None))
            .where(TradingShadowingProbe.shadowing_regime.is_not(None))
            .where(TradingShadowingProbe.shadowing_metrics.is_not(None))
        )
        if not include_staled_verdicts:
            statement = statement.where(TradingShadowingVerdict.exit_reason != "STALED")
        if resolved_since is not None:
            statement = statement.where(TradingShadowingVerdict.resolved_at >= resolved_since)
        return statement.order_by(TradingShadowingVerdict.resolved_at.asc())

    def stream_resolved_for_cortex_training(
            self,
            batch_size: int,
            include_staled_verdicts: bool,
    ) -> Iterator[TradingShadowingVerdict]:
        try:
            result = self.database_session.scalars(
                self._resolved_for_cortex_training_statement(include_staled_verdicts=include_staled_verdicts)
                .execution_options(stream_results=True, yield_per=batch_size)
            )
            yield from result
        except Exception as error:
            logger.exception("[DAO][SHADOWING_VERDICT] Failed to stream cortex training verdicts — %s", error)
            raise

    def stream_resolved_for_cortex_evaluation(
            self,
            batch_size: int,
            resolved_since: datetime,
            limit_count: int,
    ) -> Iterator[TradingShadowingVerdict]:
        try:
            result = self.database_session.scalars(
                self._resolved_for_cortex_training_statement(
                    include_staled_verdicts=True,
                    resolved_since=resolved_since,
                )
                .limit(limit_count)
                .execution_options(stream_results=True, yield_per=batch_size)
            )
            yield from result
        except Exception as error:
            logger.exception(
                "[DAO][SHADOWING_VERDICT] Failed to stream cortex evaluation verdicts since %s — %s",
                resolved_since,
                error,
            )
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
                        TradingShadowingProbe.promotion_score,
                        TradingShadowingProbe.cortex_inference_summary,
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

    def count_resolved_shadowing_and_cortex_inference_aware_outcomes(self, include_staled_verdicts: bool = False) -> int:
        from sqlalchemy import func
        try:
            statement = (
                select(func.count(TradingShadowingVerdict.id))
                .where(TradingShadowingVerdict.realized_pnl_percentage.is_not(None))
                .where(TradingShadowingVerdict.realized_pnl_usd.is_not(None))
                .where(TradingShadowingVerdict.holding_duration_minutes.is_not(None))
                .where(TradingShadowingVerdict.is_profitable.is_not(None))
                .where(TradingShadowingVerdict.exit_reason.is_not(None))
                .where(TradingShadowingVerdict.resolved_at.is_not(None))
            )
            if not include_staled_verdicts:
                statement = statement.where(TradingShadowingVerdict.exit_reason != "STALED")
            statement = self._apply_shadow_gate_eligibility_requirements(statement)
            return self.database_session.execute(statement).scalar_one_or_none() or 0
        except Exception as error:
            logger.exception("[DAO][SHADOWING_VERDICT] Failed to count shadowing/cortex-aware verdicts — %s", error)
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
