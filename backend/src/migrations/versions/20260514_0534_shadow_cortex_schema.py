from __future__ import annotations

import sqlalchemy as schema
from alembic import op as operations

revision = "20260514_0534"
down_revision = "20260512_0626"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with operations.batch_alter_table("trading_evaluations") as batch_alter:
        batch_alter.drop_column("shadow_intelligence_snapshot")

    operations.add_column(
        "trading_evaluations",
        schema.Column("cortex_inference_summary", schema.JSON(), nullable=True),
    )
    operations.add_column(
        "trading_evaluations",
        schema.Column("shadowing_summary", schema.JSON(), nullable=True),
    )
    operations.add_column(
        "trading_evaluations",
        schema.Column("shadowing_metrics", schema.JSON(), nullable=True),
    )

    operations.add_column(
        "trading_shadowing_probes",
        schema.Column("cortex_inference_summary", schema.JSON(), nullable=True),
    )
    operations.add_column(
        "trading_shadowing_probes",
        schema.Column("shadowing_summary", schema.JSON(), nullable=True),
    )
    operations.add_column(
        "trading_shadowing_probes",
        schema.Column("shadowing_metrics", schema.JSON(), nullable=True),
    )

    operations.create_table(
        "trading_cortex_model_manifests",
        schema.Column("id", schema.Integer(), primary_key=True, autoincrement=True, nullable=False),
        schema.Column("model_version", schema.String(length=64), nullable=False),
        schema.Column("feature_set_version", schema.String(length=64), nullable=False),
        schema.Column("training_record_count", schema.Integer(), nullable=False),
        schema.Column("validation_record_count", schema.Integer(), nullable=False),
        schema.Column("training_duration_seconds", schema.Float(), nullable=False),
        schema.Column("dataset_window_start_at", schema.DateTime(timezone=True), nullable=False),
        schema.Column("dataset_window_end_at", schema.DateTime(timezone=True), nullable=False),
        schema.Column("success_probability_log_loss", schema.Float(), nullable=False),
        schema.Column("success_probability_accuracy", schema.Float(), nullable=False),
        schema.Column("toxicity_probability_log_loss", schema.Float(), nullable=False),
        schema.Column("toxicity_probability_accuracy", schema.Float(), nullable=False),
        schema.Column("expected_profit_and_loss_root_mean_squared_error", schema.Float(), nullable=False),
        schema.Column("success_probability_model_path", schema.String(length=512), nullable=False),
        schema.Column("toxicity_probability_model_path", schema.String(length=512), nullable=False),
        schema.Column("expected_profit_and_loss_model_path", schema.String(length=512), nullable=False),
        schema.Column("ordered_feature_names", schema.JSON(), nullable=False),
        schema.Column("is_active", schema.Boolean(), nullable=False),
        schema.Column("created_at", schema.DateTime(timezone=True), nullable=False),
    )
    operations.create_index(
        "ix_trading_cortex_model_manifests_model_version",
        "trading_cortex_model_manifests",
        ["model_version"],
        unique=True,
    )
    operations.create_index(
        "ix_trading_cortex_model_manifests_is_active",
        "trading_cortex_model_manifests",
        ["is_active"],
    )


def downgrade() -> None:
    operations.drop_index(
        "ix_trading_cortex_model_manifests_is_active",
        table_name="trading_cortex_model_manifests",
    )
    operations.drop_index(
        "ix_trading_cortex_model_manifests_model_version",
        table_name="trading_cortex_model_manifests",
    )
    operations.drop_table("trading_cortex_model_manifests")

    with operations.batch_alter_table("trading_shadowing_probes") as batch_alter:
        batch_alter.drop_column("shadowing_metrics")
        batch_alter.drop_column("shadowing_summary")
        batch_alter.drop_column("cortex_inference_summary")

    with operations.batch_alter_table("trading_evaluations") as batch_alter:
        batch_alter.drop_column("shadowing_metrics")
        batch_alter.drop_column("shadowing_summary")
        batch_alter.drop_column("cortex_inference_summary")

    operations.add_column(
        "trading_evaluations",
        schema.Column("shadow_intelligence_snapshot", schema.JSON(), nullable=False),
    )
