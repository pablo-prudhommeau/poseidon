from __future__ import annotations

from pathlib import Path

import psycopg
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, URL
from sqlalchemy.pool import NullPool

from src.configuration.config import settings
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

SQLITE_DEFAULT_DATABASE_FILENAME: str = "poseidon.db"


def _resolve_sqlite_database_file_path() -> Path:
    database_directory = Path(settings.DATABASE_SQLITE_DIRECTORY).expanduser().resolve()
    database_directory.mkdir(parents=True, exist_ok=True)
    return database_directory / SQLITE_DEFAULT_DATABASE_FILENAME


def _build_sqlite_engine() -> Engine:
    sqlite_database_file_path = _resolve_sqlite_database_file_path()
    sqlite_connection_url = str(URL.create(drivername="sqlite", database=sqlite_database_file_path.as_posix()))
    logger.info("[DATABASE][SQLITE] Using SQLite database at %s", sqlite_database_file_path)

    sqlite_engine = create_engine(
        sqlite_connection_url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=0,
    )

    if sqlite_database_file_path.as_posix() != ":memory:":
        @event.listens_for(sqlite_engine, "connect")
        def _apply_sqlite_performance_pragmas(database_api_connection, connection_record) -> None:
            try:
                database_cursor = database_api_connection.cursor()
                database_cursor.execute("PRAGMA journal_mode=WAL;")
                database_cursor.execute("PRAGMA synchronous=NORMAL;")
                database_cursor.close()
                logger.debug("[DATABASE][SQLITE][PRAGMA] Applied WAL and NORMAL synchronous pragmas")
            except Exception as pragma_exception:
                logger.exception("[DATABASE][SQLITE][PRAGMA] Failed to apply performance pragmas: %s", pragma_exception)

    return sqlite_engine


def _build_postgresql_connection_keyword_arguments() -> dict[str, object]:
    connection_keyword_arguments: dict[str, object] = {
        "host": settings.DATABASE_HOST,
        "port": settings.DATABASE_PORT,
        "dbname": settings.DATABASE_NAME,
        "user": settings.DATABASE_USER,
        "connect_timeout": 15,
        "channel_binding": "disable",
    }

    if settings.DATABASE_PASSWORD != "":
        connection_keyword_arguments["password"] = settings.DATABASE_PASSWORD

    return connection_keyword_arguments


def _build_postgresql_engine() -> Engine:
    connection_keyword_arguments = _build_postgresql_connection_keyword_arguments()
    logger.info(
        "[DATABASE][POSTGRESQL] Connecting to %s:%s database=%s user=%s",
        connection_keyword_arguments["host"],
        connection_keyword_arguments["port"],
        connection_keyword_arguments["dbname"],
        connection_keyword_arguments["user"],
    )

    def create_raw_psycopg_connection() -> psycopg.Connection:
        return psycopg.connect(**connection_keyword_arguments)

    return create_engine(
        "postgresql+psycopg://",
        creator=create_raw_psycopg_connection,
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=0,
    )


def build_database_engine() -> Engine:
    database_mode = settings.DATABASE_MODE.lower().strip()

    if database_mode == "postgresql":
        return _build_postgresql_engine()

    if database_mode == "sqlite":
        return _build_sqlite_engine()

    raise ValueError(f"[DATABASE][CONFIGURATION] Unsupported DATABASE_MODE '{database_mode}', expected 'sqlite' or 'postgresql'")


def build_alembic_migration_engine() -> Engine:
    database_mode = settings.DATABASE_MODE.lower().strip()

    if database_mode == "postgresql":
        connection_keyword_arguments = _build_postgresql_connection_keyword_arguments()

        def create_raw_psycopg_connection_for_alembic() -> psycopg.Connection:
            return psycopg.connect(**connection_keyword_arguments)

        return create_engine(
            "postgresql+psycopg://",
            creator=create_raw_psycopg_connection_for_alembic,
            poolclass=NullPool,
        )

    sqlite_database_file_path = _resolve_sqlite_database_file_path()
    return create_engine(
        str(URL.create(drivername="sqlite", database=sqlite_database_file_path.as_posix())),
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
