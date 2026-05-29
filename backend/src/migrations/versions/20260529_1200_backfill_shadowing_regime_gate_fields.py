from __future__ import annotations

import json

import sqlalchemy as schema
from alembic import op as operations
from sqlalchemy import bindparam

revision = "20260529_1200"
down_revision = "20260519_1003"
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

    changed = False
    if "fundamentals_gate_enabled" not in value:
        value["fundamentals_gate_enabled"] = False
        changed = True
    if "toxic_metrics_gate_enabled" not in value:
        value["toxic_metrics_gate_enabled"] = False
        changed = True
    return value, changed


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
    connection = operations.get_bind()
    _migrate_shadowing_regime_column(connection, "trading_evaluations")
    _migrate_shadowing_regime_column(connection, "trading_shadowing_probes")


def downgrade() -> None:
    pass
