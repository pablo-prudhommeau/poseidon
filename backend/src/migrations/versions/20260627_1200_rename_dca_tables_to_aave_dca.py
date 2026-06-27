from __future__ import annotations

from alembic import op as operations

revision = "20260627_1200"
down_revision = "20260607_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    operations.drop_index("ix_dca_orders_strategy_id", table_name="dca_orders")
    operations.rename_table("dca_orders", "aave_dca_orders")
    operations.rename_table("dca_strategies", "aave_dca_strategies")
    operations.create_index(
        "ix_aave_dca_orders_strategy_id",
        "aave_dca_orders",
        ["strategy_id"],
    )


def downgrade() -> None:
    operations.drop_index("ix_aave_dca_orders_strategy_id", table_name="aave_dca_orders")
    operations.rename_table("aave_dca_orders", "dca_orders")
    operations.rename_table("aave_dca_strategies", "dca_strategies")
    operations.create_index("ix_dca_orders_strategy_id", "dca_orders", ["strategy_id"])
