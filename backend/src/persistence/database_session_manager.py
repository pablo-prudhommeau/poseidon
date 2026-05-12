from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from src.logging.logger import get_application_logger
from src.persistence.database_engine_builder import build_database_engine

logger = get_application_logger(__name__)

DatabaseBaseModel = declarative_base()

database_engine: Engine = build_database_engine()

DatabaseSessionLocal = sessionmaker(
    bind=database_engine,
    autocommit=False,
    autoflush=False,
    class_=Session,
)


@contextmanager
def get_database_session() -> Generator[Session, None, None]:
    database_session = DatabaseSessionLocal()
    try:
        yield database_session
        database_session.commit()
    except Exception as transaction_exception:
        database_session.rollback()
        logger.exception("[DATABASE][TRANSACTION][ROLLBACK] Rolled back transaction after error: %s", transaction_exception)
        raise transaction_exception
    finally:
        database_session.close()


def get_fastapi_database_session() -> Generator[Session, None, None]:
    database_session = DatabaseSessionLocal()
    try:
        yield database_session
        database_session.commit()
    except Exception as transaction_exception:
        database_session.rollback()
        logger.exception("[DATABASE][TRANSACTION][ROLLBACK] Rolled back FastAPI session after error: %s", transaction_exception)
        raise transaction_exception
    finally:
        database_session.close()
