from __future__ import annotations

import json

import sqlalchemy as schema
from alembic import op as operations
from sqlalchemy import bindparam
from sqlalchemy.engine import Connection

revision = "20260911_1539"
down_revision = "20260810_0700"
branch_labels = None
depends_on = None

INFERENCE_SUMMARY_TABLE_NAMES: tuple[str, str] = (
    "trading_shadowing_probes",
    "trading_evaluations",
)


def _coerce_inference_summary_json(raw_value: object) -> dict[str, object] | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, str):
        loaded_value = json.loads(raw_value)
        if not isinstance(loaded_value, dict):
            raise TypeError(f"Unexpected cortex_inference_summary JSON payload type: {type(loaded_value).__name__}")
        return loaded_value
    if isinstance(raw_value, dict):
        return dict(raw_value)
    raise TypeError(f"Unexpected cortex_inference_summary JSON type: {type(raw_value).__name__}")


def _strip_gate_verdict_from_inference_summary(raw_value: object) -> tuple[dict[str, object] | None, bool]:
    inference_summary = _coerce_inference_summary_json(raw_value)
    if inference_summary is None:
        return None, False
    if "gate_verdict" not in inference_summary:
        return inference_summary, False
    inference_summary.pop("gate_verdict")
    return inference_summary, True


def _migrate_inference_summary_column(connection: Connection, table_name: str) -> None:
    rows = connection.execute(
        schema.text(
            f"SELECT id, cortex_inference_summary FROM {table_name} WHERE cortex_inference_summary IS NOT NULL"
        )
    ).fetchall()
    update_statement = schema.text(
        f"UPDATE {table_name} SET cortex_inference_summary = :cortex_inference_summary WHERE id = :row_id"
    ).bindparams(bindparam("cortex_inference_summary", type_=schema.JSON()))
    for row_id, cortex_inference_summary in rows:
        patched_summary, changed = _strip_gate_verdict_from_inference_summary(cortex_inference_summary)
        if not changed:
            continue
        connection.execute(
            update_statement,
            {"cortex_inference_summary": patched_summary, "row_id": row_id},
        )


def upgrade() -> None:
    connection = operations.get_bind()
    for table_name in INFERENCE_SUMMARY_TABLE_NAMES:
        _migrate_inference_summary_column(connection, table_name)
    operations.add_column(
        "trading_shadowing_verdicts",
        schema.Column("stale_cause", schema.String(length=64), nullable=True),
    )
    operations.execute(
        schema.text(
            """
            UPDATE trading_shadowing_verdicts
            SET realized_pnl_percentage = NULL,
                realized_pnl_usd = NULL,
                is_profitable = NULL
            WHERE exit_reason = 'STALED'
            """
        )
    )


def downgrade() -> None:
    operations.drop_column("trading_shadowing_verdicts", "stale_cause")
