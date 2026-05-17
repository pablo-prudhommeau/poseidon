from __future__ import annotations

import sqlalchemy as schema
from alembic import op as operations

revision = "20260516_0700"
down_revision = "20260515_1548"
branch_labels = None
depends_on = None


def upgrade() -> None:
    operations.execute("DELETE FROM trading_cortex_model_manifests")

    operations.add_column(
        "trading_cortex_model_manifests",
        schema.Column("training_summary", schema.JSON(), nullable=False),
    )

    bind = operations.get_bind()
    if bind.engine.name == 'postgresql':
        operations.execute("""
                           UPDATE trading_evaluations
                           SET shadowing_summary = replace(shadowing_summary::text, 'capital_velocity', 'expected_pnl_velocity')::jsonb
                           WHERE shadowing_summary IS NOT NULL;
                           """)
        operations.execute("""
                           UPDATE trading_evaluations
                           SET shadowing_metrics = replace(shadowing_metrics::text, 'capital_velocity', 'expected_pnl_velocity')::jsonb
                           WHERE shadowing_metrics IS NOT NULL;
                           """)
        operations.execute("""
                           UPDATE trading_shadowing_probes
                           SET shadowing_summary = replace(shadowing_summary::text, 'capital_velocity', 'expected_pnl_velocity')::jsonb
                           WHERE shadowing_summary IS NOT NULL;
                           """)
        operations.execute("""
                           UPDATE trading_shadowing_probes
                           SET shadowing_metrics = replace(shadowing_metrics::text, 'capital_velocity', 'expected_pnl_velocity')::jsonb
                           WHERE shadowing_metrics IS NOT NULL;
                           """)
    else:
        # SQLite
        operations.execute("""
                           UPDATE trading_evaluations
                           SET shadowing_summary = REPLACE(shadowing_summary, 'capital_velocity', 'expected_pnl_velocity')
                           WHERE shadowing_summary IS NOT NULL;
                           """)
        operations.execute("""
                           UPDATE trading_evaluations
                           SET shadowing_metrics = REPLACE(shadowing_metrics, 'capital_velocity', 'expected_pnl_velocity')
                           WHERE shadowing_metrics IS NOT NULL;
                           """)
        operations.execute("""
                           UPDATE trading_shadowing_probes
                           SET shadowing_summary = REPLACE(shadowing_summary, 'capital_velocity', 'expected_pnl_velocity')
                           WHERE shadowing_summary IS NOT NULL;
                           """)
        operations.execute("""
                           UPDATE trading_shadowing_probes
                           SET shadowing_metrics = REPLACE(shadowing_metrics, 'capital_velocity', 'expected_pnl_velocity')
                           WHERE shadowing_metrics IS NOT NULL;
                           """)


def downgrade() -> None:
    with operations.batch_alter_table("trading_cortex_model_manifests") as batch_alter:
        batch_alter.drop_column("training_summary")
