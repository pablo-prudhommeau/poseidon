from __future__ import annotations

from logging.config import fileConfig
from pathlib import Path
import sys

from alembic import context

migrations_directory = Path(__file__).resolve().parent
persistence_directory = migrations_directory.parent
backend_root_directory = persistence_directory.parents[1]
if str(backend_root_directory) not in sys.path:
    sys.path.insert(0, str(backend_root_directory))

from src.persistence.database_session_manager import DatabaseBaseModel
from src.persistence.database_engine_builder import build_alembic_migration_engine

alembic_configuration = context.config

if alembic_configuration.config_file_name is not None:
    fileConfig(alembic_configuration.config_file_name)

database_target_metadata = DatabaseBaseModel.metadata


def run_migrations_offline() -> None:
    raise RuntimeError("[DATABASE][MIGRATION] Offline migration is not supported, use online mode")


def run_migrations_online() -> None:
    database_engine = build_alembic_migration_engine()

    with database_engine.connect() as database_connection:
        context.configure(
            connection=database_connection,
            target_metadata=database_target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
