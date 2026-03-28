from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from src.configuration.config import settings
from src.logging.logger import get_logger

logger = get_logger(__name__)

DatabaseBaseModel = declarative_base()


def _resolve_sqlite_file_path() -> Path:
    raw_database_url = settings.DATABASE_URL
    database_file_path = Path(raw_database_url).expanduser().resolve()
    database_file_path.parent.mkdir(parents=True, exist_ok=True)
    return database_file_path


def _build_database_connection_url() -> str:
    sqlite_file_path = _resolve_sqlite_file_path()
    return str(URL.create(drivername="sqlite", database=sqlite_file_path.as_posix()))


DATABASE_CONNECTION_URL: str = _build_database_connection_url()
database_parsed_url = make_url(DATABASE_CONNECTION_URL)

database_connection_arguments: dict[str, bool] = {}

if database_parsed_url.drivername.startswith("sqlite"):
    database_connection_arguments["check_same_thread"] = False

database_engine = create_engine(
    url=DATABASE_CONNECTION_URL,
    connect_args=database_connection_arguments,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=0
)

DatabaseSessionLocal = sessionmaker(
    bind=database_engine,
    autocommit=False,
    autoflush=False,
    class_=Session
)

if database_parsed_url.drivername.startswith("sqlite"):
    database_name = database_parsed_url.database
    if database_name is not None and database_name not in ("", ":memory:"):

        @event.listens_for(database_engine, "connect")
        def _apply_sqlite_performance_pragmas(database_api_connection, connection_record) -> None:
            try:
                database_cursor = database_api_connection.cursor()
                database_cursor.execute("PRAGMA journal_mode=WAL;")
                database_cursor.execute("PRAGMA synchronous=NORMAL;")
                database_cursor.close()
                logger.debug("[DATABASE][SQLITE][PRAGMA] Performance pragmas WAL and NORMAL successfully applied to connection")
            except Exception as exception:
                logger.exception("[DATABASE][SQLITE][PRAGMA] Failed to apply performance pragmas due to error: %s", exception)


@contextmanager
def _session() -> Generator[Session, None, None]:
    database_session = DatabaseSessionLocal()
    try:
        yield database_session
        database_session.commit()
    except Exception as transaction_exception:
        database_session.rollback()
        logger.exception("[DATABASE][TRANSACTION][ROLLBACK] Transaction rolled back due to error: %s", transaction_exception)
        raise transaction_exception
    finally:
        database_session.close()


def get_database_session() -> Generator[Session, None, None]:
    database_session = DatabaseSessionLocal()
    try:
        yield database_session
    finally:
        database_session.close()


def initialize_database() -> None:
    logger.info("[DATABASE][INITIALIZATION] Starting database schema creation process")
    try:
        DatabaseBaseModel.metadata.create_all(bind=database_engine)
        logger.info("[DATABASE][INITIALIZATION] Database schema successfully created on target engine")
    except Exception as initialization_exception:
        logger.critical("[DATABASE][INITIALIZATION] Failed to create database schema due to error: %s", initialization_exception)
        raise initialization_exception
