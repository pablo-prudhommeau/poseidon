from __future__ import annotations

import json

import sqlalchemy as schema
from alembic import op as operations
from sqlalchemy import bindparam

revision = "20260801_1240"
down_revision = "20260711_1509"
branch_labels = None
depends_on = None


def _coerce_shadowing_regime_json(raw_value) -> dict | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, str):
        return json.loads(raw_value)
    if isinstance(raw_value, dict):
        return dict(raw_value)
    raise TypeError(f"Unexpected shadowing_regime JSON type: {type(raw_value).__name__}")


def _patch_shadowing_regime_json(raw_value) -> tuple[dict | None, bool]:
    value = _coerce_shadowing_regime_json(raw_value)
    if value is None:
        return None, False

    if "liquidity_structure_gate_enabled" in value:
        return value, False

    value["liquidity_structure_gate_enabled"] = False
    return value, True


def _migrate_shadowing_regime_column(connection, table_name: str) -> None:
    rows = connection.execute(
        schema.text(f"SELECT id, shadowing_regime FROM {table_name} WHERE shadowing_regime IS NOT NULL")
    ).fetchall()
    update_statement = schema.text(
        f"UPDATE {table_name} SET shadowing_regime = :shadowing_regime WHERE id = :row_id"
    ).bindparams(bindparam("shadowing_regime", type_=schema.JSON()))
    for row_id, shadowing_regime in rows:
        patched_regime, changed = _patch_shadowing_regime_json(shadowing_regime)
        if not changed:
            continue
        connection.execute(
            update_statement,
            {"shadowing_regime": patched_regime, "row_id": row_id},
        )


def upgrade() -> None:
    operations.add_column(
        "trading_positions",
        schema.Column("breakeven_stop_armed_at", schema.DateTime(timezone=True), nullable=True),
    )
    operations.add_column(
        "trading_shadowing_verdicts",
        schema.Column("post_take_profit_tier_1_breakeven_touched_at", schema.DateTime(timezone=True), nullable=True),
    )
    operations.add_column(
        "trading_shadowing_verdicts",
        schema.Column("post_take_profit_tier_1_lowest_price", schema.Float(), nullable=True),
    )

    operations.execute(schema.text("DELETE FROM trading_cortex_model_manifests"))
    operations.add_column(
        "trading_cortex_model_manifests",
        schema.Column("fragility_probability_model_path", schema.String(length=512), nullable=False),
    )
    operations.add_column(
        "trading_cortex_model_manifests",
        schema.Column("fragility_probability_log_loss", schema.Float(), nullable=False),
    )
    operations.add_column(
        "trading_cortex_model_manifests",
        schema.Column("fragility_probability_accuracy", schema.Float(), nullable=False),
    )
    operations.add_column(
        "trading_cortex_model_manifests",
        schema.Column("model_role", schema.String(length=32), nullable=False),
    )
    operations.add_column(
        "trading_cortex_model_manifests",
        schema.Column("promoted_at", schema.DateTime(timezone=True), nullable=True),
    )
    operations.create_index(
        "ix_trading_cortex_model_manifests_model_role",
        "trading_cortex_model_manifests",
        ["model_role"],
    )

    operations.execute(
        schema.text("UPDATE trading_shadowing_probes SET cortex_inference_summary = NULL WHERE cortex_inference_summary IS NOT NULL")
    )
    operations.execute(
        schema.text("UPDATE trading_evaluations SET cortex_inference_summary = NULL WHERE cortex_inference_summary IS NOT NULL")
    )

    connection = operations.get_bind()
    _migrate_shadowing_regime_column(connection, "trading_evaluations")
    _migrate_shadowing_regime_column(connection, "trading_shadowing_probes")


def downgrade() -> None:
    operations.drop_index("ix_trading_cortex_model_manifests_model_role", table_name="trading_cortex_model_manifests")
    operations.drop_column("trading_cortex_model_manifests", "promoted_at")
    operations.drop_column("trading_cortex_model_manifests", "model_role")
    operations.drop_column("trading_cortex_model_manifests", "fragility_probability_accuracy")
    operations.drop_column("trading_cortex_model_manifests", "fragility_probability_log_loss")
    operations.drop_column("trading_cortex_model_manifests", "fragility_probability_model_path")
    operations.drop_column("trading_shadowing_verdicts", "post_take_profit_tier_1_lowest_price")
    operations.drop_column("trading_shadowing_verdicts", "post_take_profit_tier_1_breakeven_touched_at")
    operations.drop_column("trading_positions", "breakeven_stop_armed_at")
