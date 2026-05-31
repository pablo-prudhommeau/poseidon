from __future__ import annotations

import sqlalchemy as schema
from alembic import op as operations

revision = "20260531_1200"
down_revision = "20260529_1200"
branch_labels = None
depends_on = None


def _backfill_position_exit_reasons(connection) -> None:
    positions = connection.execute(
        schema.text(
            """
            SELECT id, evaluation_id, position_phase
            FROM trading_positions
            WHERE exit_reason IS NULL
            """,
        ),
    ).fetchall()

    latest_outcome_query = schema.text(
        """
        SELECT exit_reason
        FROM trading_outcomes
        WHERE evaluation_id = :evaluation_id
        ORDER BY occurred_at DESC, id DESC
        LIMIT 1
        """,
    )
    update_query = schema.text(
        """
        UPDATE trading_positions
        SET exit_reason = :exit_reason
        WHERE id = :position_id
        """,
    )

    for position_id, evaluation_id, position_phase in positions:
        if position_phase == "OPEN":
            continue

        outcome_row = connection.execute(
            latest_outcome_query,
            {"evaluation_id": evaluation_id},
        ).fetchone()
        if outcome_row is None:
            continue

        connection.execute(
            update_query,
            {"exit_reason": outcome_row[0], "position_id": position_id},
        )


def _backfill_outcome_exit_reasons(connection) -> None:
    connection.execute(
        schema.text(
            """
            UPDATE trading_outcomes AS outcome
            SET exit_reason = position.exit_reason
            FROM trading_positions AS position
            WHERE position.evaluation_id = outcome.evaluation_id
              AND position.exit_reason IS NOT NULL
            """,
        ),
    )


def upgrade() -> None:
    operations.add_column(
        "trading_positions",
        schema.Column("exit_reason", schema.String(length=64), nullable=True),
    )

    connection = operations.get_bind()
    _backfill_position_exit_reasons(connection)
    operations.drop_column("trading_outcomes", "exit_reason")


def downgrade() -> None:
    operations.add_column(
        "trading_outcomes",
        schema.Column(
            "exit_reason",
            schema.String(length=64),
            nullable=False,
            server_default="UNKNOWN",
        ),
    )
    operations.alter_column("trading_outcomes", "exit_reason", server_default=None)

    connection = operations.get_bind()
    _backfill_outcome_exit_reasons(connection)
    operations.drop_column("trading_positions", "exit_reason")
