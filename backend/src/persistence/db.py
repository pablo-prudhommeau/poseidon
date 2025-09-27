from __future__ import annotations

from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from src.configuration.config import settings

Base = declarative_base()


def _sqlite_path() -> Path:
    """Resolve the SQLite file path from settings.DATABASE_URL (creating parent dirs)."""
    raw = settings.DATABASE_URL
    db_file = Path(raw).expanduser().resolve()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    return db_file


def _resolve_db_url() -> str:
    """Build the database URL from settings."""
    sqlite_file = _sqlite_path()
    return str(URL.create("sqlite", database=sqlite_file.as_posix()))


DB_URL: str = _resolve_db_url()
_url = make_url(DB_URL)

connect_args: dict = {}
engine_kwargs = dict(pool_pre_ping=True)

# SQLite needs special flags for multithreaded FastAPI
if _url.drivername.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(str(_url), connect_args=connect_args, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)

# Apply SQLite pragmas for durability/perf (WAL, NORMAL) when using a file-backed DB.
if _url.drivername.startswith("sqlite") and (_url.database or "") not in ("", ":memory:"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _) -> None:  # type: ignore[no-redef]
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.close()
        except Exception:
            # Best-effort; avoid crashing on environments that disallow PRAGMA
            pass


def get_db() -> Generator[Session, None, None]:
    """Yield a scoped SQLAlchemy Session (FastAPI dependency)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables if they do not exist yet."""
    # Import here to avoid circular import issues
    from .models import Base as ModelsBase  # noqa: WPS433 (local import is intentional)

    ModelsBase.metadata.create_all(bind=engine)
