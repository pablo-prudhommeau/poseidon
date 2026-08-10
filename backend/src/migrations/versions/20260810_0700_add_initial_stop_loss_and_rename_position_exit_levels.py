from __future__ import annotations

import sqlalchemy as schema
from alembic import op as operations

revision = "20260810_0700"
down_revision = "20260802_2225"
branch_labels = None
depends_on = None


def upgrade() -> None:
    operations.execute(schema.text("DELETE FROM trading_outcomes"))
    operations.execute(schema.text("DELETE FROM trading_trades"))
    operations.execute(schema.text("DELETE FROM trading_positions"))
    operations.execute(schema.text("DELETE FROM trading_evaluations"))
    operations.execute(schema.text("DELETE FROM trading_portfolio_snapshots"))
    operations.add_column(
        "trading_positions",
        schema.Column("initial_stop_loss_price", schema.Float(), nullable=True),
    )
    operations.execute(
        schema.text(
            """
            UPDATE trading_positions
            SET initial_stop_loss_price = stop_loss_price
            """
        )
    )
    operations.alter_column(
        "trading_positions",
        "initial_stop_loss_price",
        existing_type=schema.Float(),
        nullable=False,
    )
    operations.alter_column(
        "trading_positions",
        "take_profit_tier_1_price",
        new_column_name="breakeven_arm_price",
        existing_type=schema.Float(),
        nullable=False,
    )
    operations.alter_column(
        "trading_positions",
        "take_profit_tier_2_price",
        new_column_name="take_profit_price",
        existing_type=schema.Float(),
        nullable=False,
    )


def downgrade() -> None:
    operations.alter_column(
        "trading_positions",
        "breakeven_arm_price",
        new_column_name="take_profit_tier_1_price",
        existing_type=schema.Float(),
        nullable=False,
    )
    operations.alter_column(
        "trading_positions",
        "take_profit_price",
        new_column_name="take_profit_tier_2_price",
        existing_type=schema.Float(),
        nullable=False,
    )
    operations.drop_column("trading_positions", "initial_stop_loss_price")
