from __future__ import annotations

import sqlalchemy as schema
from alembic import op as operations

revision = "20260518_0152"
down_revision = "20260516_0700"
branch_labels = None
depends_on = None


def _normalize_shadow_regime_phase_for_table(table_name: str, column_name: str) -> None:
    bind = operations.get_bind()
    if bind.engine.name == "postgresql":
        operations.execute(
            f"""
            UPDATE {table_name}
            SET {column_name} = jsonb_set(
                jsonb_set(
                    {column_name}::jsonb,
                    '{{resolved_shadowing_and_cortex_inference_aware_outcome_count}}',
                    to_jsonb(COALESCE(({column_name}::jsonb->>'resolved_shadowing_and_cortex_inference_aware_outcome_count')::int, 0)),
                    true
                ),
                '{{phase}}',
                to_jsonb(
                    CASE
                        WHEN COALESCE({column_name}::jsonb->>'phase', '') = 'DISABLED' THEN 'DISABLED'
                        WHEN COALESCE({column_name}::jsonb->>'phase', '') = 'SYNCING' THEN 'SYNCING'
                        WHEN COALESCE(({column_name}::jsonb->>'resolved_outcome_count')::int, 0) >= 10000
                             AND COALESCE(({column_name}::jsonb->>'elapsed_hours')::float, 0) >= 48
                             AND COALESCE(({column_name}::jsonb->>'resolved_shadowing_and_cortex_inference_aware_outcome_count')::int, 0) >= 30000
                            THEN 'TRADABLE'
                        WHEN COALESCE(({column_name}::jsonb->>'resolved_outcome_count')::int, 0) >= 10000
                             AND COALESCE(({column_name}::jsonb->>'elapsed_hours')::float, 0) >= 48
                             AND COALESCE(({column_name}::jsonb->>'resolved_shadowing_and_cortex_inference_aware_outcome_count')::int, 0) >= 10000
                            THEN 'CORTEXING'
                        ELSE 'SHADOWING'
                    END
                ),
                true
            )
            WHERE {column_name} IS NOT NULL;
            """
        )
    else:
        operations.execute(
            f"""
            UPDATE {table_name}
            SET {column_name} = json_set(
                {column_name},
                '$.resolved_shadowing_and_cortex_inference_aware_outcome_count',
                CAST(COALESCE(json_extract({column_name}, '$.resolved_shadowing_and_cortex_inference_aware_outcome_count'), 0) AS INTEGER),
                '$.phase',
                CASE
                    WHEN COALESCE(json_extract({column_name}, '$.phase'), '') = 'DISABLED' THEN 'DISABLED'
                    WHEN COALESCE(json_extract({column_name}, '$.phase'), '') = 'SYNCING' THEN 'SYNCING'
                    WHEN CAST(COALESCE(json_extract({column_name}, '$.resolved_outcome_count'), 0) AS INTEGER) >= 10000
                         AND CAST(COALESCE(json_extract({column_name}, '$.elapsed_hours'), 0) AS REAL) >= 48
                         AND CAST(COALESCE(json_extract({column_name}, '$.resolved_shadowing_and_cortex_inference_aware_outcome_count'), 0) AS INTEGER) >= 30000
                        THEN 'TRADABLE'
                    WHEN CAST(COALESCE(json_extract({column_name}, '$.resolved_outcome_count'), 0) AS INTEGER) >= 10000
                         AND CAST(COALESCE(json_extract({column_name}, '$.elapsed_hours'), 0) AS REAL) >= 48
                         AND CAST(COALESCE(json_extract({column_name}, '$.resolved_shadowing_and_cortex_inference_aware_outcome_count'), 0) AS INTEGER) >= 10000
                        THEN 'CORTEXING'
                    ELSE 'SHADOWING'
                END
            )
            WHERE {column_name} IS NOT NULL;
            """
        )


def _revert_shadow_regime_phase_for_table(table_name: str, column_name: str) -> None:
    bind = operations.get_bind()
    if bind.engine.name == "postgresql":
        operations.execute(
            f"""
            UPDATE {table_name}
            SET {column_name} = jsonb_set(
                {column_name}::jsonb,
                '{{phase}}',
                to_jsonb(
                    CASE
                        WHEN COALESCE({column_name}::jsonb->>'phase', '') = 'DISABLED' THEN 'DISABLED'
                        WHEN COALESCE({column_name}::jsonb->>'phase', '') = 'TRADABLE' THEN 'TRADABLE'
                        WHEN COALESCE({column_name}::jsonb->>'phase', '') = 'CORTEXING' THEN 'CORTEXING'
                        ELSE 'SHADOWING'
                    END
                ),
                true
            )
            WHERE {column_name} IS NOT NULL;
            """
        )
    else:
        operations.execute(
            f"""
            UPDATE {table_name}
            SET {column_name} = json_set(
                {column_name},
                '$.phase',
                CASE
                    WHEN COALESCE(json_extract({column_name}, '$.phase'), '') = 'DISABLED' THEN 'DISABLED'
                    WHEN COALESCE(json_extract({column_name}, '$.phase'), '') = 'TRADABLE' THEN 'TRADABLE'
                    WHEN COALESCE(json_extract({column_name}, '$.phase'), '') = 'CORTEXING' THEN 'CORTEXING'
                    ELSE 'SHADOWING'
                END
            )
            WHERE {column_name} IS NOT NULL;
            """
        )


def upgrade() -> None:
    operations.execute("DELETE FROM trading_cortex_model_manifests")
    operations.execute("UPDATE trading_evaluations SET cortex_inference_summary = NULL")
    operations.execute("UPDATE trading_shadowing_probes SET cortex_inference_summary = NULL")
    with operations.batch_alter_table("trading_evaluations") as batch_alter:
        batch_alter.alter_column("shadowing_summary", new_column_name="shadowing_regime")
    with operations.batch_alter_table("trading_shadowing_probes") as batch_alter:
        batch_alter.alter_column("shadowing_summary", new_column_name="shadowing_regime")
    _normalize_shadow_regime_phase_for_table("trading_evaluations", "shadowing_regime")
    _normalize_shadow_regime_phase_for_table("trading_shadowing_probes", "shadowing_regime")
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
    _revert_shadow_regime_phase_for_table("trading_evaluations", "shadowing_regime")
    _revert_shadow_regime_phase_for_table("trading_shadowing_probes", "shadowing_regime")
    with operations.batch_alter_table("trading_shadowing_probes") as batch_alter:
        batch_alter.alter_column("shadowing_regime", new_column_name="shadowing_summary")
    with operations.batch_alter_table("trading_evaluations") as batch_alter:
        batch_alter.alter_column("shadowing_regime", new_column_name="shadowing_summary")
    with operations.batch_alter_table("trading_cortex_model_manifests") as batch_alter:
        batch_alter.drop_column("predicted_holding_time_minutes_model_path")
        batch_alter.drop_column("predicted_holding_time_root_mean_squared_error")
