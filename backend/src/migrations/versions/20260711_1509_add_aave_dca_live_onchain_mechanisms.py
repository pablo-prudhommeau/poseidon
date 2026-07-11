from __future__ import annotations

import sqlalchemy as schema
from alembic import op as operations

revision = "20260711_1509"
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

    operations.execute(schema.text("TRUNCATE TABLE aave_dca_strategies RESTART IDENTITY CASCADE"))

    operations.add_column(
        "aave_dca_strategies",
        schema.Column("target_asset_decimals", schema.Integer(), nullable=True),
    )
    operations.execute(
        schema.text("UPDATE aave_dca_strategies SET target_asset_decimals = 8 WHERE target_asset_decimals IS NULL")
    )
    with operations.batch_alter_table("aave_dca_strategies") as batch_operations:
        batch_operations.alter_column(
            "target_asset_decimals",
            existing_type=schema.Integer(),
            nullable=False,
        )

    operations.add_column(
        "aave_dca_orders",
        schema.Column("pipeline_attempt_count", schema.Integer(), nullable=False),
    )
    operations.add_column(
        "aave_dca_orders",
        schema.Column("next_attempt_at", schema.DateTime(timezone=True), nullable=True),
    )
    operations.add_column(
        "aave_dca_orders",
        schema.Column("suspension_reason", schema.String(length=100), nullable=True),
    )
    operations.add_column(
        "aave_dca_orders",
        schema.Column("telegram_message_id", schema.Integer(), nullable=True),
    )
    operations.add_column(
        "aave_dca_orders",
        schema.Column("allocation_decision", schema.String(length=64), nullable=True),
    )
    operations.add_column(
        "aave_dca_orders",
        schema.Column("allocation_multiplier", schema.Float(), nullable=True),
    )
    operations.add_column(
        "aave_dca_orders",
        schema.Column("dry_powder_delta", schema.Float(), nullable=True),
    )
    operations.add_column(
        "aave_dca_orders",
        schema.Column("reference_market_price", schema.Float(), nullable=True),
    )
    operations.add_column(
        "aave_dca_orders",
        schema.Column("pipeline_operations", schema.JSON(), nullable=True),
    )

    with operations.batch_alter_table("aave_dca_orders") as batch_operations:
        batch_operations.drop_column("transaction_hash")
        batch_operations.drop_column("allocation_decision_description")


def downgrade() -> None:
    with operations.batch_alter_table("aave_dca_orders") as batch_operations:
        batch_operations.add_column(schema.Column("allocation_decision_description", schema.String(length=128), nullable=True))
        batch_operations.add_column(schema.Column("transaction_hash", schema.String(length=128), nullable=True))

    operations.drop_column("aave_dca_orders", "pipeline_operations")
    operations.drop_column("aave_dca_orders", "reference_market_price")
    operations.drop_column("aave_dca_orders", "dry_powder_delta")
    operations.drop_column("aave_dca_orders", "allocation_multiplier")
    operations.drop_column("aave_dca_orders", "allocation_decision")
    operations.drop_column("aave_dca_orders", "telegram_message_id")
    operations.drop_column("aave_dca_orders", "suspension_reason")
    operations.drop_column("aave_dca_orders", "next_attempt_at")
    operations.drop_column("aave_dca_orders", "pipeline_attempt_count")
    operations.drop_column("aave_dca_strategies", "target_asset_decimals")

    operations.drop_index("ix_aave_dca_orders_strategy_id", table_name="aave_dca_orders")
    operations.rename_table("aave_dca_orders", "dca_orders")
    operations.rename_table("aave_dca_strategies", "dca_strategies")
    operations.create_index("ix_dca_orders_strategy_id", "dca_orders", ["strategy_id"])
