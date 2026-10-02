from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.core.trading.shadowing.trading_shadowing_structures import TradingShadowingStaleCause
from src.core.trading.shadowing.trading_shadowing_verdict_tracker import (
    is_take_profit_percentage_aberrant_versus_entry,
)
from src.logging.logger import get_application_logger
from src.migrations.operations.migrations_operations_structures import (
    AberrantPriceVersusEntryShadowingVerdictBackfillResult,
)
from src.persistence.models import TradingShadowingVerdict

logger = get_application_logger(__name__)


def reclassify_take_profit_shadowing_verdicts_with_aberrant_price_versus_entry(
        database_session: Session,
) -> AberrantPriceVersusEntryShadowingVerdictBackfillResult:
    maximum_ratio: float = settings.TRADING_SHADOWING_ABERRANT_PRICE_VERSUS_ENTRY_MAXIMUM_RATIO
    minimum_aberrant_percentage: float = (maximum_ratio - 1.0) * 100.0
    candidate_verdicts: list[TradingShadowingVerdict] = list(
        database_session.scalars(
            select(TradingShadowingVerdict)
            .where(TradingShadowingVerdict.exit_reason == "TAKE_PROFIT_2")
            .where(TradingShadowingVerdict.realized_pnl_percentage > minimum_aberrant_percentage),
        ).all(),
    )

    reclassified_verdict_count: int = 0
    for verdict in candidate_verdicts:
        realized_profit_and_loss_percentage: Optional[float] = verdict.realized_pnl_percentage
        if realized_profit_and_loss_percentage is None:
            continue
        if not is_take_profit_percentage_aberrant_versus_entry(
                realized_profit_and_loss_percentage=realized_profit_and_loss_percentage,
        ):
            continue
        verdict.exit_reason = "STALED"
        verdict.stale_cause = TradingShadowingStaleCause.ABERRANT_PRICE_VERSUS_ENTRY
        verdict.realized_pnl_percentage = None
        verdict.realized_pnl_usd = None
        verdict.is_profitable = None
        reclassified_verdict_count += 1

    logger.info(
        "[MIGRATION][OPERATIONS][ABERRANT_PRICE] Reclassified %d / %d take-profit verdicts as STALED",
        reclassified_verdict_count,
        len(candidate_verdicts),
    )
    return AberrantPriceVersusEntryShadowingVerdictBackfillResult(
        candidate_verdict_count=len(candidate_verdicts),
        reclassified_verdict_count=reclassified_verdict_count,
    )
