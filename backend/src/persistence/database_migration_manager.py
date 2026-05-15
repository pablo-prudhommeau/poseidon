from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from src.logging.logger import get_application_logger
from src.persistence.database_session_manager import DatabaseBaseModel, database_engine

logger = get_application_logger(__name__)

INITIAL_REVISION_ID: str = "20260512_0626"
ALEMBIC_VERSION_TABLE_NAME: str = "alembic_version"


def _run_alembic_command(command_arguments: list[str]) -> None:
    repository_root_directory = Path(__file__).resolve().parents[3]
    alembic_ini_path = repository_root_directory / "alembic.ini"

    if not alembic_ini_path.is_file():
        raise FileNotFoundError(f"[DATABASE][MIGRATION] alembic.ini not found at {alembic_ini_path}")

    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(alembic_ini_path)] + command_arguments,
        cwd=str(repository_root_directory),
        check=True,
    )


def _synchronize_database_migration_state_if_needed(database_engine: Engine) -> None:
    inspector = inspect(database_engine)
    existing_table_names = inspector.get_table_names()
    if ALEMBIC_VERSION_TABLE_NAME in existing_table_names:
        return
    application_table_names = list(DatabaseBaseModel.metadata.tables.keys())
    is_populated = any(table_name in existing_table_names for table_name in application_table_names)
    if is_populated:
        logger.info(
            "[DATABASE][MIGRATION] Populated database detected without alembic versioning; synchronizing state to %s",
            INITIAL_REVISION_ID,
        )
        _run_alembic_command(["stamp", INITIAL_REVISION_ID])
        logger.info("[DATABASE][MIGRATION] Database state successfully synchronized")
    else:
        logger.debug("[DATABASE][MIGRATION] Clean database detected; alembic will handle initial schema creation")


def run_database_migrations() -> None:
    logger.info("[DATABASE][MIGRATION] Initializing database migration sequence")
    _synchronize_database_migration_state_if_needed(database_engine)
    _run_alembic_command(["upgrade", "head"])
    logger.info("[DATABASE][MIGRATION] Database migration sequence completed successfully")
