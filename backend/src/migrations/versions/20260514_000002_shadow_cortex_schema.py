from __future__ import annotations

import sqlalchemy as schema
from alembic import op as operations
from sqlalchemy import inspect

revision = "20260514_000002"
down_revision = "20260512_000001"
branch_labels = None
depends_on = None


def _table_column_names(table_name: str) -> set[str]:
    inspector = inspect(operations.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def _table_exists(table_name: str) -> bool:
    inspector = inspect(operations.get_bind())
    return table_name in inspector.get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = inspect(operations.get_bind())
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    evaluation_column_names = _table_column_names("trading_evaluations")
    if "shadow_intelligence_snapshot" in evaluation_column_names:
        with operations.batch_alter_table("trading_evaluations") as batch_alter:
            batch_alter.drop_column("shadow_intelligence_snapshot")
        evaluation_column_names = _table_column_names("trading_evaluations")

    for column_name in ("cortex_inference_summary", "shadowing_summary", "shadowing_metrics"):
        if column_name not in evaluation_column_names:
            operations.add_column("trading_evaluations", schema.Column(column_name, schema.JSON(), nullable=True))

    probe_column_names = _table_column_names("trading_shadowing_probes")
    for column_name in ("cortex_inference_summary", "shadowing_summary", "shadowing_metrics"):
        if column_name not in probe_column_names:
            operations.add_column("trading_shadowing_probes", schema.Column(column_name, schema.JSON(), nullable=True))

    if not _table_exists("trading_cortex_model_manifests"):
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

    if _table_exists("trading_cortex_model_manifests"):
        if not _index_exists("trading_cortex_model_manifests", "ix_trading_cortex_model_manifests_model_version"):
            operations.create_index(
                "ix_trading_cortex_model_manifests_model_version",
                "trading_cortex_model_manifests",
                ["model_version"],
                unique=True,
            )
        if not _index_exists("trading_cortex_model_manifests", "ix_trading_cortex_model_manifests_is_active"):
            operations.create_index(
                "ix_trading_cortex_model_manifests_is_active",
                "trading_cortex_model_manifests",
                ["is_active"],
            )


def downgrade() -> None:
    if _table_exists("trading_cortex_model_manifests"):
        if _index_exists("trading_cortex_model_manifests", "ix_trading_cortex_model_manifests_is_active"):
            operations.drop_index(
                "ix_trading_cortex_model_manifests_is_active",
                table_name="trading_cortex_model_manifests",
            )
        if _index_exists("trading_cortex_model_manifests", "ix_trading_cortex_model_manifests_model_version"):
            operations.drop_index(
                "ix_trading_cortex_model_manifests_model_version",
                table_name="trading_cortex_model_manifests",
            )
        operations.drop_table("trading_cortex_model_manifests")

    probe_column_names = _table_column_names("trading_shadowing_probes")
    probe_columns_to_drop = [
        column_name
        for column_name in ("shadowing_metrics", "shadowing_summary", "cortex_inference_summary")
        if column_name in probe_column_names
    ]
    if probe_columns_to_drop:
        with operations.batch_alter_table("trading_shadowing_probes") as batch_alter:
            for column_name in probe_columns_to_drop:
                batch_alter.drop_column(column_name)

    evaluation_column_names = _table_column_names("trading_evaluations")
    evaluation_columns_to_drop = [
        column_name
        for column_name in ("shadowing_metrics", "shadowing_summary", "cortex_inference_summary")
        if column_name in evaluation_column_names
    ]
    if evaluation_columns_to_drop:
        with operations.batch_alter_table("trading_evaluations") as batch_alter:
            for column_name in evaluation_columns_to_drop:
                batch_alter.drop_column(column_name)

    evaluation_column_names = _table_column_names("trading_evaluations")
    if "shadow_intelligence_snapshot" not in evaluation_column_names:
        operations.add_column(
            "trading_evaluations",
            schema.Column("shadow_intelligence_snapshot", schema.JSON(), nullable=False),
        )
