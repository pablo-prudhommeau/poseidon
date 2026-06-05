from __future__ import annotations

from alembic import op as operations
from sqlalchemy.orm import Session

from src.logging.logger import get_application_logger
from src.migrations.operations.migrations_operations_reclassify_honeypot_shadowing_verdicts import (
    reclassify_profitable_shadowing_verdicts_with_active_freeze_authority,
)

revision = "20260605_0207"
down_revision = "20260604_2342"
branch_labels = None
depends_on = None

logger = get_application_logger(__name__)


def upgrade() -> None:
    database_session = Session(bind=operations.get_bind())
    try:
        backfill_result = reclassify_profitable_shadowing_verdicts_with_active_freeze_authority(
            database_session=database_session,
        )
        database_session.commit()
        logger.info(
            "[MIGRATION][OPERATIONS][HONEYPOT] Completed — candidates=%d reclassified=%d",
            backfill_result.candidate_verdict_count,
            backfill_result.reclassified_verdict_count,
        )
    finally:
        database_session.close()


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported for honeypot shadowing verdict backfill")
