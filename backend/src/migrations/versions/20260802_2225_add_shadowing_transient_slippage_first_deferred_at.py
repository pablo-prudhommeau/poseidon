from __future__ import annotations

import sqlalchemy as schema
from alembic import op as operations

revision = "20260802_2225"
down_revision = "20260801_1240"
branch_labels = None
depends_on = None


def upgrade() -> None:
    operations.add_column(
        "trading_shadowing_verdicts",
        schema.Column("transient_slippage_first_deferred_at", schema.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    operations.drop_column("trading_shadowing_verdicts", "transient_slippage_first_deferred_at")
