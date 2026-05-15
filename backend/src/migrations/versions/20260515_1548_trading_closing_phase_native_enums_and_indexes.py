from __future__ import annotations

from alembic import op as operations

revision = "20260515_1548"
down_revision = "20260514_0534"
branch_labels = None
depends_on = None


def _create_supplemental_indexes() -> None:
    operations.create_index("ix_dca_orders_strategy_id", "dca_orders", ["strategy_id"])
    operations.create_index(
        "ix_trading_portfolio_snapshots_created_at",
        "trading_portfolio_snapshots",
        ["created_at"],
    )
    operations.create_index("ix_trading_positions_evaluation_id", "trading_positions", ["evaluation_id"])
    operations.create_index("ix_trading_shadowing_probes_probed_at", "trading_shadowing_probes", ["probed_at"])
    operations.create_index(
        "ix_trading_shadowing_probes_token_address_probed_at",
        "trading_shadowing_probes",
        ["token_address", "probed_at"],
    )
    operations.create_index(
        "ix_trading_shadowing_verdicts_created_at",
        "trading_shadowing_verdicts",
        ["created_at"],
    )
    operations.create_index(
        "ix_trading_shadowing_verdicts_resolved_at",
        "trading_shadowing_verdicts",
        ["resolved_at"],
    )
    operations.create_index("ix_trading_trades_created_at", "trading_trades", ["created_at"])


def _drop_supplemental_indexes() -> None:
    operations.drop_index("ix_trading_trades_created_at", table_name="trading_trades")
    operations.drop_index("ix_trading_shadowing_verdicts_resolved_at", table_name="trading_shadowing_verdicts")
    operations.drop_index("ix_trading_shadowing_verdicts_created_at", table_name="trading_shadowing_verdicts")
    operations.drop_index(
        "ix_trading_shadowing_probes_token_address_probed_at",
        table_name="trading_shadowing_probes",
    )
    operations.drop_index("ix_trading_shadowing_probes_probed_at", table_name="trading_shadowing_probes")
    operations.drop_index("ix_trading_positions_evaluation_id", table_name="trading_positions")
    operations.drop_index(
        "ix_trading_portfolio_snapshots_created_at",
        table_name="trading_portfolio_snapshots",
    )
    operations.drop_index("ix_dca_orders_strategy_id", table_name="dca_orders")


def _upgrade_postgresql_native_enums() -> None:
    operations.execute(
        "CREATE TYPE positionphase AS ENUM ('OPEN', 'PARTIAL', 'CLOSED', 'STALED', 'CLOSING')"
    )
    operations.execute("CREATE TYPE tradeside AS ENUM ('BUY', 'SELL')")
    operations.execute("CREATE TYPE executionstatus AS ENUM ('PAPER', 'LIVE')")
    operations.execute(
        "CREATE TYPE dcastrategystatus AS ENUM ('ACTIVE', 'PAUSED', 'COMPLETED', 'CANCELLED')"
    )
    operations.execute(
        "CREATE TYPE dcaorderstatus AS ENUM ("
        "'PENDING', "
        "'WAITING_USER_APPROVAL', "
        "'APPROVED', "
        "'WITHDRAWN_FROM_AAVE', "
        "'SWAPPED', "
        "'EXECUTED', "
        "'SKIPPED', "
        "'FAILED', "
        "'REJECTED'"
        ")"
    )
    operations.execute(
        """
        ALTER TABLE trading_positions
        ALTER
        COLUMN position_phase TYPE positionphase
        USING position_phase::positionphase
        """
    )
    operations.execute(
        """
        ALTER TABLE trading_trades
        ALTER
        COLUMN trade_side TYPE tradeside
        USING trade_side::tradeside
        """
    )
    operations.execute(
        """
        ALTER TABLE trading_trades
        ALTER
        COLUMN execution_status TYPE executionstatus
        USING execution_status::executionstatus
        """
    )
    operations.execute(
        """
        ALTER TABLE dca_strategies
        ALTER
        COLUMN strategy_status TYPE dcastrategystatus
        USING strategy_status::dcastrategystatus
        """
    )
    operations.execute(
        """
        ALTER TABLE dca_orders
        ALTER
        COLUMN order_status TYPE dcaorderstatus
        USING order_status::dcaorderstatus
        """
    )

    operations.execute(
        """
        UPDATE trading_positions position_row
        SET closed_at = CASE
                            WHEN position_row.position_phase = 'CLOSED'::positionphase
                    THEN latest_outcome.occurred_at
                            ELSE NULL
            END FROM (
            SELECT
                evaluation_id,
                occurred_at,
                ROW_NUMBER() OVER (
                    PARTITION BY evaluation_id
                    ORDER BY occurred_at DESC
                ) AS outcome_row_number
            FROM trading_outcomes
        ) latest_outcome
        WHERE position_row.evaluation_id = latest_outcome.evaluation_id
          AND latest_outcome.outcome_row_number = 1
          AND position_row.position_phase IN ('CLOSED'::positionphase
            , 'PARTIAL'::positionphase)
        """
    )


