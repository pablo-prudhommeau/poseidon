from __future__ import annotations

from datetime import datetime
from contextlib import contextmanager
from typing import Generator, Any, Optional

from sqlalchemy import TypeDecorator, DateTime
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, DeclarativeBase, sessionmaker

from src.core.utils.date_utils import ensure_timezone_aware
from src.logging.logger import get_application_logger
from src.persistence.database_engine_builder import build_database_engine

logger = get_application_logger(__name__)


class HybridAwareDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def load_dialect_impl(self, dialect: Any):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.TIMESTAMP(timezone=True))
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value: Optional[datetime], dialect: Any) -> Optional[datetime]:
        if value is None:
            return None
        return ensure_timezone_aware(value)

    def process_result_value(self, value: Optional[datetime], dialect: Any) -> Optional[datetime]:
        if value is None:
            return None
        return ensure_timezone_aware(value)


class DatabaseBaseModel(DeclarativeBase):
    type_annotation_map = {
        datetime: HybridAwareDateTime()
    }

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
