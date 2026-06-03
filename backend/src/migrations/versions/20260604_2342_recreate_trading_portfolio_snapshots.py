from __future__ import annotations

import sqlalchemy as schema
from alembic import op as operations

revision = "20260604_2342"
down_revision = "20260531_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    operations.drop_index("ix_trading_portfolio_snapshots_created_at", table_name="trading_portfolio_snapshots")
    operations.drop_table("trading_portfolio_snapshots")

    operations.create_table(
        "trading_portfolio_snapshots",
        schema.Column("id", schema.Integer(), primary_key=True, autoincrement=True, nullable=False),
        schema.Column("total_equity_value", schema.Float(), nullable=False),
        schema.Column("deployable_cash_usd", schema.Float(), nullable=False),
        schema.Column("holdings_mark_to_market_usd", schema.Float(), nullable=False),
        schema.Column("wallet_auxiliary_assets_usd", schema.Float(), nullable=False),
        schema.Column("sizing_capital_usd", schema.Float(), nullable=False),
        schema.Column("created_at", schema.DateTime(timezone=True), nullable=False),
    )
    operations.create_index(
        "ix_trading_portfolio_snapshots_created_at",
        "trading_portfolio_snapshots",
        ["created_at"],
    )


def downgrade() -> None:
    operations.drop_index("ix_trading_portfolio_snapshots_created_at", table_name="trading_portfolio_snapshots")
    operations.drop_table("trading_portfolio_snapshots")

    operations.create_table(
        "trading_portfolio_snapshots",
        schema.Column("id", schema.Integer(), primary_key=True, autoincrement=True, nullable=False),
        schema.Column("total_equity_value", schema.Float(), nullable=False),
        schema.Column("available_cash_balance", schema.Float(), nullable=False),
        schema.Column("active_holdings_value", schema.Float(), nullable=False),
        schema.Column("created_at", schema.DateTime(timezone=True), nullable=False),
    )
    operations.create_index(
        "ix_trading_portfolio_snapshots_created_at",
        "trading_portfolio_snapshots",
        ["created_at"],
    )
