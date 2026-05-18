from __future__ import annotations

import sqlalchemy as schema
from alembic import op as operations

revision = "20260518_0152"
down_revision = "20260516_0700"
branch_labels = None
depends_on = None


def upgrade() -> None:
    operations.execute("DELETE FROM trading_cortex_model_manifests")
    operations.execute("UPDATE trading_evaluations SET cortex_inference_summary = NULL")
    operations.execute("UPDATE trading_shadowing_probes SET cortex_inference_summary = NULL")
    with operations.batch_alter_table("trading_evaluations") as batch_alter:
        batch_alter.alter_column("shadowing_summary", new_column_name="shadowing_regime")
    with operations.batch_alter_table("trading_shadowing_probes") as batch_alter:
        batch_alter.alter_column("shadowing_summary", new_column_name="shadowing_regime")
    operations.execute("UPDATE trading_evaluations SET shadowing_regime = NULL")
    operations.execute("UPDATE trading_shadowing_probes SET shadowing_regime = NULL")
    with operations.batch_alter_table("trading_cortex_model_manifests") as batch_alter:
        batch_alter.add_column(
            schema.Column("predicted_holding_time_root_mean_squared_error", schema.Float(), nullable=False),
        )
        batch_alter.add_column(
            schema.Column("predicted_holding_time_minutes_model_path", schema.String(length=512), nullable=False),
        )


def downgrade() -> None:
    operations.execute("DELETE FROM trading_cortex_model_manifests")
    operations.execute("UPDATE trading_evaluations SET cortex_inference_summary = NULL")
    operations.execute("UPDATE trading_shadowing_probes SET cortex_inference_summary = NULL")
    operations.execute("UPDATE trading_evaluations SET shadowing_regime = NULL")
    operations.execute("UPDATE trading_shadowing_probes SET shadowing_regime = NULL")
    with operations.batch_alter_table("trading_shadowing_probes") as batch_alter:
        batch_alter.alter_column("shadowing_regime", new_column_name="shadowing_summary")
    with operations.batch_alter_table("trading_evaluations") as batch_alter:
        batch_alter.alter_column("shadowing_regime", new_column_name="shadowing_summary")
    with operations.batch_alter_table("trading_cortex_model_manifests") as batch_alter:
        batch_alter.drop_column("predicted_holding_time_minutes_model_path")
        batch_alter.drop_column("predicted_holding_time_root_mean_squared_error")
