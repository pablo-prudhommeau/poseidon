from __future__ import annotations

from alembic import op as operations
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.logging.logger import get_application_logger
from src.migrations.operations.migrations_operations_reclassify_aberrant_price_versus_entry_shadowing_verdicts import (
    reclassify_take_profit_shadowing_verdicts_with_aberrant_price_versus_entry,
)

revision = "20261002_2201"
down_revision = "20260911_1539"
branch_labels = None
depends_on = None

logger = get_application_logger(__name__)

_RESOLVED_EXCLUDING_STALED_PREDICATE = "exit_reason IS NOT NULL AND exit_reason <> 'STALED'"


def upgrade() -> None:
    database_session = Session(bind=operations.get_bind())
    try:
        backfill_result = reclassify_take_profit_shadowing_verdicts_with_aberrant_price_versus_entry(
            database_session=database_session,
        )
        database_session.commit()
        logger.info(
            "[MIGRATION][OPERATIONS][ABERRANT_PRICE] Completed — candidates=%d reclassified=%d",
            backfill_result.candidate_verdict_count,
            backfill_result.reclassified_verdict_count,
        )
    except Exception as error:
        logger.exception(
            "[MIGRATION][OPERATIONS][ABERRANT_PRICE] Failed to reclassify aberrant price verdicts — %s",
            error,
        )
        raise
    finally:
        database_session.close()

    operations.create_index(
        "ix_trading_shadowing_verdicts_resolved_at_excluding_staled",
        "trading_shadowing_verdicts",
        [text("resolved_at DESC")],
        postgresql_where=text(_RESOLVED_EXCLUDING_STALED_PREDICATE),
        sqlite_where=text(_RESOLVED_EXCLUDING_STALED_PREDICATE),
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported for aberrant price shadowing verdict backfill")