def _upgrade_sqlite_closed_at_backfill() -> None:
    operations.execute(
        """
        UPDATE trading_positions
        SET closed_at = (SELECT latest_outcome.occurred_at
                         FROM (SELECT evaluation_id,
                                      occurred_at,
                                      ROW_NUMBER() OVER (
                        PARTITION BY evaluation_id
                        ORDER BY occurred_at DESC
                    ) AS outcome_row_number
                               FROM trading_outcomes) latest_outcome
                         WHERE latest_outcome.evaluation_id = trading_positions.evaluation_id
                           AND latest_outcome.outcome_row_number = 1
                           AND trading_positions.position_phase = 'CLOSED')
        WHERE evaluation_id IN (SELECT evaluation_id
                                FROM (SELECT evaluation_id,
                                             ROW_NUMBER() OVER (
                        PARTITION BY evaluation_id
                        ORDER BY occurred_at DESC
                    ) AS outcome_row_number
                                      FROM trading_outcomes) latest_outcome
                                WHERE latest_outcome.outcome_row_number = 1)
          AND position_phase IN ('CLOSED', 'PARTIAL')
        """
    )


def _downgrade_postgresql_native_enums() -> None:
    operations.execute(
        """
        ALTER TABLE dca_orders
        ALTER
        COLUMN order_status TYPE TEXT
        USING order_status::TEXT
        """
    )
    operations.execute(
        """
        ALTER TABLE dca_strategies
        ALTER
        COLUMN strategy_status TYPE TEXT
        USING strategy_status::TEXT
        """
    )
    operations.execute(
        """
        ALTER TABLE trading_trades
        ALTER
        COLUMN execution_status TYPE TEXT
        USING execution_status::TEXT
        """
    )
    operations.execute(
        """
        ALTER TABLE trading_trades
        ALTER
        COLUMN trade_side TYPE TEXT
        USING trade_side::TEXT
        """
    )
    operations.execute(
        """
        ALTER TABLE trading_positions
        ALTER
        COLUMN position_phase TYPE TEXT
        USING position_phase::TEXT
        """
    )

    operations.execute("DROP TYPE dcaorderstatus")
    operations.execute("DROP TYPE dcastrategystatus")
    operations.execute("DROP TYPE executionstatus")
    operations.execute("DROP TYPE tradeside")
    operations.execute("DROP TYPE positionphase")


def upgrade() -> None:
    database_bind = operations.get_bind()
    if database_bind.dialect.name == "postgresql":
        _upgrade_postgresql_native_enums()
    else:
        _upgrade_sqlite_closed_at_backfill()

    _create_supplemental_indexes()


def downgrade() -> None:
    _drop_supplemental_indexes()

    database_bind = operations.get_bind()
    if database_bind.dialect.name == "postgresql":
        _downgrade_postgresql_native_enums()
